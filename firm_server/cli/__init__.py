import logging
from dataclasses import dataclass

import click
import coloredlogs
import dotenv
from firm.interfaces import ResourceStore

import firm_server.store as server_store
from firm_server.config import ServerConfig, load_config
from firm_server.store import STORE_DRIVERS, StoreDriver

dotenv.load_dotenv()

log = logging.root


@dataclass
class Context:
    store: ResourceStore
    store_driver: StoreDriver
    config: ServerConfig


@click.group(context_settings=dict(auto_envvar_prefix="FIRM"))
@click.option("--config", type=click.File("r"), envvar="FIRM_CONFIG")
@click.option(
    "--storage",
    "storage_key",
    type=click.Choice(STORE_DRIVERS),
    default="filesystem",
    show_default=True,
)
@click.pass_context
def cli(ctx: click.Context, config: click.File, storage_key: str):
    """FIRM - Federated Information Resource Manager

    To get subcommand help, use '<subcommand> --help'
    """
    coloredlogs.install()
    if storage_key not in server_store.STORE_DRIVERS:
        raise click.BadParameter(f"Unknown storage type: {storage_key}")
    log.info("Using storage driver: %s", storage_key)
    store_driver = server_store.STORE_DRIVERS[storage_key]
    server_config = load_config(config)
    store = store_driver.open(server_config)
    ctx.obj = Context(store, store_driver, server_config)


@cli.result_callback()
@click.pass_obj
def after_command(ctx: Context, result, **kwargs):
    # TODO Change this to use storage driver
    if driver := ctx.store_driver:
        driver.close()
        log.info("resource store closed")


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
