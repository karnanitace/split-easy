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
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from spliteasy.exceptions import CurrencyError, InvalidAmountError

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
