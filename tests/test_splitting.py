from collections.abc import Iterator, Mapping
from decimal import Decimal

import pytest

from spliteasy import splitting
from spliteasy.exceptions import AllocationError, SplitError
from spliteasy.models import SplitMethod
from spliteasy.splitting import (
    EqualSplit,
    SplitStrategy,
    get_strategy,
    register_strategy,
)


class DummyEqualSplit(SplitStrategy):
    """Divides the total equally, ignoring the values themselves."""

    method = SplitMethod.EQUAL

    def raw_split(
        self, total: Decimal, values: Mapping[str, Decimal]
    ) -> dict[str, Decimal]:
        self._require_values(values)
        return {member: total / len(values) for member in values}


class DummySharesSplit(SplitStrategy):
    method = SplitMethod.SHARES

    def raw_split(
        self, total: Decimal, values: Mapping[str, Decimal]
    ) -> dict[str, Decimal]:
        weight_sum = sum(values.values())
        return {
            member: total * weight / weight_sum for member, weight in values.items()
        }


class BrokenSplit(SplitStrategy):
    """Returns raw amounts that do not add up to the total."""

    method = SplitMethod.EXACT

    def raw_split(
        self, total: Decimal, values: Mapping[str, Decimal]
    ) -> dict[str, Decimal]:
        return {member: total for member in values}


@pytest.fixture(autouse=True)
def isolated_registry() -> Iterator[None]:
    """Restores the strategy registry after each test."""
    saved = dict(splitting._REGISTRY)
    yield
    splitting._REGISTRY.clear()
    splitting._REGISTRY.update(saved)


@pytest.fixture
def empty_registry() -> None:
    """Starts a test with no registered strategies.

    The autouse ``isolated_registry`` fixture restores the real strategies
    afterwards.
    """
    splitting._REGISTRY.clear()


ALICE_BOB_CAROL = {"Alice": Decimal(1), "Bob": Decimal(1), "Carol": Decimal(1)}


# SplitStrategy


def test_split_strategy_is_abstract() -> None:
    with pytest.raises(TypeError):
        SplitStrategy()  # type: ignore[abstract]


def test_subclass_without_raw_split_cannot_be_instantiated() -> None:
    class Incomplete(SplitStrategy):
        method = SplitMethod.EQUAL

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]


def test_raw_split_is_unrounded() -> None:
    raw = DummyEqualSplit().raw_split(Decimal("100.00"), ALICE_BOB_CAROL)

    assert raw["Alice"] == Decimal("100.00") / 3
    assert raw["Alice"] != Decimal("33.33")


def test_split_rounds_with_largest_remainder() -> None:
    result = DummyEqualSplit().split("100", ALICE_BOB_CAROL)

    assert result == {
        "Alice": Decimal("33.34"),
        "Bob": Decimal("33.33"),
        "Carol": Decimal("33.33"),
    }


def test_split_quantizes_total_first() -> None:
    result = DummyEqualSplit().split("10.005", {"Alice": Decimal(1)})

    assert result == {"Alice": Decimal("10.01")}


def test_split_uses_currency_minor_unit() -> None:
    result = DummyEqualSplit().split(1000, ALICE_BOB_CAROL, currency="JPY")

    assert list(result.values()) == [Decimal("334"), Decimal("333"), Decimal("333")]


def test_split_supports_negative_totals() -> None:
    result = DummyEqualSplit().split("-1.00", ALICE_BOB_CAROL)

    assert sum(result.values()) == Decimal("-1.00")
    assert all(amount < 0 for amount in result.values())


def test_split_keeps_member_order() -> None:
    values = {"Carol": Decimal(1), "Alice": Decimal(2), "Bob": Decimal(1)}

    assert list(DummySharesSplit().split("40", values)) == ["Carol", "Alice", "Bob"]


def test_split_detects_raw_amounts_not_matching_total() -> None:
    with pytest.raises(AllocationError):
        BrokenSplit().split("10.00", {"Alice": Decimal(1), "Bob": Decimal(1)})


def test_require_values_rejects_empty_values() -> None:
    with pytest.raises(SplitError, match="at least one member"):
        DummyEqualSplit().split("10.00", {})


def test_require_values_accepts_non_empty_values() -> None:
    SplitStrategy._require_values({"Alice": Decimal(1)})


# Registry


@pytest.mark.usefixtures("empty_registry")
def test_register_and_get_by_enum() -> None:
    strategy = DummyEqualSplit()

    register_strategy(strategy)

    assert get_strategy(SplitMethod.EQUAL) is strategy


@pytest.mark.parametrize("name", ["equal", " Equal ", "EQUAL"])
@pytest.mark.usefixtures("empty_registry")
def test_get_strategy_by_string(name: str) -> None:
    strategy = DummyEqualSplit()
    register_strategy(strategy)

    assert get_strategy(name) is strategy


@pytest.mark.usefixtures("empty_registry")
def test_strategies_are_registered_per_method() -> None:
    equal, shares = DummyEqualSplit(), DummySharesSplit()

    register_strategy(equal)
    register_strategy(shares)

    assert get_strategy("equal") is equal
    assert get_strategy("shares") is shares


@pytest.mark.usefixtures("empty_registry")
def test_duplicate_registration_raises_value_error() -> None:
    first = DummyEqualSplit()
    register_strategy(first)

    with pytest.raises(ValueError, match="already registered"):
        register_strategy(DummyEqualSplit())

    assert get_strategy(SplitMethod.EQUAL) is first


@pytest.mark.usefixtures("empty_registry")
def test_replace_true_replaces_registered_strategy() -> None:
    register_strategy(DummyEqualSplit())
    replacement = DummyEqualSplit()

    register_strategy(replacement, replace=True)

    assert get_strategy(SplitMethod.EQUAL) is replacement


@pytest.mark.usefixtures("empty_registry")
def test_replace_true_works_without_existing_strategy() -> None:
    strategy = DummyEqualSplit()

    register_strategy(strategy, replace=True)

    assert get_strategy(SplitMethod.EQUAL) is strategy


@pytest.mark.parametrize("name", ["weighted", "", "itemised"])
def test_get_strategy_rejects_unknown_method(name: str) -> None:
    with pytest.raises(SplitError, match="Unknown split method"):
        get_strategy(name)


@pytest.mark.usefixtures("empty_registry")
def test_get_strategy_rejects_unregistered_method() -> None:
    splitting._REGISTRY.pop(SplitMethod.PERCENTAGE, None)

    with pytest.raises(SplitError, match="No split strategy is registered"):
        get_strategy(SplitMethod.PERCENTAGE)


def test_registry_fixture_restores_previous_state() -> None:
    # Guards the fixture itself: each test starts from the original registry.
    assert not any(
        isinstance(strategy, DummyEqualSplit | DummySharesSplit | BrokenSplit)
        for strategy in splitting._REGISTRY.values()
    )


# EqualSplit


def test_equal_split_100_among_three() -> None:
    result = EqualSplit().split("100.00", ALICE_BOB_CAROL)

    assert result == {
        "Alice": Decimal("33.34"),
        "Bob": Decimal("33.33"),
        "Carol": Decimal("33.33"),
    }


def test_equal_raw_split_returns_unrounded_thirds() -> None:
    raw = EqualSplit().raw_split(Decimal("100.00"), ALICE_BOB_CAROL)

    third = Decimal("100.00") / 3
    assert raw == {"Alice": third, "Bob": third, "Carol": third}


def test_equal_split_excludes_members_with_flag_zero() -> None:
    values = {"Alice": Decimal(1), "Bob": Decimal(0), "Carol": Decimal(1)}

    raw = EqualSplit().raw_split(Decimal("10.00"), values)
    result = EqualSplit().split("10.01", values)

    assert raw == {
        "Alice": Decimal("5.00"),
        "Bob": Decimal("0"),
        "Carol": Decimal("5.00"),
    }
    assert result == {
        "Alice": Decimal("5.01"),
        "Bob": Decimal("0.00"),
        "Carol": Decimal("5.00"),
    }


def test_equal_split_treats_any_positive_value_as_included() -> None:
    values = {"Alice": Decimal("0.5"), "Bob": Decimal(3)}

    assert EqualSplit().split("10.00", values) == {
        "Alice": Decimal("5.00"),
        "Bob": Decimal("5.00"),
    }


def test_equal_split_negative_total() -> None:
    raw = EqualSplit().raw_split(Decimal("-1.00"), ALICE_BOB_CAROL)
    result = EqualSplit().split("-1.00", ALICE_BOB_CAROL)

    assert all(amount == Decimal("-1.00") / 3 for amount in raw.values())
    assert sum(result.values()) == Decimal("-1.00")
    assert sorted(result.values()) == [
        Decimal("-0.34"),
        Decimal("-0.33"),
        Decimal("-0.33"),
    ]


def test_equal_split_single_member_gets_everything() -> None:
    assert EqualSplit().split("42.42", {"Alice": Decimal(1)}) == {
        "Alice": Decimal("42.42")
    }


def test_equal_split_jpy() -> None:
    result = EqualSplit().split(1000, ALICE_BOB_CAROL, currency="JPY")

    assert result == {
        "Alice": Decimal("334"),
        "Bob": Decimal("333"),
        "Carol": Decimal("333"),
    }


def test_equal_split_rejects_empty_values() -> None:
    with pytest.raises(SplitError, match="at least one member"):
        EqualSplit().split("10.00", {})


def test_equal_split_rejects_no_included_member() -> None:
    with pytest.raises(SplitError, match="at least one included member"):
        EqualSplit().split("10.00", {"Alice": Decimal(0), "Bob": Decimal(0)})


def test_equal_split_rejects_negative_flag() -> None:
    with pytest.raises(SplitError, match="must not be negative.*'Bob'"):
        EqualSplit().split("10.00", {"Alice": Decimal(1), "Bob": Decimal(-1)})


def test_equal_split_is_registered() -> None:
    strategy = get_strategy("equal")

    assert isinstance(strategy, EqualSplit)
    assert get_strategy(SplitMethod.EQUAL) is strategy
    assert strategy.method is SplitMethod.EQUAL
