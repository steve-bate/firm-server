import logging
from typing import Awaitable, Callable, Iterable

import httpx
import mimeparse
from firm.auth.authorization import CoreAuthorizationService
from firm.auth.bearer_token import BearerTokenAuthenticator
from firm.auth.chained import AuthenticatorChain
from firm.auth.http_signature import HttpSigAuthenticator, HttpSignatureAuth
from firm.interfaces import (
    FIRM_NS,
    DeliveryService,
    HttpException,
    HttpRequest,
    HttpResponse,
    JSONObject,
    JsonResponse,
    PlainTextResponse,
    ResourceStore,
    Validator,
)
from firm.services.activitypub import ActivityPubService, ActivityPubTenant
from firm.services.nodeinfo import nodeinfo_index, nodeinfo_version
from firm.services.webfinger import webfinger
from firm.util import AP_PUBLIC_URIS, AS2_CONTENT_TYPES
from firm_jsonschema.validation import create_validator
from firm_ld.search import IndexedResource, SearchEngine
from firm_ld.sparql import create_sparql_endpoint
from firm_ld.store import RdfResourceStore
from jsonschema.exceptions import ValidationError
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.responses import PlainTextResponse as StarlettePlainTextResponse
from starlette.responses import Response
from starlette.routing import Match, Mount, Route, Scope

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
    return uri in AP_PUBLIC_URIS


# TODO Reconsider design of FirmDeliveryService (abstract class?)
class FirmDeliveryService(DeliveryService):
    _RECIPIENT_PROPS = ["to", "cc", "bto", "bcc"]

    def __init__(self, config: ServerConfig, store: ResourceStore):
        self._config = config
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
        message = None
        for inbox_uri in inboxes:
            if self._config.is_local(inbox_uri):
                inbox = await self._store.get(inbox_uri)
                items = inbox.get("orderedItems", [])
                items.insert(0, activity["id"])
                inbox["orderedItems"] = items
                await self._store.put(inbox)
            else:
                if message is None:
                    message = await self._serialize(activity)
                await self._post(inbox_uri, message=message, auth=auth)


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
        if scope["method"] in ["GET", "HEAD"]:
            if accepted_types := self._get_header(scope, b"accept"):
                return self._mimetypes is None or mimeparse.best_match(
                    self._mimetypes, accepted_types
                )
            raise HTTPException(400, "No accept header")
        elif content_type := self._get_header(scope, b"content-type"):
            return self._mimetypes is None or content_type in self._mimetypes
        else:
            raise HTTPException(400, "No content-type header")

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        return (
            super().matches(scope)
            if self._matches_mimetype(scope)
            else (Match.NONE, scope)
        )


def _rdf_search(store: RdfResourceStore) -> HttpResponse:
    # TODO support named graphs for search
    search_engine = SearchEngine(store.graph)
    search_engine.add_index(
        IndexedResource(
            "https://www.w3.org/ns/activitystreams#Note",
            [
                "https://www.w3.org/ns/activitystreams#content",
                "https://www.w3.org/ns/activitystreams#summary",
            ],
            [
                "https://www.w3.org/ns/activitystreams#content",
                "https://www.w3.org/ns/activitystreams#summary",
            ],
        )
    )
    search_engine.add_index(
        IndexedResource(
            "https://www.w3.org/ns/activitystreams#Person",
            [
                "https://www.w3.org/ns/activitystreams#summary",
            ],
            [
                "https://www.w3.org/ns/activitystreams#summary",
                "https://www.w3.org/ns/activitystreams#name",
                "https://www.w3.org/ns/activitystreams#preferredUsername",
            ],
        )
    )
    log.info("Indexing RDF store")
    search_engine.update_index()

    def _search(request: HttpRequest) -> HttpResponse:
        # TODO Need to expose query params on HttpRequest
        return JSONResponse(
            search_engine.search(request.query_params["q"]),
            headers={"Access-Control-Allow-Origin", "*"},
        )

    return _search


class JsonSchemaValidator(Validator):
    def __init__(self, config: ServerConfig):
        self._validator = create_validator(
            root_schema=config.validation.root_schema,
            schema_dirs=config.validation.schema_dirs,
            package_names=["firm_server.schemas"] + config.validation.package_names,
        )

    def validate(self, obj: JSONObject) -> None:
        try:
            self._validator.validate(obj)
        except ValidationError as e:
            raise HttpException(400, e.message)


def get_routes(store: ResourceStore, config: ServerConfig):
    validator = JsonSchemaValidator(config)
    activitypub_service = ActivityPubService(
        [
            ActivityPubTenant(
                prefix=prefix,
                store=store,
                authorizer=CoreAuthorizationService(prefix, store),
                delivery_service=FirmDeliveryService(config, store),
                validator=validator,
            )
            for prefix in config.tenants
        ]
    )
    activitypub_route = MimeTypeRoute(
        "/{path:path}",
        endpoint=_adapt_endpoint(activitypub_service.process_request, store),
        mimetypes=AS2_CONTENT_TYPES,
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
    routes = [
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
    if isinstance(store, RdfResourceStore):
        log.info("Registering SPARQL endpoint")
        example_query = """\
PREFIX as: <https://www.w3.org/ns/activitystreams#>
PREFIX firm: <https://firm.stevebate.dev#>

SELECT ?object WHERE {
    ?object is as:Note
}
""".rstrip()
        # TODO tenant-specific config for sparql endpoints
        # The namespace will always be firm.stevebate.dev
        sparql_app = create_sparql_endpoint(
            "https://firm.stevebate.dev/sparql/",
            example_query=example_query,
            favicon="https://firm.stevebate.dev/static/favicon/favicon.ico",
        )
        routes.insert(4, Mount("/sparql", app=sparql_app, name="sparql"))
        # Add a search engine
        routes.insert(4, Route("/search", endpoint=_rdf_search(store)))
    return routes
