import asyncio
import contextlib
import logging
import typing

import coloredlogs
import uvicorn
from starlette.applications import Starlette

from firm_server.config import ServerConfig, load_config
from firm_server.routes import get_routes
from firm_server.store import get_store, initialize_store

log = logging.getLogger(__name__ if __name__ != "__main__" else "firm_server.main")

_app = None


def app_factory(config: ServerConfig) -> Starlette:
    global _app
    if _app is None:

        @contextlib.asynccontextmanager
        async def lifespan(app):
            log.info("ASGI lifespan: starting")

            # context = await context_factory(config())
            # app.state.context = context
            app.state.store = get_store()

            yield

            log.info("ASGI lifespan: stopping")

        _app = Starlette(routes=get_routes(config), lifespan=lifespan)
    return _app


class FirmServer(uvicorn.Server):
    tasks: list[asyncio.Task] = []

    """Customized uvicorn.Server
    Uvicorn server overrides signals """

    def handle_exit(self, sig: int, frame) -> None:
        # Stop all tasks
        for task in self.tasks:
            if task != self:
                task.cancel()
        return super().handle_exit(sig, frame)


async def async_run(config_stream: typing.IO, verbose: bool, kwargs) -> None:
    coloredlogs.install(level=logging.DEBUG if verbose else logging.INFO)

    config = load_config(config_stream)
    logging.debug("config: %s", config)

    initialize_store(config)

    def app_factory_with_config() -> Starlette:
        return app_factory(config)

    try:
        logging.getLogger("uvicorn.error").name = "uvicorn"
        server = FirmServer(
            config=uvicorn.Config(
                app_factory_with_config,
                factory=True,
                log_config=None,
                forwarded_allow_ips="*",
                **kwargs,
            )
        )
        server.tasks = list(
            map(
                asyncio.create_task,
                [server.serve()],
            )
        )
        done, _ = await asyncio.wait(server.tasks)
        for d in done:
            if d.exception() is not None:
                raise d.exception()  # type: ignore
    finally:
        log.info("Server shutdown")
        try:
            await server.shutdown()
        except:  # noqa
            pass
        logging.getLogger("uvicorn.error").setLevel(logging.CRITICAL)


def run(config: typing.IO, verbose: bool, kwargs):
    asyncio.run(async_run(config, verbose, kwargs))
