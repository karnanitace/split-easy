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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import TypeVar

from spliteasy.exceptions import DuplicateError, MemberNotFoundError, ValidationError
from spliteasy.money import normalize_currency, parse_decimal

MAX_NAME_LENGTH = 50
"""Maximum number of characters in a normalised name."""

E = TypeVar("E", bound=Enum)


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


def normalize_name(name: str, *, kind: str = "Name") -> str:
    """Normalises a name and checks that it is valid.

    Surrounding whitespace is removed, and every run of whitespace inside the
    name is replaced by a single space.

    Args:
        name: The name to normalise, for example ``"  Italy   Trip "``.
        kind: What the name is for, used at the start of error messages, for
            example ``"Member name"``.

    Returns:
        The normalised name, for example ``"Italy Trip"``.

    Raises:
        ValidationError: If ``name`` is not a string, or the normalised name
            is empty or longer than :data:`MAX_NAME_LENGTH` characters.

    Examples:
        >>> normalize_name("  Italy    Trip ")
        'Italy Trip'
    """
    if not isinstance(name, str):
        raise ValidationError(f"{kind} must be a string, got {type(name).__name__}")
    normalized = " ".join(name.split())
    if not normalized:
        raise ValidationError(f"{kind} must not be empty")
    if len(normalized) > MAX_NAME_LENGTH:
        raise ValidationError(
            f"{kind} must be at most {MAX_NAME_LENGTH} characters, "
            f"got {len(normalized)}"
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
