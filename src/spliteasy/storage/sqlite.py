"""SQLite implementation of the repository.

:class:`SQLiteRepository` stores every group in a single SQLite database file
using the schema from :mod:`spliteasy.storage.schema`. Decimal values are
written with ``str()`` and read back with ``Decimal()``, and dates and
timestamps with ``isoformat()`` and ``fromisoformat()``, so values survive a
round trip exactly.

Group names are matched ignoring case with Python's ``str.casefold()``, like
the models, rather than with SQLite's ``NOCASE`` collation, which only folds
ASCII letters.
"""

import os
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from spliteasy.exceptions import GroupNotFoundError, StorageError
from spliteasy.models import Expense, Group, Ledger, Member, Payment
from spliteasy.storage.base import Repository
from spliteasy.storage.schema import initialize_schema

DB_ENV_VAR = "SPLITEASY_DB"
"""Environment variable that overrides the default database path."""

MEMORY = ":memory:"
"""Path value for a temporary in-memory database."""


def default_db_path() -> Path:
    """Returns the database path used when none is given.

    Returns:
        The path from the ``SPLITEASY_DB`` environment variable if it is set
        and not empty, otherwise ``~/.spliteasy/spliteasy.db``.
    """
    configured = os.environ.get(DB_ENV_VAR)
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".spliteasy" / "spliteasy.db"


class SQLiteRepository(Repository):
    """Stores ledgers in a SQLite database file.

    One connection is kept open for the lifetime of the repository. Close it
    with :meth:`close`, or use the repository as a context manager.

    Attributes:
        path: The database file, or ``":memory:"`` for an in-memory database.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        """Opens the database, creating the file and schema if needed.

        Args:
            path: The database file. ``None`` uses :func:`default_db_path`,
                and ``":memory:"`` opens a temporary in-memory database.
                Missing parent folders are created.

        Raises:
            StorageError: If the database cannot be opened or initialised.
        """
        if path is None:
            path = default_db_path()
        self.path: Path | str = MEMORY if str(path) == MEMORY else Path(path)

        try:
            if isinstance(self.path, Path):
                self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.path)
        except (OSError, sqlite3.Error) as err:
            raise StorageError(
                f"Could not open the database at {self.path}: {err}"
            ) from err
        self._conn.row_factory = sqlite3.Row
        try:
            initialize_schema(self._conn)
        except StorageError:
            self._conn.close()
            raise

    def close(self) -> None:
        """Closes the database connection. Closing twice is allowed."""
        self._conn.close()

    def list_groups(self) -> list[str]:
        """Returns the names of all stored groups.

        Returns:
            The group names as stored, sorted alphabetically ignoring case.

        Raises:
            StorageError: If the database cannot be read.
        """
        with _storage_errors("list the groups"):
            rows = self._conn.execute("SELECT name FROM groups").fetchall()
        return sorted((row["name"] for row in rows), key=str.casefold)

    def exists(self, group_name: str) -> bool:
        """Returns whether a group with this name is stored.

        Args:
            group_name: The group name, ignoring case and extra whitespace.

        Returns:
            ``True`` if the group exists, otherwise ``False``.

        Raises:
            StorageError: If the database cannot be read.
        """
        with _storage_errors(f"look up group {group_name!r}"):
            return self._find_group(group_name) is not None

    def load(self, group_name: str) -> Ledger:
        """Loads a group with its members, expenses and payments.

        Args:
            group_name: The group name, ignoring case and extra whitespace.

        Returns:
            The group's ledger, with members and payments in their stored
            order.

        Raises:
            GroupNotFoundError: If no group with this name is stored.
            StorageError: If the database cannot be read.
        """
        with _storage_errors(f"load group {group_name!r}"):
            row = self._find_group(group_name)
            if row is None:
                raise GroupNotFoundError(group_name)
            group_id = row["id"]
            member_rows = self._conn.execute(
                "SELECT name FROM members WHERE group_id = ? ORDER BY position",
                (group_id,),
            ).fetchall()
            payment_rows = self._conn.execute(
                "SELECT * FROM payments WHERE group_id = ? ORDER BY id", (group_id,)
            ).fetchall()
            group = _row_to_group(row, member_rows)
            expenses = self._load_expenses(group_id)
        return Ledger(
            group=group,
            expenses=expenses,
            payments=[_row_to_payment(payment_row) for payment_row in payment_rows],
        )

    def save(self, ledger: Ledger) -> None:
        """Saves a whole group in one transaction, replacing any stored version.

        The group is matched by name, ignoring case. An existing group keeps
        its database id; everything stored for it before is replaced. Payments
        without an id get the next free id of the group.

        This updates the ledger in place: ``ledger.group.id`` is set to the
        database id, and every payment gets its ``id`` and ``group_id``.

        Args:
            ledger: The group and all of its data.

        Raises:
            StorageError: If the ledger cannot be written. Nothing is changed
                in the database in that case.
        """
        group = ledger.group
        for payment in ledger.payments:
            if payment.id is None:
                payment.id = ledger.next_payment_id()

        with _storage_errors(f"save group {group.name!r}"), self._conn:
            existing = self._find_group(group.name)
            if existing is None:
                cursor = self._conn.execute(
                    "INSERT INTO groups (name, currency, created_at) VALUES (?, ?, ?)",
                    (group.name, group.currency, group.created_at.isoformat()),
                )
                group_id = cursor.lastrowid
            else:
                group_id = existing["id"]
                self._conn.execute(
                    "UPDATE groups SET name = ?, currency = ?, created_at = ? "
                    "WHERE id = ?",
                    (
                        group.name,
                        group.currency,
                        group.created_at.isoformat(),
                        group_id,
                    ),
                )
                # Table names come from this fixed tuple, never from user input.
                # Deleting expenses cascades to all of their child rows.
                for table in ("members", "expenses", "payments"):
                    self._conn.execute(
                        f"DELETE FROM {table} WHERE group_id = ?", (group_id,)
                    )

            self._conn.executemany(
                "INSERT INTO members (group_id, position, name) VALUES (?, ?, ?)",
                [
                    (group_id, position, name)
                    for position, name in enumerate(group.member_names)
                ],
            )
            self._save_expenses(group_id, ledger.expenses)
            self._conn.executemany(
                "INSERT INTO payments "
                "(group_id, id, from_member, to_member, amount, date, note) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [_payment_to_row(group_id, payment) for payment in ledger.payments],
            )

        group.id = group_id
        for payment in ledger.payments:
            payment.group_id = group_id

    def delete(self, group_name: str) -> None:
        """Deletes a group and, through cascading deletes, all of its data.

        Args:
            group_name: The group name, ignoring case and extra whitespace.

        Raises:
            GroupNotFoundError: If no group with this name is stored.
            StorageError: If the database cannot be written.
        """
        with _storage_errors(f"delete group {group_name!r}"), self._conn:
            row = self._find_group(group_name)
            if row is None:
                raise GroupNotFoundError(group_name)
            self._conn.execute("DELETE FROM groups WHERE id = ?", (row["id"],))

    def _find_group(self, group_name: str) -> sqlite3.Row | None:
        """Returns the stored row of a group, matching the name ignoring case.

        Args:
            group_name: The group name, ignoring case and extra whitespace.

        Returns:
            The ``groups`` row, or ``None`` if there is no such group.
        """
        wanted = " ".join(group_name.split()).casefold()
        for row in self._conn.execute("SELECT * FROM groups"):
            if row["name"].casefold() == wanted:
                return row
        return None

    def _save_expenses(self, group_id: int, expenses: Sequence[Expense]) -> None:
        """Writes a group's expenses. Placeholder: expenses are not stored yet.

        Called by :meth:`save` inside its transaction, after the group's old
        expense rows have been deleted.

        Args:
            group_id: The database id of the group.
            expenses: The group's expenses.
        """

    def _load_expenses(self, group_id: int) -> list[Expense]:
        """Reads a group's expenses. Placeholder: always returns no expenses.

        Args:
            group_id: The database id of the group.

        Returns:
            The group's expenses; currently always an empty list.
        """
        return []


@contextmanager
def _storage_errors(action: str) -> Iterator[None]:
    """Turns SQLite errors raised in the block into :class:`StorageError`.

    Args:
        action: What was being done, used in the error message, for example
            ``"load group 'Flat'"``.

    Raises:
        StorageError: If the block raises ``sqlite3.Error``.
    """
    try:
        yield
    except sqlite3.Error as err:
        raise StorageError(f"Could not {action}: {err}") from err


def _row_to_group(row: sqlite3.Row, member_rows: Sequence[sqlite3.Row]) -> Group:
    """Builds a group from its ``groups`` row and ordered ``members`` rows.

    Args:
        row: The ``groups`` row.
        member_rows: The group's ``members`` rows, ordered by position.

    Returns:
        The group, with its database id.
    """
    return Group(
        name=row["name"],
        currency=row["currency"],
        members=[Member(member_row["name"]) for member_row in member_rows],
        id=row["id"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _payment_to_row(
    group_id: int, payment: Payment
) -> tuple[int, int | None, str, str, str, str, str]:
    """Returns the ``payments`` column values for a payment.

    Args:
        group_id: The database id of the group.
        payment: The payment, which must already have an id.

    Returns:
        The values in column order.
    """
    return (
        group_id,
        payment.id,
        payment.from_member,
        payment.to_member,
        str(payment.amount),
        payment.date.isoformat(),
        payment.note,
    )


def _row_to_payment(row: sqlite3.Row) -> Payment:
    """Builds a payment from its ``payments`` row.

    Args:
        row: The ``payments`` row.

    Returns:
        The payment, with its id and group id.
    """
    return Payment(
        from_member=row["from_member"],
        to_member=row["to_member"],
        amount=Decimal(row["amount"]),
        date=date.fromisoformat(row["date"]),
        note=row["note"],
        id=row["id"],
        group_id=row["group_id"],
    )
