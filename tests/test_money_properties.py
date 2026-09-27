"""Property-based tests for allocate and split_equally."""

from decimal import Decimal
from fractions import Fraction

from hypothesis import given
from hypothesis import strategies as st

from spliteasy.money import allocate, minor_unit, split_equally

CURRENCIES = ["EUR", "JPY"]

eur_totals = st.integers(min_value=-10_000_000, max_value=10_000_000).map(
    lambda cents: Decimal(cents).scaleb(-2)
)
jpy_totals = st.integers(min_value=-100_000, max_value=100_000).map(Decimal)


@st.composite
def currency_and_total(draw: st.DrawFn) -> tuple[str, Decimal]:
    """Draws a currency and a total quantised to that currency's minor unit."""
    currency = draw(st.sampled_from(CURRENCIES))
    total = draw(jpy_totals if currency == "JPY" else eur_totals)
    return currency, total


def weight_values(*, positive: bool) -> st.SearchStrategy[Decimal | int]:
    """Integer or three-place Decimal weights up to 1000, optionally above zero."""
    return st.one_of(
        st.integers(min_value=1 if positive else 0, max_value=1_000),
        st.decimals(
            min_value=Decimal("0.001") if positive else Decimal(0),
            max_value=1_000,
            places=3,
            allow_nan=False,
            allow_infinity=False,
        ),
    )


@st.composite
def weight_maps(draw: st.DrawFn) -> dict[str, Decimal | int]:
    """Draws 1 to 12 non-negative weights by key, at least one of them positive."""
    mapping = draw(
        st.dictionaries(
            keys=st.text(min_size=1, max_size=8),
            values=weight_values(positive=False),
            min_size=1,
            max_size=12,
        )
    )
    if all(weight == 0 for weight in mapping.values()):
        first_key = next(iter(mapping))
        mapping[first_key] = draw(weight_values(positive=True))
    return mapping


unique_keys = st.lists(
    st.text(min_size=1, max_size=8), min_size=1, max_size=12, unique=True
)


def exact_share(total: Decimal, weight: Decimal | int, weight_sum: Decimal) -> Fraction:
    """Returns the exact, unrounded proportional share as a fraction."""
    return Fraction(total) * Fraction(weight) / Fraction(weight_sum)


@given(currency_and_total(), weight_maps())
def test_allocate_sums_exactly_to_total(
    money: tuple[str, Decimal], weights: dict[str, Decimal | int]
) -> None:
    """The allocated amounts always add up to exactly the total."""
    currency, total = money

    result = allocate(total, weights, currency)

    assert sum(result.values()) == total


@given(currency_and_total(), weight_maps())
def test_allocate_quantizes_to_minor_unit(
    money: tuple[str, Decimal], weights: dict[str, Decimal | int]
) -> None:
    """Every amount has exactly the currency's number of decimal places."""
    currency, total = money
    exponent = minor_unit(currency).as_tuple().exponent

    result = allocate(total, weights, currency)

    assert all(amount.as_tuple().exponent == exponent for amount in result.values())


@given(currency_and_total(), weight_maps())
def test_allocate_is_within_one_minor_unit_of_exact_share(
    money: tuple[str, Decimal], weights: dict[str, Decimal | int]
) -> None:
    """No amount is a full minor unit or more away from its exact share."""
    currency, total = money
    unit = Fraction(minor_unit(currency))
    weight_sum = sum(Decimal(weight) for weight in weights.values())

    result = allocate(total, weights, currency)

    for key, amount in result.items():
        exact = exact_share(total, weights[key], weight_sum)
        assert abs(Fraction(amount) - exact) < unit


@given(currency_and_total(), weight_maps())
def test_allocate_gives_zero_to_zero_weights(
    money: tuple[str, Decimal], weights: dict[str, Decimal | int]
) -> None:
    """Keys with a weight of zero always receive zero."""
    currency, total = money

    result = allocate(total, weights, currency)

    for key, weight in weights.items():
        if weight == 0:
            assert result[key] == 0


@given(currency_and_total(), weight_maps())
def test_allocate_keeps_keys_in_input_order(
    money: tuple[str, Decimal], weights: dict[str, Decimal | int]
) -> None:
    """The result has exactly the input keys, in the input order."""
    currency, total = money

    result = allocate(total, weights, currency)

    assert list(result) == list(weights)


@given(currency_and_total(), weight_maps())
def test_allocate_is_deterministic(
    money: tuple[str, Decimal], weights: dict[str, Decimal | int]
) -> None:
    """Allocating the same input twice gives the same result."""
    currency, total = money

    first = allocate(total, weights, currency)
    second = allocate(total, weights, currency)

    assert list(first.items()) == list(second.items())


@given(currency_and_total(), weight_maps())
def test_allocate_non_negative_total_gives_no_negative_amounts(
    money: tuple[str, Decimal], weights: dict[str, Decimal | int]
) -> None:
    """A non-negative total never produces a negative amount."""
    currency, total = money
    total = abs(total)

    result = allocate(total, weights, currency)

    assert all(amount >= 0 for amount in result.values())


@given(currency_and_total(), unique_keys)
def test_split_equally_sums_exactly_to_total(
    money: tuple[str, Decimal], keys: list[str]
) -> None:
    """The equal shares always add up to exactly the total."""
    currency, total = money

    result = split_equally(total, keys, currency)

    assert sum(result.values()) == total


@given(currency_and_total(), unique_keys)
def test_split_equally_quantizes_to_minor_unit(
    money: tuple[str, Decimal], keys: list[str]
) -> None:
    """Every equal share has exactly the currency's number of decimal places."""
    currency, total = money
    exponent = minor_unit(currency).as_tuple().exponent

    result = split_equally(total, keys, currency)

    assert all(amount.as_tuple().exponent == exponent for amount in result.values())


@given(currency_and_total(), unique_keys)
def test_split_equally_is_within_one_minor_unit_of_exact_share(
    money: tuple[str, Decimal], keys: list[str]
) -> None:
    """No share is a full minor unit or more away from total / len(keys)."""
    currency, total = money
    unit = Fraction(minor_unit(currency))
    exact = Fraction(total) / len(keys)

    result = split_equally(total, keys, currency)

    assert all(abs(Fraction(amount) - exact) < unit for amount in result.values())


@given(currency_and_total(), unique_keys)
def test_split_equally_gives_larger_shares_to_earlier_keys(
    money: tuple[str, Decimal], keys: list[str]
) -> None:
    """Shares differ by at most one minor unit, and the larger ones come first."""
    currency, total = money
    unit = minor_unit(currency)

    amounts = [abs(amount) for amount in split_equally(total, keys, currency).values()]

    assert max(amounts) - min(amounts) <= unit
    assert amounts == sorted(amounts, reverse=True)


@given(currency_and_total(), unique_keys)
def test_split_equally_keeps_keys_in_input_order(
    money: tuple[str, Decimal], keys: list[str]
) -> None:
    """The result has exactly the input keys, in the input order."""
    currency, total = money

    result = split_equally(total, keys, currency)

    assert list(result) == keys


@given(currency_and_total(), unique_keys)
def test_split_equally_is_deterministic(
    money: tuple[str, Decimal], keys: list[str]
) -> None:
    """Splitting the same input twice gives the same result."""
    currency, total = money

    first = split_equally(total, keys, currency)
    second = split_equally(total, keys, currency)

    assert list(first.items()) == list(second.items())


@given(currency_and_total(), unique_keys)
def test_split_equally_non_negative_total_gives_no_negative_amounts(
    money: tuple[str, Decimal], keys: list[str]
) -> None:
    """A non-negative total never produces a negative share."""
    currency, total = money
    total = abs(total)

    result = split_equally(total, keys, currency)

    assert all(amount >= 0 for amount in result.values())
