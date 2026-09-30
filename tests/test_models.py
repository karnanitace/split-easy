import dataclasses
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum

import pytest

from spliteasy.exceptions import (
    CurrencyError,
    DuplicateError,
    InvalidAmountError,
    MemberNotFoundError,
    ValidationError,
)
from spliteasy.models import (
    MAX_DESCRIPTION_LENGTH,
    MAX_NAME_LENGTH,
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
    normalize_name,
)


@pytest.mark.parametrize(
    ("enum_type", "value", "member"),
    [
        (SplitMethod, "equal", SplitMethod.EQUAL),
        (SplitMethod, "exact", SplitMethod.EXACT),
        (SplitMethod, "percentage", SplitMethod.PERCENTAGE),
        (SplitMethod, "shares", SplitMethod.SHARES),
        (SplitMethod, "itemized", SplitMethod.ITEMIZED),
        (AdjustmentKind, "discount", AdjustmentKind.DISCOUNT),
        (AdjustmentKind, "fee", AdjustmentKind.FEE),
        (AdjustmentKind, "deposit", AdjustmentKind.DEPOSIT),
        (DistributionMode, "proportional", DistributionMode.PROPORTIONAL),
        (DistributionMode, "equal", DistributionMode.EQUAL),
    ],
)
def test_enum_constructs_from_string_and_equals_it(
    enum_type: type[Enum], value: str, member: Enum
) -> None:
    assert enum_type(value) is member
    assert member == value
    assert member.value == value


@pytest.mark.parametrize(
    ("enum_type", "count"),
    [(SplitMethod, 5), (AdjustmentKind, 3), (DistributionMode, 2)],
)
def test_enum_has_expected_number_of_members(enum_type: type[Enum], count: int) -> None:
    assert len(enum_type) == count


@pytest.mark.parametrize(
    ("enum_type", "value"),
    [
        (SplitMethod, "EQUAL"),
        (SplitMethod, "itemised"),
        (SplitMethod, ""),
        (AdjustmentKind, "tip"),
        (DistributionMode, "weighted"),
        (DistributionMode, None),
    ],
)
def test_enum_rejects_invalid_values(enum_type: type[Enum], value: object) -> None:
    with pytest.raises(ValueError):
        enum_type(value)


def test_enum_members_are_strings_and_serialize_as_values() -> None:
    assert isinstance(SplitMethod.EQUAL, str)
    assert json.dumps({"method": SplitMethod.SHARES}) == '{"method": "shares"}'


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Ana", "Ana"),
        ("  Ana  ", "Ana"),
        ("Italy   Trip", "Italy Trip"),
        ("\tItaly \n Trip ", "Italy Trip"),
        ("Zoë", "Zoë"),
        ("a" * MAX_NAME_LENGTH, "a" * MAX_NAME_LENGTH),
        ("  " + "a" * MAX_NAME_LENGTH + "  ", "a" * MAX_NAME_LENGTH),
    ],
)
def test_normalize_name(name: str, expected: str) -> None:
    assert normalize_name(name) == expected


@pytest.mark.parametrize("name", ["", "   ", "\t\n"])
def test_normalize_name_rejects_empty_names(name: str) -> None:
    with pytest.raises(ValidationError, match="^Member name must not be empty$"):
        normalize_name(name, kind="Member name")


def test_normalize_name_rejects_names_that_are_too_long() -> None:
    with pytest.raises(ValidationError, match="Group name must be at most 50"):
        normalize_name("a" * (MAX_NAME_LENGTH + 1), kind="Group name")


def test_normalize_name_uses_default_kind_in_message() -> None:
    with pytest.raises(ValidationError, match="^Name must not be empty$"):
        normalize_name("")


@pytest.mark.parametrize("name", [None, 42, b"Ana"])
def test_normalize_name_rejects_non_strings(name: object) -> None:
    with pytest.raises(ValidationError, match="must be a string"):
        normalize_name(name)  # type: ignore[arg-type]


# Member


def test_member_normalizes_name() -> None:
    assert Member("  Alice   Smith ").name == "Alice Smith"


def test_member_keeps_spelling_for_display() -> None:
    member = Member("alice")

    assert member.name == "alice"
    assert member.key == "alice"
    assert Member("ALICE").key == "alice"


@pytest.mark.parametrize("name", ["", "   ", "a" * (MAX_NAME_LENGTH + 1), None])
def test_member_rejects_invalid_names(name: object) -> None:
    with pytest.raises(ValidationError, match="^Member name"):
        Member(name)  # type: ignore[arg-type]


def test_member_id_defaults_to_none() -> None:
    assert Member("Alice").id is None
    assert Member("Alice", id=7).id == 7


def test_member_equality_ignores_case_and_whitespace() -> None:
    assert Member("Alice") == Member("alice")
    assert Member("Alice") == Member(" ALICE ")
    assert Member("Alice") != Member("Alicia")


def test_member_equality_ignores_id() -> None:
    assert Member("Alice", id=1) == Member("alice", id=2)


def test_member_is_not_equal_to_plain_string() -> None:
    assert Member("Alice") != "Alice"


def test_member_hash_ignores_case() -> None:
    assert hash(Member("Alice")) == hash(Member("alice"))
    assert len({Member("Alice"), Member("alice"), Member("ALICE")}) == 1
    assert {Member("Alice"): 1}[Member("alice")] == 1


def test_member_is_frozen() -> None:
    member = Member("Alice")

    with pytest.raises(dataclasses.FrozenInstanceError):
        member.name = "Bob"  # type: ignore[misc]


def test_member_uses_slots() -> None:
    assert not hasattr(Member("Alice"), "__dict__")


# Group


def test_group_normalizes_name_and_currency() -> None:
    group = Group(name="  Italy   Trip ", currency=" chf ")

    assert group.name == "Italy Trip"
    assert group.currency == "CHF"


def test_group_defaults() -> None:
    before = datetime.now(timezone.utc)

    group = Group(name="Flat")

    assert group.currency == "EUR"
    assert group.members == []
    assert group.id is None
    assert group.created_at.tzinfo is not None
    assert group.created_at.utcoffset() == timedelta(0)
    assert before <= group.created_at <= datetime.now(timezone.utc)


def test_group_default_member_lists_are_independent() -> None:
    first = Group(name="A")
    second = Group(name="B")

    first.add_member("Alice")

    assert second.members == []


def test_group_is_keyword_only() -> None:
    with pytest.raises(TypeError):
        Group("Flat")  # type: ignore[misc]


@pytest.mark.parametrize("name", ["", "  ", "a" * (MAX_NAME_LENGTH + 1)])
def test_group_rejects_invalid_names(name: str) -> None:
    with pytest.raises(ValidationError, match="^Group name"):
        Group(name=name)


@pytest.mark.parametrize("currency", ["", "EURO", "E1R"])
def test_group_rejects_invalid_currency(currency: str) -> None:
    with pytest.raises(CurrencyError):
        Group(name="Flat", currency=currency)


def test_group_rejects_naive_created_at() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        Group(name="Flat", created_at=datetime(2026, 1, 1))


def test_group_accepts_initial_members_and_copies_list() -> None:
    initial = [Member("Alice"), Member("Bob")]

    group = Group(name="Flat", members=initial)
    initial.append(Member("Carol"))

    assert group.member_names == ["Alice", "Bob"]


def test_group_rejects_duplicate_initial_members() -> None:
    with pytest.raises(DuplicateError, match="'alice' appears more than once"):
        Group(name="Flat", members=[Member("Alice"), Member("Bob"), Member("alice")])


def test_group_rejects_non_member_entries() -> None:
    with pytest.raises(ValidationError, match="Member objects"):
        Group(name="Flat", members=["Alice"])  # type: ignore[list-item]


@pytest.fixture
def flat() -> Group:
    return Group(name="Flat", members=[Member("Alice"), Member("Bob")])


def test_member_names_in_insertion_order(flat: Group) -> None:
    flat.add_member("Carol")
    flat.add_member("Aaron")

    assert flat.member_names == ["Alice", "Bob", "Carol", "Aaron"]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Alice", True),
        ("alice", True),
        ("  BOB ", True),
        ("Carol", False),
        ("", False),
        ("   ", False),
    ],
)
def test_has_member(flat: Group, name: str, expected: bool) -> None:
    assert flat.has_member(name) is expected


@pytest.mark.parametrize("name", ["Alice", "alice", " ALICE  "])
def test_get_member_is_case_insensitive(flat: Group, name: str) -> None:
    member = flat.get_member(name)

    assert member is flat.members[0]
    assert member.name == "Alice"


@pytest.mark.parametrize("name", ["Carol", "", "   "])
def test_get_member_raises_for_missing_member(flat: Group, name: str) -> None:
    with pytest.raises(MemberNotFoundError) as excinfo:
        flat.get_member(name)

    assert excinfo.value.identifier == name


def test_add_member_returns_new_member(flat: Group) -> None:
    member = flat.add_member("  Carol  ")

    assert member == Member("Carol")
    assert member.name == "Carol"
    assert flat.members[-1] is member


@pytest.mark.parametrize("name", ["Alice", "alice", "  ALICE "])
def test_add_member_rejects_duplicates(flat: Group, name: str) -> None:
    with pytest.raises(DuplicateError, match="'Alice' already exists in group 'Flat'"):
        flat.add_member(name)

    assert flat.member_names == ["Alice", "Bob"]


@pytest.mark.parametrize("name", ["", "   ", "a" * (MAX_NAME_LENGTH + 1)])
def test_add_member_rejects_invalid_names(flat: Group, name: str) -> None:
    with pytest.raises(ValidationError, match="^Member name"):
        flat.add_member(name)


@pytest.mark.parametrize("name", ["Alice", "alice", " ALICE "])
def test_remove_member_is_case_insensitive(flat: Group, name: str) -> None:
    flat.remove_member(name)

    assert flat.member_names == ["Bob"]


def test_remove_member_raises_for_missing_member(flat: Group) -> None:
    with pytest.raises(MemberNotFoundError):
        flat.remove_member("Carol")

    assert flat.member_names == ["Alice", "Bob"]


def test_removed_member_can_be_added_again(flat: Group) -> None:
    flat.remove_member("Alice")
    flat.add_member("alice")

    assert flat.member_names == ["Bob", "alice"]


@pytest.mark.parametrize(
    ("name", "expected"), [("alice", "Alice"), ("ALICE", "Alice"), (" bob ", "Bob")]
)
def test_resolve_name_returns_stored_spelling(
    flat: Group, name: str, expected: str
) -> None:
    assert flat.resolve_name(name) == expected


def test_resolve_name_raises_for_missing_member(flat: Group) -> None:
    with pytest.raises(MemberNotFoundError, match="Member 'Carol' not found"):
        flat.resolve_name("Carol")


# Share


def test_share_normalizes_member_and_parses_amount() -> None:
    share = Share(" Alice ", "12,50")  # type: ignore[arg-type]

    assert share.member == "Alice"
    assert share.amount == Decimal("12.50")


def test_share_allows_zero_amount() -> None:
    assert Share("Alice", Decimal(0)).amount == 0


def test_share_keeps_unrounded_amount() -> None:
    assert Share("Alice", Decimal("3.333")).amount == Decimal("3.333")


def test_share_rejects_negative_amount() -> None:
    with pytest.raises(ValidationError, match="must not be negative"):
        Share("Alice", Decimal("-0.01"))


@pytest.mark.parametrize("amount", ["abc", "NaN", True])
def test_share_rejects_unparsable_amount(amount: object) -> None:
    with pytest.raises(InvalidAmountError):
        Share("Alice", amount)  # type: ignore[arg-type]


def test_share_rejects_empty_member() -> None:
    with pytest.raises(ValidationError, match="^Member name must not be empty$"):
        Share("  ", Decimal(1))


def test_share_is_frozen_value_object() -> None:
    share = Share("Alice", Decimal("1.00"))

    assert share == Share("Alice", Decimal("1.00"))
    assert len({share, Share("Alice", Decimal("1.00"))}) == 1
    with pytest.raises(dataclasses.FrozenInstanceError):
        share.amount = Decimal(2)  # type: ignore[misc]


# LineItem


def make_item(**overrides: object) -> LineItem:
    fields: dict[str, object] = {
        "name": "Milk",
        "price": Decimal("1.29"),
        "assignees": {"Alice": Decimal(1)},
    }
    fields.update(overrides)
    return LineItem(**fields)  # type: ignore[arg-type]


def test_line_item_normalizes_and_parses_fields() -> None:
    item = make_item(
        name="  Oat   Milk ",
        price="1,29",
        quantity=3,
        assignees={" Alice ": 1, "Bob": "2.5"},
        split_method="shares",
        category="  Dairy ",
    )

    assert item.name == "Oat Milk"
    assert item.price == Decimal("1.29")
    assert item.quantity == 3
    assert item.assignees == {"Alice": Decimal(1), "Bob": Decimal("2.5")}
    assert all(isinstance(w, Decimal) for w in item.assignees.values())
    assert item.split_method is SplitMethod.SHARES
    assert item.category == "dairy"


def test_line_item_defaults() -> None:
    item = make_item()

    assert item.quantity == 1
    assert item.split_method is SplitMethod.EQUAL
    assert item.category is None


def test_line_item_total_is_price_times_quantity() -> None:
    assert make_item(price="1.29", quantity=3).total == Decimal("3.87")


def test_line_item_allows_negative_price_for_deposit_return() -> None:
    item = make_item(name="Bottle deposit return", price="-0.25", quantity=4)

    assert item.price == Decimal("-0.25")
    assert item.total == Decimal("-1.00")


def test_line_item_stores_assignees_as_new_dict() -> None:
    assignees = {"Alice": Decimal(1)}

    item = make_item(assignees=assignees)
    assignees["Bob"] = Decimal(1)

    assert type(item.assignees) is dict
    assert item.assignees == {"Alice": Decimal(1)}


def test_line_item_keeps_assignee_order_and_zero_weights() -> None:
    item = make_item(assignees={"Carol": 0, "Alice": 1, "Bob": 2})

    assert list(item.assignees) == ["Carol", "Alice", "Bob"]
    assert item.assignees["Carol"] == 0


def test_line_item_is_frozen_and_unhashable() -> None:
    item = make_item()

    assert item == make_item()
    with pytest.raises(dataclasses.FrozenInstanceError):
        item.price = Decimal(2)  # type: ignore[misc]
    with pytest.raises(TypeError, match="unhashable"):
        hash(item)


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        ("equal", SplitMethod.EQUAL),
        ("exact", SplitMethod.EXACT),
        ("percentage", SplitMethod.PERCENTAGE),
        ("shares", SplitMethod.SHARES),
        (SplitMethod.SHARES, SplitMethod.SHARES),
    ],
)
def test_line_item_converts_split_method(method: object, expected: SplitMethod) -> None:
    assert make_item(split_method=method).split_method is expected


@pytest.mark.parametrize("method", [SplitMethod.ITEMIZED, "itemized"])
def test_line_item_rejects_itemized_split_method(method: object) -> None:
    with pytest.raises(ValidationError, match="not allowed for a line item"):
        make_item(split_method=method)


def test_line_item_rejects_unknown_split_method() -> None:
    with pytest.raises(ValidationError, match="Invalid split method 'weighted'"):
        make_item(split_method="weighted")


@pytest.mark.parametrize("category", ["", "   "])
def test_line_item_treats_blank_category_as_none(category: str) -> None:
    assert make_item(category=category).category is None


def test_line_item_rejects_non_string_category() -> None:
    with pytest.raises(ValidationError, match="Category must be a string"):
        make_item(category=42)


@pytest.mark.parametrize("name", ["", "   ", "a" * (MAX_NAME_LENGTH + 1)])
def test_line_item_rejects_invalid_name(name: str) -> None:
    with pytest.raises(ValidationError, match="^Item name"):
        make_item(name=name)


@pytest.mark.parametrize("price", [0, "0.00", Decimal("-0")])
def test_line_item_rejects_zero_price(price: object) -> None:
    with pytest.raises(ValidationError, match="must not be zero"):
        make_item(price=price)


@pytest.mark.parametrize("price", ["abc", "Infinity", None])
def test_line_item_rejects_unparsable_price(price: object) -> None:
    with pytest.raises(InvalidAmountError):
        make_item(price=price)


@pytest.mark.parametrize("quantity", [0, -1])
def test_line_item_rejects_quantity_below_one(quantity: int) -> None:
    with pytest.raises(ValidationError, match="at least 1"):
        make_item(quantity=quantity)


@pytest.mark.parametrize("quantity", [True, 1.0, "2", None])
def test_line_item_rejects_non_integer_quantity(quantity: object) -> None:
    with pytest.raises(ValidationError, match="must be an integer"):
        make_item(quantity=quantity)


def test_line_item_rejects_empty_assignees() -> None:
    with pytest.raises(ValidationError, match="at least one assignee"):
        make_item(assignees={})


def test_line_item_rejects_non_mapping_assignees() -> None:
    with pytest.raises(ValidationError, match="must be a mapping"):
        make_item(assignees=["Alice", "Bob"])


def test_line_item_rejects_all_zero_weights() -> None:
    with pytest.raises(ValidationError, match="At least one weight"):
        make_item(assignees={"Alice": 0, "Bob": Decimal("0.0")})


def test_line_item_rejects_negative_weight() -> None:
    with pytest.raises(ValidationError, match="must not be negative"):
        make_item(assignees={"Alice": 1, "Bob": -1})


def test_line_item_rejects_unparsable_weight() -> None:
    with pytest.raises(InvalidAmountError):
        make_item(assignees={"Alice": "lots"})


@pytest.mark.parametrize(
    "assignees",
    [
        {"Alice": 1, "alice": 1},
        {"Alice": 1, " ALICE ": 2},
        {"Alice": 1, "Alice  ": 1},
    ],
)
def test_line_item_rejects_duplicate_assignees(assignees: dict[str, int]) -> None:
    with pytest.raises(ValidationError, match="appears more than once"):
        make_item(assignees=assignees)


def test_line_item_rejects_invalid_assignee_name() -> None:
    with pytest.raises(ValidationError, match="^Member name must not be empty$"):
        make_item(assignees={"  ": 1})


def test_for_members_alice_and_bob() -> None:
    item = LineItem.for_members("Pizza", "12.00", ["Alice", "Bob"])

    assert item.name == "Pizza"
    assert item.price == Decimal("12.00")
    assert item.quantity == 1
    assert item.assignees == {"Alice": Decimal(1), "Bob": Decimal(1)}
    assert item.split_method is SplitMethod.EQUAL
    assert item.category is None


def test_for_members_passes_quantity_and_category() -> None:
    item = LineItem.for_members(
        "Beer", Decimal("1.10"), ["Alice"], quantity=6, category="Drinks"
    )

    assert item.total == Decimal("6.60")
    assert item.category == "drinks"


def test_for_members_rejects_empty_members() -> None:
    with pytest.raises(ValidationError, match="at least one assignee"):
        LineItem.for_members("Pizza", "12.00", [])


@pytest.mark.parametrize("members", [["Alice", "Alice"], ["Alice", " alice"]])
def test_for_members_rejects_duplicate_members(members: list[str]) -> None:
    with pytest.raises(ValidationError, match="appears more than once"):
        LineItem.for_members("Pizza", "12.00", members)


# Adjustment


def test_adjustment_converts_strings_and_parses_amount() -> None:
    adjustment = Adjustment(
        kind="fee",  # type: ignore[arg-type]
        amount="3,50",  # type: ignore[arg-type]
        distribute="equal",  # type: ignore[arg-type]
        description="  Delivery ",
    )

    assert adjustment.kind is AdjustmentKind.FEE
    assert adjustment.amount == Decimal("3.50")
    assert adjustment.distribute is DistributionMode.EQUAL
    assert adjustment.description == "Delivery"


def test_adjustment_defaults() -> None:
    adjustment = Adjustment(kind=AdjustmentKind.DISCOUNT, amount=Decimal(5))

    assert adjustment.distribute is DistributionMode.PROPORTIONAL
    assert adjustment.description == ""


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (AdjustmentKind.DISCOUNT, Decimal("-5.00")),
        (AdjustmentKind.FEE, Decimal("5.00")),
        (AdjustmentKind.DEPOSIT, Decimal("5.00")),
        ("discount", Decimal("-5.00")),
    ],
)
def test_adjustment_signed_amount(kind: object, expected: Decimal) -> None:
    adjustment = Adjustment(kind=kind, amount=Decimal("5.00"))  # type: ignore[arg-type]

    assert adjustment.signed_amount == expected


@pytest.mark.parametrize("amount", [0, "0.00", "-1"])
def test_adjustment_rejects_non_positive_amount(amount: object) -> None:
    with pytest.raises(ValidationError, match="greater than zero"):
        Adjustment(kind=AdjustmentKind.FEE, amount=amount)  # type: ignore[arg-type]


def test_adjustment_rejects_unparsable_amount() -> None:
    with pytest.raises(InvalidAmountError):
        Adjustment(kind=AdjustmentKind.FEE, amount="free")  # type: ignore[arg-type]


def test_adjustment_rejects_unknown_kind() -> None:
    with pytest.raises(ValidationError, match="Invalid adjustment kind 'tip'"):
        Adjustment(kind="tip", amount=Decimal(1))  # type: ignore[arg-type]


def test_adjustment_rejects_unknown_distribution_mode() -> None:
    with pytest.raises(ValidationError, match="Invalid distribution mode"):
        Adjustment(
            kind=AdjustmentKind.FEE,
            amount=Decimal(1),
            distribute="weighted",  # type: ignore[arg-type]
        )


def test_adjustment_rejects_non_string_description() -> None:
    with pytest.raises(ValidationError, match="description must be a string"):
        Adjustment(
            kind=AdjustmentKind.FEE,
            amount=Decimal(1),
            description=None,  # type: ignore[arg-type]
        )


def test_adjustment_is_frozen_value_object() -> None:
    adjustment = Adjustment(kind=AdjustmentKind.FEE, amount=Decimal(1))

    assert adjustment == Adjustment(kind="fee", amount="1")  # type: ignore[arg-type]
    assert (
        len({adjustment, Adjustment(kind=AdjustmentKind.FEE, amount=Decimal(1))}) == 1
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        adjustment.amount = Decimal(2)  # type: ignore[misc]


# normalize_name max_length


def test_normalize_name_accepts_custom_max_length() -> None:
    long_name = "a" * 80

    assert normalize_name(long_name, max_length=100) == long_name
    with pytest.raises(ValidationError, match="at most 10 characters, got 11"):
        normalize_name("a" * 11, kind="Name", max_length=10)


# Expense


def make_expense(**overrides: object) -> Expense:
    fields: dict[str, object] = {
        "description": "Dinner",
        "amount": Decimal("30.00"),
        "payer": "Alice",
    }
    fields.update(overrides)
    return Expense(**fields)  # type: ignore[arg-type]


@pytest.fixture
def kaufland() -> Expense:
    return make_expense(
        description="Kaufland",
        amount="20.00",
        split_method="itemized",
        category="groceries",
        items=[
            LineItem.for_members("Olive oil", "6.00", ["Alice", "Bob"]),
            LineItem.for_members("Protein bars", "5.00", ["Alice"]),
            LineItem.for_members("Yogurt", "4.00", ["Alice"]),
            LineItem.for_members("Coffee", "5.00", ["Bob"]),
        ],
    )


def test_simple_equal_expense() -> None:
    expense = make_expense(participants=["Alice", " bob "])

    assert expense.description == "Dinner"
    assert expense.amount == Decimal("30.00")
    assert expense.payer == "Alice"
    assert expense.currency == "EUR"
    assert expense.split_method is SplitMethod.EQUAL
    assert expense.participants == ["Alice", "bob"]
    assert expense.split_values == {}
    assert expense.items == []
    assert expense.adjustments == []
    assert expense.category == "other"
    assert expense.rate_to_base == Decimal("1")
    assert expense.shares == []
    assert expense.note == ""
    assert expense.id is None
    assert expense.group_id is None


def test_expense_defaults_date_to_today_and_participants_to_all() -> None:
    expense = make_expense()

    assert expense.date == date.today()
    assert expense.participants == []


def test_expense_normalizes_fields() -> None:
    expense = make_expense(
        description="  Dinner   at  Mario's ",
        amount="30,555",
        payer="  Alice ",
        currency=" eur ",
        category="  Food ",
        note="  split later ",
        date=date(2026, 9, 1),
    )

    assert expense.description == "Dinner at Mario's"
    assert expense.amount == Decimal("30.56")
    assert expense.payer == "Alice"
    assert expense.currency == "EUR"
    assert expense.category == "food"
    assert expense.note == "split later"
    assert expense.date == date(2026, 9, 1)


def test_expense_rounds_amount_to_currency_minor_unit() -> None:
    assert make_expense(amount="1500.4", currency="JPY").amount == Decimal("1500")


def test_expense_allows_long_descriptions_up_to_limit() -> None:
    description = "d" * MAX_DESCRIPTION_LENGTH

    assert make_expense(description=description).description == description
    with pytest.raises(ValidationError, match="^Description must be at most 100"):
        make_expense(description=description + "d")


def test_foreign_currency_expense_base_amount() -> None:
    expense = make_expense(amount="100.00", currency="CHF", rate_to_base="1.0612")

    assert expense.amount == Decimal("100.00")
    assert expense.rate_to_base == Decimal("1.0612")
    assert expense.base_amount("EUR") == Decimal("106.12")


def test_base_amount_rounds_half_up_to_base_currency() -> None:
    expense = make_expense(amount="10.00", currency="USD", rate_to_base="0.92345")

    assert expense.base_amount("EUR") == Decimal("9.23")
    assert expense.base_amount("JPY") == Decimal("9")


def test_base_amount_with_default_rate_is_amount() -> None:
    assert make_expense().base_amount("eur") == Decimal("30.00")


def test_expense_accepts_string_split_method_and_parses_values() -> None:
    expense = make_expense(
        split_method="percentage", split_values={" Alice ": "60", "Bob": 40}
    )

    assert expense.split_method is SplitMethod.PERCENTAGE
    assert expense.split_values == {"Alice": Decimal(60), "Bob": Decimal(40)}


@pytest.mark.parametrize("amount", [0, "0.00", "-5", "0.004"])
def test_expense_rejects_non_positive_amount(amount: object) -> None:
    with pytest.raises(ValidationError, match="greater than zero"):
        make_expense(amount=amount)


def test_expense_rejects_unparsable_amount() -> None:
    with pytest.raises(InvalidAmountError):
        make_expense(amount="thirty")


def test_expense_rejects_invalid_currency() -> None:
    with pytest.raises(CurrencyError):
        make_expense(currency="EURO")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"description": "  "}, "^Description must not be empty$"),
        ({"payer": ""}, "^Payer name must not be empty$"),
        ({"participants": ["Alice", ""]}, "^Participant name must not be empty$"),
        ({"participants": ["Alice", "alice"]}, "appears more than once"),
        ({"split_method": "weighted"}, "Invalid split method"),
        ({"category": "   "}, "category must not be empty"),
        ({"category": None}, "category must not be empty"),
        ({"date": "2026-09-01"}, "must be a date"),
        ({"date": datetime(2026, 9, 1)}, "must be a date"),
        ({"rate_to_base": 0}, "Exchange rate must be greater than zero"),
        ({"rate_to_base": "-1.1"}, "Exchange rate must be greater than zero"),
        ({"note": None}, "note must be a string"),
        ({"items": ["Milk"]}, "must be LineItem objects"),
        ({"shares": [("Alice", 1)]}, "must be Share objects"),
    ],
)
def test_expense_rejects_invalid_fields(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        make_expense(**overrides)


@pytest.mark.parametrize(
    "split_values",
    [
        {"Alice": 1, "Bob": -1},
        {"Alice": 1, "alice": 2},
        {"  ": 1},
    ],
)
def test_expense_rejects_invalid_split_values(split_values: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        make_expense(split_method="shares", split_values=split_values)


def test_expense_rejects_duplicate_share_members() -> None:
    with pytest.raises(ValidationError, match="appears more than once in shares"):
        make_expense(shares=[Share("Alice", Decimal(1)), Share("ALICE", Decimal(2))])


def test_expense_copies_input_lists() -> None:
    participants = ["Alice"]

    expense = make_expense(participants=participants)
    participants.append("Bob")

    assert expense.participants == ["Alice"]


# Consistency rules


def test_itemized_expense_requires_items() -> None:
    with pytest.raises(ValidationError, match="needs at least one item"):
        make_expense(split_method=SplitMethod.ITEMIZED)


@pytest.mark.parametrize("method", ["equal", "exact", "percentage", "shares"])
def test_non_itemized_expense_rejects_items(method: str) -> None:
    item = LineItem.for_members("Milk", "1.29", ["Alice"])

    with pytest.raises(ValidationError, match="must not have items or adjustments"):
        make_expense(split_method=method, split_values={"Alice": 1}, items=[item])


@pytest.mark.parametrize("method", ["equal", "exact", "percentage", "shares"])
def test_non_itemized_expense_rejects_adjustments(method: str) -> None:
    fee = Adjustment(kind=AdjustmentKind.FEE, amount=Decimal(1))

    with pytest.raises(ValidationError, match="must not have items or adjustments"):
        make_expense(split_method=method, split_values={"Alice": 1}, adjustments=[fee])


@pytest.mark.parametrize("method", ["exact", "percentage", "shares"])
def test_value_split_methods_require_split_values(method: str) -> None:
    with pytest.raises(ValidationError, match="needs split values"):
        make_expense(split_method=method)


def test_equal_expense_rejects_split_values() -> None:
    with pytest.raises(ValidationError, match="must not have split values"):
        make_expense(split_values={"Alice": 1})


@pytest.mark.parametrize("method", ["exact", "percentage", "shares"])
def test_value_split_methods_accept_split_values(method: str) -> None:
    expense = make_expense(split_method=method, split_values={"Alice": 10, "Bob": 20})

    assert expense.split_values == {"Alice": Decimal(10), "Bob": Decimal(20)}


# Itemized expenses


def test_itemized_kaufland_expense(kaufland: Expense) -> None:
    assert kaufland.split_method is SplitMethod.ITEMIZED
    assert kaufland.amount == Decimal("20.00")
    assert len(kaufland.items) == 4
    assert kaufland.items_total == Decimal("20.00")
    assert kaufland.items_total == kaufland.amount


def test_items_total_includes_signed_adjustments() -> None:
    expense = make_expense(
        split_method="itemized",
        items=[LineItem.for_members("Pizza", "12.00", ["Alice"], quantity=2)],
        adjustments=[
            Adjustment(kind=AdjustmentKind.DISCOUNT, amount=Decimal("5.00")),
            Adjustment(kind=AdjustmentKind.FEE, amount=Decimal("2.50")),
            Adjustment(kind=AdjustmentKind.DEPOSIT, amount=Decimal("0.25")),
        ],
    )

    assert expense.items_total == Decimal("21.75")


def test_items_total_includes_negative_item_prices() -> None:
    expense = make_expense(
        split_method="itemized",
        items=[
            LineItem.for_members("Water", "0.49", ["Alice"], quantity=6),
            LineItem.for_members("Deposit return", "-0.25", ["Alice"], quantity=4),
        ],
    )

    assert expense.items_total == Decimal("1.94")


def test_items_total_is_zero_without_items() -> None:
    total = make_expense().items_total

    assert total == 0
    assert isinstance(total, Decimal)


# involved_members and share_of


def test_involved_members_in_first_seen_order() -> None:
    expense = make_expense(
        payer="Dave",
        split_method="itemized",
        items=[
            LineItem.for_members("Bread", "2.00", ["Carol", "alice"]),
            LineItem.for_members("Milk", "1.00", ["Bob", "DAVE"]),
        ],
        shares=[Share("Eve", Decimal(1)), Share("Carol", Decimal(2))],
    )

    assert expense.involved_members == ["Dave", "Carol", "alice", "Bob", "Eve"]


def test_involved_members_covers_participants_and_split_values() -> None:
    equal = make_expense(payer="Alice", participants=["Bob", "alice", "Carol"])
    shares = make_expense(
        payer="Bob", split_method="shares", split_values={"Alice": 1, "bob": 2}
    )

    assert equal.involved_members == ["Alice", "Bob", "Carol"]
    assert shares.involved_members == ["Bob", "Alice"]


def test_involved_members_of_kaufland(kaufland: Expense) -> None:
    assert kaufland.involved_members == ["Alice", "Bob"]


def test_share_of_is_case_insensitive() -> None:
    expense = make_expense(
        shares=[Share("Alice", Decimal("12.50")), Share("Bob", Decimal("17.50"))]
    )

    assert expense.share_of("Alice") == Decimal("12.50")
    assert expense.share_of(" BOB ") == Decimal("17.50")


def test_share_of_missing_member_is_zero() -> None:
    expense = make_expense(shares=[Share("Alice", Decimal("30.00"))])

    assert expense.share_of("Carol") == Decimal("0")
    assert make_expense().share_of("Alice") == Decimal("0")


def test_expense_is_mutable_entity() -> None:
    expense = make_expense()

    expense.shares = [Share("Alice", Decimal("30.00"))]
    expense.id = 1

    assert expense.share_of("Alice") == Decimal("30.00")
    assert not hasattr(expense, "__dict__")


# Payment


def test_payment_normalizes_fields() -> None:
    payment = Payment(
        from_member="  Bob ",
        to_member="Alice",
        amount="8,005",  # type: ignore[arg-type]
        note="  cash ",
        date=date(2026, 9, 1),
    )

    assert payment.from_member == "Bob"
    assert payment.to_member == "Alice"
    assert payment.amount == Decimal("8.01")
    assert payment.note == "cash"
    assert payment.date == date(2026, 9, 1)


def test_payment_defaults() -> None:
    payment = Payment(from_member="Bob", to_member="Alice", amount=Decimal(8))

    assert payment.amount == Decimal("8.00")
    assert payment.date == date.today()
    assert payment.note == ""
    assert payment.id is None
    assert payment.group_id is None


def test_payment_is_mutable_entity() -> None:
    payment = Payment(from_member="Bob", to_member="Alice", amount=Decimal(8))

    payment.id = 3
    payment.group_id = 1

    assert payment.id == 3
    assert not hasattr(payment, "__dict__")


@pytest.mark.parametrize(("sender", "recipient"), [("Bob", "Bob"), ("Bob", " BOB ")])
def test_payment_rejects_same_member_twice(sender: str, recipient: str) -> None:
    with pytest.raises(ValidationError, match="two different members"):
        Payment(from_member=sender, to_member=recipient, amount=Decimal(8))


@pytest.mark.parametrize("amount", [0, "0.00", "-8", "0.004"])
def test_payment_rejects_non_positive_amount(amount: object) -> None:
    with pytest.raises(ValidationError, match="greater than zero"):
        Payment(from_member="Bob", to_member="Alice", amount=amount)  # type: ignore[arg-type]


def test_payment_rejects_unparsable_amount() -> None:
    with pytest.raises(InvalidAmountError):
        Payment(from_member="Bob", to_member="Alice", amount="eight")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"from_member": ""}, "^Sender name must not be empty$"),
        ({"to_member": "  "}, "^Recipient name must not be empty$"),
        ({"date": datetime(2026, 9, 1)}, "Payment date must be a date"),
        ({"note": None}, "note must be a string"),
    ],
)
def test_payment_rejects_invalid_fields(
    overrides: dict[str, object], message: str
) -> None:
    fields: dict[str, object] = {
        "from_member": "Bob",
        "to_member": "Alice",
        "amount": Decimal(8),
    }
    fields.update(overrides)

    with pytest.raises(ValidationError, match=message):
        Payment(**fields)  # type: ignore[arg-type]


# Transfer


def test_transfer_normalizes_fields() -> None:
    transfer = Transfer(" Bob ", "Alice", "8")  # type: ignore[arg-type]

    assert transfer.debtor == "Bob"
    assert transfer.creditor == "Alice"
    assert transfer.amount == Decimal("8.00")


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (Decimal("8"), "Bob -> Alice: 8.00"),
        (Decimal("1234.5"), "Bob -> Alice: 1234.50"),
    ],
)
def test_transfer_str(amount: Decimal, expected: str) -> None:
    assert str(Transfer("Bob", "Alice", amount)) == expected


@pytest.mark.parametrize(("debtor", "creditor"), [("Bob", "Bob"), ("bob", "BOB")])
def test_transfer_rejects_same_member_twice(debtor: str, creditor: str) -> None:
    with pytest.raises(ValidationError, match="two different members"):
        Transfer(debtor, creditor, Decimal(8))


@pytest.mark.parametrize("amount", [0, "0.00", "-8"])
def test_transfer_rejects_non_positive_amount(amount: object) -> None:
    with pytest.raises(ValidationError, match="Transfer amount must be greater"):
        Transfer("Bob", "Alice", amount)  # type: ignore[arg-type]


def test_transfer_rejects_empty_names() -> None:
    with pytest.raises(ValidationError, match="^Debtor name must not be empty$"):
        Transfer("", "Alice", Decimal(8))
    with pytest.raises(ValidationError, match="^Creditor name must not be empty$"):
        Transfer("Bob", " ", Decimal(8))


def test_transfer_is_frozen_value_object() -> None:
    transfer = Transfer("Bob", "Alice", Decimal("8.00"))

    assert transfer == Transfer("Bob", "Alice", Decimal("8"))
    assert len({transfer, Transfer("Bob", "Alice", Decimal("8.00"))}) == 1
    with pytest.raises(dataclasses.FrozenInstanceError):
        transfer.amount = Decimal(9)  # type: ignore[misc]


def test_transfer_to_payment_defaults() -> None:
    payment = Transfer("Bob", "Alice", Decimal("8.00")).to_payment()

    assert isinstance(payment, Payment)
    assert payment.from_member == "Bob"
    assert payment.to_member == "Alice"
    assert payment.amount == Decimal("8.00")
    assert payment.date == date.today()
    assert payment.note == ""
    assert payment.id is None


def test_transfer_to_payment_with_date_and_note() -> None:
    transfer = Transfer("Bob", "Alice", Decimal("8.00"))

    payment = transfer.to_payment(date=date(2026, 9, 30), note=" PayPal ")

    assert payment.date == date(2026, 9, 30)
    assert payment.note == "PayPal"


def test_transfer_to_payment_validates_date() -> None:
    transfer = Transfer("Bob", "Alice", Decimal("8.00"))

    with pytest.raises(ValidationError, match="Payment date must be a date"):
        transfer.to_payment(date="2026-09-30")  # type: ignore[arg-type]
