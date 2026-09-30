import dataclasses
import json
from datetime import datetime, timedelta, timezone
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
    MAX_NAME_LENGTH,
    Adjustment,
    AdjustmentKind,
    DistributionMode,
    Group,
    LineItem,
    Member,
    Share,
    SplitMethod,
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
