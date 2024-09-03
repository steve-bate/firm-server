from importlib import import_module

from . import cli

import_module("firm_server.cli.serve")
import_module("firm_server.cli.actor")
import_module("firm_server.cli.resource")

if __name__ == "__main__":
    cli()
