from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from spliteasy.exceptions import SettlementError
from spliteasy.models import Transfer
from spliteasy.settlement import apply_transfers, settle_greedy


def balances(**values: str) -> dict[str, Decimal]:
    return {name: Decimal(value) for name, value in values.items()}


def as_strings(transfers: list[Transfer]) -> list[str]:
    return [str(transfer) for transfer in transfers]


# settle_greedy


def test_two_people() -> None:
    transfers = settle_greedy(balances(Alice="8.00", Bob="-8.00"))

    assert transfers == [Transfer("Bob", "Alice", Decimal("8.00"))]


def test_three_people() -> None:
    transfers = settle_greedy(balances(Alice="140.00", Bob="-60.00", Carol="-80.00"))

    assert as_strings(transfers) == [
        "Carol -> Alice: 80.00",
        "Bob -> Alice: 60.00",
    ]


def test_four_people() -> None:
    transfers = settle_greedy(
        balances(Alice="50.00", Bob="10.00", Carol="-30.00", Dave="-30.00")
    )

    assert as_strings(transfers) == [
        "Carol -> Alice: 30.00",
        "Dave -> Alice: 20.00",
        "Dave -> Bob: 10.00",
    ]


def test_five_people_where_greedy_is_not_optimal() -> None:
    transfers = settle_greedy(balances(A="6", B="4", C="-4", D="-3", E="-3"))

    assert as_strings(transfers) == [
        "C -> A: 4.00",
        "D -> B: 3.00",
        "E -> A: 2.00",
        "E -> B: 1.00",
    ]


@pytest.mark.parametrize(
    "values",
    [
        {},
        balances(Alice="0.00"),
        balances(Alice="0.00", Bob="0", Carol="-0.00"),
    ],
)
def test_already_settled_balances_need_no_transfers(values: dict[str, Decimal]) -> None:
    assert settle_greedy(values) == []


def test_members_with_zero_balance_are_ignored() -> None:
    transfers = settle_greedy(balances(Alice="5.00", Bob="0.00", Carol="-5.00"))

    assert transfers == [Transfer("Carol", "Alice", Decimal("5.00"))]


@pytest.mark.parametrize(
    ("values", "actual_sum"),
    [
        (balances(Alice="8.00", Bob="-7.99"), "0.01"),
        (balances(Alice="8.00"), "8.00"),
        (balances(Alice="-1.00", Bob="-1.00"), "-2.00"),
    ],
)
def test_balances_not_summing_to_zero_raise(
    values: dict[str, Decimal], actual_sum: str
) -> None:
    with pytest.raises(SettlementError, match=f"got {actual_sum}$"):
        settle_greedy(values)


def test_ties_are_broken_by_name_regardless_of_input_order() -> None:
    forward = balances(Alice="10", Bob="10", Carol="-10", Dave="-10")
    backward = dict(reversed(list(forward.items())))

    assert as_strings(settle_greedy(forward)) == [
        "Carol -> Alice: 10.00",
        "Dave -> Bob: 10.00",
    ]
    assert settle_greedy(backward) == settle_greedy(forward)


def test_output_is_deterministic() -> None:
    values = balances(Eve="-3", Dave="-3", Carol="-4", Bob="4", Alice="6")

    assert settle_greedy(values) == settle_greedy(dict(values))
    assert settle_greedy(values) == settle_greedy(dict(sorted(values.items())))


def test_settle_greedy_does_not_modify_balances() -> None:
    values = balances(Alice="8.00", Bob="-8.00")

    settle_greedy(values)

    assert values == balances(Alice="8.00", Bob="-8.00")


# apply_transfers


def test_apply_transfers_moves_money_from_debtor_to_creditor() -> None:
    values = balances(Alice="8.00", Bob="-8.00")

    result = apply_transfers(values, [Transfer("Bob", "Alice", Decimal("3.00"))])

    assert result == balances(Alice="5.00", Bob="-5.00")
    assert values == balances(Alice="8.00", Bob="-8.00")


def test_apply_transfers_with_greedy_result_settles_everything() -> None:
    values = balances(A="6", B="4", C="-4", D="-3", E="-3")

    result = apply_transfers(values, settle_greedy(values))

    assert all(amount == 0 for amount in result.values())
    assert list(result) == ["A", "B", "C", "D", "E"]


def test_apply_transfers_matches_names_ignoring_case() -> None:
    result = apply_transfers(
        balances(Alice="8.00", Bob="-8.00"), [Transfer("bob", "ALICE", Decimal(8))]
    )

    assert result == balances(Alice="0.00", Bob="0.00")


def test_apply_transfers_rejects_unknown_member() -> None:
    with pytest.raises(SettlementError, match="'Carol', who has no balance"):
        apply_transfers(
            balances(Alice="8.00", Bob="-8.00"),
            [Transfer("Carol", "Alice", Decimal(8))],
        )


# Properties

NAMES = [
    "Alice",
    "Bob",
    "Carol",
    "Dave",
    "Eve",
    "Frank",
    "Grace",
    "Heidi",
    "Ivan",
    "Judy",
]


@st.composite
def zero_sum_balances(draw: st.DrawFn) -> dict[str, Decimal]:
    """Draws 1 to 10 members with balances in cents that sum to zero."""
    names = draw(st.lists(st.sampled_from(NAMES), min_size=1, max_size=10, unique=True))
    cents = draw(
        st.lists(
            st.integers(min_value=-1_000_000, max_value=1_000_000),
            min_size=len(names) - 1,
            max_size=len(names) - 1,
        )
    )
    cents.append(-sum(cents))
    return {
        name: Decimal(amount).scaleb(-2)
        for name, amount in zip(names, cents, strict=True)
    }


@given(zero_sum_balances())
def test_transfers_settle_every_balance_to_zero(values: dict[str, Decimal]) -> None:
    """Applying the suggested transfers leaves every balance at zero."""
    result = apply_transfers(values, settle_greedy(values))

    assert all(amount == 0 for amount in result.values())


@given(zero_sum_balances())
def test_at_most_n_minus_one_transfers(values: dict[str, Decimal]) -> None:
    """The number of transfers is at most (non-zero members - 1)."""
    non_zero = sum(1 for amount in values.values() if amount != 0)

    transfers = settle_greedy(values)

    assert len(transfers) <= max(non_zero - 1, 0)


@given(zero_sum_balances())
def test_every_transfer_is_positive_from_debtor_to_creditor(
    values: dict[str, Decimal],
) -> None:
    """Every transfer has a positive amount and goes from a debtor to a creditor."""
    for transfer in settle_greedy(values):
        assert transfer.amount > 0
        assert values[transfer.debtor] < 0
        assert values[transfer.creditor] > 0
