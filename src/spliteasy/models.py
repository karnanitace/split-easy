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

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from spliteasy.exceptions import DuplicateError, MemberNotFoundError, ValidationError
from spliteasy.money import normalize_currency

MAX_NAME_LENGTH = 50
"""Maximum number of characters in a normalised name."""


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
