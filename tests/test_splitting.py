from collections.abc import Iterator, Mapping
from decimal import Decimal

import pytest

from spliteasy import splitting
from spliteasy.exceptions import AllocationError, MemberNotFoundError, SplitError
from spliteasy.models import (
    Adjustment,
    AdjustmentKind,
    DistributionMode,
    Expense,
    Group,
    LineItem,
    Member,
    Share,
    SplitMethod,
)
from spliteasy.splitting import (
    EqualSplit,
    ExactSplit,
    ItemizedSplit,
    PercentageSplit,
    SharesSplit,
    SplitStrategy,
    apply_split,
    compute_shares,
    get_strategy,
    register_strategy,
    resolve_items,
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


# SharesSplit


def test_shares_split_apartment_example() -> None:
    result = SharesSplit().split("300.00", {"Alice": Decimal(2), "Bob": Decimal(1)})

    assert result == {"Alice": Decimal("200.00"), "Bob": Decimal("100.00")}


def test_shares_raw_split_is_proportional_and_unrounded() -> None:
    raw = SharesSplit().raw_split(
        Decimal("100.00"), {"Alice": Decimal(2), "Bob": Decimal(1)}
    )

    assert raw == {
        "Alice": Decimal("100.00") * 2 / 3,
        "Bob": Decimal("100.00") / 3,
    }


def test_shares_split_fractional_weights() -> None:
    values = {"Alice": Decimal("1.5"), "Bob": Decimal("0.5"), "Carol": Decimal(2)}

    result = SharesSplit().split("80.00", values)

    assert result == {
        "Alice": Decimal("30.00"),
        "Bob": Decimal("10.00"),
        "Carol": Decimal("40.00"),
    }


def test_shares_split_zero_weight_gets_nothing() -> None:
    values = {"Alice": Decimal(1), "Bob": Decimal(0), "Carol": Decimal(3)}

    result = SharesSplit().split("40.00", values)

    assert result == {
        "Alice": Decimal("10.00"),
        "Bob": Decimal("0.00"),
        "Carol": Decimal("30.00"),
    }


def test_shares_split_needs_remainder_rounding() -> None:
    result = SharesSplit().split("10.00", ALICE_BOB_CAROL)

    assert result == {
        "Alice": Decimal("3.34"),
        "Bob": Decimal("3.33"),
        "Carol": Decimal("3.33"),
    }


def test_shares_split_gives_leftover_to_largest_remainder() -> None:
    values = {"Alice": Decimal(1), "Bob": Decimal(2)}

    assert SharesSplit().split("10.00", values) == {
        "Alice": Decimal("3.33"),
        "Bob": Decimal("6.67"),
    }


def test_shares_split_negative_total() -> None:
    values = {"Alice": Decimal(2), "Bob": Decimal(1)}

    result = SharesSplit().split("-300.00", values)

    assert result == {"Alice": Decimal("-200.00"), "Bob": Decimal("-100.00")}


def test_shares_split_jpy() -> None:
    result = SharesSplit().split(1000, {"Alice": Decimal(1), "Bob": Decimal(2)}, "JPY")

    assert result == {"Alice": Decimal("333"), "Bob": Decimal("667")}


def test_shares_split_rejects_empty_values() -> None:
    with pytest.raises(SplitError, match="at least one member"):
        SharesSplit().split("10.00", {})


def test_shares_split_rejects_negative_weight() -> None:
    with pytest.raises(SplitError, match="weight for 'Bob' must not be negative"):
        SharesSplit().split("10.00", {"Alice": Decimal(1), "Bob": Decimal(-1)})


def test_shares_split_rejects_all_zero_weights() -> None:
    with pytest.raises(SplitError, match="at least one positive weight"):
        SharesSplit().split("10.00", {"Alice": Decimal(0), "Bob": Decimal("0.0")})


def test_shares_split_is_registered() -> None:
    strategy = get_strategy("shares")

    assert isinstance(strategy, SharesSplit)
    assert strategy.method is SplitMethod.SHARES


# PercentageSplit


def percentages(**values: str) -> dict[str, Decimal]:
    return {member: Decimal(value) for member, value in values.items()}


def test_percentage_split_60_40() -> None:
    result = PercentageSplit().split("50.00", percentages(Alice="60", Bob="40"))

    assert result == {"Alice": Decimal("30.00"), "Bob": Decimal("20.00")}


def test_percentage_split_thirds_of_100() -> None:
    values = percentages(Alice="33.33", Bob="33.33", Carol="33.34")

    result = PercentageSplit().split("100.00", values)

    assert result == {
        "Alice": Decimal("33.33"),
        "Bob": Decimal("33.33"),
        "Carol": Decimal("33.34"),
    }


def test_percentage_split_with_decimal_percentages() -> None:
    result = PercentageSplit().split("80.00", percentages(Alice="12.5", Bob="87.5"))

    assert result == {"Alice": Decimal("10.00"), "Bob": Decimal("70.00")}


def test_percentage_raw_split_is_unrounded() -> None:
    raw = PercentageSplit().raw_split(
        Decimal("10.00"), percentages(Alice="33.33", Bob="66.67")
    )

    assert raw == {"Alice": Decimal("3.333"), "Bob": Decimal("6.667")}


def test_percentage_split_rounds_with_largest_remainder() -> None:
    result = PercentageSplit().split("10.00", percentages(Alice="33.33", Bob="66.67"))

    assert result == {"Alice": Decimal("3.33"), "Bob": Decimal("6.67")}


def test_percentage_split_zero_percentage() -> None:
    values = percentages(Alice="100", Bob="0")

    assert PercentageSplit().split("25.00", values) == {
        "Alice": Decimal("25.00"),
        "Bob": Decimal("0.00"),
    }


def test_percentage_split_negative_total() -> None:
    result = PercentageSplit().split("-50.00", percentages(Alice="60", Bob="40"))

    assert result == {"Alice": Decimal("-30.00"), "Bob": Decimal("-20.00")}


@pytest.mark.parametrize(
    ("values", "actual_sum"),
    [
        (percentages(Alice="60", Bob="39.5"), "99.5"),
        (percentages(Alice="33.33", Bob="33.33", Carol="33.33"), "99.99"),
        (percentages(Alice="60", Bob="41"), "101"),
        (percentages(Alice="50.001", Bob="50"), "100.001"),
        (percentages(Alice="0", Bob="0"), "0"),
    ],
)
def test_percentage_split_rejects_sum_not_100(
    values: dict[str, Decimal], actual_sum: str
) -> None:
    with pytest.raises(SplitError) as excinfo:
        PercentageSplit().split("10.00", values)

    assert str(excinfo.value) == f"Percentages must sum to 100, got {actual_sum}"


def test_percentage_split_rejects_negative_percentage() -> None:
    with pytest.raises(SplitError, match="Percentage for 'Bob' must not be negative"):
        PercentageSplit().split("10.00", percentages(Alice="110", Bob="-10"))


def test_percentage_split_rejects_empty_values() -> None:
    with pytest.raises(SplitError, match="at least one member"):
        PercentageSplit().split("10.00", {})


def test_percentage_split_is_registered() -> None:
    strategy = get_strategy("percentage")

    assert isinstance(strategy, PercentageSplit)
    assert strategy.method is SplitMethod.PERCENTAGE


# ExactSplit


def amounts(**values: str) -> dict[str, Decimal]:
    return {member: Decimal(value) for member, value in values.items()}


def test_exact_split_dinner_example() -> None:
    values = amounts(Alice="40", Bob="30", Carol="50")

    result = ExactSplit().split("120.00", values)

    assert result == {
        "Alice": Decimal("40.00"),
        "Bob": Decimal("30.00"),
        "Carol": Decimal("50.00"),
    }


def test_exact_raw_split_returns_values_as_new_dict() -> None:
    values = amounts(Alice="40.00", Bob="80.00")

    raw = ExactSplit().raw_split(Decimal("120.00"), values)

    assert raw == values
    assert raw is not values


def test_exact_split_zero_amount_for_one_member() -> None:
    values = amounts(Alice="120.00", Bob="0")

    assert ExactSplit().split("120.00", values) == {
        "Alice": Decimal("120.00"),
        "Bob": Decimal("0.00"),
    }


def test_exact_split_accepts_integer_values() -> None:
    values = {"Alice": 40, "Bob": 80}

    result = ExactSplit().split("120.00", values)  # type: ignore[arg-type]

    assert result == {"Alice": Decimal("40.00"), "Bob": Decimal("80.00")}


@pytest.mark.parametrize(
    ("values", "message"),
    [
        (
            amounts(Alice="40.00", Bob="30.00", Carol="45.00"),
            "Exact amounts sum to 115.00 but the total is 120.00 (missing 5.00)",
        ),
        (
            amounts(Alice="40", Bob="30", Carol="45"),
            "Exact amounts sum to 115.00 but the total is 120.00 (missing 5.00)",
        ),
        (
            amounts(Alice="40.00", Bob="30.00", Carol="50.01"),
            "Exact amounts sum to 120.01 but the total is 120.00 (exceeding 0.01)",
        ),
        (
            amounts(Alice="100", Bob="100"),
            "Exact amounts sum to 200.00 but the total is 120.00 (exceeding 80.00)",
        ),
    ],
)
def test_exact_split_rejects_wrong_sum(
    values: dict[str, Decimal], message: str
) -> None:
    with pytest.raises(SplitError) as excinfo:
        ExactSplit().split("120.00", values)

    assert str(excinfo.value) == message


def test_exact_split_rejects_negative_amount() -> None:
    with pytest.raises(SplitError, match="Exact amount for 'Bob' must not be negative"):
        ExactSplit().split("120.00", amounts(Alice="130", Bob="-10"))


def test_exact_split_negative_total_with_non_positive_amounts() -> None:
    values = amounts(Alice="-0.75", Bob="-0.25", Carol="0")

    result = ExactSplit().split("-1.00", values)

    assert result == {
        "Alice": Decimal("-0.75"),
        "Bob": Decimal("-0.25"),
        "Carol": Decimal("0.00"),
    }


def test_exact_split_negative_total_rejects_positive_amount() -> None:
    with pytest.raises(SplitError, match="must not be positive for a negative total"):
        ExactSplit().split("-1.00", amounts(Alice="-1.50", Bob="0.50"))


def test_exact_split_negative_total_reports_wrong_sum() -> None:
    with pytest.raises(SplitError) as excinfo:
        ExactSplit().split("-1.00", amounts(Alice="-0.75"))

    assert str(excinfo.value) == (
        "Exact amounts sum to -0.75 but the total is -1.00 (missing 0.25)"
    )


def test_exact_split_rejects_empty_values() -> None:
    with pytest.raises(SplitError, match="at least one member"):
        ExactSplit().split("10.00", {})


def test_exact_split_is_registered() -> None:
    strategy = get_strategy("exact")

    assert isinstance(strategy, ExactSplit)
    assert strategy.method is SplitMethod.EXACT


def test_exact_split_negative_total_reports_exceeding_sum() -> None:
    with pytest.raises(SplitError) as excinfo:
        ExactSplit().split("-1.00", amounts(Alice="-0.75", Bob="-0.50"))

    assert str(excinfo.value) == (
        "Exact amounts sum to -1.25 but the total is -1.00 (exceeding 0.25)"
    )


# compute_shares and apply_split


@pytest.fixture
def flat() -> Group:
    return Group(
        name="Flat",
        members=[Member("Alice"), Member("Bob"), Member("Carol")],
    )


def make_expense(**overrides: object) -> Expense:
    fields: dict[str, object] = {
        "description": "Dinner",
        "amount": Decimal("120.00"),
        "payer": "Alice",
    }
    fields.update(overrides)
    return Expense(**fields)  # type: ignore[arg-type]


def as_dict(shares: list[Share]) -> dict[str, Decimal]:
    return {share.member: share.amount for share in shares}


def test_equal_split_with_explicit_participants(flat: Group) -> None:
    expense = make_expense(amount="10.00", participants=["Alice", "Bob"])

    shares = compute_shares(expense, flat)

    assert shares == [Share("Alice", Decimal("5.00")), Share("Bob", Decimal("5.00"))]


def test_equal_split_among_all_members_when_participants_empty(flat: Group) -> None:
    expense = make_expense(amount="100.00")

    shares = compute_shares(expense, flat)

    assert as_dict(shares) == {
        "Alice": Decimal("33.34"),
        "Bob": Decimal("33.33"),
        "Carol": Decimal("33.33"),
    }


def test_names_are_resolved_to_stored_spelling(flat: Group) -> None:
    expense = make_expense(
        amount="10.00", payer="alice", participants=["CAROL", " bob "]
    )

    shares = compute_shares(expense, flat)

    assert [share.member for share in shares] == ["Carol", "Bob"]


def test_exact_split_end_to_end(flat: Group) -> None:
    expense = make_expense(
        split_method="exact",
        split_values={"alice": "40", "Bob": "30", "Carol": "50"},
    )

    shares = compute_shares(expense, flat)

    assert as_dict(shares) == {
        "Alice": Decimal("40.00"),
        "Bob": Decimal("30.00"),
        "Carol": Decimal("50.00"),
    }


def test_exact_split_keeps_zero_amount_members(flat: Group) -> None:
    expense = make_expense(split_method="exact", split_values={"Alice": 120, "Bob": 0})

    shares = compute_shares(expense, flat)

    assert shares == [Share("Alice", Decimal("120.00")), Share("Bob", Decimal("0.00"))]


def test_exact_split_rejects_wrong_sum_end_to_end(flat: Group) -> None:
    expense = make_expense(split_method="exact", split_values={"Alice": 40, "Bob": 30})

    with pytest.raises(SplitError, match=r"missing 50\.00"):
        compute_shares(expense, flat)


@pytest.mark.parametrize(("value", "currency"), [("60.005", "EUR"), ("60.5", "JPY")])
def test_exact_split_rejects_amount_with_too_many_decimals(
    flat: Group, value: str, currency: str
) -> None:
    expense = make_expense(
        amount="120.005" if currency == "EUR" else "121",
        currency=currency,
        split_method="exact",
        split_values={"Alice": value, "Bob": "60.5" if currency == "JPY" else "60"},
    )

    with pytest.raises(SplitError, match=f"not a valid {currency} amount"):
        compute_shares(expense, flat)


def test_percentage_split_end_to_end(flat: Group) -> None:
    expense = make_expense(
        amount="50.00", split_method="percentage", split_values={"Alice": 60, "Bob": 40}
    )

    assert as_dict(compute_shares(expense, flat)) == {
        "Alice": Decimal("30.00"),
        "Bob": Decimal("20.00"),
    }


def test_shares_split_end_to_end(flat: Group) -> None:
    expense = make_expense(
        amount="300.00", split_method="shares", split_values={"Alice": 2, "Carol": 1}
    )

    assert as_dict(compute_shares(expense, flat)) == {
        "Alice": Decimal("200.00"),
        "Carol": Decimal("100.00"),
    }


def test_chf_expense_shares_sum_to_converted_total(flat: Group) -> None:
    expense = make_expense(
        amount="96.00",
        currency="CHF",
        rate_to_base="1.06",
        split_method="shares",
        split_values={"Alice": 1, "Bob": 1, "Carol": 2},
    )

    shares = compute_shares(expense, flat)

    assert expense.base_amount("EUR") == Decimal("101.76")
    assert as_dict(shares) == {
        "Alice": Decimal("25.44"),
        "Bob": Decimal("25.44"),
        "Carol": Decimal("50.88"),
    }
    assert sum(share.amount for share in shares) == Decimal("101.76")


def test_converted_split_rounds_once_after_conversion(flat: Group) -> None:
    expense = make_expense(amount="100.00", currency="CHF", rate_to_base="1.0612")

    shares = compute_shares(expense, flat)

    assert expense.base_amount("EUR") == Decimal("106.12")
    assert sum(share.amount for share in shares) == Decimal("106.12")
    assert as_dict(shares) == {
        "Alice": Decimal("35.38"),
        "Bob": Decimal("35.37"),
        "Carol": Decimal("35.37"),
    }


def test_shares_use_group_currency_minor_unit() -> None:
    group = Group(name="Tokyo", currency="JPY", members=[Member("A"), Member("B")])
    expense = make_expense(
        amount="10.00", payer="A", currency="EUR", rate_to_base="161.37"
    )

    shares = compute_shares(expense, group)

    assert as_dict(shares) == {"A": Decimal("807"), "B": Decimal("807")}
    assert sum(share.amount for share in shares) == expense.base_amount("JPY")


def test_unknown_payer_raises_member_not_found(flat: Group) -> None:
    with pytest.raises(MemberNotFoundError, match="Member 'Dave' not found"):
        compute_shares(make_expense(payer="Dave"), flat)


def test_unknown_participant_raises_member_not_found(flat: Group) -> None:
    expense = make_expense(participants=["Alice", "Dave"])

    with pytest.raises(MemberNotFoundError, match="Member 'Dave' not found"):
        compute_shares(expense, flat)


def test_unknown_split_value_member_raises_member_not_found(flat: Group) -> None:
    expense = make_expense(split_method="shares", split_values={"Alice": 1, "Eve": 1})

    with pytest.raises(MemberNotFoundError, match="'Eve'"):
        compute_shares(expense, flat)


def test_group_without_members_raises_split_error() -> None:
    with pytest.raises(SplitError, match="has no members"):
        compute_shares(make_expense(), Group(name="Empty"))


def test_itemized_split_end_to_end(flat: Group) -> None:
    expense = make_expense(
        split_method="itemized",
        items=[LineItem.for_members("Pizza", "120.00", ["Alice", "Bob"])],
    )

    assert as_dict(compute_shares(expense, flat)) == {
        "Alice": Decimal("60.00"),
        "Bob": Decimal("60.00"),
    }


def test_compute_shares_does_not_modify_expense(flat: Group) -> None:
    expense = make_expense()

    compute_shares(expense, flat)

    assert expense.shares == []


def test_apply_split_sets_shares_and_returns_expense(flat: Group) -> None:
    expense = make_expense(amount="9.00")

    result = apply_split(expense, flat)

    assert result is expense
    assert expense.shares == [
        Share("Alice", Decimal("3.00")),
        Share("Bob", Decimal("3.00")),
        Share("Carol", Decimal("3.00")),
    ]
    assert expense.share_of("bob") == Decimal("3.00")


def test_apply_split_replaces_existing_shares(flat: Group) -> None:
    expense = make_expense(amount="9.00", participants=["Alice", "Bob"])
    apply_split(expense, flat)
    expense.participants = ["Carol"]

    apply_split(expense, flat)

    assert expense.shares == [Share("Carol", Decimal("9.00"))]


# ItemizedSplit


def kaufland_items() -> list[LineItem]:
    return [
        LineItem.for_members("Olive oil", "6.00", ["Alice", "Bob"]),
        LineItem.for_members("Protein bars", "5.00", ["Alice"]),
        LineItem.for_members("Yogurt", "4.00", ["Alice"]),
        LineItem.for_members("Coffee", "5.00", ["Bob"]),
    ]


def itemized(amount: str, items: list[LineItem], **fields: object) -> Expense:
    return make_expense(amount=amount, split_method="itemized", items=items, **fields)


def test_kaufland_example(flat: Group) -> None:
    shares = compute_shares(itemized("20.00", kaufland_items()), flat)

    assert shares == [Share("Alice", Decimal("12.00")), Share("Bob", Decimal("8.00"))]


def test_kaufland_raw_breakdown() -> None:
    rows = ItemizedSplit().raw_breakdown(kaufland_items())

    assert rows == [
        ("Olive oil", {"Alice": Decimal("3.00"), "Bob": Decimal("3.00")}),
        ("Protein bars", {"Alice": Decimal("5.00")}),
        ("Yogurt", {"Alice": Decimal("4.00")}),
        ("Coffee", {"Bob": Decimal("5.00")}),
    ]


def test_proportional_discount(flat: Group) -> None:
    discount = Adjustment(kind=AdjustmentKind.DISCOUNT, amount=Decimal("2.00"))

    shares = compute_shares(
        itemized("18.00", kaufland_items(), adjustments=[discount]), flat
    )

    # Alice bought 12.00 of 20.00, so she gets 60% of the discount.
    assert as_dict(shares) == {"Alice": Decimal("10.80"), "Bob": Decimal("7.20")}


def test_proportional_discount_needing_rounding(flat: Group) -> None:
    items = [
        LineItem.for_members("Bread", "3.00", ["Alice"]),
        LineItem.for_members("Cheese", "4.00", ["Bob"]),
        LineItem.for_members("Wine", "3.00", ["Carol"]),
    ]
    discount = Adjustment(kind=AdjustmentKind.DISCOUNT, amount=Decimal("1.00"))

    shares = compute_shares(itemized("9.00", items, adjustments=[discount]), flat)

    assert sum(share.amount for share in shares) == Decimal("9.00")
    assert as_dict(shares) == {
        "Alice": Decimal("2.70"),
        "Bob": Decimal("3.60"),
        "Carol": Decimal("2.70"),
    }


def test_equal_fee_is_spread_among_members_with_items(flat: Group) -> None:
    fee = Adjustment(
        kind=AdjustmentKind.FEE,
        amount=Decimal("3.00"),
        distribute=DistributionMode.EQUAL,
        description="Delivery",
    )

    shares = compute_shares(
        itemized("23.00", kaufland_items(), adjustments=[fee]), flat
    )

    # Carol has no item, so the fee is shared by Alice and Bob only.
    assert as_dict(shares) == {"Alice": Decimal("13.50"), "Bob": Decimal("9.50")}


def test_several_adjustments_use_item_subtotals(flat: Group) -> None:
    adjustments = [
        Adjustment(kind=AdjustmentKind.DISCOUNT, amount=Decimal("2.00")),
        Adjustment(kind=AdjustmentKind.DEPOSIT, amount=Decimal("1.00")),
    ]

    shares = compute_shares(
        itemized("19.00", kaufland_items(), adjustments=adjustments), flat
    )

    assert as_dict(shares) == {"Alice": Decimal("11.40"), "Bob": Decimal("7.60")}


def test_deposit_return_item_with_negative_price(flat: Group) -> None:
    items = [
        LineItem.for_members("Water", "0.49", ["Alice"], quantity=6),
        LineItem.for_members("Deposit return", "-0.25", ["Alice"], quantity=6),
        LineItem.for_members("Coffee", "5.00", ["Bob"]),
    ]

    shares = compute_shares(itemized("6.44", items), flat)

    assert as_dict(shares) == {"Alice": Decimal("1.44"), "Bob": Decimal("5.00")}


def test_shared_deposit_return_uses_equal_split_of_negative_total(
    flat: Group,
) -> None:
    items = [
        LineItem.for_members("Beer crate", "15.00", ["Alice", "Bob", "Carol"]),
        LineItem.for_members(
            "Crate deposit return", "-3.10", ["Alice", "Bob", "Carol"]
        ),
    ]

    shares = compute_shares(itemized("11.90", items), flat)

    assert sum(share.amount for share in shares) == Decimal("11.90")
    assert sorted(share.amount for share in shares) == [
        Decimal("3.96"),
        Decimal("3.97"),
        Decimal("3.97"),
    ]


def test_percentage_split_item(flat: Group) -> None:
    items = [
        LineItem(
            name="Coffee",
            price=Decimal("5.00"),
            assignees={"Alice": Decimal(70), "Bob": Decimal(30)},
            split_method=SplitMethod.PERCENTAGE,
        ),
        LineItem.for_members("Milk", "1.00", ["Carol"]),
    ]

    shares = compute_shares(itemized("6.00", items), flat)

    assert as_dict(shares) == {
        "Alice": Decimal("3.50"),
        "Bob": Decimal("1.50"),
        "Carol": Decimal("1.00"),
    }


def test_exact_and_shares_split_items(flat: Group) -> None:
    items = [
        LineItem(
            name="Pizza",
            price=Decimal("10.00"),
            quantity=2,
            assignees={"Alice": Decimal("12.00"), "Bob": Decimal("8.00")},
            split_method=SplitMethod.EXACT,
        ),
        LineItem(
            name="Wine",
            price=Decimal("9.00"),
            assignees={"Bob": Decimal(1), "Carol": Decimal(2)},
            split_method=SplitMethod.SHARES,
        ),
    ]

    shares = compute_shares(itemized("29.00", items), flat)

    assert as_dict(shares) == {
        "Alice": Decimal("12.00"),
        "Bob": Decimal("11.00"),
        "Carol": Decimal("6.00"),
    }


@pytest.mark.parametrize(
    ("amount", "message"),
    [
        (
            "21.00",
            "Items and adjustments sum to 20.00 but the total is 21.00 (missing 1.00)",
        ),
        (
            "19.50",
            "Items and adjustments sum to 20.00 but the total is 19.50 "
            "(exceeding 0.50)",
        ),
    ],
)
def test_mismatched_total_raises_split_error(
    flat: Group, amount: str, message: str
) -> None:
    with pytest.raises(SplitError) as excinfo:
        compute_shares(itemized(amount, kaufland_items()), flat)

    assert str(excinfo.value) == message


def test_item_errors_name_the_item(flat: Group) -> None:
    item = LineItem(
        name="Coffee",
        price=Decimal("5.00"),
        assignees={"Alice": Decimal(60), "Bob": Decimal(30)},
        split_method=SplitMethod.PERCENTAGE,
    )

    with pytest.raises(SplitError, match="Item 'Coffee': Percentages must sum to 100"):
        compute_shares(itemized("5.00", [item]), flat)


def test_itemized_names_are_resolved_and_merged(flat: Group) -> None:
    items = [
        LineItem.for_members("Bread", "2.00", ["alice", "BOB"]),
        LineItem.for_members("Milk", "1.00", ["Alice"]),
    ]

    shares = compute_shares(itemized("3.00", items), flat)

    assert shares == [Share("Alice", Decimal("2.00")), Share("Bob", Decimal("1.00"))]


def test_itemized_unknown_assignee_raises(flat: Group) -> None:
    items = [LineItem.for_members("Bread", "2.00", ["Dave"])]

    with pytest.raises(MemberNotFoundError, match="'Dave'"):
        compute_shares(itemized("2.00", items), flat)


def test_itemized_foreign_currency_rounds_once_after_conversion(flat: Group) -> None:
    expense = itemized("20.00", kaufland_items(), currency="CHF", rate_to_base="1.0612")

    shares = compute_shares(expense, flat)

    assert sum(share.amount for share in shares) == expense.base_amount("EUR")
    assert as_dict(shares) == {"Alice": Decimal("12.73"), "Bob": Decimal("8.49")}


def test_member_with_only_a_refund_is_rejected(flat: Group) -> None:
    items = [
        LineItem.for_members("Beer", "5.00", ["Alice"]),
        LineItem.for_members("Deposit return", "-1.00", ["Bob"]),
    ]

    with pytest.raises(SplitError, match="Bob's share would be negative"):
        compute_shares(itemized("4.00", items), flat)


def test_proportional_adjustment_needs_non_zero_subtotal() -> None:
    items = [
        LineItem.for_members("Bottle", "1.00", ["Alice"]),
        LineItem.for_members("Bottle return", "-1.00", ["Alice"]),
    ]
    discount = Adjustment(kind=AdjustmentKind.DISCOUNT, amount=Decimal("0.50"))

    with pytest.raises(SplitError, match="items total zero"):
        ItemizedSplit().raw_split_receipt(items, [discount])


def test_itemized_split_needs_items() -> None:
    with pytest.raises(SplitError, match="at least one item"):
        ItemizedSplit().raw_split_receipt([])


def test_itemized_strategy_is_registered_but_needs_items() -> None:
    strategy = get_strategy("itemized")

    assert isinstance(strategy, ItemizedSplit)
    with pytest.raises(SplitError, match="needs line items"):
        strategy.raw_split(Decimal("10.00"), {"Alice": Decimal(1)})


def test_breakdown_labels_quantities_and_adjustments() -> None:
    items = [LineItem.for_members("Beer", "1.10", ["Alice"], quantity=6)]
    adjustments = [
        Adjustment(kind=AdjustmentKind.DISCOUNT, amount=Decimal("0.60")),
        Adjustment(kind=AdjustmentKind.FEE, amount=Decimal(1), description="Tip"),
    ]

    labels = [label for label, _ in ItemizedSplit().raw_breakdown(items, adjustments)]

    assert labels == ["Beer x6", "Discount", "Tip"]


def test_resolve_items_uses_stored_spelling(flat: Group) -> None:
    items = [LineItem.for_members("Bread", "2.00", ["alice", "BOB"])]

    resolved = resolve_items(items, flat)

    assert list(resolved[0].assignees) == ["Alice", "Bob"]
    assert resolved[0].price == Decimal("2.00")
    assert list(items[0].assignees) == ["alice", "BOB"]
