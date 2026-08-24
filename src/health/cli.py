import typer

from core.mcp_client import MCPClient

item_app = typer.Typer(no_args_is_help=True, add_completion=False, help='Read item data (edits go through MCP)')


def register(root: typer.Typer) -> None:
    root.command(help='Print the health plan as JSON (read via MCP).')(report)
    root.add_typer(item_app, name='item')


def report(ctx: typer.Context):
    print(MCPClient.from_config(ctx.obj.config).call('report'))


@item_app.command(help='Print a single field from an item file (read via MCP).')
def get(ctx: typer.Context, key: str, field: str):
    print(MCPClient.from_config(ctx.obj.config).call('item_get', key=key, field=field))


@item_app.command(name='list', help='List item keys, optionally by kind/category (read via MCP).')
def list_items(
    ctx: typer.Context,
    kind: str = typer.Option(None, help='edible, clothing, durable'),
    category: str = typer.Option(None, help='e.g. snack, supplement, topwear'),
):
    print(MCPClient.from_config(ctx.obj.config).call('item_list', kind=kind, category=category))
