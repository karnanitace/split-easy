# SplitEasy Architecture

This document describes the design of SplitEasy as it is built: what it is for,
how the code is organised, how data is modelled and stored, and the reasoning
behind the main design decisions. It is written for readers who are new to the
code base, such as a course grader. Ideas that are not implemented are listed
separately in [§9](#9-future-work).

## Contents

1. [Purpose and use cases](#1-purpose-and-use-cases)
2. [Layered architecture](#2-layered-architecture)
3. [Modules](#3-modules)
4. [Data model](#4-data-model)
5. [Storage schema](#5-storage-schema)
6. [Key design decisions](#6-key-design-decisions)
7. [Settlement algorithms](#7-settlement-algorithms)
8. [Development conventions and testing](#8-development-conventions-and-testing)
9. [Future work](#9-future-work)

---

## 1. Purpose and use cases

SplitEasy tracks expenses that are shared within a group of people and works
out how to settle up with few payments. It can be used in two ways:

- as a **command-line tool** (`uv run -m spliteasy ...` or `spliteasy ...`),
- as an **importable Python library** (`import spliteasy`).

| Use case | Example | Features involved |
| --- | --- | --- |
| Flatmates | Rent is split by room size; internet and groceries equally. | Exact and equal splits, running balances, recorded payments |
| Trips | Four friends take turns paying for hotels, fuel and dinners. | All split methods, settlement with few transfers |
| Itemised grocery receipts | Some items are shared, some are personal, a coupon applies and bottles are returned. | Itemised split with adjustments and negative-price items |
| Multiple currencies | A trip through Switzerland and Italy, settled in EUR. | Per-expense currency with a frozen exchange rate |

Beyond recording and settling, SplitEasy draws PNG charts of balances,
spending per category, and paid versus owed per member.

---

## 2. Layered architecture

The code is organised into five layers. **Each layer depends only on the
layers below it**, never on the layers above. This keeps the rules of
splitting and settling independent of how data is stored or shown, and makes
every layer testable on its own.

```
 ┌─────────────────────────────────────────────────────────────────┐
 │ 5  Interface       cli/  app.py, group_cmds.py, expense_cmds.py │
 │                          parsing.py  (typer + rich; the only    │
 │                          code that prints or reads input)       │
 ├─────────────────────────────────────────────────────────────────┤
 │ 4  Application     services.py  (GroupService facade)           │
 │                    demo.py, __init__.py  (public API, __all__)  │
 ├────────────────────────────────┬────────────────────────────────┤
 │ 3  Persistence                 │ 3  Reporting                   │
 │    storage/  base.py,          │    reports/  charts.py         │
 │    schema.py, sqlite.py        │    (matplotlib, lazy import)   │
 ├────────────────────────────────┴────────────────────────────────┤
 │ 2  Domain          splitting.py  balances.py  settlement.py     │
 ├─────────────────────────────────────────────────────────────────┤
 │ 1  Foundation      exceptions.py  models.py  money.py           │
 └─────────────────────────────────────────────────────────────────┘
                 dependencies point downwards only
```

**1. Foundation.** `exceptions.py` defines the exception hierarchy that every
layer raises from. `money.py` holds the `Decimal` helpers that all money goes
through: parsing, rounding to a currency's minor unit, largest-remainder
allocation and formatting. It also validates currency codes. `models.py`
defines the dataclasses that the other layers pass around. This layer uses
only the standard library.

**2. Domain.** The rules of the problem, as pure functions and classes with
no I/O. `splitting.py` turns an expense into per-member shares, with one
strategy class per split method. `balances.py` combines expenses and payments
into a net balance per member. `settlement.py` turns balances into suggested
transfers.

**3. Persistence and reporting.** Two packages side by side that do not
depend on each other. `storage/` defines the abstract `Repository` and a
`SQLiteRepository` that maps whole ledgers to database tables. `reports/`
draws charts from domain data and writes them to a path given by the caller.

**4. Application.** `GroupService` is a facade with one method per use case,
such as "add an expense" or "suggest a settlement". It loads a group's ledger
from the repository, applies the change with the domain code, and saves the
ledger again. The CLI and library users both go through it, so every rule is
implemented once. `demo.py` builds the demo groups through the service, and
the top-level `__init__.py` re-exports the public API through `__all__`.

**5. Interface.** `cli/` is a thin Typer layer. Each command parses its
arguments, calls the service (or a chart function), and renders the result
with rich. It contains no business rules and is the only code that prints.

The foundation and domain layers use only the standard library. Third-party
packages belong to exactly one layer: typer and rich to `cli/`, and
matplotlib to `reports/`.

---

## 3. Modules

```
src/spliteasy/
├── __init__.py         public API (__all__) and __version__
├── __main__.py         `python -m spliteasy` entry point
├── exceptions.py       exception hierarchy
├── money.py            Decimal helpers, currencies, largest remainder
├── models.py           dataclasses: Group, Member, Expense, ..., Ledger
├── splitting.py        split strategies, compute_shares, apply_split
├── balances.py         compute_balances, member_summary
├── settlement.py       settle_greedy, apply_transfers
├── services.py         GroupService facade
├── demo.py             demo groups
├── storage/
│   ├── base.py         abstract Repository
│   ├── schema.py       SQL schema and initialize_schema
│   └── sqlite.py       SQLiteRepository
├── reports/
│   └── charts.py       plot_balances, plot_categories, plot_member_spending
└── cli/
    ├── app.py          root app, --db, error handling, demo and chart commands
    ├── group_cmds.py   group and member commands
    ├── expense_cmds.py expense, balance, settle and pay commands
    └── parsing.py      parse_values and parse_item for CLI input
```

| Module | Layer | Responsibility |
| --- | --- | --- |
| `exceptions.py` | 1 | `SplitEasyError` and specific errors for validation, money, currencies, splits, missing and duplicate entities, settlement and storage. |
| `money.py` | 1 | `parse_decimal`, `to_money`, `minor_unit`, `normalize_currency`, `distribute_remainder`, `allocate`, `split_equally`, `format_money`. |
| `models.py` | 1 | Value objects (`Member`, `Share`, `LineItem`, `Adjustment`, `Transfer`), entities (`Group`, `Expense`, `Payment`), the `Ledger` aggregate, the enums and `normalize_name`. |
| `splitting.py` | 2 | `SplitStrategy` and `EqualSplit`, `ExactSplit`, `PercentageSplit`, `SharesSplit`, `ItemizedSplit`; the strategy registry; `compute_shares`, `apply_split`, `resolve_items`. |
| `balances.py` | 2 | `compute_balances` and `member_summary` (paid, owed, sent, received, balance), including the zero-sum check. |
| `settlement.py` | 2 | `settle_greedy` (two-heap greedy) and `apply_transfers`. |
| `storage/` | 3 | `Repository` interface; SQLite schema with versioning; `SQLiteRepository` that loads and saves whole ledgers. |
| `reports/` | 3 | Three PNG charts, with matplotlib imported inside the functions. |
| `services.py` | 4 | `GroupService`: groups, members, expenses, balances, settlement and payments. |
| `demo.py` | 4 | `create_demo_data`: the "Flat" and "Italy Trip" groups. |
| `__init__.py` | 4 | Package docstring, `__version__` and the public API. |
| `cli/` | 5 | Typer commands, rich tables and CLI input parsing. |

---

## 4. Data model

All models are dataclasses in `models.py`. Every model validates and
normalises its own data in `__post_init__`, so an invalid object cannot be
created: names are stripped and have their whitespace collapsed, amounts are
parsed with `parse_decimal` or `to_money`, enum fields also accept their string
values, and rule violations raise `ValidationError`. All money fields are
`Decimal`.

```
Ledger (one group and all of its data: the unit of loading and saving)
 │
 ├── Group ──< Member                     (unique by name, ignoring case)
 │
 ├──< Expense ── payer (name)
 │       ├── participants                 (names, EQUAL splits)
 │       ├── split_values                 (name → value, EXACT / PERCENTAGE / SHARES)
 │       ├──< LineItem ── assignees       (name → weight, ITEMIZED splits)
 │       ├──< Adjustment                  (ITEMIZED splits)
 │       └──< Share                       (name → amount, the computed result)
 │
 └──< Payment  (from_member ──► to_member)

Transfer: computed settlement suggestion, never stored
```

### Value objects and entities

| Kind | Classes | Properties |
| --- | --- | --- |
| **Frozen value objects** | `Member`, `Share`, `LineItem`, `Adjustment`, `Transfer` | `@dataclass(frozen=True, slots=True)`. Defined only by their values, cannot be changed after creation, compared by value. |
| **Mutable entities** | `Group`, `Expense`, `Payment`, `Ledger` | `@dataclass(slots=True, kw_only=True)`. Have an identity (`id`, `None` until saved) and change over time, for example when the service fills in an expense's shares. |

`LineItem` is frozen but not hashable, because its `assignees` field is a
`dict`; callers must not modify that dict. Entities validate their fields when
they are created; code that changes an entity later (mainly the service) is
responsible for keeping it consistent.

### Members are referenced by name

Inside a group, a member is referred to by **name**, not by a database id:
as the payer, in participants, split values, item assignees, shares and
payments.

- **Names are what users type.** CLI arguments say "Alice", so nothing has to
  be translated to ids.
- **Models work without a database.** An expense can be built, split and
  tested before anything is saved.
- **Names are unambiguous keys.** They are normalised (`" Alice  Smith "` →
  `"Alice Smith"`) and unique within a group **ignoring case**. `Member`
  implements `__eq__` and `__hash__` on `name.casefold()`, so `Member("Alice")`
  and `Member("alice")` are the same person and one person can never end up
  with two balances.
- **The stored spelling is kept for display.** `Group.resolve_name("alice")`
  returns `"Alice"`, and the service stores every name in its stored spelling.

The trade-off is that renaming a member would have to update every place the
name is used; SplitEasy therefore has no rename command yet.

### Classes

*Normalised name* means: whitespace stripped and collapsed, 1–50 characters
(100 for expense descriptions).

**`Group`** (entity)

| Field | Type | Default | Rules |
| --- | --- | --- | --- |
| `name` | `str` | required | Normalised name. |
| `currency` | `str` | `"EUR"` | ISO 4217 code. All balances in the group are in this currency. |
| `members` | `list[Member]` | `[]` | No duplicates, ignoring case. |
| `id` | `int \| None` | `None` | Set by the repository. |
| `created_at` | `datetime` | now, UTC | Must be timezone-aware. |

Methods: `member_names`, `has_member`, `get_member`, `add_member`,
`remove_member`, `resolve_name`. Lookups ignore case and extra whitespace.
`remove_member` does not check balances; that rule needs the group's
expenses and is enforced by the service.

**`Member`** (value object): `name` (normalised; equality and hashing use
`name.casefold()`) and `id` (ignored in comparisons).

**`Expense`** (entity)

| Field | Type | Default | Rules |
| --- | --- | --- | --- |
| `description` | `str` | required | Normalised, at most 100 characters. |
| `amount` | `Decimal` | required | In `currency`, rounded to its minor unit, greater than zero. |
| `payer` | `str` | required | Member name. |
| `currency` | `str` | `"EUR"` | ISO 4217 code of `amount`. |
| `split_method` | `SplitMethod` | `EQUAL` | See the consistency rules below. |
| `participants` | `list[str]` | `[]` | EQUAL only. Empty means all group members. |
| `split_values` | `dict[str, Decimal]` | `{}` | EXACT, PERCENTAGE and SHARES: amount, percentage or weight per member, each ≥ 0. |
| `items` | `list[LineItem]` | `[]` | ITEMIZED only. |
| `adjustments` | `list[Adjustment]` | `[]` | ITEMIZED only. |
| `category` | `str` | `"other"` | Stripped, lower case, not empty. Free text. |
| `date` | `date` | today | A plain date, not a datetime. |
| `rate_to_base` | `Decimal` | `1` | Rate from `currency` to the group currency, fixed at entry. Greater than zero. |
| `shares` | `list[Share]` | `[]` | The computed split, filled in by `apply_split`. No duplicate members. |
| `note` | `str` | `""` | Stripped. |
| `id`, `group_id` | `int \| None` | `None` | Set when saved. Expense ids are numbered per group. |

Consistency rules: ITEMIZED needs at least one item; every other method must
have no items and no adjustments. EXACT, PERCENTAGE and SHARES need
`split_values`; EQUAL must not have them. Derived values:
`base_amount(currency)` (amount × rate, rounded to that currency),
`items_total` (item totals plus signed adjustments), `involved_members` and
`share_of(member)`.

**`Share`** (value object): `member` and `amount` (≥ 0, in the group
currency).

**`LineItem`** (value object)

| Field | Type | Default | Rules |
| --- | --- | --- | --- |
| `name` | `str` | required | Normalised name. |
| `price` | `Decimal` | required | Unit price. Not zero; negative for refunds such as a returned bottle deposit. |
| `quantity` | `int` | `1` | At least 1. |
| `assignees` | `dict[str, Decimal]` | required | Member name → weight. Not empty, weights ≥ 0, at least one > 0, no duplicate names. |
| `split_method` | `SplitMethod` | `EQUAL` | EQUAL, EXACT, PERCENTAGE or SHARES (not ITEMIZED). |
| `category` | `str \| None` | `None` | Stripped and in lower case. |

`total` is `price × quantity`. `LineItem.for_members(name, price, members)`
builds the common "shared equally by these people" case.

**`Adjustment`** (value object): `kind` (DISCOUNT, FEE or DEPOSIT), `amount`
(> 0; the kind decides the sign), `distribute` (PROPORTIONAL or EQUAL) and
`description`. `signed_amount` is negative for a discount and positive for a
fee or deposit.

**`Payment`** (entity) and **`Transfer`** (value object)

| Class | Fields | Rules |
| --- | --- | --- |
| `Payment` | `from_member`, `to_member`, `amount`, `date` (today), `note` (`""`), `id`, `group_id` | Two different members, ignoring case. `amount` is in the group currency and greater than zero. |
| `Transfer` | `debtor`, `creditor`, `amount` | Two different members, ignoring case. `amount` greater than zero. `str()` gives `"Bob -> Alice: 8.00"`; `to_payment()` turns it into a `Payment`. |

**`Ledger`** (entity): `group`, `expenses` and `payments`. It checks that ids
are unique, hands out the next expense and payment ids (largest id + 1,
starting at 1), and finds or removes expenses by id.

### Payment vs Transfer

The two classes look alike but mean different things:

- A **`Payment`** records money that was **actually sent**. The user enters
  it after paying. It is stored, and it changes the balances of both members.
- A **`Transfer`** is a payment **suggested** by the settlement algorithm. It
  is computed from the current balances, never stored, and changes whenever
  the balances change.

Keeping them apart means a suggestion can never be mistaken for a settled
debt.

### Enums

All enums are `class X(str, Enum)`, so their members compare equal to plain
strings and are easy to store (`StrEnum` would need Python 3.11).

| Enum | Values |
| --- | --- |
| `SplitMethod` | `equal`, `exact`, `percentage`, `shares`, `itemized` |
| `AdjustmentKind` | `discount`, `fee`, `deposit` |
| `DistributionMode` | `proportional`, `equal` |

### Invariants and where they are enforced

| Invariant | Enforced in |
| --- | --- |
| Member names are unique within a group and within each expense field, ignoring case. | Models (`__post_init__`) |
| Positive amounts (expenses, adjustments, payments, transfers, rates) are greater than zero. | Models |
| The fields of an expense match its split method. | `Expense.__post_init__` |
| Every name used in an expense or payment belongs to the group. | `compute_shares`, `member_summary`, `GroupService` |
| Item prices plus adjustments equal the amount of an itemised expense. | `compute_shares` |
| The shares of an expense sum to exactly its converted amount. | `compute_shares` (by construction) |
| The balances of a group sum to exactly zero. | `member_summary` (checked; raises `SettlementError`) |

A member's **net balance** is:

```
balance = (expenses paid) − (shares owed) + (payments sent) − (payments received)
```

A positive balance means the member is owed money, a negative balance means
they owe money.

---

## 5. Storage schema

`SQLiteRepository` uses Python's built-in `sqlite3` module, so no database
server is needed. The default file is `~/.spliteasy/spliteasy.db`
(`C:\Users\<name>\.spliteasy\spliteasy.db` on Windows). It can be changed with
the `--db` option, the `SPLITEASY_DB` environment variable, or the
`SQLiteRepository(path)` argument, and `":memory:"` gives a temporary
database. One connection is kept open for the repository's lifetime.

Money, exchange rates, weights and percentages are stored as `TEXT` (for
example `'12.50'`), written with `str()` and read with `Decimal()`, because
SQLite's `REAL` is a binary float. Dates and timestamps are ISO 8601 text.
Enums are stored by value. Expense and payment ids are numbered **per group**,
so their primary keys include `group_id`. List order is kept in `position`
columns, because rounding leftovers go to earlier entries and the order must
survive a round trip.

| Table | Columns | Keys and constraints |
| --- | --- | --- |
| `schema_version` | `version` | One row with the schema version (currently 1). |
| `groups` | `id`, `name`, `currency`, `created_at` | PK `id`. `name` unique, `COLLATE NOCASE`. |
| `members` | `group_id`, `position`, `name` | PK `(group_id, position)`. `(group_id, name)` unique, `COLLATE NOCASE`. |
| `expenses` | `group_id`, `id`, `description`, `amount`, `currency`, `rate_to_base`, `payer`, `split_method`, `category`, `date`, `note` | PK `(group_id, id)`. |
| `expense_participants` | `group_id`, `expense_id`, `position`, `member` | PK `(group_id, expense_id, position)`. |
| `expense_split_values` | `group_id`, `expense_id`, `position`, `member`, `value` | PK `(group_id, expense_id, position)`. |
| `expense_shares` | `group_id`, `expense_id`, `position`, `member`, `amount` | PK `(group_id, expense_id, position)`. |
| `expense_items` | `group_id`, `expense_id`, `position`, `name`, `price`, `quantity`, `split_method`, `category` | PK `(group_id, expense_id, position)`. |
| `item_assignees` | `group_id`, `expense_id`, `item_position`, `position`, `member`, `weight` | PK `(group_id, expense_id, item_position, position)`; FK to `expense_items`. |
| `expense_adjustments` | `group_id`, `expense_id`, `position`, `kind`, `amount`, `distribute`, `description` | PK `(group_id, expense_id, position)`. |
| `payments` | `group_id`, `id`, `from_member`, `to_member`, `amount`, `date`, `note` | PK `(group_id, id)`. |

Every child table references its parent with a foreign key and
`ON DELETE CASCADE`: deleting a group removes everything that belongs to it,
and deleting an expense removes its participants, split values, shares,
items, assignees and adjustments. Foreign keys are switched on with
`PRAGMA foreign_keys = ON`, because SQLite leaves them off by default.

**Saving and loading.** The repository reads and writes whole ledgers. `save`
runs in a single transaction: it inserts the group, or updates it (keeping
its id) if a group with the same name exists, deletes the group's old member,
expense and payment rows, and inserts the current ones. If anything fails,
the transaction is rolled back and the database is unchanged. `load` reads
each child table with one query for the whole group and groups the rows by
expense in Python.

**Name matching.** Group names are matched with Python's `str.casefold()`,
the same rule the models use, rather than with SQLite's `NOCASE`, which only
folds ASCII letters. The `NOCASE` constraints are an extra safety net for
data written by other tools.

**Versioning.** `initialize_schema` reads the stored version **before** it
changes anything. A database written by a newer SplitEasy is rejected with
`StorageError` and left untouched. All SQLite errors are wrapped in
`StorageError` with a message that says what was being done.

---

## 6. Key design decisions

### Decimal for money

Binary floats cannot represent most decimal fractions exactly
(`0.1 + 0.2 == 0.30000000000000004`), so cents would appear or disappear.
Every amount is therefore a `decimal.Decimal`:

- All input goes through `parse_decimal`, which accepts `Decimal`, `int`,
  strings with a decimal point or a decimal comma (`"12,50"`, but not both
  separators at once) and, for convenience, `float` values converted through
  `str()` so that `0.1` becomes `Decimal("0.1")`. It rejects booleans, NaN,
  infinity and anything it cannot parse.
- `to_money` rounds half up (`ROUND_HALF_UP`) to the currency's minor unit:
  0.01 for most currencies, 1 for JPY and KRW, and 0.01 for unknown but
  well-formed codes.
- Amounts are converted to `float` in exactly one place: when they are handed
  to matplotlib for drawing. Chart labels are still formatted from the
  original `Decimal`.

### Largest-remainder rounding

Splitting 100.00 three ways gives 33.333… each; rounding each share to 33.33
loses a cent. `distribute_remainder` uses the **largest remainder method**
(Hamilton's method):

1. Round every exact share down to the minor unit.
2. Hand out the leftover minor units one at a time to the shares with the
   largest fractional remainders. Ties go to the entry that comes first, so
   the result is deterministic.

```
100.00 split equally among 3  →  33.34, 33.33, 33.33   (sum = 100.00)
10.00  split equally among 7  →  1.43 ×6, 1.42 ×1      (sum = 10.00)
```

Every split goes through this function, so shares always add up to the exact
total and each share is less than one minor unit from its exact value.
Hypothesis property tests check both claims for random totals, weights,
currencies and exchange rates.

### Strategy pattern for splits

Each split method is a subclass of `SplitStrategy`:

```python
class SplitStrategy(ABC):
    method: ClassVar[SplitMethod]

    @abstractmethod
    def raw_split(
        self, total: Decimal, values: Mapping[str, Decimal]
    ) -> dict[str, Decimal]:
        """Returns unrounded amounts per member that sum to ``total``."""

    def split(
        self,
        total: Decimal | int | str,
        values: Mapping[str, Decimal],
        currency: str = "EUR",
    ) -> dict[str, Decimal]:
        """to_money(total), then raw_split, then distribute_remainder."""
```

| Method | Class | `values` means | Validation (raises `SplitError`) | Example |
| --- | --- | --- | --- | --- |
| `equal` | `EqualSplit` | Inclusion flag: > 0 includes a member, 0 excludes them. | Empty, a negative flag, or nobody included. | 100.00 for 3 → 33.34 / 33.33 / 33.33 |
| `shares` | `SharesSplit` | Weight, for example nights stayed; fractions allowed. | Empty, a negative weight, or all weights zero. | 300.00, 2 and 1 nights → 200.00 / 100.00 |
| `percentage` | `PercentageSplit` | Percentage. | Empty, a negative percentage, or a sum that is not exactly 100 (no tolerance). | 60 % / 40 % of 50.00 → 30.00 / 20.00 |
| `exact` | `ExactSplit` | Exact amount in the expense currency. | Empty, wrong sign, more decimals than the currency allows, or a sum that differs from the total (the message says how much is missing or exceeding). | 40 / 30 / 50 of 120.00 |
| `itemized` | `ItemizedSplit` | Not used; works on line items and adjustments (see below). | No items, an invalid item (named in the message), a total mismatch, or an adjustment that cannot be spread. | Kaufland receipt |

One instance of each strategy is kept in a registry (`register_strategy`,
`get_strategy`). The rest of the code only uses the interface and the
registry, so adding a split method means adding one class and registering it
(the open/closed principle).

**Raw vs rounded.** `raw_split` returns *unrounded* amounts and `split`
rounds them once. Every `raw_split` also accepts a negative total, for refund
items.

**Itemised receipts** compose the other strategies. `ItemizedSplit` splits
every line item with the registered strategy for that item's split method,
so one receipt can mix equal, exact, percentage and shares items, and adds up
the unrounded parts per member. Receipt-level adjustments are then spread:
PROPORTIONAL in proportion to each member's item subtotal (whoever bought
more gets more of a coupon), EQUAL in equal parts among members who have any
item. `raw_breakdown` exposes the rows so the CLI can print a table of items ×
members. Because the parts are summed before rounding, a long receipt never
collects a cent of error per item.

### Currency conversion: split in the expense currency, round once

`compute_shares(expense, group)` turns an expense into shares in the group
currency:

1. Check that the group has members and that every name used in the expense
   belongs to it; resolve names to their stored spelling.
2. Compute the raw amounts in the **expense currency**, so that exact amounts
   and receipt prices keep the meaning the user entered. For an itemised
   expense, first check that `items_total == amount` exactly.
3. Multiply every raw amount by the frozen `rate_to_base`.
4. Round **once** with `distribute_remainder` against
   `expense.base_amount(group.currency)`.

Rounding once, after conversion, avoids rounding in both currencies, which
could leave the shares a cent away from the converted total. The step cannot
fail: the converted total is the half-up rounding of the exact sum of the
converted raw amounts, so it is always within the leftover that largest
remainder can hand out. A share that would be negative (a member whose only
item is a refund) is rejected with a clear message.

### Frozen exchange rates

Each expense stores its original `amount` and `currency` and the
`rate_to_base` **at the time it is entered**. Balances always use
`base_amount`, so they do not change when rates move, results are
reproducible, and the stored rate can match what the payer's bank charged.
The rate is typed in by the user: for a foreign currency it is required
(`CurrencyError: An exchange rate is required for CHF -> EUR`), and for the
group's own currency only a rate of 1 is accepted. SplitEasy needs no network
access.

### Repository pattern for storage

`GroupService` talks to the abstract `Repository` (`list_groups`, `exists`,
`load`, `save`, `delete`, `close`) and never uses SQL. `SQLiteRepository` is
the implementation. Tests use temporary files or `":memory:"`, the domain
code does not know how data is stored, and another backend could be added
without touching the layers above. Repositories and the service are context
managers, so connections are always closed. This matters on Windows, which
cannot delete a database file that is still open.

### Service facade

`GroupService` is the single entry point for every use case. Each changing
method loads the group's ledger, applies the change with the domain code,
and saves the ledger; if anything fails before the save, nothing is written.
The service also enforces the rules that need a whole group:

- a member can only be removed while their balance is zero and they appear in
  no expense or payment;
- group names are unique ignoring case;
- payment amounts are rounded to the group currency.

```python
from spliteasy import GroupService, SQLiteRepository

with GroupService(SQLiteRepository("trip.db")) as service:
    service.create_group("Italy Trip", members=["John", "Steve"])
    service.add_expense("Italy Trip", "Dinner", "90.00", "John")
    transfers = service.suggest_settlement("Italy Trip")
```

### Exception hierarchy

All errors raised on purpose come from `exceptions.py` and derive from one
base class, `SplitEasyError`:

```
SplitEasyError
├── ValidationError            (+ ValueError)
├── MoneyError                 (+ ValueError)
│   ├── InvalidAmountError
│   └── AllocationError
├── CurrencyError              (+ ValueError)
├── SplitError                 (+ ValueError)
├── NotFoundError              (+ LookupError)
│   ├── GroupNotFoundError
│   ├── MemberNotFoundError
│   └── ExpenseNotFoundError
├── DuplicateError             (+ ValueError)
├── SettlementError
└── StorageError
```

| Exception | Raised when |
| --- | --- |
| `ValidationError` | Model data is invalid: an empty name, a non-positive amount, fields that do not match the split method, ... |
| `InvalidAmountError` | An amount cannot be parsed or is not allowed (NaN, infinity, bool, wrong type). |
| `AllocationError` | An amount cannot be allocated: no weights, negative or all-zero weights, or inconsistent totals. |
| `CurrencyError` | A currency code is malformed or an exchange rate is missing. |
| `SplitError` | A split is invalid, for example exact amounts that do not add up to the total. |
| `GroupNotFoundError`, `MemberNotFoundError`, `ExpenseNotFoundError` | A requested entity does not exist. |
| `DuplicateError` | A group or member with the same name already exists. |
| `SettlementError` | Balances cannot be settled, for example because they do not sum to zero. |
| `StorageError` | A database operation failed. |

- **One base class.** Library users and the CLI can catch every SplitEasy
  error with `except SplitEasyError`.
- **Built-in bases as well.** Invalid-input errors also derive from
  `ValueError`, and the not-found errors from `LookupError`, so generic
  handlers keep working.
- **Structured not-found errors.** `NotFoundError` stores `entity` and
  `identifier` and builds messages such as `Group 'Italy Trip' not found`.
- **Wrapped low-level errors.** `sqlite3.Error` is re-raised as
  `StorageError` with `raise ... from err`, keeping the original cause.

### Command-line interface

- The root callback creates the `GroupService` for the database chosen with
  `--db` or `SPLITEASY_DB`, stores it in `ctx.obj`, and registers
  `ctx.call_on_close(service.close)`. The `version` command skips this, so it
  never creates a database.
- Errors are handled in one place: a custom `TyperGroup` wraps every
  subcommand, turns a `SplitEasyError` into a red `Error: ...` message on
  stderr, and exits with code 1. Usage errors exit with code 2 (from Typer),
  and declined confirmations exit with code 1.
- The command modules read the service from `ctx.obj` and never import
  `app.py`, which avoids circular imports.
- Tables use ASCII borders. The only non-ASCII characters in normal output are
  currency symbols.
- Input formats (`--values "A=40,B=30"`, `--item "NAME:PRICE:A,B[:QTY]"`) are
  parsed by small, separately tested functions in `cli/parsing.py`.

### Lazy matplotlib import

matplotlib takes a noticeable time to import, so `reports/charts.py` imports
it inside its functions only and selects the non-interactive `Agg` backend.
Commands that do not draw charts start quickly, the library can be imported
without loading matplotlib (a test checks this in a fresh interpreter), and
charts render on machines without a display, including CI. Every figure is
closed after saving.

---

## 7. Settlement algorithms

Given the net balances `b₁ … bₙ` of the members with a non-zero balance (they
sum to zero), settlement produces transfers from debtors to creditors that
bring every balance to zero, ideally with few transfers. Balances are exact
`Decimal` amounts, so comparisons with zero are exact.

### Greedy (implemented)

`settle_greedy` in `settlement.py`:

1. Check that the balances sum to zero (`SettlementError` otherwise) and
   ignore members whose balance is zero.
2. Put the creditors in a max-heap by amount owed to them, and the debtors in
   a max-heap by amount they owe.
3. Pop the largest creditor `c` and the largest debtor `d` and suggest a
   transfer of `min(c, |d|)` from `d` to `c`.
4. Push back whichever of the two still has a non-zero balance. Repeat until
   both heaps are empty.

Every step brings at least one member to zero and the last step brings two,
so greedy makes **at most n − 1 transfers** in O(n log n) time. Ties are
broken by name, so the output is deterministic. `apply_transfers` applies
transfers to balances; the tests use it to check that every balance ends at
zero.

Greedy is fast and usually good, but it is not always optimal:

```
balances: A +6, B +4, C −4, D −3, E −3

greedy (4 transfers):  C→A 4,  D→B 3,  E→A 2,  E→B 1
optimal (3 transfers): C→B 4,  D→A 3,  E→A 3
```

### Optimal (future work)

**Key observation.** Suppose the members can be split into `k` disjoint
groups whose balances each sum to zero. Each group can be settled internally
with (size − 1) transfers, which gives n − k transfers in total. Conversely,
any set of transfers splits the members into connected components, and each
component must sum to zero. So the minimum number of transfers is
**n − k\***, where k\* is the largest number of zero-sum groups in a partition.

**Bitmask dynamic programming.** Let `sum[mask]` be the total balance of the
members in the subset `mask`, and let

```
dp[mask] = max over i in mask of dp[mask without i]  +  (1 if sum[mask] == 0 else 0)
```

with `dp[0] = 0`. Adding members one at a time, `dp[mask]` counts how many
times the running total returns to zero, and the best order gives the largest
number of zero-sum groups, so `k* = dp[full set]`. Following the choices back
recovers the groups, and each group is settled with greedy. This needs
O(2ⁿ · n) time and O(2ⁿ) memory, so it would only be used up to about 15
members with a non-zero balance, falling back to greedy above that.

### Why the optimal problem is NP-hard

n − 1 transfers are always enough. Settling with **fewer** than n − 1
transfers is possible exactly when some non-empty proper subset of the
balances sums to zero, because then k\* ≥ 2. Deciding whether such a subset
exists is the **zero-sum subset problem**, a form of Subset Sum, which is
NP-complete. So even answering "can we save a single transfer?" is
NP-complete, and computing the minimum number of transfers is NP-hard in
general. This is why SplitEasy uses a fast heuristic by default.

---

## 8. Development conventions and testing

| Area | Convention |
| --- | --- |
| Python | 3.10 or newer. src layout (`src/spliteasy/`). Built with hatchling, managed with uv; `uv.lock` pins exact versions. |
| Money | Always `Decimal`; floats only at the moment of drawing a chart. |
| Types | Full type hints on every function and method. |
| Docstrings | Google style on every public module, class and function, checked by ruff (`D` rules, `convention = "google"`). Several docstrings contain doctest examples. |
| Comments | Explain the code itself (why, not what). No history or changelog comments. |
| Errors | Raise the most specific exception from `spliteasy.exceptions`, never a bare `Exception`. Wrap third-party errors (for example `sqlite3.Error` → `StorageError`) with `raise ... from err`. |
| Purity | Layers 1–4 never print or read input. They take data in and return data out. Only `cli/` does terminal I/O. |
| Imports | Internal modules import from sibling modules directly (`from spliteasy.models import Expense`), never from the top-level package, which avoids import cycles. The one exception is `cli/app.py` reading `__version__`. |
| Layering | A module may only import from its own layer or the layers below it. |
| Style | `ruff check` (rules E, F, I, N, UP, B, D) and `ruff format`, line length 88. |
| Commits | [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`, `ci:`, with an optional scope, for example `feat(splitting): add ItemizedSplit`. |

**Tests.** Every module has a matching test file under `tests/` (about 975
tests):

- **Unit tests** with pytest, heavily parametrised, including every error
  case and its message.
- **Property-based tests** with Hypothesis. Allocations always sum to the
  total and stay within one minor unit of the exact value; shares always sum
  to the converted amount for any split method, rate and currency (including
  itemised receipts); balances always sum to zero; settlement leaves every
  balance at zero with at most n − 1 positive transfers.
- **Storage tests** on real SQLite files in `tmp_path`, including round trips
  of every kind of expense, cascading deletes and rolled-back transactions.
- **CLI tests** through `invoke` in `tests/conftest.py`, which runs the app
  with Typer's `CliRunner`, strips ANSI styling (Typer forces colour on GitHub
  Actions) and uses a wide terminal, so assertions compare the same plain text
  locally and in CI.
- **Windows safety.** Paths are built with `pathlib`, and every test closes
  its repository or service so database files can be deleted.

**Continuous integration.** GitHub Actions runs `uv sync --locked`,
`ruff check`, `ruff format --check` and `pytest` on Ubuntu and Windows with
Python 3.10 and 3.12 for every push and pull request to `main`.

Before every commit, run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

---

## 9. Future work

| Idea | Notes |
| --- | --- |
| Optimal settlement | The bitmask DP from §7 for up to about 15 members, greedy above. |
| Live exchange rates | Suggest the current rate when a foreign-currency expense is entered; the stored rate would still be frozen. |
| Markdown, PDF and CSV export | A `reports/export.py` next to the charts; PDF via fpdf2. |
| Recurring expenses | For example monthly rent, added automatically. |
| GiroCode QR codes | EPC QR codes for suggested transfers, to scan into a banking app. |
| Receipt import from YAML | An alternative to `--item` options for long receipts (PyYAML). |
| Editing and renaming | Edit an expense in place; rename a member everywhere the name is used. |
| Payments column in `balance` | Show *sent − received*, so the balance column is fully explained. |
| Schema migrations | `schema_version` is stored and checked; migrations would run when it is older than the code. |
