import json
from enum import Enum

import pytest

from spliteasy.exceptions import ValidationError
from spliteasy.models import (
    MAX_NAME_LENGTH,
    AdjustmentKind,
    DistributionMode,
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
