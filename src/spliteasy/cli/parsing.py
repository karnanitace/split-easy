"""Parsing helpers for command-line input.

These functions turn the text users type into Python values and raise
:class:`~spliteasy.exceptions.ValidationError` with a clear message for bad
input, so the CLI reports it like any other SplitEasy error.
"""

from decimal import Decimal

from spliteasy.exceptions import InvalidAmountError, ValidationError
from spliteasy.models import LineItem
from spliteasy.money import parse_decimal

ITEM_FORMAT = "NAME:PRICE:MEMBER,MEMBER[:QUANTITY]"
"""The format of ``--item`` values, shown in error messages."""


def parse_values(text: str) -> dict[str, Decimal]:
    """Parses per-member values such as ``"Alice=40,Bob=30"``.

    Pairs are separated by commas. If the text contains a semicolon, pairs
    are separated by semicolons instead, so values can use a decimal comma:
    ``"Alice=12,50;Bob=7,50"``. Whitespace around names and values is
    ignored.

    Args:
        text: The text given with ``--values``.

    Returns:
        The value for each member, in the given order.

    Raises:
        ValidationError: If the text is empty, a pair has no ``=``, a name
            is empty or appears twice (ignoring case), or a value is not a
            number.

    Examples:
        >>> parse_values("Alice=40, Bob=30")
        {'Alice': Decimal('40'), 'Bob': Decimal('30')}
        >>> parse_values("Alice=12,50;Bob=7,50")
        {'Alice': Decimal('12.50'), 'Bob': Decimal('7.50')}
    """
    separator = ";" if ";" in text else ","
    pairs = [pair.strip() for pair in text.split(separator)]
    if not any(pairs):
        raise ValidationError(
            "No values given; use the form NAME=VALUE, for example Alice=40,Bob=30"
        )

    values: dict[str, Decimal] = {}
    seen: set[str] = set()
    for pair in pairs:
        if not pair:
            continue
        name, equals, raw_value = pair.partition("=")
        name, raw_value = name.strip(), raw_value.strip()
        if not equals:
            raise ValidationError(
                f"Invalid value {pair!r}: expected NAME=VALUE, for example Alice=40"
            )
        if not name:
            raise ValidationError(f"Invalid value {pair!r}: the name is missing")
        if name.casefold() in seen:
            raise ValidationError(f"{name!r} appears more than once in the values")
        try:
            values[name] = parse_decimal(raw_value)
        except InvalidAmountError:
            raise ValidationError(
                f"Invalid value for {name!r}: {raw_value!r} is not a number"
            ) from None
        seen.add(name.casefold())
    return values


def parse_item(text: str) -> LineItem:
    """Parses a receipt item such as ``"Olive oil:6.00:Alice,Bob"``.

    The format is ``NAME:PRICE:MEMBERS`` with an optional fourth field
    ``QUANTITY``. ``PRICE`` is the unit price and may use a decimal comma or be
    negative (for a deposit return). ``MEMBERS`` is a comma-separated list of
    the members who share the item equally. Whitespace around each field is
    ignored.

    Args:
        text: The text given with ``--item``.

    Returns:
        A line item shared equally by the given members.

    Raises:
        ValidationError: If the text does not have three or four fields, the
            price is not a number, the quantity is not a whole number of at
            least 1, there are no members, or the item is otherwise invalid.

    Examples:
        >>> item = parse_item("Protein bars:2,50:Alice:2")
        >>> item.name, item.price, item.quantity, list(item.assignees)
        ('Protein bars', Decimal('2.50'), 2, ['Alice'])
    """
    fields = [field.strip() for field in text.split(":")]
    if len(fields) not in (3, 4):
        raise ValidationError(
            f"Invalid item {text!r}: expected {ITEM_FORMAT}, "
            'for example "Olive oil:6.00:Alice,Bob"'
        )
    name, raw_price, raw_members = fields[:3]

    try:
        price = parse_decimal(raw_price)
    except InvalidAmountError:
        raise ValidationError(
            f"Invalid price for item {name!r}: {raw_price!r} is not a number"
        ) from None

    quantity = 1
    if len(fields) == 4:
        raw_quantity = fields[3]
        if not (raw_quantity.isascii() and raw_quantity.isdigit()):
            raise ValidationError(
                f"Invalid quantity for item {name!r}: {raw_quantity!r} is not a "
                "whole number"
            )
        quantity = int(raw_quantity)

    members = [member.strip() for member in raw_members.split(",") if member.strip()]
    if not members:
        raise ValidationError(f"Item {name!r} needs at least one member")
    return LineItem.for_members(name, price, members, quantity=quantity)
