"""Application service: the single entry point to SplitEasy.

:class:`GroupService` is a facade. It offers one method per use case (create
a group, add an expense, suggest a settlement, ...) and hides how the
repository, the domain modules (splitting, balances, settlement) and the
models fit together. The command-line interface and library users both go
through it, so every rule is implemented and validated in one place.

Every changing method follows the same pattern: load the group's ledger from
the repository, apply the change to the models, and save the whole ledger
again. If anything fails before the save, nothing is written.
"""

import datetime as dt
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from types import TracebackType
from typing import TypeVar

from spliteasy.balances import compute_balances, member_summary
from spliteasy.exceptions import CurrencyError, DuplicateError, ValidationError
from spliteasy.models import (
    Adjustment,
    Expense,
    Group,
    Ledger,
    LineItem,
    Member,
    Payment,
    SplitMethod,
    Transfer,
)
from spliteasy.money import normalize_currency, parse_decimal, to_money
from spliteasy.settlement import settle_greedy
from spliteasy.splitting import apply_split, resolve_items
from spliteasy.storage import Repository, SQLiteRepository

S = TypeVar("S", bound="GroupService")

Amount = Decimal | int | str
"""Types accepted wherever the service takes an amount or a rate."""


class GroupService:
    """Facade for managing groups, expenses, payments and settlements.

    Groups are identified by name, ignoring case. Member names passed to any
    method are also matched ignoring case, and results always use the
    spelling stored in the group.

    The service owns its repository: closing the service closes the
    repository. Use it as a context manager to close it automatically::

        with GroupService() as service:
            service.create_group("Flat", members=["Alice", "Bob"])
    """

    def __init__(self, repository: Repository | None = None) -> None:
        """Creates a service on a repository.

        Args:
            repository: Where ledgers are stored. Defaults to a
                :class:`~spliteasy.storage.SQLiteRepository` at its default
                path.

        Raises:
            StorageError: If the default database cannot be opened.
        """
        self.repository = repository if repository is not None else SQLiteRepository()

    def close(self) -> None:
        """Closes the service and its repository."""
        self.repository.close()

    def __enter__(self: S) -> S:
        """Returns the service itself for use in a ``with`` block."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Closes the service at the end of a ``with`` block.

        Args:
            exc_type: The type of the exception that ended the block, if any.
            exc: The exception that ended the block, if any.
            traceback: The traceback of that exception, if any.
        """
        self.close()

    # Groups

    def create_group(
        self, name: str, currency: str = "EUR", members: Iterable[str] = ()
    ) -> Group:
        """Creates and saves a new group.

        Args:
            name: The group's name.
            currency: The ISO 4217 code all balances are kept in.
            members: The names of the initial members.

        Returns:
            The saved group, with its database id.

        Raises:
            DuplicateError: If a group with this name already exists
                (ignoring case) or two members have the same name.
            ValidationError: If the name or a member name is invalid.
            CurrencyError: If the currency code is malformed.
            StorageError: If the group cannot be saved.
        """
        group = Group(
            name=name, currency=currency, members=[Member(name) for name in members]
        )
        if self.repository.exists(group.name):
            raise DuplicateError(f"A group named {group.name!r} already exists")
        self.repository.save(Ledger(group=group))
        return group

    def delete_group(self, name: str) -> None:
        """Deletes a group with all of its expenses and payments.

        Args:
            name: The group's name, ignoring case.

        Raises:
            GroupNotFoundError: If there is no such group.
            StorageError: If the group cannot be deleted.
        """
        self.repository.delete(name)

    def list_groups(self) -> list[str]:
        """Returns the names of all groups, sorted ignoring case.

        Raises:
            StorageError: If the groups cannot be read.
        """
        return self.repository.list_groups()

    def get_ledger(self, name: str) -> Ledger:
        """Returns a group with all of its expenses and payments.

        Args:
            name: The group's name, ignoring case.

        Returns:
            The group's ledger.

        Raises:
            GroupNotFoundError: If there is no such group.
            StorageError: If the group cannot be read.
        """
        return self.repository.load(name)

    # Members

    def add_members(self, group_name: str, names: Iterable[str]) -> list[Member]:
        """Adds new members to a group.

        Either all members are added or, if one of them is invalid, none.

        Args:
            group_name: The group's name, ignoring case.
            names: The new members' names.

        Returns:
            The new members, in the given order.

        Raises:
            GroupNotFoundError: If there is no such group.
            DuplicateError: If a name is already used in the group, ignoring
                case.
            ValidationError: If a name is invalid.
            StorageError: If the group cannot be read or saved.
        """
        ledger = self.repository.load(group_name)
        added = [ledger.group.add_member(name) for name in names]
        self.repository.save(ledger)
        return added

    def remove_member(self, group_name: str, name: str) -> None:
        """Removes a member who has no balance and no history in the group.

        Args:
            group_name: The group's name, ignoring case.
            name: The member's name, ignoring case.

        Raises:
            GroupNotFoundError: If there is no such group.
            MemberNotFoundError: If the group has no such member.
            ValidationError: If the member's balance is not zero, or the
                member appears in any expense or payment.
            StorageError: If the group cannot be read or saved.
        """
        ledger = self.repository.load(group_name)
        member = ledger.group.resolve_name(name)
        balance = self._compute_balances(ledger)[member]
        if balance != 0:
            raise ValidationError(
                f"Cannot remove {member!r}: their balance is {balance}, not zero"
            )
        if _appears_in_history(ledger, member):
            raise ValidationError(
                f"Cannot remove {member!r}: they appear in existing expenses "
                "or payments"
            )
        ledger.group.remove_member(member)
        self.repository.save(ledger)

    # Expenses

    def add_expense(
        self,
        group_name: str,
        description: str,
        amount: Amount,
        payer: str,
        *,
        split: SplitMethod | str = SplitMethod.EQUAL,
        participants: Iterable[str] = (),
        split_values: Mapping[str, Amount] | None = None,
        currency: str | None = None,
        rate: Amount | None = None,
        category: str = "other",
        date: dt.date | None = None,
        note: str = "",
        items: Sequence[LineItem] = (),
        adjustments: Sequence[Adjustment] = (),
    ) -> Expense:
        """Adds an expense to a group, splits it and saves it.

        Args:
            group_name: The group's name, ignoring case.
            description: What the expense was for.
            amount: The amount paid, in ``currency``.
            payer: The name of the member who paid.
            split: The split method, as an enum or its value such as
                ``"shares"``.
            participants: For equal splits, the members sharing the expense.
                Empty means all members.
            split_values: For exact, percentage and shares splits, the value
                for each member.
            currency: The currency of ``amount``. Defaults to the group's
                currency.
            rate: The exchange rate from ``currency`` to the group's
                currency. Required when the currencies differ.
            category: The expense category.
            date: The day of the expense. Defaults to today.
            note: An optional note.
            items: For itemised splits, the receipt's line items. Their
                total plus the adjustments must equal ``amount``.
            adjustments: For itemised splits, receipt-level adjustments.

        Returns:
            The saved expense, with its id and computed shares.

        Raises:
            GroupNotFoundError: If there is no such group.
            MemberNotFoundError: If a name is not a member of the group.
            CurrencyError: If the currency code is malformed, a rate is
                missing for a foreign currency, or a rate other than 1 is
                given for the group's own currency.
            ValidationError: If a field of the expense is invalid.
            SplitError: If the expense cannot be split.
            InvalidAmountError: If an amount or rate cannot be parsed.
            StorageError: If the group cannot be read or saved.
        """
        ledger = self.repository.load(group_name)
        group = ledger.group
        expense_currency = (
            group.currency if currency is None else normalize_currency(currency)
        )
        rate_to_base = _rate_to_base(expense_currency, group.currency, rate)

        fields: dict[str, object] = {}
        if date is not None:
            fields["date"] = date
        expense = Expense(
            description=description,
            amount=amount,  # type: ignore[arg-type]
            payer=group.resolve_name(payer),
            currency=expense_currency,
            split_method=split,  # type: ignore[arg-type]
            participants=[group.resolve_name(name) for name in participants],
            split_values={
                group.resolve_name(name): value  # type: ignore[misc]
                for name, value in (split_values or {}).items()
            },
            items=resolve_items(items, group),
            adjustments=list(adjustments),
            category=category,
            rate_to_base=rate_to_base,
            note=note,
            id=ledger.next_expense_id(),
            group_id=group.id,
            **fields,  # type: ignore[arg-type]
        )
        apply_split(expense, group)
        ledger.expenses.append(expense)
        self.repository.save(ledger)
        return expense

    def list_expenses(
        self,
        group_name: str,
        *,
        member: str | None = None,
        category: str | None = None,
    ) -> list[Expense]:
        """Returns a group's expenses, optionally filtered.

        Args:
            group_name: The group's name, ignoring case.
            member: Only expenses this member paid for or has a non-zero
                share in.
            category: Only expenses in this category, ignoring case.

        Returns:
            The matching expenses, sorted by date and then by id.

        Raises:
            GroupNotFoundError: If there is no such group.
            MemberNotFoundError: If ``member`` is not a member of the group.
            StorageError: If the group cannot be read.
        """
        ledger = self.repository.load(group_name)
        expenses = ledger.expenses
        if member is not None:
            name = ledger.group.resolve_name(member)
            expenses = [
                expense
                for expense in expenses
                if expense.payer.casefold() == name.casefold()
                or expense.share_of(name) != 0
            ]
        if category is not None:
            wanted = category.strip().lower()
            expenses = [expense for expense in expenses if expense.category == wanted]
        return sorted(expenses, key=lambda expense: (expense.date, expense.id or 0))

    def delete_expense(self, group_name: str, expense_id: int) -> None:
        """Deletes an expense from a group.

        Args:
            group_name: The group's name, ignoring case.
            expense_id: The id of the expense within the group.

        Raises:
            GroupNotFoundError: If there is no such group.
            ExpenseNotFoundError: If the group has no expense with this id.
            StorageError: If the group cannot be read or saved.
        """
        ledger = self.repository.load(group_name)
        ledger.remove_expense(expense_id)
        self.repository.save(ledger)

    # Balances and settlement

    def balances(self, group_name: str) -> dict[str, Decimal]:
        """Returns the net balance of every member of a group.

        Args:
            group_name: The group's name, ignoring case.

        Returns:
            The balance of each member in the group's currency, in member
            order. Positive means the member is owed money.

        Raises:
            GroupNotFoundError: If there is no such group.
            StorageError: If the group cannot be read.
        """
        return self._compute_balances(self.repository.load(group_name))

    def summary(self, group_name: str) -> dict[str, dict[str, Decimal]]:
        """Returns what every member paid, owes, sent and received.

        Args:
            group_name: The group's name, ignoring case.

        Returns:
            The per-member totals described in
            :func:`~spliteasy.balances.member_summary`.

        Raises:
            GroupNotFoundError: If there is no such group.
            StorageError: If the group cannot be read.
        """
        ledger = self.repository.load(group_name)
        return member_summary(ledger.group, ledger.expenses, ledger.payments)

    def suggest_settlement(self, group_name: str) -> list[Transfer]:
        """Suggests transfers that settle all balances of a group.

        Args:
            group_name: The group's name, ignoring case.

        Returns:
            The suggested transfers from the greedy algorithm; empty if the
            group is already settled.

        Raises:
            GroupNotFoundError: If there is no such group.
            StorageError: If the group cannot be read.
        """
        return settle_greedy(self.balances(group_name))

    def record_payment(
        self,
        group_name: str,
        from_member: str,
        to_member: str,
        amount: Amount,
        *,
        date: dt.date | None = None,
        note: str = "",
    ) -> Payment:
        """Records money one member actually sent to another.

        Args:
            group_name: The group's name, ignoring case.
            from_member: The name of the member who sent the money.
            to_member: The name of the member who received it.
            amount: The amount, in the group's currency. It is rounded to the
                currency's minor unit.
            date: The day of the payment. Defaults to today.
            note: An optional note.

        Returns:
            The saved payment, with its id.

        Raises:
            GroupNotFoundError: If there is no such group.
            MemberNotFoundError: If a name is not a member of the group.
            ValidationError: If both names are the same member or the amount
                is not positive.
            InvalidAmountError: If the amount cannot be parsed.
            StorageError: If the group cannot be read or saved.
        """
        ledger = self.repository.load(group_name)
        group = ledger.group
        fields: dict[str, object] = {}
        if date is not None:
            fields["date"] = date
        payment = Payment(
            from_member=group.resolve_name(from_member),
            to_member=group.resolve_name(to_member),
            amount=to_money(amount, group.currency),
            note=note,
            id=ledger.next_payment_id(),
            group_id=group.id,
            **fields,  # type: ignore[arg-type]
        )
        ledger.payments.append(payment)
        self.repository.save(ledger)
        return payment

    @staticmethod
    def _compute_balances(ledger: Ledger) -> dict[str, Decimal]:
        """Returns the balances of a loaded ledger."""
        return compute_balances(ledger.group, ledger.expenses, ledger.payments)


def _rate_to_base(currency: str, base_currency: str, rate: Amount | None) -> Decimal:
    """Returns the exchange rate to store on an expense.

    Args:
        currency: The expense currency, normalised.
        base_currency: The group's currency.
        rate: The rate given by the caller, if any.

    Returns:
        The rate from ``currency`` to ``base_currency``; ``1`` when they are
        the same.

    Raises:
        CurrencyError: If the currencies differ and no rate is given, or they
            are the same and a rate other than 1 is given.
        InvalidAmountError: If the rate cannot be parsed.
    """
    if currency == base_currency:
        if rate is not None and parse_decimal(rate) != 1:
            raise CurrencyError(
                f"The expense is in the group currency {base_currency}, "
                f"so the exchange rate must be 1, got {rate}"
            )
        return Decimal(1)
    if rate is None:
        raise CurrencyError(
            f"An exchange rate is required for {currency} -> {base_currency}"
        )
    return parse_decimal(rate)


def _appears_in_history(ledger: Ledger, member: str) -> bool:
    """Returns whether a member appears in any expense or payment.

    Args:
        ledger: The group's ledger.
        member: The member's stored name.

    Returns:
        ``True`` if the member is named anywhere in an expense or payment.
    """
    key = member.casefold()
    in_expenses = any(
        key in (name.casefold() for name in expense.involved_members)
        for expense in ledger.expenses
    )
    in_payments = any(
        key in (payment.from_member.casefold(), payment.to_member.casefold())
        for payment in ledger.payments
    )
    return in_expenses or in_payments
