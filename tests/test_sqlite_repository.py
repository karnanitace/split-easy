from collections.abc import Iterator
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from spliteasy.exceptions import GroupNotFoundError, StorageError
from spliteasy.models import Group, Ledger, Member, Payment
from spliteasy.storage import Repository, SQLiteRepository
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
