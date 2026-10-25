from pathlib import Path

import typer

from core.mcp_client import MCPClient
from transactions import statements

transactions_app = typer.Typer(no_args_is_help=True, add_completion=False, help='Bank/card transactions parsed from messages')


def register(root: typer.Typer) -> None:
    root.add_typer(transactions_app, name='transactions')


@transactions_app.command(help='Replay every inbox message through the parser on the server (no alerts; idempotent).')
def backfill(ctx: typer.Context):
    print(MCPClient.from_config(ctx.obj.config).call('transactions_backfill'))


@transactions_app.command(name='list', help='List recorded transactions for a month (YYYY-MM, default current).')
def list_transactions(ctx: typer.Context, month: str = typer.Argument(None, help='YYYY-MM')):
    print(MCPClient.from_config(ctx.obj.config).call('transactions_list', month=month))


@transactions_app.command(name='statement-lines', help='Print transfer lines from unlocked bank statement PDFs as JSON lines.')
def statement_lines(folders: list[Path] = typer.Argument(..., help='Folders holding unlocked statement PDFs')):
    for folder in folders:
        for path in sorted(folder.glob('*.pdf')):
            for line in statements.parse(path):
                print(line.model_dump_json())
