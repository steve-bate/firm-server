import logging
import mimetypes
import os
from urllib.parse import urlparse

from firm.interfaces import HttpRequest, HttpResponse, get_url_prefix
from firm.util import get_version
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.templating import Jinja2Templates

from firm_server.config import ServerConfig

log = logging.getLogger(__name__)

STATIC_DIR = "firm_server/html/static"


def html_static_endpoint(config: ServerConfig):
    tenant_static_dirs = {}
    for tenant in config.tenants:
        prefix = urlparse(tenant)
        static_dir = os.path.join(
            "firm_server/html/tenants", prefix.hostname or "", "static"
        )
        tenant_static_dirs[tenant] = (
            [static_dir, STATIC_DIR] if os.path.exists(static_dir) else [STATIC_DIR]
        )

    async def _static_endpoint(request: Request):
        prefix = get_url_prefix(str(request.url))
        if static_dirs := tenant_static_dirs.get(prefix):
            file_path = request.path_params["file_path"]
            for static_dir in static_dirs:
                file_path = os.path.join(static_dir, file_path)
                if os.path.exists(file_path):
                    mime_type, _ = mimetypes.guess_type(file_path)
                    mime_type = mime_type or "application/octet-stream"
                    return FileResponse(file_path, media_type=mime_type)
        return Response("File not found", status_code=404)

    return _static_endpoint


ACTOR_TEMPLATE = "actor.jinja2"
DOCUMENT_TEMPLATE = "document.jinja2"

RESOURCE_TEMPLATES = {
    "Person": ACTOR_TEMPLATE,
    "Organization": ACTOR_TEMPLATE,
    "Group": ACTOR_TEMPLATE,
    "Application": ACTOR_TEMPLATE,
    "Service": ACTOR_TEMPLATE,
    "Note": DOCUMENT_TEMPLATE,
}


def _configure_tenant_templates(config: ServerConfig):
    tenant_templates = {}
    for tenant in config.tenants:
        default_templates = Jinja2Templates(directory="firm_server/html/templates")
        prefix = urlparse(tenant)
        templates_dir = os.path.join(
            "firm_server/html/tenants", prefix.hostname or "", "templates"
        )
        tenant_templates[tenant] = (
            Jinja2Templates(directory=[templates_dir, "firm_server/html/templates"])
            if os.path.exists(templates_dir)
            else default_templates
        )
    return tenant_templates


def html_endpoint(config: ServerConfig):
    tenant_templates = _configure_tenant_templates(config)

    async def _endpoint(request: HttpRequest) -> HttpResponse:
        uri = str(request.url)
        if uri.endswith("/"):
            uri = uri[:-1]
        prefix = get_url_prefix(uri)
        templates = tenant_templates.get(prefix)
        if uri == prefix:
            # store = request.app.state.store
            # resource = await store.get(str(request.url))
            # if not resource:
            return templates.TemplateResponse(
                "home.jinja2",
                dict(
                    request=request,
                    get_version=get_version,
                ),
            )
        elif request.url.path == "/login":
            return templates.TemplateResponse(
                "login.jinja2",
                dict(
                    request=request,
                    get_version=get_version,
                ),
            )
        else:
            store = request.app.state.store
            resource = await store.get(str(request.url))
            if not resource:
                return Response("Resource not found", status_code=404)
            else:
                if template := RESOURCE_TEMPLATES.get(resource.get("type")):
                    return templates.TemplateResponse(
                        template,
                        dict(
                            request=request,
                            get_version=get_version,
                            resource=resource,
                        ),
                    )
                return JSONResponse(resource)

    return _endpoint
