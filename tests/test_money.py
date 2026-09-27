from decimal import Decimal

import pytest

from spliteasy.exceptions import CurrencyError, InvalidAmountError
from spliteasy.money import (
    CURRENCY_DECIMALS,
    minor_unit,
    normalize_currency,
    to_money,
)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("EUR", "EUR"),
        ("eur", "EUR"),
        ("  usd ", "USD"),
        ("\tJpy\n", "JPY"),
        ("XYZ", "XYZ"),
    ],
)
def test_normalize_currency_strips_and_uppercases(code: str, expected: str) -> None:
    assert normalize_currency(code) == expected


@pytest.mark.parametrize(
    "code", ["", "   ", "EU", "EURO", "E1R", "E R", "€€€", "US$", 978, None]
)
def test_normalize_currency_rejects_malformed_codes(code: object) -> None:
    with pytest.raises(CurrencyError):
        normalize_currency(code)  # type: ignore[arg-type]


def test_currency_decimals_contains_zero_decimal_currencies() -> None:
    assert CURRENCY_DECIMALS["JPY"] == 0
    assert CURRENCY_DECIMALS["KRW"] == 0
    assert CURRENCY_DECIMALS["EUR"] == 2


@pytest.mark.parametrize(
    ("currency", "expected"),
    [
        ("EUR", Decimal("0.01")),
        ("usd", Decimal("0.01")),
        ("JPY", Decimal("1")),
        ("KRW", Decimal("1")),
        ("XYZ", Decimal("0.01")),
    ],
)
def test_minor_unit(currency: str, expected: Decimal) -> None:
    unit = minor_unit(currency)

    assert unit == expected
    assert unit.as_tuple().exponent == expected.as_tuple().exponent


def test_minor_unit_defaults_to_eur() -> None:
    assert minor_unit() == Decimal("0.01")


def test_minor_unit_rejects_malformed_code() -> None:
    with pytest.raises(CurrencyError):
        minor_unit("EURO")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("12.50", "12.50"),
        ("12", "12.00"),
        ("  7.1  ", "7.10"),
        ("-3.20", "-3.20"),
        ("1e2", "100.00"),
        (12, "12.00"),
        (0, "0.00"),
        (-5, "-5.00"),
        (Decimal("9.99"), "9.99"),
        (Decimal("1.5"), "1.50"),
        (0.1, "0.10"),
        (19.99, "19.99"),
        (2.675, "2.68"),
    ],
)
def test_to_money_accepts_valid_inputs(
    value: Decimal | int | str | float, expected: str
) -> None:
    result = to_money(value)

    assert result == Decimal(expected)
    assert str(result) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("12,50", "12.50"), (" 0,5 ", "0.50"), ("-1,99", "-1.99")],
)
def test_to_money_accepts_german_decimal_comma(value: str, expected: str) -> None:
    assert str(to_money(value)) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2.345", "2.35"),
        ("2.344", "2.34"),
        ("2.355", "2.36"),
        ("0.005", "0.01"),
        ("-2.345", "-2.35"),
    ],
)
def test_to_money_rounds_half_up(value: str, expected: str) -> None:
    assert str(to_money(value)) == expected


@pytest.mark.parametrize("value", ["-0", "-0.001", Decimal("-0.00")])
def test_to_money_returns_positive_zero(value: str | Decimal) -> None:
    result = to_money(value)

    assert result == 0
    assert not result.is_signed()


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1500", "1500"), ("1500.4", "1500"), ("1500.5", "1501"), (1500, "1500")],
)
def test_to_money_uses_zero_decimals_for_jpy(value: str | int, expected: str) -> None:
    assert str(to_money(value, "JPY")) == expected


def test_to_money_normalizes_currency_argument() -> None:
    assert str(to_money("1.999", " usd ")) == "2.00"


@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        "",
        "   ",
        "abc",
        "12.5x",
        "1.234,50",
        "1,234.50",
        "1,2,3",
        "NaN",
        "nan",
        "Infinity",
        "-inf",
        float("nan"),
        float("inf"),
        float("-inf"),
        Decimal("NaN"),
        Decimal("Infinity"),
        "1e100",
        None,
        [1],
        b"12.50",
    ],
)
def test_to_money_rejects_invalid_amounts(value: object) -> None:
    with pytest.raises(InvalidAmountError):
        to_money(value)  # type: ignore[arg-type]


def test_to_money_rejects_both_separators_with_helpful_message() -> None:
    with pytest.raises(InvalidAmountError, match="both ',' and '.'"):
        to_money("1.234,50")


def test_to_money_rejects_malformed_currency() -> None:
    with pytest.raises(CurrencyError):
        to_money("1.00", "EURO")
