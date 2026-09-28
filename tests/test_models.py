import dataclasses
import json
from datetime import datetime, timedelta, timezone
from enum import Enum

import pytest

from spliteasy.exceptions import (
    CurrencyError,
    DuplicateError,
    MemberNotFoundError,
    ValidationError,
)
from spliteasy.models import (
    MAX_NAME_LENGTH,
    AdjustmentKind,
    DistributionMode,
    Group,
    Member,
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
