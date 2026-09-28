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

from enum import Enum

from spliteasy.exceptions import ValidationError

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
