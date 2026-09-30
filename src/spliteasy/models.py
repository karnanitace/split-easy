"""Data model for SplitEasy.

The model uses two kinds of objects:

* **Value objects** are frozen dataclasses, such as a share of an expense or a
  suggested transfer. They are defined only by their values, cannot be changed
  after creation, and two value objects with the same values are equal.
* **Entities** are mutable dataclasses with an identity, such as a group or an
  expense. They can change over time (a group gains members, an expense is
  edited) while remaining the same entity.

Within a group, members are referenced by their name rather than by a database
id. Names are unique within a group and are normalised with
:func:`normalize_name`, so ``"  Ana "`` and ``"Ana"`` refer to the same member.

Entities that are stored in the database have an ``id`` that is ``None`` until
the object has been saved. The repository assigns the id when it saves the
object.

Every model validates its own data in ``__post_init__`` and raises
:class:`~spliteasy.exceptions.ValidationError` if the data is invalid, so an
invalid object can never be created.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import TypeVar

from spliteasy.exceptions import DuplicateError, MemberNotFoundError, ValidationError
from spliteasy.money import normalize_currency, parse_decimal, to_money

MAX_NAME_LENGTH = 50
"""Maximum number of characters in a normalised name."""

MAX_DESCRIPTION_LENGTH = 100
"""Maximum number of characters in a normalised expense description."""

E = TypeVar("E", bound=Enum)
T = TypeVar("T")


class SplitMethod(str, Enum):
    """How an expense is divided among the people who share it."""

    EQUAL = "equal"
    """Everyone pays the same amount."""
    EXACT = "exact"
    """Each person pays a given amount; the amounts add up to the total."""
    PERCENTAGE = "percentage"
    """Each person pays a percentage; the percentages add up to 100."""
    SHARES = "shares"
    """Each person pays in proportion to a number of shares, such as 2 : 1 : 1."""
    ITEMIZED = "itemized"
    """Each person pays for the receipt items they consumed."""


class AdjustmentKind(str, Enum):
    """A receipt-level amount that changes the total of an itemised expense."""

    DISCOUNT = "discount"
    """Reduces the total, for example a coupon."""
    FEE = "fee"
    """Increases the total, for example a delivery fee or a tip."""
    DEPOSIT = "deposit"
    """Increases the total, for example a bottle deposit."""


class DistributionMode(str, Enum):
    """How a receipt-level adjustment is spread across the people sharing it."""

    PROPORTIONAL = "proportional"
    """In proportion to each person's item subtotal."""
    EQUAL = "equal"
    """In equal parts."""


def normalize_name(
    name: str, *, kind: str = "Name", max_length: int = MAX_NAME_LENGTH
) -> str:
    """Normalises a name and checks that it is valid.

    Surrounding whitespace is removed, and every run of whitespace inside the
    name is replaced by a single space.

    Args:
        name: The name to normalise, for example ``"  Italy   Trip "``.
        kind: What the name is for, used at the start of error messages, for
            example ``"Member name"``.
        max_length: The maximum number of characters after normalisation.

    Returns:
        The normalised name, for example ``"Italy Trip"``.

    Raises:
        ValidationError: If ``name`` is not a string, or the normalised name
            is empty or longer than ``max_length`` characters.

    Examples:
        >>> normalize_name("  Italy    Trip ")
        'Italy Trip'
    """
    if not isinstance(name, str):
        raise ValidationError(f"{kind} must be a string, got {type(name).__name__}")
    normalized = " ".join(name.split())
    if not normalized:
        raise ValidationError(f"{kind} must not be empty")
    if len(normalized) > max_length:
        raise ValidationError(
            f"{kind} must be at most {max_length} characters, got {len(normalized)}"
        )
    return normalized


@dataclass(frozen=True, slots=True, eq=False)
class Member:
    """A person who takes part in a group's expenses.

    Members are compared by name, ignoring case: ``Member("Alice")`` and
    ``Member("alice")`` are equal and have the same hash, so a set or dict
    holds at most one of them. People type names inconsistently, and treating
    ``"alice"`` as a different person from ``"Alice"`` would silently split one
    person's balance in two. The ``id`` is ignored in comparisons, so a member
    loaded from the database equals the same member before it was saved.

    Attributes:
        name: The member's name, normalised with :func:`normalize_name`. Its
            spelling and capitalisation are kept for display.
        id: The database id, or ``None`` if the member has not been saved.
    """

    name: str
    id: int | None = None

    def __post_init__(self) -> None:
        """Normalises the name.

        Raises:
            ValidationError: If the name is empty, too long or not a string.
        """
        # The dataclass is frozen, so the normalised value must bypass
        # the generated __setattr__.
        object.__setattr__(self, "name", normalize_name(self.name, kind="Member name"))

    @property
    def key(self) -> str:
        """The case-insensitive form of the name used for comparisons."""
        return self.name.casefold()

    def __eq__(self, other: object) -> bool:
        """Returns whether ``other`` is a member with the same name, ignoring case."""
        if not isinstance(other, Member):
            return NotImplemented
        return self.key == other.key

    def __hash__(self) -> int:
        """Returns a hash consistent with the case-insensitive equality."""
        return hash(self.key)


@dataclass(slots=True, kw_only=True)
class Group:
    """A group of people who share expenses, such as flatmates or a trip.

    Member names are unique within a group, ignoring case. All lookups by name
    are case-insensitive and ignore extra whitespace, so ``"alice"`` finds the
    member stored as ``"Alice"``.

    Attributes:
        name: The group's name, normalised with :func:`normalize_name`.
        currency: The ISO 4217 code that balances in the group are expressed
            in, normalised with :func:`~spliteasy.money.normalize_currency`.
        members: The group's members, in the order they were added.
        id: The database id, or ``None`` if the group has not been saved.
        created_at: When the group was created, as a timezone-aware datetime.
            Defaults to the current time in UTC.
    """

    name: str
    currency: str = "EUR"
    members: list[Member] = field(default_factory=list)
    id: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        """Normalises the name and currency and validates the members.

        Raises:
            ValidationError: If the name is invalid, a member is not a
                :class:`Member`, or ``created_at`` has no timezone.
            CurrencyError: If the currency code is malformed.
            DuplicateError: If two members have the same name, ignoring case.
        """
        self.name = normalize_name(self.name, kind="Group name")
        self.currency = normalize_currency(self.currency)
        if self.created_at.tzinfo is None:
            raise ValidationError("Group created_at must be timezone-aware")

        members = list(self.members)
        seen: set[Member] = set()
        for member in members:
            if not isinstance(member, Member):
                raise ValidationError(
                    f"Group members must be Member objects, got {member!r}"
                )
            if member in seen:
                raise DuplicateError(
                    f"Member {member.name!r} appears more than once "
                    f"in group {self.name!r}"
                )
            seen.add(member)
        # A copy, so later changes to the caller's list do not affect the group.
        self.members = members

    @property
    def member_names(self) -> list[str]:
        """The names of all members, in the order they were added."""
        return [member.name for member in self.members]

    def has_member(self, name: str) -> bool:
        """Returns whether the group has a member with this name.

        Args:
            name: The name to look up, ignoring case and extra whitespace.

        Returns:
            ``True`` if such a member exists, otherwise ``False``.
        """
        return self._find(name) is not None

    def get_member(self, name: str) -> Member:
        """Returns the member with this name.

        Args:
            name: The name to look up, ignoring case and extra whitespace.

        Returns:
            The stored member.

        Raises:
            MemberNotFoundError: If the group has no such member.
        """
        member = self._find(name)
        if member is None:
            raise MemberNotFoundError(name)
        return member

    def add_member(self, name: str) -> Member:
        """Adds a new member to the end of the group.

        Args:
            name: The new member's name. It is normalised with
                :func:`normalize_name`.

        Returns:
            The new member.

        Raises:
            ValidationError: If the name is empty, too long or not a string.
            DuplicateError: If a member with the same name already exists,
                ignoring case.
        """
        member = Member(name)
        existing = self._find(member.name)
        if existing is not None:
            raise DuplicateError(
                f"Member {existing.name!r} already exists in group {self.name!r}"
            )
        self.members.append(member)
        return member

    def remove_member(self, name: str) -> None:
        """Removes a member from the group.

        This only changes the member list. It does not check whether the
        member still owes or is owed money; that rule needs the group's
        expenses and payments, so it is enforced by the service layer before
        this method is called.

        Args:
            name: The name of the member to remove, ignoring case and extra
                whitespace.

        Raises:
            MemberNotFoundError: If the group has no such member.
        """
        self.members.remove(self.get_member(name))

    def resolve_name(self, name: str) -> str:
        """Returns the stored spelling of a member's name.

        Args:
            name: The name to look up, ignoring case and extra whitespace,
                for example ``"alice"``.

        Returns:
            The name exactly as stored, for example ``"Alice"``.

        Raises:
            MemberNotFoundError: If the group has no such member.
        """
        return self.get_member(name).name

    def _find(self, name: str) -> Member | None:
        """Returns the member with this name, or ``None`` if there is none.

        Args:
            name: The name to look up. A name that is not valid (for example
                an empty string) matches no member.

        Returns:
            The stored member, or ``None``.
        """
        try:
            wanted = Member(name)
        except ValidationError:
            return None
        return next((member for member in self.members if member == wanted), None)


ITEM_SPLIT_METHODS = frozenset(
    {SplitMethod.EQUAL, SplitMethod.EXACT, SplitMethod.PERCENTAGE, SplitMethod.SHARES}
)
"""Split methods allowed for a single line item (everything except ITEMIZED)."""


@dataclass(frozen=True, slots=True)
class Share:
    """How much of an expense one member is responsible for.

    The amount is in the group's base currency.

    Attributes:
        member: The member's name, normalised with :func:`normalize_name`.
        amount: The member's part of the expense. It may be zero but not
            negative.
    """

    member: str
    amount: Decimal

    def __post_init__(self) -> None:
        """Normalises the member name and parses the amount.

        Raises:
            ValidationError: If the member name is invalid or the amount is
                negative.
            InvalidAmountError: If the amount cannot be parsed.
        """
        object.__setattr__(
            self, "member", normalize_name(self.member, kind="Member name")
        )
        amount = parse_decimal(self.amount)
        if amount < 0:
            raise ValidationError(
                f"Share amount for {self.member!r} must not be negative, got {amount}"
            )
        object.__setattr__(self, "amount", amount)


@dataclass(frozen=True, slots=True, kw_only=True)
class LineItem:
    """One item on a receipt and the members who share it.

    ``assignees`` maps each member's name to a weight whose meaning depends on
    ``split_method``: ignored beyond being positive for EQUAL, a percentage
    for PERCENTAGE, a number of shares for SHARES and an amount for EXACT.
    Whether percentages add up to 100 or exact amounts to the item total is
    checked when the item is split, not here.

    ``assignees`` is stored as a new plain ``dict``. The item is frozen, but a
    ``dict`` itself is mutable, so callers must not modify it. Because of this
    field, line items are not hashable; ``hash()`` raises ``TypeError``.

    Attributes:
        name: The item's name, normalised with :func:`normalize_name`.
        price: The unit price. It may be negative (for example a returned
            bottle deposit) but not zero.
        quantity: How many units were bought, at least 1.
        assignees: Weights by member name, normalised and parsed.
        split_method: How the item total is divided among the assignees.
        category: An optional category, stripped and in lower case.
    """

    name: str
    price: Decimal
    quantity: int = 1
    assignees: Mapping[str, Decimal]
    split_method: SplitMethod = SplitMethod.EQUAL
    category: str | None = None

    # A frozen dataclass would otherwise get a __hash__ that fails on the dict.
    __hash__ = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        """Normalises and validates all fields.

        Raises:
            ValidationError: If the name, price, quantity, assignees, split
                method or category is invalid.
            InvalidAmountError: If the price or a weight cannot be parsed.
        """
        object.__setattr__(self, "name", normalize_name(self.name, kind="Item name"))

        price = parse_decimal(self.price)
        if price == 0:
            raise ValidationError(f"Price of item {self.name!r} must not be zero")
        object.__setattr__(self, "price", price)

        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int):
            raise ValidationError(
                f"Quantity of item {self.name!r} must be an integer, "
                f"got {self.quantity!r}"
            )
        if self.quantity < 1:
            raise ValidationError(
                f"Quantity of item {self.name!r} must be at least 1, "
                f"got {self.quantity}"
            )

        object.__setattr__(self, "assignees", self._normalize_assignees())

        split_method = _to_enum(SplitMethod, self.split_method, "split method")
        if split_method not in ITEM_SPLIT_METHODS:
            raise ValidationError(
                f"Split method {split_method.value!r} is not allowed for a line item"
            )
        object.__setattr__(self, "split_method", split_method)

        object.__setattr__(self, "category", _normalize_category(self.category))

    @classmethod
    def for_members(
        cls,
        name: str,
        price: Decimal | int | str,
        members: Sequence[str],
        quantity: int = 1,
        category: str | None = None,
    ) -> "LineItem":
        """Creates an item shared equally by the given members.

        This covers the common case of "this item is for Alice and Bob".

        Args:
            name: The item's name.
            price: The unit price.
            members: The names of the members who share the item.
            quantity: How many units were bought.
            category: An optional category.

        Returns:
            A line item with weight 1 for each member and
            :attr:`SplitMethod.EQUAL`.

        Raises:
            ValidationError: If any field is invalid, ``members`` is empty or
                a name appears twice, ignoring case.
            InvalidAmountError: If the price cannot be parsed.
        """
        _check_unique_names(
            (normalize_name(member, kind="Member name") for member in members),
            context=f"item {name!r}",
        )
        return cls(
            name=name,
            price=price,  # type: ignore[arg-type]
            quantity=quantity,
            assignees=dict.fromkeys(members, Decimal(1)),
            split_method=SplitMethod.EQUAL,
            category=category,
        )

    @property
    def total(self) -> Decimal:
        """The price of all units together: ``price * quantity``."""
        return self.price * self.quantity

    def _normalize_assignees(self) -> dict[str, Decimal]:
        """Returns the assignees with normalised names and parsed weights.

        Raises:
            ValidationError: If there are no assignees, a name is invalid or
                appears twice (ignoring case), a weight is negative, or all
                weights are zero.
            InvalidAmountError: If a weight cannot be parsed.
        """
        if not isinstance(self.assignees, Mapping):
            raise ValidationError(
                f"Assignees of item {self.name!r} must be a mapping of names to weights"
            )
        if not self.assignees:
            raise ValidationError(f"Item {self.name!r} must have at least one assignee")

        pairs: list[tuple[str, Decimal]] = []
        for raw_name, raw_weight in self.assignees.items():
            member = normalize_name(raw_name, kind="Member name")
            weight = parse_decimal(raw_weight)
            if weight < 0:
                raise ValidationError(
                    f"Weight of {member!r} for item {self.name!r} must not be "
                    f"negative, got {weight}"
                )
            pairs.append((member, weight))
        # Checked before building the dict, because names that differ only in
        # whitespace would otherwise collapse into one key silently.
        _check_unique_names(
            (member for member, _ in pairs), context=f"item {self.name!r}"
        )
        assignees = dict(pairs)
        if all(weight == 0 for weight in assignees.values()):
            raise ValidationError(
                f"At least one weight for item {self.name!r} must be positive"
            )
        return assignees


@dataclass(frozen=True, slots=True, kw_only=True)
class Adjustment:
    """A receipt-level correction, such as a coupon or a delivery fee.

    The amount is always positive; the kind decides whether it reduces or
    increases the receipt total (see :attr:`signed_amount`).

    Attributes:
        kind: What the adjustment is.
        amount: The size of the adjustment, greater than zero.
        distribute: How the adjustment is spread across the people on the
            receipt.
        description: An optional description, stripped of surrounding
            whitespace.
    """

    kind: AdjustmentKind
    amount: Decimal
    distribute: DistributionMode = DistributionMode.PROPORTIONAL
    description: str = ""

    def __post_init__(self) -> None:
        """Converts the enums, parses the amount and validates all fields.

        Raises:
            ValidationError: If the kind or distribution mode is unknown, the
                amount is not positive, or the description is not a string.
            InvalidAmountError: If the amount cannot be parsed.
        """
        object.__setattr__(
            self, "kind", _to_enum(AdjustmentKind, self.kind, "adjustment kind")
        )
        amount = parse_decimal(self.amount)
        if amount <= 0:
            raise ValidationError(
                f"Adjustment amount must be greater than zero, got {amount}"
            )
        object.__setattr__(self, "amount", amount)
        object.__setattr__(
            self,
            "distribute",
            _to_enum(DistributionMode, self.distribute, "distribution mode"),
        )
        if not isinstance(self.description, str):
            raise ValidationError(
                f"Adjustment description must be a string, got {self.description!r}"
            )
        object.__setattr__(self, "description", self.description.strip())

    @property
    def signed_amount(self) -> Decimal:
        """The amount with its effect on the total: negative for a discount."""
        if self.kind is AdjustmentKind.DISCOUNT:
            return -self.amount
        return self.amount


# Split methods whose split_values hold per-member amounts, percentages or weights.
_VALUE_SPLIT_METHODS = frozenset(
    {SplitMethod.EXACT, SplitMethod.PERCENTAGE, SplitMethod.SHARES}
)


@dataclass(slots=True, kw_only=True)
class Expense:
    """Money one member paid on behalf of a group, and how it is divided.

    How the expense is divided depends on ``split_method``:

    * ``EQUAL`` divides the amount equally among ``participants``. An empty
      ``participants`` list means "all members of the group"; the service
      layer resolves it against the group when the expense is split.
    * ``EXACT``, ``PERCENTAGE`` and ``SHARES`` use ``split_values``, which map
      each member to an exact amount, a percentage or a share weight.
    * ``ITEMIZED`` uses ``items`` and ``adjustments`` from a receipt.

    The result of splitting is stored in ``shares`` by the service layer. The
    fields are validated when the expense is created; code that changes an
    expense later is responsible for keeping it consistent.

    Attributes:
        description: What the expense was for, normalised with
            :func:`normalize_name` (at most :data:`MAX_DESCRIPTION_LENGTH`
            characters).
        amount: The amount paid in ``currency``, rounded to its minor unit.
            It must be greater than zero.
        payer: The name of the member who paid.
        currency: The ISO 4217 code of ``amount``.
        split_method: How the amount is divided.
        participants: For EQUAL splits, the members who share the expense.
            Empty means all members of the group.
        split_values: For EXACT, PERCENTAGE and SHARES splits, a
            non-negative value by member name.
        items: For ITEMIZED splits, the receipt's line items.
        adjustments: For ITEMIZED splits, receipt-level discounts and fees.
        category: The expense category, stripped and in lower case.
        date: The day the expense was made.
        rate_to_base: The exchange rate from ``currency`` to the group's base
            currency, fixed when the expense is entered. It must be greater
            than zero.
        shares: The computed share of each member, filled in by the service.
        note: An optional free-text note, stripped of surrounding whitespace.
        id: The database id, or ``None`` if the expense has not been saved.
        group_id: The id of the group the expense belongs to, or ``None``.
    """

    description: str
    amount: Decimal
    payer: str
    currency: str = "EUR"
    split_method: SplitMethod = SplitMethod.EQUAL
    participants: list[str] = field(default_factory=list)
    split_values: dict[str, Decimal] = field(default_factory=dict)
    items: list[LineItem] = field(default_factory=list)
    adjustments: list[Adjustment] = field(default_factory=list)
    category: str = "other"
    date: date = field(default_factory=date.today)
    rate_to_base: Decimal = Decimal("1")
    shares: list[Share] = field(default_factory=list)
    note: str = ""
    id: int | None = None
    group_id: int | None = None

    def __post_init__(self) -> None:
        """Normalises and validates all fields and checks their consistency.

        Raises:
            ValidationError: If a field is invalid or the fields do not match
                the split method.
            InvalidAmountError: If the amount, a split value or the exchange
                rate cannot be parsed.
            CurrencyError: If the currency code is malformed.
        """
        self.description = normalize_name(
            self.description, kind="Description", max_length=MAX_DESCRIPTION_LENGTH
        )
        self.currency = normalize_currency(self.currency)
        self.amount = to_money(self.amount, self.currency)
        if self.amount <= 0:
            raise ValidationError(
                f"Amount of expense {self.description!r} must be greater than zero, "
                f"got {self.amount}"
            )
        self.payer = normalize_name(self.payer, kind="Payer name")
        self.split_method = _to_enum(SplitMethod, self.split_method, "split method")

        self.participants = [
            normalize_name(name, kind="Participant name") for name in self.participants
        ]
        _check_unique_names(self.participants, context="participants")
        self.split_values = self._normalize_split_values()
        self.items = _check_instances(self.items, LineItem, "items")
        self.adjustments = _check_instances(self.adjustments, Adjustment, "adjustments")
        self.shares = _check_instances(self.shares, Share, "shares")
        _check_unique_names((share.member for share in self.shares), context="shares")

        category = _normalize_category(self.category)
        if category is None:
            raise ValidationError("Expense category must not be empty")
        self.category = category

        _check_date(self.date, "Expense")

        self.rate_to_base = parse_decimal(self.rate_to_base)
        if self.rate_to_base <= 0:
            raise ValidationError(
                f"Exchange rate must be greater than zero, got {self.rate_to_base}"
            )

        if not isinstance(self.note, str):
            raise ValidationError(f"Expense note must be a string, got {self.note!r}")
        self.note = self.note.strip()

        self._check_split_consistency()

    @property
    def items_total(self) -> Decimal:
        """The sum of the item totals plus the signed adjustments.

        This is ``Decimal("0")`` if the expense has no items.
        """
        if not self.items:
            return Decimal("0")
        items = sum((item.total for item in self.items), Decimal("0"))
        adjustments = sum(
            (adjustment.signed_amount for adjustment in self.adjustments), Decimal("0")
        )
        return items + adjustments

    @property
    def involved_members(self) -> list[str]:
        """Every member name that appears anywhere in the expense.

        The payer comes first, followed by names from ``participants``,
        ``split_values``, item assignees and ``shares``, in that order. Each
        name appears once (ignoring case), with the spelling of its first
        appearance.
        """
        names = [
            self.payer,
            *self.participants,
            *self.split_values,
            *(member for item in self.items for member in item.assignees),
            *(share.member for share in self.shares),
        ]
        first_seen: dict[str, str] = {}
        for name in names:
            first_seen.setdefault(name.casefold(), name)
        return list(first_seen.values())

    def base_amount(self, base_currency: str) -> Decimal:
        """Returns the amount converted to the group's base currency.

        Args:
            base_currency: The ISO 4217 code of the group's base currency.

        Returns:
            ``amount * rate_to_base``, rounded to the base currency's minor
            unit.

        Raises:
            CurrencyError: If the currency code is malformed.
        """
        return to_money(self.amount * self.rate_to_base, base_currency)

    def share_of(self, member: str) -> Decimal:
        """Returns a member's computed share of the expense.

        Args:
            member: The member's name, ignoring case and extra whitespace.

        Returns:
            The amount from ``shares``, or ``Decimal("0")`` if the member has
            no share.
        """
        wanted = " ".join(member.split()).casefold()
        for share in self.shares:
            if share.member.casefold() == wanted:
                return share.amount
        return Decimal("0")

    def _normalize_split_values(self) -> dict[str, Decimal]:
        """Returns ``split_values`` with normalised names and parsed values.

        Raises:
            ValidationError: If ``split_values`` is not a mapping, a name is
                invalid or appears twice (ignoring case), or a value is
                negative.
            InvalidAmountError: If a value cannot be parsed.
        """
        if not isinstance(self.split_values, Mapping):
            raise ValidationError("Split values must be a mapping of names to values")
        pairs: list[tuple[str, Decimal]] = []
        for raw_name, raw_value in self.split_values.items():
            member = normalize_name(raw_name, kind="Member name")
            value = parse_decimal(raw_value)
            if value < 0:
                raise ValidationError(
                    f"Split value for {member!r} must not be negative, got {value}"
                )
            pairs.append((member, value))
        _check_unique_names((member for member, _ in pairs), context="split values")
        return dict(pairs)

    def _check_split_consistency(self) -> None:
        """Checks that the fields in use match the split method.

        Raises:
            ValidationError: If the split method is missing data it needs or
                has data that belongs to another method.
        """
        method = self.split_method.value
        if self.split_method is SplitMethod.ITEMIZED:
            if not self.items:
                raise ValidationError("An itemized expense needs at least one item")
            return
        if self.items or self.adjustments:
            raise ValidationError(
                f"A {method!r} expense must not have items or adjustments"
            )
        if self.split_method in _VALUE_SPLIT_METHODS and not self.split_values:
            raise ValidationError(f"A {method!r} expense needs split values")
        if self.split_method is SplitMethod.EQUAL and self.split_values:
            raise ValidationError(
                "An 'equal' expense must not have split values; use participants"
            )


@dataclass(slots=True, kw_only=True)
class Payment:
    """Money one member actually sent to another to settle a debt.

    A payment is a record of something that happened: the user enters it
    after paying, and it changes the balances of both members. A
    :class:`Transfer` is only a suggestion from the settlement algorithm; it
    becomes a payment once the money has been sent (see
    :meth:`Transfer.to_payment`).

    Attributes:
        from_member: The name of the member who sent the money.
        to_member: The name of the member who received it. It must differ
            from ``from_member``, ignoring case.
        amount: The amount sent, always in the group's base currency. It is
            rounded to two decimal places and must be greater than zero.
        date: The day the money was sent.
        note: An optional free-text note, stripped of surrounding whitespace.
        id: The database id, or ``None`` if the payment has not been saved.
        group_id: The id of the group the payment belongs to, or ``None``.
    """

    from_member: str
    to_member: str
    amount: Decimal
    date: date = field(default_factory=date.today)
    note: str = ""
    id: int | None = None
    group_id: int | None = None

    def __post_init__(self) -> None:
        """Normalises and validates all fields.

        Raises:
            ValidationError: If a name is invalid, both names are the same
                member, the amount is not positive, the date is not a date, or
                the note is not a string.
            InvalidAmountError: If the amount cannot be parsed.
        """
        self.from_member = normalize_name(self.from_member, kind="Sender name")
        self.to_member = normalize_name(self.to_member, kind="Recipient name")
        _check_different_members(self.from_member, self.to_member, "A payment")
        self.amount = _positive_money(self.amount, "Payment amount")
        _check_date(self.date, "Payment")
        if not isinstance(self.note, str):
            raise ValidationError(f"Payment note must be a string, got {self.note!r}")
        self.note = self.note.strip()


@dataclass(frozen=True, slots=True)
class Transfer:
    """A payment suggested by the settlement algorithm that has not been made.

    Transfers are computed from the current balances and are never stored;
    they change whenever the balances change. Once the debtor has actually
    sent the money, the transfer is recorded as a :class:`Payment` with
    :meth:`to_payment`.

    Attributes:
        debtor: The name of the member who should pay.
        creditor: The name of the member who should be paid. It must differ
            from ``debtor``, ignoring case.
        amount: The suggested amount in the group's base currency, rounded to
            two decimal places. It must be greater than zero.
    """

    debtor: str
    creditor: str
    amount: Decimal

    def __post_init__(self) -> None:
        """Normalises and validates all fields.

        Raises:
            ValidationError: If a name is invalid, both names are the same
                member, or the amount is not positive.
            InvalidAmountError: If the amount cannot be parsed.
        """
        object.__setattr__(
            self, "debtor", normalize_name(self.debtor, kind="Debtor name")
        )
        object.__setattr__(
            self, "creditor", normalize_name(self.creditor, kind="Creditor name")
        )
        _check_different_members(self.debtor, self.creditor, "A transfer")
        object.__setattr__(
            self, "amount", _positive_money(self.amount, "Transfer amount")
        )

    def __str__(self) -> str:
        """Returns the transfer as ``"Bob -> Alice: 8.00"``."""
        return f"{self.debtor} -> {self.creditor}: {self.amount}"

    def to_payment(self, date: date | None = None, note: str = "") -> Payment:
        """Converts the suggestion into a payment that can be recorded.

        Args:
            date: The day the money was sent. Defaults to today.
            note: An optional note for the payment.

        Returns:
            A new, unsaved payment from the debtor to the creditor for the
            suggested amount.

        Raises:
            ValidationError: If the date or note is invalid.
        """
        payment = Payment(
            from_member=self.debtor,
            to_member=self.creditor,
            amount=self.amount,
            note=note,
        )
        # The parameter shadows the date class, so the default is left to
        # Payment and an explicit date is applied with a validated copy.
        return payment if date is None else replace(payment, date=date)


def _check_different_members(first: str, second: str, what: str) -> None:
    """Checks that two member names refer to different members.

    Args:
        first: A normalised member name.
        second: Another normalised member name.
        what: What the names belong to, used at the start of error messages.

    Raises:
        ValidationError: If the names are equal, ignoring case.
    """
    if first.casefold() == second.casefold():
        raise ValidationError(
            f"{what} needs two different members, got {first!r} twice"
        )


def _positive_money(value: Decimal | int | str, what: str) -> Decimal:
    """Converts a value with :func:`to_money` and checks that it is positive.

    Args:
        value: The amount to convert.
        what: What the amount is, used at the start of error messages.

    Returns:
        The amount rounded to two decimal places.

    Raises:
        ValidationError: If the rounded amount is zero or negative.
        InvalidAmountError: If the amount cannot be parsed.
    """
    amount = to_money(value)
    if amount <= 0:
        raise ValidationError(f"{what} must be greater than zero, got {amount}")
    return amount


def _check_date(value: object, what: str) -> None:
    """Checks that a value is a plain date and not a datetime.

    Args:
        value: The value to check.
        what: What the date belongs to, used at the start of error messages.

    Raises:
        ValidationError: If the value is not a ``date`` or is a ``datetime``.
    """
    if isinstance(value, datetime) or not isinstance(value, date):
        raise ValidationError(f"{what} date must be a date, got {value!r}")


def _check_instances(values: Iterable[object], cls: type[T], what: str) -> list[T]:
    """Returns the values as a new list after checking their type.

    Args:
        values: The values to check.
        cls: The class every value must be an instance of.
        what: The name of the field, used in error messages.

    Returns:
        A new list with the same values.

    Raises:
        ValidationError: If a value is not an instance of ``cls``.
    """
    checked: list[T] = []
    for value in values:
        if not isinstance(value, cls):
            raise ValidationError(
                f"Expense {what} must be {cls.__name__} objects, got {value!r}"
            )
        checked.append(value)
    return checked


def _to_enum(enum_type: type[E], value: object, what: str) -> E:
    """Converts a value to a member of an enum.

    Args:
        enum_type: The enum class.
        value: An enum member or its string value.
        what: A description of the field, used in error messages.

    Returns:
        The matching enum member.

    Raises:
        ValidationError: If the value is not a member or value of the enum.
    """
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except ValueError:
        allowed = ", ".join(repr(member.value) for member in enum_type)
        raise ValidationError(
            f"Invalid {what} {value!r}; expected one of {allowed}"
        ) from None


def _normalize_category(category: object) -> str | None:
    """Strips and lower-cases a category; an empty category becomes ``None``.

    Args:
        category: The category, or ``None``.

    Returns:
        The normalised category, or ``None``.

    Raises:
        ValidationError: If the category is not a string or ``None``.
    """
    if category is None:
        return None
    if not isinstance(category, str):
        raise ValidationError(f"Category must be a string, got {category!r}")
    return category.strip().lower() or None


def _check_unique_names(names: Iterable[str], *, context: str) -> None:
    """Checks that no name appears twice, ignoring case.

    Args:
        names: Normalised names.
        context: What the names belong to, used in error messages.

    Raises:
        ValidationError: If a name appears more than once.
    """
    seen: set[str] = set()
    for name in names:
        key = name.casefold()
        if key in seen:
            raise ValidationError(
                f"Member {name!r} appears more than once in {context}"
            )
        seen.add(key)
