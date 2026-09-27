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
from collections.abc import Mapping, Sequence
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


def allocate(
    total: Decimal | int | str,
    weights: Mapping[K, Decimal | int | str],
    currency: str = "EUR",
) -> dict[K, Decimal]:
    """Divides a total among keys in proportion to their weights.

    Each key receives ``total * weight / sum(weights)``, rounded to the
    currency's minor unit with :func:`distribute_remainder`, so the results
    always sum exactly to the total. Keys with a zero weight receive zero.

    A negative total (for example a refund or a discount) is allocated by
    splitting its absolute value and negating the results, so the rounding is
    the mirror image of the positive case.

    Args:
        total: The amount to divide. It is converted with :func:`to_money`.
        weights: Non-negative weights by key, such as share counts or
            percentages. They are converted to ``Decimal`` without rounding.
        currency: The ISO 4217 code whose minor unit the results are rounded to.

    Returns:
        A new dict with the same keys in the same order as ``weights``, where
        the values sum exactly to the quantised total.

    Raises:
        AllocationError: If ``weights`` is empty, a weight is not a finite
            number, a weight is negative, or all weights are zero.
        InvalidAmountError: If ``total`` is not a valid amount.
        CurrencyError: If the currency code is malformed.

    Examples:
        >>> allocate("10.00", {"Ana": 1, "Ben": 2})
        {'Ana': Decimal('3.33'), 'Ben': Decimal('6.67')}
    """
    amount = to_money(total, currency)
    if not weights:
        raise AllocationError("Cannot allocate an amount over no weights")
    decimal_weights = {key: _to_weight(key, weight) for key, weight in weights.items()}
    weight_sum = sum(decimal_weights.values())
    if weight_sum == 0:
        raise AllocationError("Cannot allocate an amount when all weights are zero")

    magnitude = abs(amount)
    raw = {
        key: magnitude * weight / weight_sum for key, weight in decimal_weights.items()
    }
    shares = distribute_remainder(raw, magnitude, currency)
    if amount < 0:
        # Zero shares stay positive zero instead of becoming Decimal("-0.00").
        return {key: -share if share else share for key, share in shares.items()}
    return shares


def split_equally(
    total: Decimal | int | str,
    keys: Sequence[K],
    currency: str = "EUR",
) -> dict[K, Decimal]:
    """Divides a total equally among keys.

    This is :func:`allocate` with a weight of 1 for every key. When the total
    does not divide evenly, the leftover minor units go to the earliest keys.

    Args:
        total: The amount to divide. It is converted with :func:`to_money`.
        keys: The keys to divide among, in order. Each key must appear once.
        currency: The ISO 4217 code whose minor unit the results are rounded to.

    Returns:
        A new dict with the keys in the given order, where the values sum
        exactly to the quantised total.

    Raises:
        AllocationError: If ``keys`` is empty or contains duplicates.
        InvalidAmountError: If ``total`` is not a valid amount.
        CurrencyError: If the currency code is malformed.

    Examples:
        >>> split_equally("100.00", ["Ana", "Ben", "Chen"])
        {'Ana': Decimal('33.34'), 'Ben': Decimal('33.33'), 'Chen': Decimal('33.33')}
    """
    if not keys:
        raise AllocationError("Cannot split an amount among no keys")
    weights = dict.fromkeys(keys, 1)
    if len(weights) != len(keys):
        duplicates = sorted({repr(key) for key in keys if keys.count(key) > 1})
        raise AllocationError(f"Duplicate keys: {', '.join(duplicates)}")
    return allocate(total, weights, currency)


def _to_weight(key: object, weight: object) -> Decimal:
    """Converts one allocation weight to a finite, non-negative ``Decimal``.

    Args:
        key: The key the weight belongs to, used in error messages.
        weight: The weight to convert.

    Returns:
        The weight as an unrounded ``Decimal``.

    Raises:
        AllocationError: If the weight cannot be converted, is not finite or
            is negative.
    """
    try:
        value = _to_decimal(weight)
    except InvalidAmountError as err:
        raise AllocationError(f"Invalid weight for {key!r}: {err}") from err
    if not value.is_finite():
        raise AllocationError(f"Weight for {key!r} must be finite, got {weight!r}")
    if value < 0:
        raise AllocationError(
            f"Weight for {key!r} must not be negative, got {weight!r}"
        )
    return value


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
