"""Persistence for SplitEasy ledgers.

:class:`Repository` is the abstract interface used by the rest of the code.
The SQLite schema lives in :mod:`spliteasy.storage.schema`.
"""

from spliteasy.storage.base import Repository

__all__ = ["Repository"]
