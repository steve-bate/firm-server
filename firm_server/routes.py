import logging
from typing import Awaitable, Callable, Iterable

import httpx
import mimeparse
from firm.auth.bearer_token import BearerTokenAuthenticator
from firm.auth.chained import AuthenticatorChain
from firm.auth.http_signature import HttpSigAuthenticator, HttpSignatureAuth
from firm.interfaces import (
    FIRM_NS,
    HttpException,
    HttpRequest,
    HttpResponse,
    JSONObject,
    JsonResponse,
    PlainTextResponse,
    ResourceStore,
)
from firm.services.activitypub import ActivityPubService, ActivityPubTenant
from firm.services.nodeinfo import nodeinfo_index, nodeinfo_version
from firm.services.webfinger import webfinger
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.responses import PlainTextResponse as StarlettePlainTextResponse
from starlette.responses import Response
from starlette.routing import Match, Route, Scope

from firm_server.adapters import (
    AuthenticationBackendAdapter,
    HttpConnectionAdapter,
    HttpxAuthAdapter,
)
from firm_server.config import ServerConfig
from firm_server.html.endpoint import html_endpoint, html_static_endpoint

log = logging.getLogger(__name__)


def _adapt_response(r: HttpResponse) -> Response:
    if isinstance(r, JsonResponse):
        return JSONResponse(r.json, status_code=r.status_code, headers=r.headers)
    if isinstance(r, PlainTextResponse):
        return StarlettePlainTextResponse(
            r.content, status_code=r.status_code, headers=r.headers
        )


def _adapt_endpoint(
    method: Callable[[HttpRequest], Awaitable[HttpResponse]],
    store: ResourceStore,
    authenticated=False,
) -> Response:
    async def wrapper(request: Request):
        try:
            if authenticated and not request.user.is_authenticated:
                raise HTTPException(401)
            return _adapt_response(await method(HttpConnectionAdapter(request, store)))
        except HttpException as e:
            raise HTTPException(e.status_code, detail=e.detail, headers=e.headers)

    return wrapper


# TODO Move to util
def is_collection(obj: JSONObject) -> bool:
    return obj.get("type") in ["Collection", "OrderedCollection"]


def is_local(prefix: str, uri: str):
    return uri.startswith(prefix)


def is_public(uri: str):
    return uri in [
        "https://www.w3.org/ns/activitystreams#Public",
        "as:Public",
        "Public",
    ]


# TODO Reconsider design of FirmDeliveryService (abstract class?)
class FirmDeliveryService:
    _RECIPIENT_PROPS = ["to", "cc", "bto", "bcc"]

    def __init__(self, store: ResourceStore):
        self._store = store

    async def _resolve_inboxes(self, recipient_uris: Iterable[str]) -> set[str]:
        inboxes = set()
        for uri in recipient_uris:
            if is_public(uri):
                continue
            obj = await self._store.get(uri)
            if is_collection(obj):  # TODO and self._store.is_local(uri):
                if items := obj.get("items") or obj.get("orderedItems"):
                    for item in await self._resolve_inboxes(items):
                        inboxes.add(item)
            else:
                if inbox := obj.get("sharedInbox") or obj.get("inbox"):
                    inboxes.add(inbox)
        return inboxes

    def _remove_keys(self, obj: JSONObject, predicate: Callable[[str], bool]) -> None:
        for key, value in obj.items():
            if key.startswith("firm:"):
                obj.pop(key)
            else:
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            self._remove_keys(item, predicate)
                else:
                    if isinstance(value, dict):
                        self._remove_keys(value, predicate)

    async def _post(
        self,
        inbox: str,
        /,
        message: JSONObject,
        auth: HttpSignatureAuth,
    ) -> None:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                inbox,
                json=message,
                headers={"Content-Type": "application/activity+json"},
                auth=HttpxAuthAdapter(auth, self._store),
            )
            log.info(
                f"FirmDeliveryService POST {inbox} "
                f"{response.status_code} text={response.text}"
            )

    async def _serialize(self, activity: JSONObject) -> JSONObject:
        message = activity.copy()
        message.pop("bto", None)
        message.pop("bcc", None)
        self._remove_keys(message, lambda k: k.startswith("fir:"))
        # TODO message specific serialization
        # (selected object embedding, collection paging, etc.)
        return message

    async def deliver(self, activity: JSONObject) -> None:
        # TODO Handle failures and redelivery
        actor = await self._store.get(activity["actor"])
        key_uri = actor.get("publicKey", {}).get("id")
        if not key_uri:
            log.error("No key for actor %s", actor["id"])
            return
        credentials = await self._store.query_one(
            {
                "@prefix": "urn:",  # private
                "type": FIRM_NS.Credentials.value,
                "attributedTo": actor["id"],
            }
        )
        private_key_pem = credentials.get(FIRM_NS.privateKey.value)
        if not private_key_pem:
            log.error("No private key found for actor %s", actor["id"])
            return
        auth = HttpSignatureAuth(key_uri, private_key_pem)
        recipient_uris: set[str] = set()
        for prop in self._RECIPIENT_PROPS:
            if r := activity.get(prop):
                if isinstance(r, str):
                    recipient_uris.add(r)
                elif isinstance(r, list):
                    recipient_uris.update(r)
        inboxes = await self._resolve_inboxes(recipient_uris)
        message = await self._serialize(activity)
        for inbox in inboxes:
            await self._post(inbox, message=message, auth=auth)


class MimeTypeRoute(Route):
    def __init__(self, *args, **kwargs):
        self._mimetypes = kwargs.pop("mimetypes", None)
        super().__init__(*args, **kwargs)

    @staticmethod
    def _get_header(scope: Scope, name: bytes) -> str | None:
        for key, value in scope["headers"]:
            if key == name:
                return value.decode()
        return ""

    def _matches_mimetype(self, scope: Scope) -> bool:
        if accepted_types := self._get_header(scope, b"accept"):
            return self._mimetypes is None or mimeparse.best_match(
                self._mimetypes, accepted_types
            )
        elif content_type := self._get_header(scope, b"content-type"):
            return self._mimetypes is None or content_type in self._mimetypes
        else:
            raise HTTPException(400, "No accept or content-type header")

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        return (
            super().matches(scope)
            if self._matches_mimetype(scope)
            else (Match.NONE, scope)
        )


def get_routes(store: ResourceStore, config: ServerConfig):
    activitypub_service = ActivityPubService(
        [
            ActivityPubTenant(
                prefix,
                store,
                FirmDeliveryService(store),
            )
            for prefix in config.tenants
        ]
    )
    activitypub_route = MimeTypeRoute(
        "/{path:path}",
        endpoint=_adapt_endpoint(activitypub_service.process_request, store),
        mimetypes=[
            "application/activity+json",
            'application/ld+json; profile="https://www.w3.org/ns/activitystreams"',
        ],
        methods=["GET", "POST"],
        middleware=[
            Middleware(
                AuthenticationMiddleware,
                backend=AuthenticationBackendAdapter(
                    AuthenticatorChain(
                        [
                            BearerTokenAuthenticator(),
                            HttpSigAuthenticator(),
                        ]
                    ),
                    store,
                ),
            )
        ],
    )
    return [
        Route("/.well-known/webfinger", endpoint=_adapt_endpoint(webfinger, store)),
        Route("/.well-known/nodeinfo", endpoint=_adapt_endpoint(nodeinfo_index, store)),
        Route("/nodeinfo/{version}", endpoint=_adapt_endpoint(nodeinfo_version, store)),
        Route("/static/{file_path:path}", endpoint=html_static_endpoint(config)),
        MimeTypeRoute(
            "/{path:path}",
            endpoint=html_endpoint(config),
            mimetypes=["text/html"],
        ),
        activitypub_route,
    ]
