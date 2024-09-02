import asyncio
import logging
import ssl
from typing import IO

import click
import dotenv
import uvicorn
from colorama import Fore, Style

from firm_server.exceptions import ServerException
from firm_server.server import run

dotenv.load_dotenv()

log = logging.root


@click.group(context_settings=dict(auto_envvar_prefix="FIRM"))
def cli():
    """FIRM - Federated Information Resource Manager

    To get subcommand help, use '<subcommand> --help'
    """


def print_banner() -> None:
    banner = """\
 _____ ___ ____  __  __
|  ___|_ _|  _ \|  \/  |
| |_   | || |_) | |\/| |
|  _|  | ||  _ <| |  | |
|_|   |___|_| \_\_|  |_|
"""
    print(Fore.LIGHTGREEN_EX + banner + Style.RESET_ALL)
    # for line in banner.splitlines():
    #     log.info(line)


class LiteralChoice(click.ParamType):
    name = "literal"

    def __init__(self, literal):
        self.values = literal.__args__

    def convert(self, value, param, ctx):
        if value in self.values:
            return value
        self.fail(
            f'{value} is not a valid choice. Choose from {", ".join(self.values)}.',
            param,
            ctx,
        )


@cli.command
@click.option("--host", metavar="HOST", default="0.0.0.0", show_default=True)
@click.option("--port", metavar="PORT", type=int, default="7000", show_default=True)
@click.option(
    "--config",
    type=click.File(),
    default="firm.json",
    metavar="FILEPATH",
    show_default=True,
)
@click.option(
    "--verbose",
    "-v",
    type=bool,
    is_flag=True,
    default=False,
    show_default=True,
)
@click.option(
    "--loop",
    type=LiteralChoice(uvicorn.config.LoopSetupType),
    default="auto",
    show_default=True,
)
@click.option(
    "--http",
    type=LiteralChoice(uvicorn.config.HTTPProtocolType),
    default="auto",
    show_default=True,
)
@click.option("--ws-max-size", type=int, default=(16 * 1024 * 1024), show_default=True)
@click.option("--ws-max-queue", type=int, default=32, show_default=True)
@click.option("--ws-ping-interval", type=float, default=20.0, show_default=True)
@click.option("--ws-ping-timeout", type=float, default=20.0, show_default=True)
@click.option(
    "--ws-per-message-deflate",
    type=bool,
    is_flag=True,
    default=True,
    show_default=True,
)
@click.option(
    "--interface",
    type=LiteralChoice(uvicorn.config.InterfaceType),
    default="auto",
    show_default=True,
)
@click.option(
    "--proxy-headers",
    type=bool,
    is_flag=True,
    default=True,
    show_default=True,
)
@click.option(
    "--server-header",
    type=bool,
    is_flag=True,
    default=True,
    show_default=True,
)
@click.option("--date-header", type=bool, is_flag=True, default=True, show_default=True)
@click.option("--limit-concurrency", type=int, default=None, show_default=True)
@click.option("--limit-max-requests", type=int, default=None, show_default=True)
@click.option("--backlog", type=int, default=2048, show_default=True)
@click.option("--timeout-keep-alive", type=int, default=5, show_default=True)
@click.option("--timeout-notify", type=int, default=30, show_default=True)
@click.option("--timeout-graceful-shutdown", type=int, default=None, show_default=True)
@click.option("--ssl-keyfile", type=str, default=None, show_default=True)
@click.option("--ssl-certfile", type=str, default=None, show_default=True)
@click.option("--ssl-keyfile-password", type=str, default=None, show_default=True)
@click.option(
    "--ssl-version",
    type=int,
    default=uvicorn.config.SSL_PROTOCOL_VERSION,
    show_default=True,
)
@click.option("--ssl-cert-reqs", type=int, default=ssl.CERT_NONE, show_default=True)
@click.option("--ssl-ca-certs", type=str, default=None, show_default=True)
@click.option("--ssl-ciphers", type=str, default="TLSv1", show_default=True)
@click.option(
    "--h11-max-incomplete-event-size",
    type=int,
    default=None,
    show_default=True,
)
@click.option("--no-banner", type=bool, is_flag=True, default=False, show_default=True)
def server(config: IO, verbose: bool, no_banner: bool, **kwargs):
    """Run the FIRM server"""
    try:
        if not no_banner:
            print_banner()
        run(config, verbose, kwargs)
    except (asyncio.exceptions.CancelledError, KeyboardInterrupt):
        pass
    except ServerException as ex:
        logging.log(ex.level, ex.message)
        raise SystemExit(1)


if __name__ == "__main__":
    cli()
