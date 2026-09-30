"""Abstract storage interface for SplitEasy.

The rest of the code talks to storage only through :class:`Repository`. This
is the Repository pattern: the service layer does not know whether data lives
in SQLite, in files or in memory, and tests can swap in another
implementation.

A repository stores whole :class:`~spliteasy.models.Ledger` objects, one per
group. Groups are identified by name, ignoring case.
"""

from abc import ABC, abstractmethod
from types import TracebackType
from typing import TypeVar

from spliteasy.models import Ledger

R = TypeVar("R", bound="Repository")


class Repository(ABC):
    """Loads and saves ledgers, one per group.

    Repositories can be used as context managers, which closes them at the
    end of the ``with`` block::

        with SQLiteRepository("spliteasy.db") as repository:
            ledger = repository.load("Italy Trip")
    """

    @abstractmethod
    def list_groups(self) -> list[str]:
        """Returns the names of all stored groups.

        Returns:
            The group names as stored, sorted alphabetically ignoring case.

        Raises:
            StorageError: If the storage cannot be read.
        """

    @abstractmethod
    def exists(self, group_name: str) -> bool:
        """Returns whether a group with this name is stored.

        Args:
            group_name: The group name, ignoring case.

        Returns:
            ``True`` if the group exists, otherwise ``False``.

        Raises:
            StorageError: If the storage cannot be read.
        """

    @abstractmethod
    def load(self, group_name: str) -> Ledger:
        """Loads a group with all of its expenses and payments.

        Args:
            group_name: The group name, ignoring case.

        Returns:
            The group's ledger.

        Raises:
            GroupNotFoundError: If no group with this name is stored.
            StorageError: If the storage cannot be read.
        """

    @abstractmethod
    def save(self, ledger: Ledger) -> None:
        """Saves a whole group, replacing any stored version of it.

        The group is matched by name, ignoring case. Everything stored for it
        before is replaced by the contents of ``ledger``.

        Args:
            ledger: The group and all of its data.

        Raises:
            StorageError: If the ledger cannot be written.
        """

    @abstractmethod
    def delete(self, group_name: str) -> None:
        """Deletes a group and all of its data.

        Args:
            group_name: The group name, ignoring case.

        Raises:
            GroupNotFoundError: If no group with this name is stored.
            StorageError: If the storage cannot be written.
        """

    def close(self) -> None:  # noqa: B027
        """Releases any resources held by the repository.

        The default implementation does nothing. Subclasses that hold
        resources, such as a database connection, override it.
        """

    def __enter__(self: R) -> R:
        """Returns the repository itself for use in a ``with`` block."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Closes the repository at the end of a ``with`` block.

        Args:
            exc_type: The type of the exception that ended the block, if any.
            exc: The exception that ended the block, if any.
            traceback: The traceback of that exception, if any.
        """
        self.close()
