import typer

from core.mcp_client import MCPClient

transactions_app = typer.Typer(no_args_is_help=True, add_completion=False, help='Bank/card transactions parsed from messages')


def register(root: typer.Typer) -> None:
    root.add_typer(transactions_app, name='transactions')


@transactions_app.command(help='Replay every inbox message through the parser on the server (no alerts; idempotent).')
def backfill(ctx: typer.Context):
    print(MCPClient.from_config(ctx.obj.config).call('transactions_backfill'))


@transactions_app.command(name='list', help='List recorded transactions for a month (YYYY-MM, default current).')
def list_transactions(ctx: typer.Context, month: str = typer.Argument(None, help='YYYY-MM')):
    print(MCPClient.from_config(ctx.obj.config).call('transactions_list', month=month))
