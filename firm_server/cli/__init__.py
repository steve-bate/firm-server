import logging
from dataclasses import dataclass

import click
import coloredlogs
import dotenv
from firm.interfaces import ResourceStore

from firm_server.config import ServerConfig, load_config
from firm_server.store import initialize_store

dotenv.load_dotenv()

log = logging.root


@dataclass
class Context:
    store: ResourceStore
    config: ServerConfig


@click.group(context_settings=dict(auto_envvar_prefix="FIRM"))
@click.option("--config", type=click.File("r"), envvar="FIRM_CONFIG")
@click.pass_context
def cli(ctx: click.Context, config: click.File):
    """FIRM - Federated Information Resource Manager

    To get subcommand help, use '<subcommand> --help'
    """
    config_data = load_config(config)
    store = initialize_store(config_data)
    ctx.obj = Context(store, config_data)
    coloredlogs.install()


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
