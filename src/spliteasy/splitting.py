"""Split strategies that divide an expense total among members.

Each way of splitting an expense (equal, exact amounts, percentages, shares,
itemised) is a subclass of :class:`SplitStrategy`. This is the Strategy
pattern: code that splits an expense asks the registry for the strategy that
matches the expense's :class:`~spliteasy.models.SplitMethod` with
:func:`get_strategy` and calls it through the common interface, without
knowing which concrete class it is. A new split method is added by writing
one subclass and registering it with :func:`register_strategy`; nothing else
has to change.

Every strategy offers two levels:

* :meth:`SplitStrategy.raw_split` returns **unrounded** amounts per member,
  for example ``33.333...`` three times for 100.00 split equally. The amounts
  sum to the total, but are not valid money amounts yet.
* :meth:`SplitStrategy.split` returns **rounded** amounts. It calls
  ``raw_split`` and then rounds once with the largest remainder method
  (:func:`~spliteasy.money.distribute_remainder`), so the result is
  ``33.34, 33.33, 33.33`` and sums exactly to the total.

Itemised splits need the raw level. A receipt has many items, each split among
its own members with its own strategy, plus receipt-level discounts and fees.
Rounding every item separately could leave each member up to a cent off per
item, and those errors would add up across a long receipt. Instead, the raw
amounts of all items and adjustments are summed per member first, and the
result is rounded only once against the receipt total.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from decimal import Decimal
from typing import ClassVar

from spliteasy.exceptions import InvalidAmountError, SplitError
from spliteasy.models import Expense, Group, Share, SplitMethod
from spliteasy.money import distribute_remainder, to_money

_REGISTRY: dict[SplitMethod, "SplitStrategy"] = {}
"""The registered strategy for each split method."""


class SplitStrategy(ABC):
    """Base class for all split strategies.

    Subclasses set :attr:`method` and implement :meth:`raw_split`. The meaning
    of ``values`` depends on the strategy: participants for an equal split, an
    amount, a percentage or a weight per member for the others.

    Attributes:
        method: The split method this strategy implements.
    """

    method: ClassVar[SplitMethod]

    @abstractmethod
    def raw_split(
        self, total: Decimal, values: Mapping[str, Decimal]
    ) -> dict[str, Decimal]:
        """Returns unrounded amounts per member that sum to ``total``.

        ``total`` may be negative, for example for a refund item such as a
        returned bottle deposit. Subclasses must support negative totals and
        return negative amounts for them.

        Args:
            total: The amount to divide. It may be negative.
            values: The strategy-specific value for each member.

        Returns:
            The unrounded amount for each member, in the order of ``values``.

        Raises:
            SplitError: If the values are not valid for this strategy.
        """

    def split(
        self,
        total: Decimal | int | str,
        values: Mapping[str, Decimal],
        currency: str = "EUR",
    ) -> dict[str, Decimal]:
        """Divides a total among members and rounds the result.

        The total is converted with :func:`~spliteasy.money.to_money`, divided
        with :meth:`raw_split`, and rounded to the currency's minor unit with
        :func:`~spliteasy.money.distribute_remainder`.

        Args:
            total: The amount to divide.
            values: The strategy-specific value for each member.
            currency: The ISO 4217 code of the total.

        Returns:
            The amount for each member, in the order of ``values``, summing
            exactly to the rounded total.

        Raises:
            SplitError: If the values are not valid for this strategy.
            InvalidAmountError: If the total is not a valid amount.
            CurrencyError: If the currency code is malformed.
        """
        amount = to_money(total, currency)
        raw = self.raw_split(amount, values)
        return distribute_remainder(raw, amount, currency)

    @staticmethod
    def _require_values(values: Mapping[str, Decimal]) -> None:
        """Checks that at least one member takes part in the split.

        Args:
            values: The strategy-specific value for each member.

        Raises:
            SplitError: If ``values`` is empty.
        """
        if not values:
            raise SplitError("A split needs at least one member")


def register_strategy(strategy: SplitStrategy, *, replace: bool = False) -> None:
    """Registers a strategy for its split method.

    Args:
        strategy: The strategy instance. It is registered under
            ``strategy.method``.
        replace: Whether to replace a strategy already registered for the
            same method.

    Raises:
        ValueError: If a strategy is already registered for the method and
            ``replace`` is ``False``.
    """
    method = SplitMethod(strategy.method)
    if method in _REGISTRY and not replace:
        raise ValueError(
            f"A strategy for split method {method.value!r} is already registered; "
            "pass replace=True to replace it"
        )
    _REGISTRY[method] = strategy


def get_strategy(method: SplitMethod | str) -> SplitStrategy:
    """Returns the registered strategy for a split method.

    Args:
        method: A split method, or its string value such as ``"equal"``.
            Strings are stripped and compared in lower case.

    Returns:
        The registered strategy.

    Raises:
        SplitError: If the method is unknown or no strategy is registered
            for it.
    """
    if isinstance(method, str) and not isinstance(method, SplitMethod):
        method = method.strip().lower()
    try:
        split_method = SplitMethod(method)
    except ValueError:
        allowed = ", ".join(repr(member.value) for member in SplitMethod)
        raise SplitError(
            f"Unknown split method {method!r}; expected one of {allowed}"
        ) from None
    try:
        return _REGISTRY[split_method]
    except KeyError:
        raise SplitError(
            f"No split strategy is registered for {split_method.value!r}"
        ) from None


class EqualSplit(SplitStrategy):
    """Divides the total equally among the included members.

    The values act as "included" flags: a member whose value is greater than
    zero takes part, and a member whose value is zero does not. Both
    ``{"Alice": 1, "Bob": 1}`` and ``{"Alice": 1, "Bob": 0}`` are valid. Every
    key appears in the result; excluded members get ``Decimal("0")``.

    Examples:
        >>> EqualSplit().split("100.00", {"Alice": 1, "Bob": 1, "Carol": 1})
        {'Alice': Decimal('33.34'), 'Bob': Decimal('33.33'), 'Carol': Decimal('33.33')}
    """

    method = SplitMethod.EQUAL

    def raw_split(
        self, total: Decimal, values: Mapping[str, Decimal]
    ) -> dict[str, Decimal]:
        """Returns ``total / n`` for each of the ``n`` included members.

        Args:
            total: The amount to divide. It may be negative.
            values: An inclusion flag for each member: greater than zero to
                include the member, zero to exclude them.

        Returns:
            The unrounded amount for each member, in the order of ``values``,
            with ``Decimal("0")`` for excluded members.

        Raises:
            SplitError: If ``values`` is empty, a flag is negative, or no
                member is included.
        """
        self._require_values(values)
        negative = [member for member, flag in values.items() if flag < 0]
        if negative:
            raise SplitError(
                f"Equal split flags must not be negative, got one for {negative[0]!r}"
            )
        included = [member for member, flag in values.items() if flag > 0]
        if not included:
            raise SplitError("An equal split needs at least one included member")
        amount = total / len(included)
        return {
            member: amount if flag > 0 else Decimal("0")
            for member, flag in values.items()
        }


class SharesSplit(SplitStrategy):
    """Divides the total in proportion to each member's weight.

    Weights can be anything that measures use, such as nights stayed or room
    sizes. Each member gets ``total * weight / sum(weights)``. Fractional
    weights such as ``1.5`` are allowed, and a member with weight zero gets
    nothing.

    Examples:
        A 300.00 apartment where Alice stayed 2 nights and Bob 1 night:

        >>> SharesSplit().split("300.00", {"Alice": 2, "Bob": 1})
        {'Alice': Decimal('200.00'), 'Bob': Decimal('100.00')}
    """

    method = SplitMethod.SHARES

    def raw_split(
        self, total: Decimal, values: Mapping[str, Decimal]
    ) -> dict[str, Decimal]:
        """Returns ``total * weight / sum(weights)`` for each member.

        Args:
            total: The amount to divide. It may be negative.
            values: A non-negative weight for each member.

        Returns:
            The unrounded amount for each member, in the order of ``values``.

        Raises:
            SplitError: If ``values`` is empty, a weight is negative, or all
                weights are zero.
        """
        self._require_values(values)
        for member, weight in values.items():
            if weight < 0:
                raise SplitError(
                    f"Share weight for {member!r} must not be negative, got {weight}"
                )
        weight_sum = sum(values.values(), Decimal(0))
        if weight_sum == 0:
            raise SplitError("A shares split needs at least one positive weight")
        return {
            member: total * weight / weight_sum for member, weight in values.items()
        }


class PercentageSplit(SplitStrategy):
    """Divides the total by a percentage for each member.

    The percentages must add up to exactly 100. They are compared as
    ``Decimal`` values without any tolerance, so ``33.33 + 33.33 + 33.33``
    (99.99) is rejected. Each member gets ``total * percentage / 100``, and a
    member with 0 percent gets nothing.

    Examples:
        >>> PercentageSplit().split("50.00", {"Alice": 60, "Bob": 40})
        {'Alice': Decimal('30.00'), 'Bob': Decimal('20.00')}
    """

    method = SplitMethod.PERCENTAGE

    def raw_split(
        self, total: Decimal, values: Mapping[str, Decimal]
    ) -> dict[str, Decimal]:
        """Returns ``total * percentage / 100`` for each member.

        Args:
            total: The amount to divide. It may be negative.
            values: A non-negative percentage for each member. They must add
                up to exactly 100.

        Returns:
            The unrounded amount for each member, in the order of ``values``.

        Raises:
            SplitError: If ``values`` is empty, a percentage is negative, or
                the percentages do not add up to exactly 100.
        """
        self._require_values(values)
        for member, percentage in values.items():
            if percentage < 0:
                raise SplitError(
                    f"Percentage for {member!r} must not be negative, got {percentage}"
                )
        percentage_sum = sum(values.values(), Decimal(0))
        if percentage_sum != 100:
            raise SplitError(f"Percentages must sum to 100, got {percentage_sum}")
        return {
            member: total * percentage / 100 for member, percentage in values.items()
        }


class ExactSplit(SplitStrategy):
    """Uses an exact amount for each member.

    The amounts must add up to exactly the total. A member with amount zero
    pays nothing.

    For a normal (positive) total, every amount must be zero or positive. For
    a negative total, such as a refund item like a returned bottle deposit,
    every amount must be zero or negative instead, so that each member's part
    of the refund has the same sign as the refund itself.

    Examples:
        >>> ExactSplit().split("120.00", {"Alice": 40, "Bob": 30, "Carol": 50})
        {'Alice': Decimal('40.00'), 'Bob': Decimal('30.00'), 'Carol': Decimal('50.00')}
    """

    method = SplitMethod.EXACT

    def raw_split(
        self, total: Decimal, values: Mapping[str, Decimal]
    ) -> dict[str, Decimal]:
        """Returns the exact amounts unchanged, after checking them.

        Args:
            total: The amount the exact amounts must add up to. It may be
                negative.
            values: The exact amount for each member. They must have the same
                sign as ``total`` (or be zero).

        Returns:
            A new dict with each member's amount as a ``Decimal``, in the order
            of ``values``.

        Raises:
            SplitError: If ``values`` is empty, an amount has the wrong sign,
                or the amounts do not add up to exactly ``total``.
        """
        self._require_values(values)
        amounts = {member: Decimal(amount) for member, amount in values.items()}
        for member, amount in amounts.items():
            if total >= 0 and amount < 0:
                raise SplitError(
                    f"Exact amount for {member!r} must not be negative, got {amount}"
                )
            if total < 0 and amount > 0:
                raise SplitError(
                    f"Exact amount for {member!r} must not be positive for a "
                    f"negative total, got {amount}"
                )

        amount_sum = sum(amounts.values(), Decimal(0))
        if amount_sum != total:
            # Compared by size so that a refund whose parts are too small is
            # also reported as "missing".
            direction = "missing" if abs(amount_sum) < abs(total) else "exceeding"
            shown_sum, shown_total, shown_difference = _same_places(
                amount_sum, total, abs(total - amount_sum)
            )
            raise SplitError(
                f"Exact amounts sum to {shown_sum} but the total is {shown_total} "
                f"({direction} {shown_difference})"
            )
        return amounts


def _same_places(*numbers: Decimal) -> list[Decimal]:
    """Returns the numbers with the same number of decimal places for display.

    Every number gets as many decimal places as the most precise one, so
    ``115`` and ``120.00`` are shown as ``115.00`` and ``120.00``.

    Args:
        *numbers: Finite ``Decimal`` values.

    Returns:
        The numbers, quantised to a common exponent.
    """
    exponent = min(int(number.as_tuple().exponent) for number in numbers)
    unit = Decimal(1).scaleb(exponent)
    return [number.quantize(unit) for number in numbers]


register_strategy(EqualSplit())
register_strategy(SharesSplit())
register_strategy(PercentageSplit())
register_strategy(ExactSplit())


def compute_shares(expense: Expense, group: Group) -> list[Share]:
    """Computes how much of an expense each member owes.

    The expense is split in its own currency first, with the strategy for its
    split method. The unrounded amounts are then converted to the group's
    currency with the expense's frozen exchange rate and rounded **once**
    with the largest remainder method against the converted total:

    * Splitting in the expense currency keeps the user's input meaningful:
      exact amounts and the receipt refer to the currency that was paid.
    * Rounding only once, after conversion, avoids rounding twice (once in
      each currency), which could make the shares disagree with the
      converted total by a cent or more.

    The rounding step cannot fail. The raw amounts sum to the expense amount,
    so the converted raw amounts sum exactly to ``amount * rate_to_base``,
    and the converted total is the half-up rounding of that sum. It therefore
    differs from the sum of the rounded-down amounts by between zero and one
    minor unit per member, which is exactly what largest remainder allows.

    Args:
        expense: The expense to split.
        group: The group the expense belongs to. Its members are used to
            validate and resolve names, and its currency is the currency of
            the shares.

    Returns:
        One share per member taking part, in the order of the split input,
        using the members' stored spelling. The amounts are in the group's
        currency and sum exactly to ``expense.base_amount(group.currency)``.
        Members whose amount is zero (for example an exact amount of 0) are
        included.

    Raises:
        SplitError: If the group has no members, the split values are not
            valid for the split method, or the expense is itemised (not
            supported yet).
        MemberNotFoundError: If the payer or any other name used in the
            expense is not a member of the group.
    """
    if not group.members:
        raise SplitError(f"Group {group.name!r} has no members to split between")
    for name in expense.involved_members:
        group.resolve_name(name)

    values = _strategy_values(expense, group)
    strategy = get_strategy(expense.split_method)
    raw = strategy.raw_split(expense.amount, values)
    raw_base = {member: amount * expense.rate_to_base for member, amount in raw.items()}
    total_base = expense.base_amount(group.currency)
    amounts = distribute_remainder(raw_base, total_base, group.currency)
    return [Share(member, amount) for member, amount in amounts.items()]


def apply_split(expense: Expense, group: Group) -> Expense:
    """Computes an expense's shares and stores them on the expense.

    This **mutates** ``expense``: its ``shares`` list is replaced.

    Args:
        expense: The expense to split.
        group: The group the expense belongs to.

    Returns:
        The same expense object, so calls can be chained.

    Raises:
        SplitError: If the expense cannot be split (see :func:`compute_shares`).
        MemberNotFoundError: If a name used in the expense is not a member of
            the group.
    """
    expense.shares = compute_shares(expense, group)
    return expense


def _strategy_values(expense: Expense, group: Group) -> dict[str, Decimal]:
    """Builds the strategy input for an expense, using stored member names.

    Args:
        expense: The expense to split.
        group: The group used to resolve member names.

    Returns:
        The value for each member, keyed by the member's stored name.

    Raises:
        SplitError: If the expense is itemised, or an exact amount is not a
            valid amount in the expense currency.
        MemberNotFoundError: If a name is not a member of the group.
    """
    method = expense.split_method
    if method is SplitMethod.ITEMIZED:
        raise SplitError("Itemized splits are not supported yet")
    if method is SplitMethod.EQUAL:
        names = expense.participants or group.member_names
        return {group.resolve_name(name): Decimal(1) for name in names}

    values = {
        group.resolve_name(name): value for name, value in expense.split_values.items()
    }
    if method is SplitMethod.EXACT:
        for member, value in values.items():
            _check_exact_amount(member, value, expense.currency)
    return values


def _check_exact_amount(member: str, value: Decimal, currency: str) -> None:
    """Checks that an exact amount is a valid amount in a currency.

    Args:
        member: The member the amount belongs to, used in error messages.
        value: The exact amount.
        currency: The currency of the amount.

    Raises:
        SplitError: If the amount cannot be converted with
            :func:`~spliteasy.money.to_money` or has more decimal places than
            the currency allows (for example ``10.005`` EUR or ``10.5`` JPY).
    """
    try:
        amount = to_money(value, currency)
    except InvalidAmountError as err:
        raise SplitError(f"Invalid exact amount for {member!r}: {err}") from err
    if amount != value:
        raise SplitError(
            f"Exact amount {value} for {member!r} is not a valid {currency} amount"
        )
