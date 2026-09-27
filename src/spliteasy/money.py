"""Money helpers built on :class:`decimal.Decimal`.

Every monetary value in SplitEasy is a ``Decimal`` that has been quantised to
the minor unit of its currency (cents for EUR, whole yen for JPY). Binary
floats are avoided because they cannot represent most decimal fractions
exactly: ``0.1 + 0.2`` is ``0.30000000000000004`` as a float, and such errors
make cents appear or disappear when amounts are added up or split. ``Decimal``
stores ``0.1`` exactly and lets SplitEasy choose how and when to round.

All conversions from user input to money go through :func:`to_money`.
"""

import re
from collections.abc import Mapping
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import TypeVar

from spliteasy.exceptions import AllocationError, CurrencyError, InvalidAmountError

K = TypeVar("K")

CURRENCY_DECIMALS: dict[str, int] = {
    "EUR": 2,
    "USD": 2,
    "GBP": 2,
    "CHF": 2,
    "PLN": 2,
    "CZK": 2,
    "SEK": 2,
    "NOK": 2,
    "DKK": 2,
    "INR": 2,
    "CAD": 2,
    "AUD": 2,
    "JPY": 0,
    "KRW": 0,
}
"""Number of minor unit digits for common ISO 4217 currency codes."""

_DEFAULT_DECIMALS = 2
_CURRENCY_CODE = re.compile(r"[A-Z]{3}")


def normalize_currency(code: str) -> str:
    """Normalises and validates an ISO 4217 currency code."""
    if not isinstance(code, str):
        raise CurrencyError(f"Currency code must be a string, got {code!r}")
    normalized = code.strip().upper()
    if not _CURRENCY_CODE.fullmatch(normalized):
        raise CurrencyError(
            f"Invalid currency code {code!r}: expected three letters such as 'EUR'"
        )
    return normalized


def minor_unit(currency: str = "EUR") -> Decimal:
    """Returns the smallest unit of a currency."""
    code = normalize_currency(currency)
    decimals = CURRENCY_DECIMALS.get(code, _DEFAULT_DECIMALS)
    return Decimal(1).scaleb(-decimals)


def to_money(value: Decimal | int | str | float, currency: str = "EUR") -> Decimal:
    """Converts a value to a money amount in the given currency."""
    unit = minor_unit(currency)
    amount = _to_decimal(value)
    if not amount.is_finite():
        raise InvalidAmountError(f"Amount must be a finite number, got {value!r}")
    try:
        quantized = amount.quantize(unit, rounding=ROUND_HALF_UP)
    except InvalidOperation as err:
        raise InvalidAmountError(f"Amount {value!r} is too large") from err
    return abs(quantized) if quantized.is_zero() else quantized


def distribute_remainder(
    raw: Mapping[K, Decimal],
    total: Decimal,
    currency: str = "EUR",
) -> dict[K, Decimal]:
    """Rounds unrounded amounts so that they sum exactly to ``total``.

    This uses the largest remainder method. Every raw
    amount is first rounded down to the currency's minor unit. The minor units
    still missing from ``total`` are then handed out one each to the keys with
    the largest fractional remainders. Ties go to the key that comes first in
    ``raw``, so the result is deterministic. Each result differs from its raw
    amount by less than one minor unit.

    Because rounding is always downwards, negative amounts (such as refunds)
    are handled the same way as positive ones.

    Args:
        raw: Unrounded amounts by key, for example exact shares by member name.
        total: The amount the results must sum to. It must already be
            quantised to the currency's minor unit.
        currency: The ISO 4217 code whose minor unit the amounts are rounded to.

    Returns:
        A new dict with the same keys in the same order as ``raw``, where every
        value is quantised to the minor unit and the values sum to ``total``.

    Raises:
        AllocationError: If ``raw`` is empty, ``total`` is not quantised to
            the minor unit, any amount is not finite, or the raw amounts do not
            add up to ``total`` (more than rounding can explain).
        CurrencyError: If the currency code is malformed.

    Examples:
        Splitting 100.00 into three exact thirds:

        >>> third = Decimal("100.00") / 3
        >>> distribute_remainder(
        ...     {"Ana": third, "Ben": third, "Chen": third}, Decimal("100.00")
        ... )
        {'Ana': Decimal('33.34'), 'Ben': Decimal('33.33'), 'Chen': Decimal('33.33')}

        All three round down to 33.33, leaving 0.01. The remainders are equal,
        so the extra cent goes to the first key.
    """
    if not raw:
        raise AllocationError("Cannot allocate an amount over no keys")
    unit = minor_unit(currency)
    if not total.is_finite() or total != total.quantize(unit):
        raise AllocationError(
            f"Total {total} must be a finite amount quantised to {unit}"
        )
    if not all(amount.is_finite() for amount in raw.values()):
        raise AllocationError("All raw amounts must be finite")

    keys = list(raw)
    floored = [raw[key].quantize(unit, rounding=ROUND_FLOOR) for key in keys]
    leftover_units = (total - sum(floored)) / unit
    if not 0 <= leftover_units <= len(keys):
        difference = total - sum(raw.values())
        raise AllocationError(
            f"Raw amounts sum to {sum(raw.values())}, which differs from the "
            f"total {total} by {difference}"
        )

    remainders = [
        raw[key] - rounded for key, rounded in zip(keys, floored, strict=True)
    ]
    # sorted() is stable, so equal remainders keep the original key order.
    by_largest_remainder = sorted(range(len(keys)), key=lambda i: -remainders[i])
    for index in by_largest_remainder[: int(leftover_units)]:
        floored[index] += unit
    return dict(zip(keys, floored, strict=True))


def _to_decimal(value: object) -> Decimal:
    """Converts a supported input value to an unrounded ``Decimal``."""
    # bool is a subclass of int, so it must be rejected before the int check.
    if isinstance(value, bool):
        raise InvalidAmountError(f"Amount must not be a boolean, got {value!r}")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        return _parse_amount_string(value)
    raise InvalidAmountError(
        f"Amount must be a Decimal, int, str or float, got {type(value).__name__}"
    )


def _parse_amount_string(text: str) -> Decimal:
    """Parses a string with a decimal point or a decimal comma."""
    stripped = text.strip()
    if not stripped:
        raise InvalidAmountError("Amount must not be empty")
    if "," in stripped and "." in stripped:
        raise InvalidAmountError(
            f"Amount {text!r} must not contain both ',' and '.'; "
            "use one of them as the decimal separator"
        )
    try:
        return Decimal(stripped.replace(",", "."))
    except InvalidOperation as err:
        raise InvalidAmountError(f"Amount {text!r} is not a valid number") from err
