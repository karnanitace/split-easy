"""Exception hierarchy for SplitEasy.

All custom errors in SplitEasy inherit from SplitEasyError, so callers can
catch any package-specific error with a single except clause.
"""


class SplitEasyError(Exception):
    """Base class for all errors raised by SplitEasy."""


class MoneyError(SplitEasyError, ValueError):
    """Base class for errors in money parsing and arithmetic."""


class InvalidAmountError(MoneyError):
    """Raised when an amount cannot be parsed or is not allowed."""


class AllocationError(MoneyError):
    """Raised when an amount cannot be allocated over a set of weights."""


class CurrencyError(SplitEasyError, ValueError):
    """Raised for an unknown currency code or a missing exchange rate."""


class SplitError(SplitEasyError, ValueError):
    """Raised when an expense split is invalid."""


class ValidationError(SplitEasyError, ValueError):
    """Raised when model data is invalid, such as an empty name."""


class NotFoundError(SplitEasyError, LookupError):
    """Base class for errors raised when a requested entity does not exist.

    Attributes:
        entity: Human-readable name of the entity type, such as ``"Group"``.
        identifier: The name or id that was looked up.
    """

    def __init__(self, entity: str, identifier: object) -> None:
        """Initialises the error and builds its message.

        Args:
            entity: Human-readable name of the entity type, such as ``"Group"``.
            identifier: The name or id that was looked up.
        """
        self.entity = entity
        self.identifier = identifier
        super().__init__(f"{entity} {identifier!r} not found")


class GroupNotFoundError(NotFoundError):
    """Raised when no group matches the given name or id."""

    def __init__(self, identifier: object) -> None:
        """Initialises the error for a missing group.

        Args:
            identifier: The group name or id that was looked up.
        """
        super().__init__("Group", identifier)


class MemberNotFoundError(NotFoundError):
    """Raised when no member of a group matches the given name or id."""

    def __init__(self, identifier: object) -> None:
        """Initialises the error for a missing member.

        Args:
            identifier: The member name or id that was looked up.
        """
        super().__init__("Member", identifier)


class ExpenseNotFoundError(NotFoundError):
    """Raised when no expense matches the given id."""

    def __init__(self, identifier: object) -> None:
        """Initialises the error for a missing expense.

        Args:
            identifier: The expense id that was looked up.
        """
        super().__init__("Expense", identifier)


class DuplicateError(SplitEasyError, ValueError):
    """Raised when an entity with the same name already exists."""


class SettlementError(SplitEasyError):
    """Raised when a set of balances cannot be settled."""


class StorageError(SplitEasyError):
    """Raised when a database operation fails."""
