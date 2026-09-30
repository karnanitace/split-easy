"""Typer application that defines the ``spliteasy`` command and its subcommands.

The root callback opens a :class:`~spliteasy.services.GroupService` on the
database chosen with ``--db`` (or the ``SPLITEASY_DB`` environment variable)
and stores it in ``ctx.obj`` for the subcommands. The service is closed when
the command finishes.

Errors raised on purpose by SplitEasy (:class:`~spliteasy.exceptions.SplitEasyError`)
are shown as a short red message with exit code 1 instead of a traceback. This
is handled once, in :class:`SplitEasyGroup`, for every subcommand.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.markup import escape
from typer.core import TyperGroup

from spliteasy import __version__
from spliteasy.cli.expense_cmds import expense_app, pay, settle, show_balance
from spliteasy.cli.group_cmds import group_app, member_app
from spliteasy.exceptions import SplitEasyError
from spliteasy.services import GroupService
from spliteasy.storage import SQLiteRepository
from spliteasy.storage.sqlite import DB_ENV_VAR

console = Console()
error_console = Console(stderr=True)


@contextmanager
def handle_errors() -> Iterator[None]:
    """Turns SplitEasy errors into a red message and exit code 1.

    Raises:
        typer.Exit: With code 1 if the block raises a ``SplitEasyError``.
    """
    try:
        yield
    except SplitEasyError as err:
        error_console.print(f"[bold red]Error:[/] {escape(str(err))}")
        raise typer.Exit(code=1) from err


class SplitEasyGroup(TyperGroup):
    """Root command group that reports SplitEasy errors without a traceback."""

    def invoke(self, ctx: Any) -> Any:
        """Runs the group and its subcommand inside :func:`handle_errors`.

        Args:
            ctx: The Typer context of the root command.

        Returns:
            Whatever the invoked subcommand returns.
        """
        with handle_errors():
            return super().invoke(ctx)


app = typer.Typer(
    name="spliteasy",
    cls=SplitEasyGroup,
    help=(
        "SplitEasy: track shared expenses in groups and settle up with the "
        "minimum number of payments."
    ),
    no_args_is_help=True,
)
app.add_typer(group_app)
app.add_typer(member_app)
app.add_typer(expense_app)
app.command("balance")(show_balance)
app.command("settle")(settle)
app.command("pay")(pay)


@app.callback()
def main(
    ctx: typer.Context,
    db: Annotated[
        Path | None,
        typer.Option(
            "--db",
            envvar=DB_ENV_VAR,
            help="SQLite database file. Defaults to ~/.spliteasy/spliteasy.db.",
        ),
    ] = None,
) -> None:
    """Track shared expenses in groups and settle up with minimal payments."""
    # `version` needs no database, so it must not create one.
    if ctx.invoked_subcommand == "version":
        return
    service = GroupService(SQLiteRepository(db))
    ctx.obj = service
    ctx.call_on_close(service.close)


@app.command()
def version() -> None:
    """Show the installed SplitEasy version."""
    console.print(f"SplitEasy {__version__}")
