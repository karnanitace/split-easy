from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from spliteasy.exceptions import (
    CurrencyError,
    DuplicateError,
    ExpenseNotFoundError,
    GroupNotFoundError,
    MemberNotFoundError,
    SplitError,
    StorageError,
    ValidationError,
)
from spliteasy.models import Expense, LineItem, Share, SplitMethod
from spliteasy.services import GroupService
from spliteasy.storage import SQLiteRepository
from spliteasy.storage.sqlite import DB_ENV_VAR


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "spliteasy.db"


@pytest.fixture
def service(db_path: Path) -> Iterator[GroupService]:
    group_service = GroupService(SQLiteRepository(db_path))
    yield group_service
    group_service.close()


@pytest.fixture
def flat(service: GroupService) -> str:
    service.create_group("Flat", members=["Alice", "Bob", "Carol"])
    return "Flat"


def zeros(*names: str) -> dict[str, Decimal]:
    return dict.fromkeys(names, Decimal("0.00"))


# Full roommate scenario


def test_roommate_scenario(service: GroupService) -> None:
    group = service.create_group("Flat", currency="eur", members=["Alice"])
    added = service.add_members("flat", ["Bob", "Carol"])

    service.add_expense(
        "Flat",
        "Rent",
        "900.00",
        "Alice",
        split="shares",
        split_values={"Alice": 2, "Bob": 1, "Carol": 1},
        category="rent",
    )
    service.add_expense("Flat", "Groceries", "60", "bob", category="food")
    service.add_expense(
        "Flat",
        "Internet",
        "45",
        "Carol",
        split=SplitMethod.EXACT,
        split_values={"alice": "15", "bob": "15", "carol": "15"},
    )

    assert group.currency == "EUR"
    assert [member.name for member in added] == ["Bob", "Carol"]
    assert service.balances("Flat") == {
        "Alice": Decimal("415.00"),
        "Bob": Decimal("-200.00"),
        "Carol": Decimal("-215.00"),
    }

    transfers = service.suggest_settlement("Flat")
    assert [str(transfer) for transfer in transfers] == [
        "Carol -> Alice: 215.00",
        "Bob -> Alice: 200.00",
    ]

    for transfer in transfers:
        service.record_payment(
            "Flat", transfer.debtor, transfer.creditor, transfer.amount
        )

    assert service.balances("Flat") == zeros("Alice", "Bob", "Carol")
    assert service.suggest_settlement("Flat") == []
    ledger = service.get_ledger("Flat")
    assert len(ledger.expenses) == 3
    assert [payment.id for payment in ledger.payments] == [1, 2]


def test_summary(service: GroupService, flat: str) -> None:
    service.add_expense(flat, "Pizza", "30", "Alice")
    service.record_payment(flat, "Bob", "Alice", "10")

    summary = service.summary(flat)

    assert summary["Alice"] == {
        "paid": Decimal("30.00"),
        "owed": Decimal("10.00"),
        "sent": Decimal("0.00"),
        "received": Decimal("10.00"),
        "balance": Decimal("10.00"),
    }
    assert summary["Bob"]["balance"] == Decimal("0.00")


# Groups


def test_create_group_returns_saved_group(service: GroupService) -> None:
    group = service.create_group("  Italy   Trip ", members=["Alice", "Bob"])

    assert group.name == "Italy Trip"
    assert group.id is not None
    assert service.list_groups() == ["Italy Trip"]
    assert service.get_ledger("italy trip").group.member_names == ["Alice", "Bob"]


def test_create_group_rejects_duplicate_name(service: GroupService, flat: str) -> None:
    with pytest.raises(DuplicateError, match="'FLAT' already exists"):
        service.create_group("FLAT")


def test_create_group_rejects_duplicate_members(service: GroupService) -> None:
    with pytest.raises(DuplicateError):
        service.create_group("Flat", members=["Alice", "alice"])

    assert service.list_groups() == []


def test_delete_group(service: GroupService, flat: str) -> None:
    service.create_group("Trip")

    service.delete_group("flat")

    assert service.list_groups() == ["Trip"]
    with pytest.raises(GroupNotFoundError):
        service.get_ledger("Flat")


def test_missing_group_raises(service: GroupService) -> None:
    with pytest.raises(GroupNotFoundError, match="Group 'Nowhere' not found"):
        service.balances("Nowhere")


# Members


def test_add_members_rejects_duplicates_without_saving_any(
    service: GroupService, flat: str
) -> None:
    with pytest.raises(DuplicateError):
        service.add_members(flat, ["Dave", "alice"])

    assert service.get_ledger(flat).group.member_names == ["Alice", "Bob", "Carol"]


def test_remove_member_without_activity(service: GroupService, flat: str) -> None:
    service.add_expense(flat, "Pizza", "20", "Alice", participants=["Alice", "Bob"])

    service.remove_member(flat, "carol")

    assert service.get_ledger(flat).group.member_names == ["Alice", "Bob"]


def test_remove_member_with_balance_is_rejected(
    service: GroupService, flat: str
) -> None:
    service.add_expense(flat, "Pizza", "30", "Alice")

    with pytest.raises(ValidationError, match="'Bob': their balance is -10.00"):
        service.remove_member(flat, "Bob")


def test_remove_member_in_expense_with_zero_balance_is_rejected(
    service: GroupService, flat: str
) -> None:
    service.add_expense(flat, "Snack", "5", "Carol", participants=["Carol"])

    assert service.balances(flat)["Carol"] == 0
    with pytest.raises(ValidationError, match="appear in existing expenses"):
        service.remove_member(flat, "Carol")


def test_remove_member_in_payment_with_zero_balance_is_rejected(
    service: GroupService, flat: str
) -> None:
    service.record_payment(flat, "Bob", "Carol", "5")
    service.record_payment(flat, "Carol", "Bob", "5")

    assert service.balances(flat)["Carol"] == 0
    with pytest.raises(ValidationError, match="or payments"):
        service.remove_member(flat, "Carol")


def test_remove_unknown_member_raises(service: GroupService, flat: str) -> None:
    with pytest.raises(MemberNotFoundError):
        service.remove_member(flat, "Dave")


# Expenses


def test_add_expense_resolves_names_and_assigns_ids(
    service: GroupService, flat: str
) -> None:
    first = service.add_expense(
        flat, "Pizza", "20", "alice", participants=["ALICE", "bob"]
    )
    second = service.add_expense(flat, "Taxi", "9", "CAROL")

    assert first.id == 1
    assert second.id == 2
    assert first.payer == "Alice"
    assert first.participants == ["Alice", "Bob"]
    assert first.shares == [
        Share("Alice", Decimal("10.00")),
        Share("Bob", Decimal("10.00")),
    ]
    assert first.group_id == service.get_ledger(flat).group.id


def test_add_expense_with_unknown_member_saves_nothing(
    service: GroupService, flat: str
) -> None:
    with pytest.raises(MemberNotFoundError):
        service.add_expense(flat, "Pizza", "20", "Alice", participants=["Dave"])

    assert service.get_ledger(flat).expenses == []


def test_itemized_expense_is_not_supported_yet(
    service: GroupService, flat: str
) -> None:
    with pytest.raises(SplitError, match="not supported yet"):
        service.add_expense(
            flat,
            "Kaufland",
            "6.00",
            "Alice",
            split="itemized",
            items=[LineItem.for_members("Oil", "6.00", ["Alice", "Bob"])],
        )

    assert service.get_ledger(flat).expenses == []


def test_foreign_currency_with_rate(service: GroupService, flat: str) -> None:
    expense = service.add_expense(
        flat,
        "Fondue",
        "96.00",
        "Carol",
        currency="chf",
        rate="1.06",
        split="shares",
        split_values={"Alice": 1, "Bob": 1, "Carol": 2},
    )

    assert expense.currency == "CHF"
    assert expense.rate_to_base == Decimal("1.06")
    assert expense.base_amount("EUR") == Decimal("101.76")
    assert service.balances(flat) == {
        "Alice": Decimal("-25.44"),
        "Bob": Decimal("-25.44"),
        "Carol": Decimal("50.88"),
    }


def test_foreign_currency_without_rate_is_rejected(
    service: GroupService, flat: str
) -> None:
    with pytest.raises(
        CurrencyError, match="An exchange rate is required for CHF -> EUR"
    ):
        service.add_expense(flat, "Fondue", "96.00", "Carol", currency="CHF")

    assert service.get_ledger(flat).expenses == []


def test_group_currency_accepts_rate_of_one(service: GroupService, flat: str) -> None:
    expense = service.add_expense(flat, "Pizza", "30", "Alice", currency="EUR", rate=1)

    assert expense.rate_to_base == Decimal(1)


def test_group_currency_rejects_other_rate(service: GroupService, flat: str) -> None:
    with pytest.raises(CurrencyError, match="must be 1"):
        service.add_expense(flat, "Pizza", "30", "Alice", rate="1.2")


def test_add_expense_passes_date_note_and_category(
    service: GroupService, flat: str
) -> None:
    expense = service.add_expense(
        flat,
        "Pizza",
        "30",
        "Alice",
        category=" Food ",
        date=date(2026, 9, 1),
        note="Friday",
    )

    stored = service.get_ledger(flat).get_expense(expense.id)  # type: ignore[arg-type]
    assert stored.category == "food"
    assert stored.date == date(2026, 9, 1)
    assert stored.note == "Friday"


@pytest.fixture
def filled_flat(service: GroupService, flat: str) -> str:
    service.add_expense(
        flat, "Rent", "900", "Alice", category="rent", date=date(2026, 9, 1)
    )
    service.add_expense(
        flat,
        "Dinner",
        "40",
        "Bob",
        participants=["Bob", "Carol"],
        category="food",
        date=date(2026, 9, 5),
    )
    service.add_expense(
        flat,
        "Snacks",
        "10",
        "Carol",
        split="exact",
        split_values={"Carol": 10, "Alice": 0},
        category="Food",
        date=date(2026, 8, 30),
    )
    service.add_expense(
        flat, "Taxi", "15", "Alice", category="transport", date=date(2026, 9, 1)
    )
    return flat


def descriptions(expenses: list[Expense]) -> list[str]:
    return [expense.description for expense in expenses]


def test_list_expenses_sorted_by_date_then_id(
    service: GroupService, filled_flat: str
) -> None:
    assert descriptions(service.list_expenses(filled_flat)) == [
        "Snacks",
        "Rent",
        "Taxi",
        "Dinner",
    ]


def test_list_expenses_by_member(service: GroupService, filled_flat: str) -> None:
    # Alice paid Rent and Taxi; her exact share of Snacks is zero.
    assert descriptions(service.list_expenses(filled_flat, member="alice")) == [
        "Rent",
        "Taxi",
    ]
    assert descriptions(service.list_expenses(filled_flat, member="Carol")) == [
        "Snacks",
        "Rent",
        "Taxi",
        "Dinner",
    ]


def test_list_expenses_by_category(service: GroupService, filled_flat: str) -> None:
    assert descriptions(service.list_expenses(filled_flat, category="FOOD")) == [
        "Snacks",
        "Dinner",
    ]


def test_list_expenses_by_member_and_category(
    service: GroupService, filled_flat: str
) -> None:
    result = service.list_expenses(filled_flat, member="Bob", category="food")

    assert descriptions(result) == ["Dinner"]


def test_list_expenses_unknown_member_raises(
    service: GroupService, filled_flat: str
) -> None:
    with pytest.raises(MemberNotFoundError):
        service.list_expenses(filled_flat, member="Dave")


def test_delete_expense(service: GroupService, flat: str) -> None:
    pizza = service.add_expense(flat, "Pizza", "30", "Alice")
    service.add_expense(flat, "Taxi", "12", "Bob")

    service.delete_expense(flat, pizza.id)  # type: ignore[arg-type]

    assert descriptions(service.list_expenses(flat)) == ["Taxi"]
    assert service.balances(flat) == {
        "Alice": Decimal("-4.00"),
        "Bob": Decimal("8.00"),
        "Carol": Decimal("-4.00"),
    }


def test_delete_missing_expense_raises(service: GroupService, flat: str) -> None:
    with pytest.raises(ExpenseNotFoundError, match="Expense 99 not found"):
        service.delete_expense(flat, 99)


# Payments


def test_record_payment(service: GroupService, flat: str) -> None:
    payment = service.record_payment(
        flat, "bob", "ALICE", "12,345", date=date(2026, 9, 2), note="cash"
    )

    assert payment.from_member == "Bob"
    assert payment.to_member == "Alice"
    assert payment.amount == Decimal("12.35")
    assert payment.id == 1
    assert service.get_ledger(flat).payments == [payment]


def test_record_payment_rounds_to_group_currency(service: GroupService) -> None:
    service.create_group("Tokyo", currency="JPY", members=["Aiko", "Ben"])

    payment = service.record_payment("Tokyo", "Ben", "Aiko", "1500.5")

    assert payment.amount == Decimal("1501")


@pytest.mark.parametrize(
    ("sender", "recipient", "error"),
    [
        ("Bob", "bob", ValidationError),
        ("Bob", "Dave", MemberNotFoundError),
    ],
)
def test_record_payment_rejects_invalid_members(
    service: GroupService, flat: str, sender: str, recipient: str, error: type
) -> None:
    with pytest.raises(error):
        service.record_payment(flat, sender, recipient, "5")

    assert service.get_ledger(flat).payments == []


# Persistence and lifecycle


def test_persistence_across_service_instances(db_path: Path) -> None:
    first = GroupService(SQLiteRepository(db_path))
    first.create_group("Flat", members=["Alice", "Bob"])
    first.add_expense("Flat", "Pizza", "30", "Alice")
    first.record_payment("Flat", "Bob", "Alice", "5")
    first.close()

    second = GroupService(SQLiteRepository(db_path))
    try:
        assert second.list_groups() == ["Flat"]
        assert second.balances("Flat") == {
            "Alice": Decimal("10.00"),
            "Bob": Decimal("-10.00"),
        }
        assert second.add_expense("Flat", "Taxi", "8", "Bob").id == 2
    finally:
        second.close()


def test_service_as_context_manager_closes_repository(db_path: Path) -> None:
    with GroupService(SQLiteRepository(db_path)) as service:
        service.create_group("Flat")

    with pytest.raises(StorageError):
        service.list_groups()


def test_default_repository_uses_environment_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "env.db"
    monkeypatch.setenv(DB_ENV_VAR, str(path))

    with GroupService() as service:
        service.create_group("Flat")
        assert isinstance(service.repository, SQLiteRepository)

    assert path.is_file()
