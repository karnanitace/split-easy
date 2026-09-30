"""Parsing helpers for command-line input.

These functions turn the text users type into Python values and raise
:class:`~spliteasy.exceptions.ValidationError` with a clear message for bad
input, so the CLI reports it like any other SplitEasy error.
"""

from decimal import Decimal

from spliteasy.exceptions import InvalidAmountError, ValidationError
from spliteasy.money import parse_decimal


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
