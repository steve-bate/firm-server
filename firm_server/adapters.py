from typing import Any, AsyncIterable, Generator, Iterable, MutableMapping

import httpx
from firm.interfaces import (
    DEFAULT_HTTP_TIMEOUT,
    Authenticator,
    HttpApplication,
    HttpApplicationState,
    HttpMethod,
    HttpRequest,
    HttpRequestSigner,
    HttpResponse,
    HttpTransport,
    Identity,
    JSONObject,
    Mapping,
    ResourceStore,
    Url,
    UrlTypes,
)
from starlette.authentication import (
    AuthCredentials,
    AuthenticationBackend,
    BaseUser,
    UnauthenticatedUser,
)
from starlette.requests import HTTPConnection, Request
from starlette.responses import Response


class HttpxAuthAdapter(httpx.Auth):
    def __init__(self, auth: HttpRequestSigner, store: ResourceStore) -> None:
        super().__init__()
        self._auth = auth
        self._store = store

    def auth_flow(self, request: Request) -> Generator[Request, Response, None]:
        self._auth.sign(HttpxRequestAdapter(request, self._store))
        return super().auth_flow(request)


class HttpxRequestAdapter(HttpRequest):
    def __init__(self, request: httpx.Request, store: ResourceStore):
        self._request = request
        self._store = store

    @property
    def method(self) -> HttpMethod:
        """The HTTP method of the request (e.g., 'GET', 'POST')."""
        return self._request.method

    @property
    def url(self) -> Url:
        """The full URL of the request."""
        # should have an adapter for URL?
        return self._request.url

    @property
    def path_params(self) -> Mapping[str, str]:
        """The path parameters of the request."""
        return {}

    @property
    def headers(self) -> MutableMapping[str, str]:
        """The request headers."""
        return self._request.headers

    @property
    def cookies(self) -> MutableMapping[str, str]:
        """The cookies sent with the request."""
        return {}

    # TODO Remove this?
    @property
    def client(self) -> tuple[str, int] | None:
        """The IP address and port of the client making the request."""
        raise NotImplementedError()

    def stream(self) -> AsyncIterable[bytes]:
        """Asynchronous stream of the request body."""
        raise NotImplementedError()

    async def body(self) -> bytes:
        """Read the entire request body at once as bytes."""
        return self._request.content

    def content(self) -> bytes:
        return self._request.content

    async def json(self) -> Mapping[str, Any]:
        """Parse the request body as JSON."""
        raise NotImplementedError()

    async def form(self) -> Mapping[str, str]:
        """Parse the request body as form data."""
        raise NotImplementedError()

    async def files(self) -> Mapping[str, Any]:
        """Parse the request body for file uploads."""
        raise NotImplementedError()

    @property
    def auth(self) -> Identity | None:
        """The authentication credentials provided with the request."""
        raise NotImplementedError()

    @property
    def state(self) -> HttpApplicationState:
        return self

    @property
    def store(self) -> ResourceStore:
        return self._store

    @property
    def app(self) -> HttpApplication:
        """The application (for getting state)"""
        return self


class User(BaseUser):
    def __init__(self, identity: Identity):
        self._identity = identity

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def display_name(self) -> str:
        return self._identity.actor.get("preferredUsername", "Anonymous")

    @property
    def identity(self) -> str:
        return self._identity.uri

    # awkward naming given starlette property name
    @property
    def firm_identity(self) -> JSONObject:
        return self._identity


class HttpConnectionAdapter(HttpRequest):
    def __init__(self, conn: HTTPConnection, store: ResourceStore):
        self._conn = conn
        self._store = store

    @property
    def method(self) -> HttpMethod:
        """The HTTP method of the request (e.g., 'GET', 'POST')."""
        return self._conn["method"]

    @property
    def url(self) -> Url:
        """The full URL of the request."""
        return self._conn.url

    @property
    def path_params(self) -> Mapping[str, str]:
        """The path parameters of the request."""
        return self._conn.path_params

    @property
    def headers(self) -> MutableMapping[str, str]:
        """The request headers."""
        return self._conn.headers

    @property
    def cookies(self) -> MutableMapping[str, str]:
        """The cookies sent with the request."""
        return self._conn.cookies

    # TODO Remove this?
    @property
    def client(self) -> tuple[str, int] | None:
        """The IP address and port of the client making the request."""
        raise NotImplementedError()

    def stream(self) -> AsyncIterable[bytes]:
        """Asynchronous stream of the request body."""
        raise NotImplementedError()

    def content(self) -> bytes:
        return self._conn.content

    async def body(self) -> bytes:
        """Read the entire request body at once as bytes."""
        return self._conn.content

    async def json(self) -> Mapping[str, Any]:
        """Parse the request body as JSON."""
        return await self._conn.json()

    async def form(self) -> Mapping[str, str]:
        """Parse the request body as form data."""
        raise NotImplementedError()

    async def files(self) -> Mapping[str, Any]:
        """Parse the request body for file uploads."""
        raise NotImplementedError()

    @property
    def auth(self) -> Identity | None:
        """The authentication credentials provided with the request."""
        if isinstance(self._conn, Request) and self._conn.user.is_authenticated:
            return self._conn.user.firm_identity
        return None

    @property
    def state(self) -> HttpApplicationState:
        return self

    @property
    def store(self) -> ResourceStore:
        return self._store

    @property
    def app(self) -> HttpApplication:
        """The application (for getting state)"""
        return self


class AuthenticationBackendAdapter(AuthenticationBackend):
    def __init__(self, authenticator: Authenticator, store: ResourceStore) -> None:
        super().__init__()
        self._authenticator = authenticator
        self._store = store

    async def authenticate(
        self, request: HTTPConnection
    ) -> tuple[AuthCredentials, BaseUser]:
        identity = await self._authenticator.authenticate(
            HttpConnectionAdapter(request, self._store)
        )  # Call the authenticate method
        if identity:
            return AuthCredentials(["authenticated"]), User(identity)
        return AuthCredentials(["unauthenticated"]), UnauthenticatedUser()


class HttpxTransport(HttpTransport):
    def __init__(self, store: ResourceStore):
        self._store = store

    async def get(
        self,
        url: UrlTypes,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        auth: HttpRequestSigner | None = None,
        # proxy: ProxyTypes | None = None,
        # proxies: ProxiesTypes | None = None,
        follow_redirects: bool = False,
        # cert: CertTypes | None = None,
        verify: bool = True,
        timeout: float = DEFAULT_HTTP_TIMEOUT,
        # trust_env: bool = True,
    ) -> HttpResponse:
        async with httpx.AsyncClient(verify=verify) as client:
            response = await client.get(
                url,
                params=params,
                headers=headers,
                cookies=cookies,
                auth=HttpxAuthAdapter(auth, self._store) if auth else None,
                follow_redirects=follow_redirects,
                timeout=timeout,
            )
            return HttpResponse(
                status_code=response.status_code,
                headers=response.headers,
                body=response.content,
                reason_phrase=response.reason_phrase,
            )

    async def post(
        self,
        url: UrlTypes,
        content: str | bytes | Iterable[bytes] | AsyncIterable[bytes] | None = None,
        data: Mapping[str, Any] | None = None,
        # files: RequestFiles | None = None,
        json: JSONObject | None = None,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        auth: HttpRequestSigner = None,
        # proxy: ProxyTypes | None = None,
        # proxies: ProxiesTypes | None = None,
        follow_redirects: bool = False,
        # cert: CertTypes | None = None,
        verify: bool = True,
        timeout: float = DEFAULT_HTTP_TIMEOUT,
        # trust_env: bool = True,
    ) -> HttpResponse:
        async with httpx.AsyncClient(verify=verify) as client:
            response = await client.post(
                url,
                json=data,
                content=content,
                headers=headers,
                cookies=cookies,
                auth=HttpxAuthAdapter(auth, self._store)
                if auth
                else httpx.USE_CLIENT_DEFAULT,
                follow_redirects=follow_redirects,
                timeout=timeout,
            )
            return HttpResponse(
                status_code=response.status_code,
                headers=response.headers,
                body=response.content,
                reason_phrase=response.reason_phrase,
            )
