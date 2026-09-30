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

from spliteasy.balances import compute_balances, member_summary
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
    Ledger,
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

# charts.py imports matplotlib inside its functions only, so this import
# keeps package start-up fast.
from spliteasy.reports.charts import (
    plot_balances,
    plot_categories,
    plot_member_spending,
)
from spliteasy.services import GroupService
from spliteasy.settlement import apply_transfers, settle_greedy
from spliteasy.splitting import (
    EqualSplit,
    ExactSplit,
    ItemizedSplit,
    PercentageSplit,
    SharesSplit,
    SplitStrategy,
    apply_split,
    compute_shares,
    get_strategy,
    register_strategy,
    resolve_items,
)
from spliteasy.storage import Repository, SQLiteRepository

__version__ = "0.1.0"

__all__ = [
    # Application service
    "GroupService",
    # Models
    "Group",
    "Member",
    "Expense",
    "Share",
    "LineItem",
    "Adjustment",
    "Payment",
    "Transfer",
    "Ledger",
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
    "ItemizedSplit",
    "get_strategy",
    "register_strategy",
    "compute_shares",
    "apply_split",
    "resolve_items",
    # Balances and settlement
    "compute_balances",
    "member_summary",
    "settle_greedy",
    "apply_transfers",
    # Storage
    "Repository",
    "SQLiteRepository",
    # Charts
    "plot_balances",
    "plot_categories",
    "plot_member_spending",
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
