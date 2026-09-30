from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from spliteasy.balances import SUMMARY_FIELDS, compute_balances, member_summary
from spliteasy.exceptions import MemberNotFoundError, SettlementError, SplitError
from spliteasy.models import Expense, Group, Member, Payment, Share
from spliteasy.splitting import apply_split


def make_group(*names: str, currency: str = "EUR") -> Group:
    return Group(
        name="Test", currency=currency, members=[Member(name) for name in names]
    )


def expense_with_shares(
    payer: str, amount: str, shares: dict[str, str], **fields: object
) -> Expense:
    return Expense(
        description=str(fields.pop("description", "Expense")),
        amount=Decimal(amount),
        payer=payer,
        shares=[Share(member, Decimal(value)) for member, value in shares.items()],
        **fields,  # type: ignore[arg-type]
    )


def payment(sender: str, recipient: str, amount: str) -> Payment:
    return Payment(from_member=sender, to_member=recipient, amount=Decimal(amount))


# compute_balances


def test_alice_pays_groceries_for_alice_and_bob() -> None:
    group = make_group("Alice", "Bob")
    groceries = expense_with_shares("Alice", "20.00", {"Alice": "12.00", "Bob": "8.00"})

    balances = compute_balances(group, [groceries])

    assert balances == {"Alice": Decimal("8.00"), "Bob": Decimal("-8.00")}


def test_three_person_trip() -> None:
    group = make_group("Alice", "Bob", "Carol")
    expenses = [
        apply_split(Expense(description="Hotel", amount="300", payer="Alice"), group),
        apply_split(Expense(description="Fuel", amount="90", payer="Bob"), group),
        apply_split(
            Expense(
                description="Dinner",
                amount="60",
                payer="Carol",
                split_method="exact",
                split_values={"Alice": 30, "Bob": 20, "Carol": 10},
            ),
            group,
        ),
    ]

    balances = compute_balances(group, expenses)

    # Alice: paid 300, owes 100 + 30 + 30; Bob: paid 90, owes 100 + 30 + 20;
    # Carol: paid 60, owes 100 + 30 + 10.
    assert balances == {
        "Alice": Decimal("140.00"),
        "Bob": Decimal("-60.00"),
        "Carol": Decimal("-80.00"),
    }


def test_payment_settles_debt_to_zero() -> None:
    group = make_group("Alice", "Bob")
    groceries = expense_with_shares("Alice", "20.00", {"Alice": "12.00", "Bob": "8.00"})

    balances = compute_balances(group, [groceries], [payment("Bob", "Alice", "8.00")])

    assert balances == {"Alice": Decimal("0.00"), "Bob": Decimal("0.00")}


def test_partial_payment_reduces_debt() -> None:
    group = make_group("Alice", "Bob")
    groceries = expense_with_shares("Alice", "20.00", {"Alice": "12.00", "Bob": "8.00"})

    balances = compute_balances(group, [groceries], [payment("Bob", "Alice", "5.00")])

    assert balances == {"Alice": Decimal("3.00"), "Bob": Decimal("-3.00")}


def test_member_without_activity_has_zero_balance() -> None:
    group = make_group("Alice", "Bob", "Dave")
    groceries = expense_with_shares("Alice", "20.00", {"Alice": "12.00", "Bob": "8.00"})

    balances = compute_balances(group, [groceries])

    assert balances["Dave"] == Decimal("0.00")
    assert str(balances["Dave"]) == "0.00"


def test_balances_cover_every_member_in_group_order() -> None:
    group = make_group("Carol", "Alice", "Bob")
    groceries = expense_with_shares("Bob", "10.00", {"Bob": "5.00", "Alice": "5.00"})

    assert list(compute_balances(group, [groceries])) == ["Carol", "Alice", "Bob"]


def test_no_expenses_gives_zero_balances() -> None:
    group = make_group("Alice", "Bob", currency="JPY")

    assert compute_balances(group, []) == {"Alice": Decimal(0), "Bob": Decimal(0)}
    assert str(compute_balances(group, [])["Alice"]) == "0"


def test_names_are_resolved_to_stored_spelling() -> None:
    group = make_group("Alice", "Bob")
    groceries = expense_with_shares("alice", "20.00", {"ALICE": "12.00", "bob": "8.00"})

    balances = compute_balances(group, [groceries], [payment("BOB", "alice", "1.00")])

    assert balances == {"Alice": Decimal("7.00"), "Bob": Decimal("-7.00")}


def test_foreign_currency_expense_uses_base_amount() -> None:
    group = make_group("Alice", "Bob")
    expense = apply_split(
        Expense(
            description="Fondue",
            amount="96.00",
            payer="Bob",
            currency="CHF",
            rate_to_base="1.06",
        ),
        group,
    )

    balances = compute_balances(group, [expense])

    assert balances == {"Alice": Decimal("-50.88"), "Bob": Decimal("50.88")}


def test_expense_without_shares_raises_split_error() -> None:
    group = make_group("Alice", "Bob")
    expense = Expense(description="Taxi", amount="15.00", payer="Alice")

    with pytest.raises(SplitError, match="Expense 'Taxi' has no computed shares"):
        compute_balances(group, [expense])


@pytest.mark.parametrize(
    ("expenses", "payments"),
    [
        ([expense_with_shares("Dave", "10.00", {"Alice": "10.00"})], []),
        ([expense_with_shares("Alice", "10.00", {"Eve": "10.00"})], []),
        ([], [payment("Alice", "Eve", "1.00")]),
        ([], [payment("Eve", "Alice", "1.00")]),
    ],
)
def test_unknown_member_raises_member_not_found(
    expenses: list[Expense], payments: list[Payment]
) -> None:
    with pytest.raises(MemberNotFoundError):
        compute_balances(make_group("Alice", "Bob"), expenses, payments)


def test_shares_not_matching_amount_raise_settlement_error() -> None:
    group = make_group("Alice", "Bob")
    stale = expense_with_shares("Alice", "20.00", {"Alice": "10.00", "Bob": "8.00"})

    with pytest.raises(SettlementError, match="sum to 2.00"):
        compute_balances(group, [stale])


def test_compute_balances_does_not_modify_inputs() -> None:
    group = make_group("Alice", "Bob")
    groceries = expense_with_shares("Alice", "20.00", {"Alice": "12.00", "Bob": "8.00"})
    shares_before = list(groceries.shares)

    compute_balances(group, [groceries], [payment("Bob", "Alice", "8.00")])

    assert groceries.shares == shares_before
    assert group.member_names == ["Alice", "Bob"]


# member_summary


def test_member_summary_values() -> None:
    group = make_group("Alice", "Bob", "Carol")
    expenses = [
        expense_with_shares(
            "Alice", "30.00", {"Alice": "10.00", "Bob": "10.00", "Carol": "10.00"}
        ),
        expense_with_shares("Bob", "12.00", {"Alice": "6.00", "Bob": "6.00"}),
    ]
    payments = [payment("Carol", "Alice", "10.00"), payment("Bob", "Alice", "2.00")]

    summary = member_summary(group, expenses, payments)

    assert summary == {
        "Alice": {
            "paid": Decimal("30.00"),
            "owed": Decimal("16.00"),
            "sent": Decimal("0.00"),
            "received": Decimal("12.00"),
            "balance": Decimal("2.00"),
        },
        "Bob": {
            "paid": Decimal("12.00"),
            "owed": Decimal("16.00"),
            "sent": Decimal("2.00"),
            "received": Decimal("0.00"),
            "balance": Decimal("-2.00"),
        },
        "Carol": {
            "paid": Decimal("0.00"),
            "owed": Decimal("10.00"),
            "sent": Decimal("10.00"),
            "received": Decimal("0.00"),
            "balance": Decimal("0.00"),
        },
    }


def test_member_summary_keys_are_in_documented_order() -> None:
    summary = member_summary(make_group("Alice"), [])

    assert tuple(summary["Alice"]) == SUMMARY_FIELDS


def test_member_summary_balance_matches_compute_balances() -> None:
    group = make_group("Alice", "Bob")
    groceries = expense_with_shares("Alice", "20.00", {"Alice": "12.00", "Bob": "8.00"})
    payments = [payment("Bob", "Alice", "3.00")]

    summary = member_summary(group, [groceries], payments)

    assert {name: row["balance"] for name, row in summary.items()} == compute_balances(
        group, [groceries], payments
    )


# Invariant: balances always sum to zero

NAMES = ["Alice", "Bob", "Carol", "Dave", "Eve"]


@st.composite
def expense_lists(draw: st.DrawFn) -> list[Expense]:
    """Draws equal-split expenses with random payers, participants and rates."""
    expenses = []
    for index in range(draw(st.integers(min_value=0, max_value=8))):
        participants = draw(
            st.lists(st.sampled_from(NAMES), min_size=1, max_size=5, unique=True)
        )
        expenses.append(
            Expense(
                description=f"Expense {index}",
                amount=Decimal(draw(st.integers(1, 1_000_000))).scaleb(-2),
                payer=draw(st.sampled_from(NAMES)),
                participants=participants,
                rate_to_base=draw(
                    st.decimals(
                        min_value=Decimal("0.01"),
                        max_value=Decimal(200),
                        places=4,
                        allow_nan=False,
                        allow_infinity=False,
                    )
                ),
                date=date(2026, 9, 1),
            )
        )
    return expenses


@st.composite
def payment_lists(draw: st.DrawFn) -> list[Payment]:
    """Draws payments between two different random members."""
    payments = []
    for _ in range(draw(st.integers(min_value=0, max_value=5))):
        sender, recipient = draw(
            st.lists(st.sampled_from(NAMES), min_size=2, max_size=2, unique=True)
        )
        amount = Decimal(draw(st.integers(1, 100_000))).scaleb(-2)
        payments.append(Payment(from_member=sender, to_member=recipient, amount=amount))
    return payments


@given(expense_lists(), payment_lists())
def test_balances_always_sum_to_zero(
    expenses: list[Expense], payments: list[Payment]
) -> None:
    """Invariant: the balances of a group always sum to exactly zero."""
    group = make_group(*NAMES)
    for expense in expenses:
        apply_split(expense, group)

    balances = compute_balances(group, expenses, payments)

    assert sum(balances.values()) == 0
    assert list(balances) == NAMES
