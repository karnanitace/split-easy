"""Persistence for SplitEasy ledgers.

:class:`Repository` is the abstract interface used by the rest of the code,
and :class:`SQLiteRepository` stores ledgers in a SQLite database. The schema
lives in :mod:`spliteasy.storage.schema`.
"""

from spliteasy.storage.base import Repository
from spliteasy.storage.sqlite import SQLiteRepository

__all__ = ["Repository", "SQLiteRepository"]
