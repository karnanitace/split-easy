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

from spliteasy.exceptions import SplitError
from spliteasy.models import SplitMethod
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
