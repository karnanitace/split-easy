"""Net balances of group members from expenses and payments.

A member's balance says how much money the member is owed by the rest of the
group (positive) or owes to it (negative). It is computed in the group's
currency as::

    balance = paid - owed + sent - received

* **paid**: the converted amount of every expense the member paid for,
  using :meth:`~spliteasy.models.Expense.base_amount`.
* **owed**: the member's shares of all expenses.
* **sent** and **received**: recorded payments between members. Sending money
  to someone reduces what you owe, so it increases your balance.

Expenses must already have their shares computed (see
:func:`~spliteasy.splitting.apply_split`). Because each expense's shares sum
to its converted amount and each payment moves money between two members,
the balances of a group always sum to exactly zero. This is checked, so an
expense whose stored shares no longer match its amount is detected.

The functions only read their inputs; they never modify expenses, payments or
groups.
"""

from collections.abc import Sequence
from decimal import Decimal

from spliteasy.exceptions import SettlementError, SplitError
from spliteasy.models import Expense, Group, Payment
from spliteasy.money import to_money

SUMMARY_FIELDS = ("paid", "owed", "sent", "received", "balance")
"""The keys of each member's entry in :func:`member_summary`, in order."""


def compute_balances(
    group: Group,
    expenses: Sequence[Expense],
    payments: Sequence[Payment] = (),
) -> dict[str, Decimal]:
    """Computes the net balance of every member of a group.

    Args:
        group: The group. Its members and currency are used.
        expenses: The group's expenses, each with computed shares.
        payments: The payments recorded between members.

    Returns:
        The balance of every member in the order of ``group.members``, keyed
        by the member's stored name, in the group's currency. Positive means
        the member is owed money, negative means they owe money. Members
        without any activity have a balance of zero.

    Raises:
        SplitError: If an expense has no computed shares.
        MemberNotFoundError: If an expense or payment names someone who is
            not a member of the group.
        SettlementError: If the balances do not sum to zero, which means an
            expense's shares do not match its amount.

    Examples:
        >>> from spliteasy.models import Member, Share
        >>> group = Group(name="Flat", members=[Member("Alice"), Member("Bob")])
        >>> groceries = Expense(
        ...     description="Groceries",
        ...     amount="20.00",
        ...     payer="Alice",
        ...     shares=[Share("Alice", Decimal(12)), Share("Bob", Decimal(8))],
        ... )
        >>> compute_balances(group, [groceries])
        {'Alice': Decimal('8.00'), 'Bob': Decimal('-8.00')}
    """
    summary = member_summary(group, expenses, payments)
    return {member: totals["balance"] for member, totals in summary.items()}


def member_summary(
    group: Group,
    expenses: Sequence[Expense],
    payments: Sequence[Payment] = (),
) -> dict[str, dict[str, Decimal]]:
    """Summarises what every member paid, owes, sent and received.

    Args:
        group: The group. Its members and currency are used.
        expenses: The group's expenses, each with computed shares.
        payments: The payments recorded between members.

    Returns:
        For every member in the order of ``group.members``, a dict with the
        keys in :data:`SUMMARY_FIELDS`:

        * ``paid``: the total converted amount of expenses the member paid.
        * ``owed``: the total of the member's shares.
        * ``sent``: the total of payments the member sent.
        * ``received``: the total of payments the member received.
        * ``balance``: ``paid - owed + sent - received``.

        All values are in the group's currency.

    Raises:
        SplitError: If an expense has no computed shares.
        MemberNotFoundError: If an expense or payment names someone who is
            not a member of the group.
        SettlementError: If the balances do not sum to zero.
    """
    zero = to_money(0, group.currency)
    totals = {
        name: dict.fromkeys(SUMMARY_FIELDS[:-1], zero) for name in group.member_names
    }

    for expense in expenses:
        if not expense.shares:
            raise SplitError(f"Expense {expense.description!r} has no computed shares")
        payer = group.resolve_name(expense.payer)
        totals[payer]["paid"] += expense.base_amount(group.currency)
        for share in expense.shares:
            totals[group.resolve_name(share.member)]["owed"] += share.amount

    for payment in payments:
        totals[group.resolve_name(payment.from_member)]["sent"] += payment.amount
        totals[group.resolve_name(payment.to_member)]["received"] += payment.amount

    for values in totals.values():
        paid, owed = values["paid"], values["owed"]
        values["balance"] = paid - owed + values["sent"] - values["received"]
    _check_sum_is_zero(totals)
    return totals


def _check_sum_is_zero(summary: dict[str, dict[str, Decimal]]) -> None:
    """Checks that the balances of a group sum to exactly zero.

    Args:
        summary: The per-member totals, including ``balance``.

    Raises:
        SettlementError: If the balances do not sum to zero.
    """
    total = sum((values["balance"] for values in summary.values()), Decimal(0))
    if total != 0:
        raise SettlementError(
            f"Balances must sum to zero but sum to {total}; "
            "an expense's shares probably do not match its amount"
        )
