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

from spliteasy.cli.parsing import ITEM_FORMAT, parse_item, parse_values
from spliteasy.exceptions import ValidationError
from spliteasy.models import Adjustment, AdjustmentKind, Expense, SplitMethod
from spliteasy.money import format_money
from spliteasy.services import GroupService
from spliteasy.splitting import ItemizedSplit

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
    item: Annotated[
        list[str] | None,
        typer.Option(
            "--item",
            help=f"Receipt item as {ITEM_FORMAT}. Repeat for each item; "
            "the split becomes itemized.",
        ),
    ] = None,
    discount: Annotated[
        str | None,
        typer.Option(
            "--discount",
            help="Receipt discount, spread in proportion to each member's items.",
        ),
    ] = None,
) -> None:
    """Add an expense and show how it was split."""
    method = split.strip().lower()
    items = [parse_item(text) for text in item or []]
    if items:
        if method not in (SplitMethod.EQUAL.value, SplitMethod.ITEMIZED.value):
            raise ValidationError(f"--item cannot be combined with --split {method}")
        if among or values is not None:
            raise ValidationError("--item cannot be combined with --among or --values")
        method = SplitMethod.ITEMIZED.value
    elif discount is not None:
        raise ValidationError("--discount can only be used together with --item")
    adjustments = (
        [Adjustment(kind=AdjustmentKind.DISCOUNT, amount=discount)]  # type: ignore[arg-type]
        if discount is not None
        else []
    )

    service = _service(ctx)
    expense = service.add_expense(
        group,
        description,
        amount,
        paid_by,
        split=method,
        participants=among or [],
        split_values=parse_values(values) if values is not None else None,
        currency=currency,
        rate=rate,
        category=category,
        date=date.date() if date is not None else None,
        note=note,
        items=items,
        adjustments=adjustments,
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

    if expense.split_method is SplitMethod.ITEMIZED:
        console.print(itemized_breakdown_table(expense, group_currency))
        return

    table = Table(title="Shares", box=box.ASCII)
    table.add_column("Member")
    table.add_column("Share", justify="right")
    for share in expense.shares:
        table.add_row(escape(share.member), format_money(share.amount, group_currency))
    console.print(table)


def itemized_breakdown_table(expense: Expense, group_currency: str) -> Table:
    """Builds a table of an itemised expense: items as rows, members as columns.

    Item and adjustment cells are each member's part, rounded for display in
    the expense currency. The bottom row shows the actual shares, which are
    rounded only once for the whole receipt, so a column can differ from the
    sum of its cells by a cent.

    Args:
        expense: An itemised expense with computed shares.
        group_currency: The currency of the shares.

    Returns:
        The table, ready to print.
    """
    members = [share.member for share in expense.shares]
    rows = ItemizedSplit().raw_breakdown(expense.items, expense.adjustments)

    table = Table(title="Breakdown", box=box.ASCII, show_footer=True)
    total_label = (
        "Total" if expense.currency == group_currency else f"Total ({group_currency})"
    )
    table.add_column("Item", footer=total_label)
    for member in members:
        table.add_column(
            escape(member),
            justify="right",
            footer=format_money(expense.share_of(member), group_currency),
        )
    for label, parts in rows:
        cells = [
            format_money(parts[member], expense.currency) if parts.get(member) else "-"
            for member in members
        ]
        table.add_row(escape(label), *cells)
    return table


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
