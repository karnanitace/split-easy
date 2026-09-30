"""SQLite schema for SplitEasy.

The schema stores one row per group and one row per member, expense and
payment, with separate tables for the lists inside an expense (participants,
split values, shares, receipt items and their assignees, adjustments).
Expense and payment ids are numbered per group, so their primary keys include
``group_id``. List order is kept in ``position`` columns, because rounding
leftovers go to earlier entries and the order must survive a round trip.
"""

import sqlite3

from spliteasy.exceptions import StorageError

SCHEMA_VERSION = 1
"""The version of the schema created by :func:`initialize_schema`."""

# All money amounts, exchange rates, weights and percentages are stored as
# TEXT (for example '12.50'), because SQLite's REAL is a binary float and
# would lose Decimal precision. Dates and timestamps are ISO 8601 TEXT.
# Names use COLLATE NOCASE so that uniqueness ignores case, as in the models.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS groups (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    currency    TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS members (
    group_id  INTEGER NOT NULL REFERENCES groups (id) ON DELETE CASCADE,
    position  INTEGER NOT NULL,
    name      TEXT NOT NULL COLLATE NOCASE,
    PRIMARY KEY (group_id, position),
    UNIQUE (group_id, name)
);

CREATE TABLE IF NOT EXISTS expenses (
    group_id      INTEGER NOT NULL REFERENCES groups (id) ON DELETE CASCADE,
    id            INTEGER NOT NULL,
    description   TEXT NOT NULL,
    amount        TEXT NOT NULL,
    currency      TEXT NOT NULL,
    rate_to_base  TEXT NOT NULL,
    payer         TEXT NOT NULL,
    split_method  TEXT NOT NULL,
    category      TEXT NOT NULL,
    date          TEXT NOT NULL,
    note          TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (group_id, id)
);

CREATE TABLE IF NOT EXISTS expense_participants (
    group_id    INTEGER NOT NULL,
    expense_id  INTEGER NOT NULL,
    position    INTEGER NOT NULL,
    member      TEXT NOT NULL,
    PRIMARY KEY (group_id, expense_id, position),
    FOREIGN KEY (group_id, expense_id)
        REFERENCES expenses (group_id, id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS expense_split_values (
    group_id    INTEGER NOT NULL,
    expense_id  INTEGER NOT NULL,
    position    INTEGER NOT NULL,
    member      TEXT NOT NULL,
    value       TEXT NOT NULL,
    PRIMARY KEY (group_id, expense_id, position),
    FOREIGN KEY (group_id, expense_id)
        REFERENCES expenses (group_id, id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS expense_shares (
    group_id    INTEGER NOT NULL,
    expense_id  INTEGER NOT NULL,
    position    INTEGER NOT NULL,
    member      TEXT NOT NULL,
    amount      TEXT NOT NULL,
    PRIMARY KEY (group_id, expense_id, position),
    FOREIGN KEY (group_id, expense_id)
        REFERENCES expenses (group_id, id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS expense_items (
    group_id      INTEGER NOT NULL,
    expense_id    INTEGER NOT NULL,
    position      INTEGER NOT NULL,
    name          TEXT NOT NULL,
    price         TEXT NOT NULL,
    quantity      INTEGER NOT NULL,
    split_method  TEXT NOT NULL,
    category      TEXT,
    PRIMARY KEY (group_id, expense_id, position),
    FOREIGN KEY (group_id, expense_id)
        REFERENCES expenses (group_id, id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS item_assignees (
    group_id       INTEGER NOT NULL,
    expense_id     INTEGER NOT NULL,
    item_position  INTEGER NOT NULL,
    position       INTEGER NOT NULL,
    member         TEXT NOT NULL,
    weight         TEXT NOT NULL,
    PRIMARY KEY (group_id, expense_id, item_position, position),
    FOREIGN KEY (group_id, expense_id, item_position)
        REFERENCES expense_items (group_id, expense_id, position)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS expense_adjustments (
    group_id     INTEGER NOT NULL,
    expense_id   INTEGER NOT NULL,
    position     INTEGER NOT NULL,
    kind         TEXT NOT NULL,
    amount       TEXT NOT NULL,
    distribute   TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (group_id, expense_id, position),
    FOREIGN KEY (group_id, expense_id)
        REFERENCES expenses (group_id, id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS payments (
    group_id     INTEGER NOT NULL REFERENCES groups (id) ON DELETE CASCADE,
    id           INTEGER NOT NULL,
    from_member  TEXT NOT NULL,
    to_member    TEXT NOT NULL,
    amount       TEXT NOT NULL,
    date         TEXT NOT NULL,
    note         TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (group_id, id)
);
"""

TABLES = (
    "schema_version",
    "groups",
    "members",
    "expenses",
    "expense_participants",
    "expense_split_values",
    "expense_shares",
    "expense_items",
    "item_assignees",
    "expense_adjustments",
    "payments",
)
"""The names of all tables created by :data:`SCHEMA_SQL`."""


def initialize_schema(conn: sqlite3.Connection) -> None:
    """Creates the schema on a connection if it does not exist yet.

    Foreign keys are enabled on the connection, because SQLite turns them off
    by default and the schema relies on ``ON DELETE CASCADE``. Running this
    on a database that already has the schema changes nothing.

    Args:
        conn: An open SQLite connection.

    Raises:
        StorageError: If the database was created by a newer version of
            SplitEasy, or a database operation fails.
    """
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        stored = _stored_version(conn)
        if stored is not None and stored > SCHEMA_VERSION:
            raise StorageError(
                f"Database schema version {stored} is newer than the supported "
                f"version {SCHEMA_VERSION}; please upgrade SplitEasy"
            )
        conn.executescript(SCHEMA_SQL)
        if stored is None:
            with conn:
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (SCHEMA_VERSION,),
                )
    except sqlite3.Error as err:
        raise StorageError(f"Could not initialise the database: {err}") from err


def _stored_version(conn: sqlite3.Connection) -> int | None:
    """Returns the schema version stored in the database, if any.

    Args:
        conn: An open SQLite connection.

    Returns:
        The stored version, or ``None`` if the database has no version yet.
    """
    table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'"
    ).fetchone()
    if table is None:
        return None
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return row[0]
