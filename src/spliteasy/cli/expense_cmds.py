"""CLI commands for expenses, balances, settling up and payments.

``spliteasy expense ...`` is a sub-app; ``balance``, ``settle`` and ``pay``
are top-level commands registered in :mod:`spliteasy.cli.app`. Every command
gets the :class:`~spliteasy.services.GroupService` from ``ctx.obj``, calls the
service and prints the result. Errors are reported by the root app.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated

import typer
from rich import box
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from spliteasy.cli.parsing import parse_values
from spliteasy.models import Expense
from spliteasy.money import format_money
from spliteasy.services import GroupService

console = Console()

expense_app = typer.Typer(
    name="expense", help="Add, list and delete expenses.", no_args_is_help=True
)

DATE_FORMATS = ["%Y-%m-%d"]


def _service(ctx: typer.Context) -> GroupService:
    """Returns the service opened by the root command."""
    return ctx.obj


def balance_markup(amount: Decimal, text: str) -> str:
    """Colours a formatted balance: green if positive, red if negative.

    Args:
        amount: The balance.
        text: The balance, already formatted for display.

    Returns:
        The text with rich colour markup, or unchanged for a zero balance.
    """
    if amount > 0:
        return f"[green]{text}[/]"
    if amount < 0:
        return f"[red]{text}[/]"
    return text


# expense


@expense_app.command("add")
def add_expense(
    ctx: typer.Context,
    group: Annotated[str, typer.Argument(help="Name of the group.")],
    description: Annotated[str, typer.Argument(help="What the expense was for.")],
    amount: Annotated[str, typer.Argument(help="Amount paid, e.g. 12.50.")],
    paid_by: Annotated[str, typer.Option("--paid-by", "-p", help="Member who paid.")],
    split: Annotated[
        str,
        typer.Option(
            "--split", "-s", help="Split method: equal, exact, percentage or shares."
        ),
    ] = "equal",
    among: Annotated[
        list[str] | None,
        typer.Option(
            "--among",
            help="Participant of an equal split. Repeat for several; "
            "default is everyone.",
        ),
    ] = None,
    values: Annotated[
        str | None,
        typer.Option(
            "--values",
            help='Values for exact, percentage or shares splits, e.g. "A=40,B=30".',
        ),
    ] = None,
    currency: Annotated[
        str | None,
        typer.Option("--currency", help="Currency of the amount. Default: group's."),
    ] = None,
    rate: Annotated[
        str | None,
        typer.Option("--rate", help="Exchange rate to the group currency."),
    ] = None,
    category: Annotated[
        str, typer.Option("--category", help="Expense category.")
    ] = "other",
    date: Annotated[
        datetime | None,
        typer.Option("--date", formats=DATE_FORMATS, help="Date as YYYY-MM-DD."),
    ] = None,
    note: Annotated[str, typer.Option("--note", help="Optional note.")] = "",
) -> None:
    """Add an expense and show how it was split."""
    service = _service(ctx)
    expense = service.add_expense(
        group,
        description,
        amount,
        paid_by,
        split=split.strip().lower(),
        participants=among or [],
        split_values=parse_values(values) if values is not None else None,
        currency=currency,
        rate=rate,
        category=category,
        date=date.date() if date is not None else None,
        note=note,
    )
    group_currency = service.get_ledger(group).group.currency
    _print_added_expense(expense, group_currency)


def _print_added_expense(expense: Expense, group_currency: str) -> None:
    """Prints a confirmation and the table of computed shares."""
    paid = format_money(expense.amount, expense.currency)
    if expense.currency != group_currency:
        converted = format_money(expense.base_amount(group_currency), group_currency)
        paid = f"{paid} at rate {expense.rate_to_base} = {converted}"
    console.print(
        f"Added expense #{expense.id}: {escape(expense.description)} "
        f"({paid}, paid by {escape(expense.payer)})"
    )

    table = Table(title="Shares", box=box.ASCII)
    table.add_column("Member")
    table.add_column("Share", justify="right")
    for share in expense.shares:
        table.add_row(escape(share.member), format_money(share.amount, group_currency))
    console.print(table)


@expense_app.command("list")
def list_expenses(
    ctx: typer.Context,
    group: Annotated[str, typer.Argument(help="Name of the group.")],
    member: Annotated[
        str | None,
        typer.Option(
            "--member", help="Only expenses paid by or shared by this member."
        ),
    ] = None,
    category: Annotated[
        str | None, typer.Option("--category", help="Only this category.")
    ] = None,
) -> None:
    """List a group's expenses, oldest first."""
    expenses = _service(ctx).list_expenses(group, member=member, category=category)
    if not expenses:
        console.print("No expenses found.")
        return

    table = Table(title="Expenses", box=box.ASCII)
    table.add_column("ID", justify="right")
    table.add_column("Date")
    table.add_column("Description")
    table.add_column("Category")
    table.add_column("Paid by")
    table.add_column("Amount", justify="right")
    table.add_column("Currency")
    for expense in expenses:
        table.add_row(
            str(expense.id),
            expense.date.isoformat(),
            escape(expense.description),
            escape(expense.category),
            escape(expense.payer),
            format_money(expense.amount, expense.currency),
            expense.currency,
        )
    console.print(table)


@expense_app.command("delete")
def delete_expense(
    ctx: typer.Context,
    group: Annotated[str, typer.Argument(help="Name of the group.")],
    expense_id: Annotated[int, typer.Argument(help="ID of the expense.")],
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Delete without asking for confirmation."),
    ] = False,
) -> None:
    """Delete an expense."""
    service = _service(ctx)
    expense = service.get_ledger(group).get_expense(expense_id)
    label = (
        f"#{expense.id} {expense.description} "
        f"({format_money(expense.amount, expense.currency)})"
    )
    if not yes:
        typer.confirm(f"Delete expense {label}?", abort=True)
    service.delete_expense(group, expense_id)
    console.print(f"Deleted expense {escape(label)}.")


# balance, settle, pay


def show_balance(
    ctx: typer.Context,
    group: Annotated[str, typer.Argument(help="Name of the group.")],
) -> None:
    """Show what every member paid, owes and their net balance."""
    service = _service(ctx)
    currency = service.get_ledger(group).group.currency
    summary = service.summary(group)

    table = Table(title="Balances", box=box.ASCII)
    table.add_column("Member")
    table.add_column("Paid", justify="right")
    table.add_column("Owed", justify="right")
    table.add_column("Balance", justify="right")
    for member, totals in summary.items():
        balance = totals["balance"]
        table.add_row(
            escape(member),
            format_money(totals["paid"], currency),
            format_money(totals["owed"], currency),
            balance_markup(balance, format_money(balance, currency)),
        )
    console.print(table)


def settle(
    ctx: typer.Context,
    group: Annotated[str, typer.Argument(help="Name of the group.")],
) -> None:
    """Suggest the payments that settle all balances."""
    service = _service(ctx)
    currency = service.get_ledger(group).group.currency
    transfers = service.suggest_settlement(group)
    if not transfers:
        console.print("Everyone is settled up.")
        return
    for transfer in transfers:
        console.print(
            f"{escape(transfer.debtor)} -> {escape(transfer.creditor)}: "
            f"{format_money(transfer.amount, currency)}"
        )


def pay(
    ctx: typer.Context,
    group: Annotated[str, typer.Argument(help="Name of the group.")],
    from_member: Annotated[
        str, typer.Option("--from", help="Member who sent the money.")
    ],
    to_member: Annotated[
        str, typer.Option("--to", help="Member who received the money.")
    ],
    amount: Annotated[
        str, typer.Option("--amount", help="Amount in the group currency.")
    ],
    note: Annotated[str, typer.Option("--note", help="Optional note.")] = "",
) -> None:
    """Record a payment from one member to another."""
    service = _service(ctx)
    payment = service.record_payment(group, from_member, to_member, amount, note=note)
    currency = service.get_ledger(group).group.currency
    console.print(
        f"Recorded payment: {escape(payment.from_member)} -> "
        f"{escape(payment.to_member)}: {format_money(payment.amount, currency)}"
    )
