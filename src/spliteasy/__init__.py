"""SplitEasy: track shared expenses in groups and settle up with minimal payments.

SplitEasy is both a command-line tool and an importable library. It records
expenses shared among members of a group (roommates, trips, events), computes
who owes whom, and suggests the smallest set of payments needed to settle all
balances.

Example:
    >>> from spliteasy import Expense, Group, Member, apply_split
    >>> trip = Group(
    ...     name="Italy Trip",
    ...     members=[Member("Alice"), Member("Bob"), Member("Carol")],
    ... )
    >>> dinner = Expense(description="Dinner", amount="100.00", payer="Alice")
    >>> for share in apply_split(dinner, trip).shares:
    ...     print(share.member, share.amount)
    Alice 33.34
    Bob 33.33
    Carol 33.33
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
from spliteasy.splitting import (
    EqualSplit,
    ExactSplit,
    PercentageSplit,
    SharesSplit,
    SplitStrategy,
    apply_split,
    compute_shares,
    get_strategy,
    register_strategy,
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
    # Splitting
    "SplitStrategy",
    "EqualSplit",
    "SharesSplit",
    "PercentageSplit",
    "ExactSplit",
    "get_strategy",
    "register_strategy",
    "compute_shares",
    "apply_split",
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
