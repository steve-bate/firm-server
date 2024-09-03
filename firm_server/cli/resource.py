import json
from typing import IO

import click

from firm_server.utils import async_command

from . import Context, cli


@cli.group
def resource():
    """Resource management"""


@resource.command("add")
@click.argument("file", type=click.File("r"))
@click.pass_obj
@async_command
async def add_resource(ctx: Context, file: IO) -> None:
    """Add a resource from a file."""
    store = ctx.store
    resource = json.loads(file.read())
    if "id" not in resource:
        raise click.ClickException("Resource missing 'id' field")
    await store.put(resource)


@resource.command("remove")
@click.argument("uri")
@click.pass_obj
@async_command
async def remove_resource(ctx: Context, uri: str) -> None:
    """Remove a resource"""
    store = ctx.store
    await store.remove(uri)


@resource.command("get")
@click.argument("uri")
@click.pass_obj
@async_command
async def get_resource(ctx: Context, uri: str) -> None:
    """Get a resource"""
    store = ctx.store
    resource = await store.get(uri)
    print(json.dumps(resource, indent=2))


@resource.command("query")
@click.pass_obj
@click.option("--prefix", "prefix")
@click.option("--type", "resource_type")
@async_command
async def resource_query(
    ctx: Context, resource_type: str | None, prefix: str | None
) -> None:
    """Query resources"""
    store = ctx.store
    query = {}
    if prefix:
        query["@prefix"] = prefix
    if resource_type:
        query["type"] = resource_type
    resources = await store.query(query)
    print(json.dumps(resources, indent=2))


if __name__ == "__main__":
    resource()
