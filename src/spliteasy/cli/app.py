"""Typer application that defines the ``spliteasy`` command and its subcommands.

The root callback opens a :class:`~spliteasy.services.GroupService` on the
database chosen with ``--db`` (or the ``SPLITEASY_DB`` environment variable)
and stores it in ``ctx.obj`` for the subcommands. The service is closed when
the command finishes.

Errors raised on purpose by SplitEasy (:class:`~spliteasy.exceptions.SplitEasyError`)
are shown as a short red message with exit code 1 instead of a traceback. This
is handled once, in :class:`SplitEasyGroup`, for every subcommand.
"""

import re
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.markup import escape
from typer.core import TyperGroup

from spliteasy import __version__
from spliteasy.cli.expense_cmds import expense_app, pay, settle, show_balance
from spliteasy.cli.group_cmds import group_app, member_app
from spliteasy.demo import DEMO_GROUPS, ITALY_TRIP, create_demo_data
from spliteasy.exceptions import SplitEasyError
from spliteasy.reports.charts import (
    plot_balances,
    plot_categories,
    plot_member_spending,
)
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


@app.command()
def demo(
    ctx: typer.Context,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes", "-y", help="Replace existing demo groups without asking."
        ),
    ] = False,
) -> None:
    """Create two example groups to explore SplitEasy with."""
    service: GroupService = ctx.obj
    existing = {name.casefold(): name for name in service.list_groups()}
    replaced = [
        existing[name.casefold()] for name in DEMO_GROUPS if name.casefold() in existing
    ]
    if replaced and not yes:
        typer.confirm(
            f"Replace the existing groups {', '.join(replaced)} with demo data?",
            abort=True,
        )

    groups = create_demo_data(service)
    console.print(f"Created demo groups: {', '.join(groups)}")
    console.print()
    show_balance(ctx, ITALY_TRIP)
    console.print()
    console.print(f"Suggested settlement for {ITALY_TRIP}:")
    settle(ctx, ITALY_TRIP)
    console.print()
    console.print("Try next:")
    for command in (
        "spliteasy group list",
        'spliteasy expense list "Italy Trip" --category food',
        "spliteasy balance Flat",
        "spliteasy settle Flat",
        'spliteasy pay "Italy Trip" --from Dan --to Steve --amount 272.02',
    ):
        console.print(f"  {command}", markup=False)


class ChartType(str, Enum):
    """The charts that ``spliteasy chart`` can draw."""

    BALANCES = "balances"
    CATEGORIES = "categories"
    MEMBERS = "members"


def default_chart_path(group: str, chart_type: ChartType) -> Path:
    """Returns the default file for a chart, such as ``italy-trip-balances.png``.

    Args:
        group: The group name.
        chart_type: The kind of chart.

    Returns:
        A path in the current folder, named after the group and chart type.
        The name uses only lower-case ASCII letters, digits and hyphens;
        accented letters are transliterated (``"Zoë"`` becomes ``"zoe"``).
    """
    ascii_name = unicodedata.normalize("NFKD", group).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-") or "group"
    return Path(f"{slug}-{chart_type.value}.png")


@app.command()
def chart(
    ctx: typer.Context,
    group: Annotated[str, typer.Argument(help="Name of the group.")],
    chart_type: Annotated[
        ChartType,
        typer.Option("--type", "-t", help="Which chart to draw."),
    ] = ChartType.BALANCES,
    out: Annotated[
        Path | None,
        typer.Option(
            "--out",
            "-o",
            help="PNG file to write. Default: GROUP-TYPE.png in the current folder.",
        ),
    ] = None,
) -> None:
    """Save a chart of a group's balances, categories or members as PNG."""
    service: GroupService = ctx.obj
    ledger = service.get_ledger(group)
    currency = ledger.group.currency
    path = out if out is not None else default_chart_path(ledger.group.name, chart_type)

    if chart_type is ChartType.BALANCES:
        saved = plot_balances(service.balances(group), currency, path)
    elif chart_type is ChartType.CATEGORIES:
        saved = plot_categories(ledger.expenses, currency, path)
    else:
        saved = plot_member_spending(service.summary(group), currency, path)
    console.print(f"Saved chart to {escape(str(saved.resolve()))}")
