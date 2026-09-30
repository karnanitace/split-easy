"""SplitEasy: track shared expenses in groups and settle up with minimal payments.

SplitEasy is both a command-line tool and an importable library. It records
expenses shared among members of a group (roommates, trips, events), computes
who owes whom, and suggests the smallest set of payments needed to settle all
balances.

Example:
    >>> from spliteasy import Expense, Group, Member, allocate
    >>> trip = Group(name="Italy Trip", members=[Member("Alice"), Member("Bob")])
    >>> dinner = Expense(description="Dinner", amount="45.50", payer="Alice")
    >>> dinner.amount
    Decimal('45.50')
    >>> allocate(dinner.amount, dict.fromkeys(trip.member_names, 1))
    {'Alice': Decimal('22.75'), 'Bob': Decimal('22.75')}
"""

from spliteasy.exceptions import (
    AllocationError,
    CurrencyError,
    DuplicateError,
    ExpenseNotFoundError,
    GroupNotFoundError,
    InvalidAmountError,
    MemberNotFoundError,
    MoneyError,
    NotFoundError,
    SettlementError,
    SplitEasyError,
    SplitError,
    StorageError,
    ValidationError,
)
from spliteasy.models import (
    Adjustment,
    AdjustmentKind,
    DistributionMode,
    Expense,
    Group,
    LineItem,
    Member,
    Payment,
    Share,
    SplitMethod,
    Transfer,
)
from spliteasy.money import (
    allocate,
    format_money,
    parse_decimal,
    split_equally,
    to_money,
)

__version__ = "0.1.0"

__all__ = [
    # Models
    "Group",
    "Member",
    "Expense",
    "Share",
    "LineItem",
    "Adjustment",
    "Payment",
    "Transfer",
    "SplitMethod",
    "AdjustmentKind",
    "DistributionMode",
    # Money helpers
    "to_money",
    "parse_decimal",
    "allocate",
    "split_equally",
    "format_money",
    # Exceptions
    "SplitEasyError",
    "ValidationError",
    "MoneyError",
    "InvalidAmountError",
    "AllocationError",
    "CurrencyError",
    "SplitError",
    "NotFoundError",
    "GroupNotFoundError",
    "MemberNotFoundError",
    "ExpenseNotFoundError",
    "DuplicateError",
    "SettlementError",
    "StorageError",
]
