from collections.abc import Iterator
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from spliteasy.exceptions import GroupNotFoundError, StorageError
from spliteasy.models import (
    Adjustment,
    AdjustmentKind,
    DistributionMode,
    Expense,
    Group,
    Ledger,
    LineItem,
    Member,
    Payment,
    Share,
    SplitMethod,
)
from spliteasy.splitting import apply_split
from spliteasy.storage import Repository, SQLiteRepository
from spliteasy.storage.schema import TABLES
from spliteasy.storage.sqlite import DB_ENV_VAR, default_db_path


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "spliteasy.db"


@pytest.fixture
def repo(db_path: Path) -> Iterator[SQLiteRepository]:
    repository = SQLiteRepository(db_path)
    yield repository
    repository.close()


def make_ledger(
    name: str = "Italy Trip",
    members: tuple[str, ...] = ("Alice", "Bob", "Carol"),
    payments: tuple[Payment, ...] = (),
) -> Ledger:
    return Ledger(
        group=Group(
            name=name,
            currency="EUR",
            members=[Member(member) for member in members],
            created_at=datetime(2026, 9, 1, 12, 30, tzinfo=timezone.utc),
        ),
        payments=list(payments),
    )


def bob_pays_alice(amount: str = "8.00", **fields: object) -> Payment:
    return Payment(
        from_member="Bob",
        to_member="Alice",
        amount=Decimal(amount),
        date=date(2026, 9, 2),
        **fields,  # type: ignore[arg-type]
    )


# Save and load


def test_save_and_load_group_with_members_and_payments(repo: SQLiteRepository) -> None:
    ledger = make_ledger(
        payments=(bob_pays_alice("8.00", note="cash"), bob_pays_alice("1.50"))
    )

    repo.save(ledger)
    loaded = repo.load("Italy Trip")

    assert loaded.group.name == "Italy Trip"
    assert loaded.group.currency == "EUR"
    assert loaded.group.created_at == datetime(2026, 9, 1, 12, 30, tzinfo=timezone.utc)
    assert loaded.group.member_names == ["Alice", "Bob", "Carol"]
    assert loaded.expenses == []
    assert loaded.payments == [
        bob_pays_alice("8.00", note="cash", id=1, group_id=loaded.group.id),
        bob_pays_alice("1.50", id=2, group_id=loaded.group.id),
    ]


def test_decimals_and_dates_round_trip_exactly(repo: SQLiteRepository) -> None:
    repo.save(make_ledger(payments=(bob_pays_alice("1234567.89"),)))

    payment = repo.load("Italy Trip").payments[0]

    assert payment.amount == Decimal("1234567.89")
    assert str(payment.amount) == "1234567.89"
    assert payment.date == date(2026, 9, 2)


def test_member_order_is_preserved(repo: SQLiteRepository) -> None:
    repo.save(make_ledger(members=("Zoë", "Alice", "Mallory", "Bob")))

    assert repo.load("Italy Trip").group.member_names == [
        "Zoë",
        "Alice",
        "Mallory",
        "Bob",
    ]


def test_save_sets_group_and_payment_ids(repo: SQLiteRepository) -> None:
    ledger = make_ledger(payments=(bob_pays_alice(id=7), bob_pays_alice()))

    repo.save(ledger)

    assert ledger.group.id is not None
    assert [payment.id for payment in ledger.payments] == [7, 8]
    assert all(payment.group_id == ledger.group.id for payment in ledger.payments)


def test_load_returns_database_ids(repo: SQLiteRepository) -> None:
    ledger = make_ledger(payments=(bob_pays_alice(),))
    repo.save(ledger)

    loaded = repo.load("Italy Trip")

    assert loaded.group.id == ledger.group.id
    assert loaded.payments[0].id == 1
    assert loaded.payments[0].group_id == ledger.group.id


# Lookups by name


@pytest.mark.parametrize(
    "name", ["Italy Trip", "italy trip", "ITALY TRIP", "  italy   Trip "]
)
def test_load_and_exists_ignore_case(repo: SQLiteRepository, name: str) -> None:
    repo.save(make_ledger())

    assert repo.exists(name)
    assert repo.load(name).group.name == "Italy Trip"


def test_non_ascii_names_match_ignoring_case(repo: SQLiteRepository) -> None:
    repo.save(make_ledger(name="Zoë's Flat"))

    assert repo.exists("ZOË'S FLAT")
    assert repo.load("zoë's flat").group.name == "Zoë's Flat"


def test_exists_is_false_for_missing_group(repo: SQLiteRepository) -> None:
    assert not repo.exists("Nowhere")


def test_load_missing_group_raises(repo: SQLiteRepository) -> None:
    with pytest.raises(GroupNotFoundError, match="Group 'Nowhere' not found"):
        repo.load("Nowhere")


def test_list_groups_sorted_ignoring_case(repo: SQLiteRepository) -> None:
    for name in ("flat", "Berlin", "Italy Trip", "apartment"):
        repo.save(make_ledger(name=name))

    assert repo.list_groups() == ["apartment", "Berlin", "flat", "Italy Trip"]


def test_list_groups_is_empty_for_new_database(repo: SQLiteRepository) -> None:
    assert repo.list_groups() == []


# Delete


def test_delete_removes_group_and_its_data(repo: SQLiteRepository) -> None:
    repo.save(make_ledger(payments=(bob_pays_alice(),)))
    repo.save(make_ledger(name="Flat"))

    repo.delete("ITALY trip")

    assert not repo.exists("Italy Trip")
    assert repo.list_groups() == ["Flat"]
    assert repo._conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0
    assert repo._conn.execute("SELECT COUNT(*) FROM members").fetchone()[0] == 3


def test_delete_missing_group_raises(repo: SQLiteRepository) -> None:
    with pytest.raises(GroupNotFoundError):
        repo.delete("Nowhere")


# Updating


def test_updating_a_group_keeps_its_id(repo: SQLiteRepository) -> None:
    ledger = make_ledger(payments=(bob_pays_alice(),))
    repo.save(ledger)
    original_id = ledger.group.id

    updated = make_ledger(
        name="italy trip",
        members=("Alice", "Bob", "Carol", "Dave"),
        payments=(bob_pays_alice("2.00"), bob_pays_alice("3.00")),
    )
    repo.save(updated)
    loaded = repo.load("Italy Trip")

    assert updated.group.id == original_id
    assert loaded.group.id == original_id
    assert loaded.group.name == "italy trip"
    assert loaded.group.member_names == ["Alice", "Bob", "Carol", "Dave"]
    assert [payment.amount for payment in loaded.payments] == [
        Decimal("2.00"),
        Decimal("3.00"),
    ]
    assert repo.list_groups() == ["italy trip"]


def test_save_replaces_removed_members_and_payments(repo: SQLiteRepository) -> None:
    repo.save(make_ledger(payments=(bob_pays_alice(),)))

    repo.save(make_ledger(members=("Alice",)))
    loaded = repo.load("Italy Trip")

    assert loaded.group.member_names == ["Alice"]
    assert loaded.payments == []


def test_failed_save_leaves_database_unchanged(repo: SQLiteRepository) -> None:
    repo.save(make_ledger(payments=(bob_pays_alice(),)))
    broken = make_ledger(payments=(bob_pays_alice(id=1), bob_pays_alice()))
    broken.payments[1].id = 1  # two payments with the same id violate the key

    with pytest.raises(StorageError, match="Could not save group 'Italy Trip'"):
        repo.save(broken)

    loaded = repo.load("Italy Trip")
    assert [payment.id for payment in loaded.payments] == [1]
    assert loaded.group.member_names == ["Alice", "Bob", "Carol"]


# Files and paths


def test_persists_across_repository_instances(db_path: Path) -> None:
    with SQLiteRepository(db_path) as first:
        first.save(make_ledger(payments=(bob_pays_alice(),)))

    with SQLiteRepository(db_path) as second:
        loaded = second.load("Italy Trip")

    assert loaded.group.member_names == ["Alice", "Bob", "Carol"]
    assert len(loaded.payments) == 1


def test_creates_missing_parent_folders(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "folders" / "data.db"

    with SQLiteRepository(path) as repository:
        assert repository.path == path

    assert path.is_file()


def test_accepts_string_paths(tmp_path: Path) -> None:
    path = tmp_path / "string.db"

    with SQLiteRepository(str(path)) as repository:
        repository.save(make_ledger())

    assert path.is_file()


def test_in_memory_database(tmp_path: Path) -> None:
    with SQLiteRepository(":memory:") as repository:
        repository.save(make_ledger())

        assert repository.path == ":memory:"
        assert repository.list_groups() == ["Italy Trip"]

    assert list(tmp_path.iterdir()) == []


def test_uses_spliteasy_db_environment_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "from-env" / "env.db"
    monkeypatch.setenv(DB_ENV_VAR, str(path))

    with SQLiteRepository() as repository:
        repository.save(make_ledger())
        assert repository.path == path

    assert path.is_file()


def test_default_path_is_in_home_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(DB_ENV_VAR, raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert default_db_path() == tmp_path / ".spliteasy" / "spliteasy.db"
    with SQLiteRepository() as repository:
        assert repository.path == tmp_path / ".spliteasy" / "spliteasy.db"


def test_empty_environment_variable_uses_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DB_ENV_VAR, "")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert default_db_path() == tmp_path / ".spliteasy" / "spliteasy.db"


# Lifecycle and errors


def test_is_a_repository() -> None:
    with SQLiteRepository(":memory:") as repository:
        assert isinstance(repository, Repository)


def test_context_manager_closes_connection(db_path: Path) -> None:
    with SQLiteRepository(db_path) as repository:
        repository.save(make_ledger())

    with pytest.raises(StorageError, match="Could not list the groups"):
        repository.list_groups()


def test_close_twice_is_allowed(db_path: Path) -> None:
    repository = SQLiteRepository(db_path)

    repository.close()
    repository.close()


def test_database_file_can_be_deleted_after_close(db_path: Path) -> None:
    with SQLiteRepository(db_path) as repository:
        repository.save(make_ledger())

    db_path.unlink()

    assert not db_path.exists()


def test_unopenable_path_raises_storage_error(tmp_path: Path) -> None:
    with pytest.raises(StorageError, match="Could not open the database"):
        SQLiteRepository(tmp_path)


def test_newer_schema_raises_storage_error_and_closes(db_path: Path) -> None:
    with SQLiteRepository(db_path) as repository:
        repository._conn.execute("UPDATE schema_version SET version = 99")
        repository._conn.commit()

    with pytest.raises(StorageError, match="newer than the supported"):
        SQLiteRepository(db_path)

    db_path.unlink()


# Expenses


def split(expense: Expense, ledger: Ledger) -> Expense:
    return apply_split(expense, ledger.group)


def round_trip(repo: SQLiteRepository, ledger: Ledger) -> Ledger:
    repo.save(ledger)
    return repo.load(ledger.group.name)


def test_round_trip_equal_expense(repo: SQLiteRepository) -> None:
    ledger = make_ledger()
    ledger.expenses.append(
        split(
            Expense(
                description="Pizza",
                amount="25.00",
                payer="Alice",
                participants=["Alice", "Bob"],
                category="food",
                date=date(2026, 9, 3),
                note="Friday night",
            ),
            ledger,
        )
    )

    loaded = round_trip(repo, ledger)

    assert loaded.expenses == ledger.expenses
    assert loaded.expenses[0].participants == ["Alice", "Bob"]
    assert loaded.expenses[0].shares == [
        Share("Alice", Decimal("12.50")),
        Share("Bob", Decimal("12.50")),
    ]


def test_round_trip_equal_expense_among_all_members(repo: SQLiteRepository) -> None:
    ledger = make_ledger()
    ledger.expenses.append(
        split(Expense(description="Taxi", amount="100.00", payer="Carol"), ledger)
    )

    loaded = round_trip(repo, ledger)

    assert loaded.expenses == ledger.expenses
    assert loaded.expenses[0].participants == []


@pytest.mark.parametrize(
    ("method", "values"),
    [
        (SplitMethod.EXACT, {"Alice": "40.00", "Bob": "30.00", "Carol": "50.00"}),
        (SplitMethod.PERCENTAGE, {"Carol": "12.5", "Alice": "50", "Bob": "37.5"}),
        (SplitMethod.SHARES, {"Bob": "1.5", "Alice": "2", "Carol": "0"}),
    ],
)
def test_round_trip_expense_with_split_values(
    repo: SQLiteRepository, method: SplitMethod, values: dict[str, str]
) -> None:
    ledger = make_ledger()
    ledger.expenses.append(
        split(
            Expense(
                description="Dinner",
                amount="120.00",
                payer="Bob",
                split_method=method,
                split_values={member: Decimal(v) for member, v in values.items()},
            ),
            ledger,
        )
    )

    loaded = round_trip(repo, ledger)

    assert loaded.expenses == ledger.expenses
    expense = loaded.expenses[0]
    assert expense.split_method is method
    assert list(expense.split_values) == list(values)
    assert [str(v) for v in expense.split_values.values()] == list(values.values())


def test_round_trip_foreign_currency_expense(repo: SQLiteRepository) -> None:
    ledger = make_ledger()
    ledger.expenses.append(
        split(
            Expense(
                description="Fondue",
                amount="96.00",
                payer="Carol",
                currency="CHF",
                rate_to_base="1.061234",
                split_method="shares",
                split_values={"Alice": 1, "Bob": 1, "Carol": 2},
            ),
            ledger,
        )
    )

    loaded = round_trip(repo, ledger)

    assert loaded.expenses == ledger.expenses
    expense = loaded.expenses[0]
    assert expense.currency == "CHF"
    assert str(expense.rate_to_base) == "1.061234"
    assert sum(share.amount for share in expense.shares) == expense.base_amount("EUR")


def kaufland_expense() -> Expense:
    return Expense(
        description="Kaufland",
        amount="13.50",
        payer="Alice",
        split_method=SplitMethod.ITEMIZED,
        category="groceries",
        items=[
            LineItem.for_members("Olive oil", "6.00", ["Alice", "Bob"]),
            LineItem.for_members("Protein bars", "2.50", ["Alice"], quantity=2),
            LineItem(
                name="Coffee",
                price=Decimal("5.00"),
                assignees={"Bob": Decimal(70), "Alice": Decimal(30)},
                split_method=SplitMethod.PERCENTAGE,
                category="Drinks",
            ),
            LineItem.for_members(
                "Bottle deposit return",
                "-0.25",
                ["Bob"],
                quantity=4,
                category="deposit",
            ),
        ],
        adjustments=[
            Adjustment(
                kind=AdjustmentKind.DISCOUNT,
                amount=Decimal("2.00"),
                description="Loyalty coupon",
            ),
            Adjustment(
                kind=AdjustmentKind.FEE,
                amount=Decimal("0.50"),
                distribute=DistributionMode.EQUAL,
            ),
        ],
        shares=[Share("Alice", Decimal("7.40")), Share("Bob", Decimal("6.10"))],
    )


def test_round_trip_itemized_expense(repo: SQLiteRepository) -> None:
    ledger = make_ledger()
    ledger.expenses.append(kaufland_expense())

    loaded = round_trip(repo, ledger)

    assert loaded.expenses == ledger.expenses
    expense = loaded.expenses[0]
    assert expense.items_total == Decimal("13.50")
    assert expense.items_total == expense.amount
    assert [item.name for item in expense.items] == [
        "Olive oil",
        "Protein bars",
        "Coffee",
        "Bottle deposit return",
    ]
    assert expense.items[2].assignees == {"Bob": Decimal(70), "Alice": Decimal(30)}
    assert list(expense.items[2].assignees) == ["Bob", "Alice"]
    assert expense.items[2].split_method is SplitMethod.PERCENTAGE
    assert expense.items[3].price == Decimal("-0.25")
    assert expense.items[3].total == Decimal("-1.00")
    assert expense.adjustments[0].signed_amount == Decimal("-2.00")
    assert expense.adjustments[1].distribute is DistributionMode.EQUAL


def test_expenses_are_loaded_sorted_by_id(repo: SQLiteRepository) -> None:
    ledger = make_ledger()
    for expense_id, description in [(5, "Later"), (2, "Earlier"), (9, "Latest")]:
        expense = Expense(
            description=description, amount="3.00", payer="Alice", id=expense_id
        )
        ledger.expenses.append(split(expense, ledger))

    loaded = round_trip(repo, ledger)

    assert [expense.id for expense in loaded.expenses] == [2, 5, 9]


def test_save_assigns_expense_ids_and_group_ids(repo: SQLiteRepository) -> None:
    ledger = make_ledger()
    ledger.expenses.append(
        split(Expense(description="A", amount="3.00", payer="Alice", id=4), ledger)
    )
    ledger.expenses.append(
        split(Expense(description="B", amount="3.00", payer="Alice"), ledger)
    )

    repo.save(ledger)

    assert [expense.id for expense in ledger.expenses] == [4, 5]
    assert all(expense.group_id == ledger.group.id for expense in ledger.expenses)


def full_ledger() -> Ledger:
    ledger = make_ledger(payments=(bob_pays_alice(),))
    ledger.expenses.append(kaufland_expense())
    ledger.expenses.append(
        split(
            Expense(
                description="Dinner",
                amount="30.00",
                payer="Bob",
                participants=["Alice", "Bob"],
            ),
            ledger,
        )
    )
    ledger.expenses.append(
        split(
            Expense(
                description="Hotel",
                amount="90.00",
                payer="Carol",
                split_method="shares",
                split_values={"Alice": 1, "Carol": 2},
            ),
            ledger,
        )
    )
    return ledger


def row_counts(repo: SQLiteRepository) -> dict[str, int]:
    return {
        table: repo._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in TABLES
        if table != "schema_version"
    }


def test_deleting_a_group_removes_all_child_rows(repo: SQLiteRepository) -> None:
    repo.save(full_ledger())
    assert all(count > 0 for count in row_counts(repo).values())

    repo.delete("Italy Trip")

    assert all(count == 0 for count in row_counts(repo).values())


def test_deleting_one_group_keeps_other_groups(repo: SQLiteRepository) -> None:
    other = full_ledger()
    other.group.name = "Flat"
    repo.save(full_ledger())
    repo.save(other)

    repo.delete("Italy Trip")

    assert repo.load("Flat").expenses == other.expenses


def test_saving_after_removing_an_expense_removes_its_rows(
    repo: SQLiteRepository,
) -> None:
    ledger = full_ledger()
    repo.save(ledger)
    kaufland_id = ledger.expenses[0].id

    ledger.remove_expense(kaufland_id)  # type: ignore[arg-type]
    repo.save(ledger)

    loaded = repo.load("Italy Trip")
    assert [expense.description for expense in loaded.expenses] == ["Dinner", "Hotel"]
    for table in (
        "expense_shares",
        "expense_items",
        "item_assignees",
        "expense_adjustments",
    ):
        count = repo._conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE expense_id = ?", (kaufland_id,)
        ).fetchone()[0]
        assert count == 0, table
    assert row_counts(repo)["expense_items"] == 0
    assert row_counts(repo)["expense_participants"] == 2


def test_full_ledger_round_trip(repo: SQLiteRepository) -> None:
    ledger = full_ledger()

    loaded = round_trip(repo, ledger)

    assert loaded.group.member_names == ledger.group.member_names
    assert loaded.expenses == ledger.expenses
    assert loaded.payments == ledger.payments
