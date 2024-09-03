import logging
import mimetypes
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from firm.interfaces import (
    FIRM_NS,
    HttpRequest,
    HttpResponse,
    ResourceStore,
    get_url_prefix,
)
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
            request_file_path = request.path_params["file_path"]
            for static_dir in static_dirs:
                file_path = os.path.join(static_dir, request_file_path)
                if os.path.exists(file_path):
                    mime_type, _ = mimetypes.guess_type(file_path)
                    mime_type = mime_type or "application/octet-stream"
                    return FileResponse(file_path, media_type=mime_type)
        return Response("File not found", status_code=404)

    return _static_endpoint


# TODO extend the document list
# TODO Move to core utils?
DOCUMENT_TYPES = ["Note", "Article", "Document"]


async def _create_timeline(uris: list[str], store: ResourceStore):
    observed_resources = set()
    timeline = []
    for uri in uris:
        activity = await store.get(uri)
        obj = activity.get("object")
        if isinstance(obj, str):
            obj = await store.get(obj)
        if (
            obj
            and obj["id"] not in observed_resources
            and obj.get("type") in DOCUMENT_TYPES
        ):
            if activity.get("type") in ["Create", "Update"]:
                timeline.append(obj)
                observed_resources.add(obj["id"])
                if len(timeline) >= 10:
                    break
    return timeline


async def _actor_context(uri: str, store: ResourceStore):
    context = {}
    credentials = await store.query_one(
        {
            "@prefix": "urn:",
            "type": FIRM_NS.Credentials.value,
            "attributedTo": uri,
        }
    )
    context["roles"] = credentials.get(FIRM_NS.role.value) if credentials else []
    actor = await store.get(uri)
    outbox = await store.get(actor["outbox"])
    timeline = await _create_timeline(outbox.get("orderedItems", []), store)
    context["timeline"] = timeline
    return context


@dataclass
class TemplateConfig:
    template: str
    context: Callable[[str, ResourceStore], Awaitable[dict[str, Any]]] | None = None


ACTOR_TEMPLATE = TemplateConfig("actor.jinja2", _actor_context)
DOCUMENT_TEMPLATE = "document.jinja2"

RESOURCE_TEMPLATES: dict[str, TemplateConfig | str] = {
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
                if template_config := RESOURCE_TEMPLATES.get(resource.get("type")):
                    if isinstance(template_config, str):
                        template_config = TemplateConfig(template_config)
                    context = dict(
                        request=request,
                        get_version=get_version,
                        resource=resource,
                    )
                    if template_config.context:
                        context.update(
                            await template_config.context(str(request.url), store)
                        )
                    return templates.TemplateResponse(template_config.template, context)
                return JSONResponse(resource)

    return _endpoint
