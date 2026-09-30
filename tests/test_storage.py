import sqlite3
from collections.abc import Iterator

import pytest

from spliteasy.exceptions import StorageError
from spliteasy.models import Group, Ledger
from spliteasy.storage import Repository
from spliteasy.storage.schema import SCHEMA_VERSION, TABLES, initialize_schema


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(":memory:")
    yield connection
    connection.close()


def table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {name for (name,) in rows}


def versions(conn: sqlite3.Connection) -> list[int]:
    return [
        version for (version,) in conn.execute("SELECT version FROM schema_version")
    ]


# initialize_schema


def test_initialize_schema_creates_all_tables(conn: sqlite3.Connection) -> None:
    initialize_schema(conn)

    assert table_names(conn) == set(TABLES)


def test_initialize_schema_stores_version_1(conn: sqlite3.Connection) -> None:
    initialize_schema(conn)

    assert SCHEMA_VERSION == 1
    assert versions(conn) == [1]


def test_initialize_schema_is_idempotent(conn: sqlite3.Connection) -> None:
    initialize_schema(conn)
    conn.execute(
        "INSERT INTO groups (name, currency, created_at) VALUES ('Flat', 'EUR', 'x')"
    )
    conn.commit()

    initialize_schema(conn)

    assert table_names(conn) == set(TABLES)
    assert versions(conn) == [1]
    assert conn.execute("SELECT COUNT(*) FROM groups").fetchone() == (1,)


def test_initialize_schema_fills_empty_version_table(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")

    initialize_schema(conn)

    assert versions(conn) == [1]


def test_initialize_schema_rejects_newer_version(conn: sqlite3.Connection) -> None:
    initialize_schema(conn)
    conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION + 1,))
    conn.commit()

    with pytest.raises(StorageError, match="version 2 is newer than the supported"):
        initialize_schema(conn)


def test_initialize_schema_does_not_touch_newer_database(
    conn: sqlite3.Connection,
) -> None:
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    conn.execute("INSERT INTO schema_version (version) VALUES (99)")
    conn.commit()

    with pytest.raises(StorageError):
        initialize_schema(conn)

    assert table_names(conn) == {"schema_version"}


def test_initialize_schema_enables_foreign_keys(conn: sqlite3.Connection) -> None:
    initialize_schema(conn)

    assert conn.execute("PRAGMA foreign_keys").fetchone() == (1,)


def test_initialize_schema_wraps_sqlite_errors(conn: sqlite3.Connection) -> None:
    conn.close()

    with pytest.raises(StorageError, match="Could not initialise the database"):
        initialize_schema(conn)


# Schema behaviour


@pytest.fixture
def db(conn: sqlite3.Connection) -> sqlite3.Connection:
    initialize_schema(conn)
    conn.execute(
        "INSERT INTO groups (id, name, currency, created_at) "
        "VALUES (1, 'Flat', 'EUR', '2026-09-30T12:00:00+00:00')"
    )
    conn.execute("INSERT INTO members VALUES (1, 0, 'Alice'), (1, 1, 'Bob')")
    conn.execute(
        "INSERT INTO expenses VALUES "
        "(1, 1, 'Groceries', '20.00', 'EUR', '1', 'Alice', 'itemized', "
        "'groceries', '2026-09-30', '')"
    )
    conn.execute(
        "INSERT INTO expense_items VALUES (1, 1, 0, 'Oil', '6.00', 1, 'equal', NULL)"
    )
    conn.execute(
        "INSERT INTO item_assignees VALUES (1, 1, 0, 0, 'Alice', '1'), "
        "(1, 1, 0, 1, 'Bob', '1')"
    )
    conn.execute("INSERT INTO expense_shares VALUES (1, 1, 0, 'Alice', '12.00')")
    conn.execute(
        "INSERT INTO payments VALUES (1, 1, 'Bob', 'Alice', '8.00', '2026-09-30', '')"
    )
    conn.commit()
    return conn


def count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_deleting_a_group_cascades_to_all_child_tables(db: sqlite3.Connection) -> None:
    db.execute("DELETE FROM groups WHERE id = 1")

    for table in TABLES:
        if table != "schema_version":
            assert count(db, table) == 0, table


def test_deleting_an_expense_cascades_to_its_items_and_assignees(
    db: sqlite3.Connection,
) -> None:
    db.execute("DELETE FROM expenses WHERE group_id = 1 AND id = 1")

    assert count(db, "expense_items") == 0
    assert count(db, "item_assignees") == 0
    assert count(db, "expense_shares") == 0
    assert count(db, "payments") == 1


def test_group_names_are_unique_ignoring_case(db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO groups (name, currency, created_at) "
            "VALUES ('FLAT', 'EUR', 'x')"
        )


def test_member_names_are_unique_per_group_ignoring_case(
    db: sqlite3.Connection,
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO members VALUES (1, 2, 'alice')")


def test_child_rows_need_an_existing_parent(db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO expense_shares VALUES (1, 99, 0, 'Alice', '1.00')")


def test_money_is_stored_as_text(db: sqlite3.Connection) -> None:
    row = db.execute(
        "SELECT typeof(amount), typeof(rate_to_base) FROM expenses"
    ).fetchone()

    assert row == ("text", "text")


# Repository


class InMemoryRepository(Repository):
    """A minimal repository for testing the abstract base class."""

    def __init__(self) -> None:
        self.ledgers: dict[str, Ledger] = {}
        self.closed = False

    def list_groups(self) -> list[str]:
        return sorted(self.ledgers)

    def exists(self, group_name: str) -> bool:
        return group_name in self.ledgers

    def load(self, group_name: str) -> Ledger:
        return self.ledgers[group_name]

    def save(self, ledger: Ledger) -> None:
        self.ledgers[ledger.group.name] = ledger

    def delete(self, group_name: str) -> None:
        del self.ledgers[group_name]

    def close(self) -> None:
        self.closed = True


def test_repository_is_abstract() -> None:
    with pytest.raises(TypeError):
        Repository()  # type: ignore[abstract]


def test_repository_works_as_context_manager() -> None:
    with InMemoryRepository() as repository:
        repository.save(Ledger(group=Group(name="Flat")))
        assert repository.exists("Flat")

    assert repository.closed


def test_repository_closes_when_block_raises() -> None:
    repository = InMemoryRepository()

    with pytest.raises(RuntimeError), repository:
        raise RuntimeError("boom")

    assert repository.closed


def test_default_close_does_nothing() -> None:
    class MinimalRepository(InMemoryRepository):
        close = Repository.close

    with MinimalRepository() as repository:
        pass

    assert repository.closed is False
