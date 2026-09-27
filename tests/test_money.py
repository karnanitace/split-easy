from decimal import Decimal

import pytest

from spliteasy.exceptions import AllocationError, CurrencyError, InvalidAmountError
from spliteasy.money import (
    CURRENCY_DECIMALS,
    distribute_remainder,
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


def test_distribute_remainder_three_way_split() -> None:
    third = Decimal("100.00") / 3

    result = distribute_remainder(
        {"Ana": third, "Ben": third, "Chen": third}, Decimal("100.00")
    )

    assert result == {
        "Ana": Decimal("33.34"),
        "Ben": Decimal("33.33"),
        "Chen": Decimal("33.33"),
    }
    assert sum(result.values()) == Decimal("100.00")


def test_distribute_remainder_favours_largest_remainders() -> None:
    raw = {
        "a": Decimal("1.001"),
        "b": Decimal("1.009"),
        "c": Decimal("1.005"),
        "d": Decimal("0.985"),
    }

    result = distribute_remainder(raw, Decimal("4.00"))

    assert result == {
        "a": Decimal("1.00"),
        "b": Decimal("1.01"),
        "c": Decimal("1.01"),
        "d": Decimal("0.98"),
    }


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        (["x", "y", "z"], ["3.34", "3.33", "3.33"]),
        (["z", "y", "x"], ["3.34", "3.33", "3.33"]),
        ([3, 1, 2], ["3.34", "3.33", "3.33"]),
    ],
)
def test_distribute_remainder_breaks_ties_by_key_order(
    keys: list[object], expected: list[str]
) -> None:
    third = Decimal("10.00") / 3

    result = distribute_remainder(dict.fromkeys(keys, third), Decimal("10.00"))

    assert list(result) == keys
    assert list(result.values()) == [Decimal(v) for v in expected]


def test_distribute_remainder_ties_after_larger_remainder() -> None:
    raw = {
        "a": Decimal("0.334"),
        "b": Decimal("0.338"),
        "c": Decimal("0.334"),
        "d": Decimal("0.994"),
    }

    result = distribute_remainder(raw, Decimal("2.00"))

    assert result == {
        "a": Decimal("0.34"),
        "b": Decimal("0.34"),
        "c": Decimal("0.33"),
        "d": Decimal("0.99"),
    }


def test_distribute_remainder_jpy_uses_whole_units() -> None:
    third = Decimal("1000") / 3

    result = distribute_remainder(
        {1: third, 2: third, 3: third}, Decimal("1000"), "JPY"
    )

    assert result == {1: Decimal("334"), 2: Decimal("333"), 3: Decimal("333")}
    assert all(value.as_tuple().exponent == 0 for value in result.values())


def test_distribute_remainder_without_leftover() -> None:
    raw = {"a": Decimal("12.50"), "b": Decimal("7.25"), "c": Decimal("0.25")}

    result = distribute_remainder(raw, Decimal("20.00"))

    assert result == raw
    assert all(value.as_tuple().exponent == -2 for value in result.values())


def test_distribute_remainder_handles_negative_amounts() -> None:
    third = Decimal("-100.00") / 3

    result = distribute_remainder(
        {"a": third, "b": third, "c": third}, Decimal("-100.00")
    )

    assert result == {
        "a": Decimal("-33.33"),
        "b": Decimal("-33.33"),
        "c": Decimal("-33.34"),
    }


def test_distribute_remainder_returns_new_dict() -> None:
    raw = {"a": Decimal("5.00"), "b": Decimal("5.00")}

    result = distribute_remainder(raw, Decimal("10.00"))

    assert result is not raw


@pytest.mark.parametrize(
    "total", [Decimal("10.001"), Decimal("10.005"), Decimal("NaN"), Decimal("Infinity")]
)
def test_distribute_remainder_rejects_unquantized_total(total: Decimal) -> None:
    with pytest.raises(AllocationError, match="quantised"):
        distribute_remainder({"a": Decimal("5"), "b": Decimal("5")}, total)


def test_distribute_remainder_rejects_fractional_total_for_jpy() -> None:
    with pytest.raises(AllocationError):
        distribute_remainder({"a": Decimal("5.5")}, Decimal("5.5"), "JPY")


@pytest.mark.parametrize(
    ("raw", "total"),
    [
        ({"a": Decimal("5.00"), "b": Decimal("5.00")}, Decimal("10.03")),
        ({"a": Decimal("5.00"), "b": Decimal("5.00")}, Decimal("9.99")),
        ({"a": Decimal("50"), "b": Decimal("50")}, Decimal("10.00")),
    ],
)
def test_distribute_remainder_rejects_raw_not_matching_total(
    raw: dict[str, Decimal], total: Decimal
) -> None:
    with pytest.raises(AllocationError, match="differs from the total"):
        distribute_remainder(raw, total)


def test_distribute_remainder_rejects_non_finite_raw_amount() -> None:
    with pytest.raises(AllocationError, match="finite"):
        distribute_remainder({"a": Decimal("NaN")}, Decimal("1.00"))


def test_distribute_remainder_rejects_empty_input() -> None:
    with pytest.raises(AllocationError, match="no keys"):
        distribute_remainder({}, Decimal("10.00"))
