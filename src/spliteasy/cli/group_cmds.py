"""CLI commands for managing groups and their members.

Two sub-apps are defined here and registered in :mod:`spliteasy.cli.app`:
``spliteasy group ...`` and ``spliteasy member ...``. Every command gets the
:class:`~spliteasy.services.GroupService` from ``ctx.obj``, calls one service
method and prints the result. Errors are reported by the root app.
"""

from decimal import Decimal
from typing import Annotated

import typer
from rich import box
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from spliteasy.money import format_money
from spliteasy.services import GroupService

console = Console()

group_app = typer.Typer(
    name="group", help="Create, list and delete groups.", no_args_is_help=True
)
member_app = typer.Typer(
    name="member", help="Add and remove group members.", no_args_is_help=True
)


def _service(ctx: typer.Context) -> GroupService:
    """Returns the service opened by the root command."""
    return ctx.obj


def _names(names: list[str]) -> str:
    """Formats member names for display, or a dash if there are none."""
    return escape(", ".join(names)) if names else "-"


@group_app.command("create")
def create_group(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Name of the new group.")],
    currency: Annotated[
        str, typer.Option("--currency", "-c", help="Currency of all balances.")
    ] = "EUR",
    members: Annotated[
        list[str] | None,
        typer.Option("--member", "-m", help="Initial member. Repeat to add several."),
    ] = None,
) -> None:
    """Create a new group."""
    group = _service(ctx).create_group(name, currency, members or [])
    console.print(
        f"Created group [bold]{escape(group.name)}[/] ({group.currency}) "
        f"with members: {_names(group.member_names)}"
    )


@group_app.command("list")
def list_groups(ctx: typer.Context) -> None:
    """List all groups."""
    service = _service(ctx)
    names = service.list_groups()
    if not names:
        console.print("No groups yet. Create one with: spliteasy group create NAME")
        return

    table = Table(title="Groups", box=box.ASCII)
    table.add_column("Name")
    table.add_column("Currency")
    table.add_column("Members")
    table.add_column("Expenses", justify="right")
    for name in names:
        ledger = service.get_ledger(name)
        table.add_row(
            escape(ledger.group.name),
            ledger.group.currency,
            _names(ledger.group.member_names),
            str(len(ledger.expenses)),
        )
    console.print(table)


@group_app.command("delete")
def delete_group(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Name of the group to delete.")],
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Delete without asking for confirmation."),
    ] = False,
) -> None:
    """Delete a group with all of its expenses and payments."""
    service = _service(ctx)
    stored_name = service.get_ledger(name).group.name
    if not yes:
        typer.confirm(
            f"Delete group '{stored_name}' with all of its expenses and payments?",
            abort=True,
        )
    service.delete_group(stored_name)
    console.print(f"Deleted group [bold]{escape(stored_name)}[/].")


@group_app.command("show")
def show_group(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Name of the group.")],
) -> None:
    """Show a group's members, number of expenses and total spent."""
    ledger = _service(ctx).get_ledger(name)
    group = ledger.group
    total = sum(
        (expense.base_amount(group.currency) for expense in ledger.expenses),
        Decimal(0),
    )
    console.print(f"[bold]{escape(group.name)}[/] ({group.currency})")
    console.print(f"Members:     {_names(group.member_names)}")
    console.print(f"Expenses:    {len(ledger.expenses)}")
    console.print(f"Total spent: {format_money(total, group.currency)}")


@member_app.command("add")
def add_members(
    ctx: typer.Context,
    group: Annotated[str, typer.Argument(help="Name of the group.")],
    names: Annotated[list[str], typer.Argument(help="Names of the new members.")],
) -> None:
    """Add one or more members to a group."""
    service = _service(ctx)
    added = service.add_members(group, names)
    group_name = service.get_ledger(group).group.name
    console.print(
        f"Added {_names([member.name for member in added])} "
        f"to [bold]{escape(group_name)}[/]."
    )


@member_app.command("remove")
def remove_member(
    ctx: typer.Context,
    group: Annotated[str, typer.Argument(help="Name of the group.")],
    name: Annotated[str, typer.Argument(help="Name of the member to remove.")],
) -> None:
    """Remove a member who has no balance and no expenses or payments."""
    service = _service(ctx)
    stored_group = service.get_ledger(group).group
    stored_name = stored_group.resolve_name(name)
    service.remove_member(group, name)
    console.print(
        f"Removed {escape(stored_name)} from [bold]{escape(stored_group.name)}[/]."
    )
