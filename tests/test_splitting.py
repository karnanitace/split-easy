from collections.abc import Iterator, Mapping
from decimal import Decimal

import pytest

from spliteasy import splitting
from spliteasy.exceptions import AllocationError, SplitError
from spliteasy.models import SplitMethod
from spliteasy.splitting import SplitStrategy, get_strategy, register_strategy


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


def test_register_and_get_by_enum() -> None:
    strategy = DummyEqualSplit()

    register_strategy(strategy)

    assert get_strategy(SplitMethod.EQUAL) is strategy


@pytest.mark.parametrize("name", ["equal", " Equal ", "EQUAL"])
def test_get_strategy_by_string(name: str) -> None:
    strategy = DummyEqualSplit()
    register_strategy(strategy)

    assert get_strategy(name) is strategy


def test_strategies_are_registered_per_method() -> None:
    equal, shares = DummyEqualSplit(), DummySharesSplit()

    register_strategy(equal)
    register_strategy(shares)

    assert get_strategy("equal") is equal
    assert get_strategy("shares") is shares


def test_duplicate_registration_raises_value_error() -> None:
    first = DummyEqualSplit()
    register_strategy(first)

    with pytest.raises(ValueError, match="already registered"):
        register_strategy(DummyEqualSplit())

    assert get_strategy(SplitMethod.EQUAL) is first


def test_replace_true_replaces_registered_strategy() -> None:
    register_strategy(DummyEqualSplit())
    replacement = DummyEqualSplit()

    register_strategy(replacement, replace=True)

    assert get_strategy(SplitMethod.EQUAL) is replacement


def test_replace_true_works_without_existing_strategy() -> None:
    strategy = DummyEqualSplit()

    register_strategy(strategy, replace=True)

    assert get_strategy(SplitMethod.EQUAL) is strategy


@pytest.mark.parametrize("name", ["weighted", "", "itemised"])
def test_get_strategy_rejects_unknown_method(name: str) -> None:
    with pytest.raises(SplitError, match="Unknown split method"):
        get_strategy(name)


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
