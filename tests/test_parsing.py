from decimal import Decimal

import pytest

from spliteasy.cli.parsing import parse_item, parse_values
from spliteasy.exceptions import ValidationError
from spliteasy.models import SplitMethod


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Alice=40,Bob=30", {"Alice": "40", "Bob": "30"}),
        ("Alice=40", {"Alice": "40"}),
        (" Alice = 40 , Bob= 30.5 ", {"Alice": "40", "Bob": "30.5"}),
        ("Alice=12,50;Bob=7,50", {"Alice": "12.50", "Bob": "7.50"}),
        ("Alice=12.5; Bob=7.5;", {"Alice": "12.5", "Bob": "7.5"}),
        ("Alice=40,Bob=30,", {"Alice": "40", "Bob": "30"}),
        ("Mary Ann=1,Bob=0", {"Mary Ann": "1", "Bob": "0"}),
        ("Alice=-1.5", {"Alice": "-1.5"}),
    ],
)
def test_parse_values(text: str, expected: dict[str, str]) -> None:
    assert parse_values(text) == {
        name: Decimal(value) for name, value in expected.items()
    }


def test_parse_values_keeps_order_and_exact_digits() -> None:
    result = parse_values("Carol=33.34,Alice=33.33,Bob=33.33")

    assert list(result) == ["Carol", "Alice", "Bob"]
    assert [str(value) for value in result.values()] == ["33.34", "33.33", "33.33"]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("Alice40", "Invalid value 'Alice40': expected NAME=VALUE"),
        ("Alice=40,Bob30", "Invalid value 'Bob30': expected NAME=VALUE"),
        ("Alice=abc", "Invalid value for 'Alice': 'abc' is not a number"),
        ("Alice=", "Invalid value for 'Alice': '' is not a number"),
        ("Alice=NaN", "Invalid value for 'Alice': 'NaN' is not a number"),
        ("=40", "Invalid value '=40': the name is missing"),
        ("Alice=1,alice=2", "'alice' appears more than once"),
        ("", "No values given"),
        (" , ", "No values given"),
        ("Alice=12,50", "Invalid value '50': expected NAME=VALUE"),
    ],
)
def test_parse_values_rejects_bad_input(text: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message.replace("(", r"\(")):
        parse_values(text)


# parse_item


@pytest.mark.parametrize(
    ("text", "name", "price", "members", "quantity"),
    [
        ("Olive oil:6.00:Alice,Bob", "Olive oil", "6.00", ["Alice", "Bob"], 1),
        ("Yogurt:4:Alice", "Yogurt", "4", ["Alice"], 1),
        ("Protein bars:2.50:Alice:2", "Protein bars", "2.50", ["Alice"], 2),
        (" Milk : 1,29 : Alice , Bob : 3 ", "Milk", "1.29", ["Alice", "Bob"], 3),
        ("Deposit return:-0.25:Bob:4", "Deposit return", "-0.25", ["Bob"], 4),
        ("Bread:2.00:Alice,,Bob,", "Bread", "2.00", ["Alice", "Bob"], 1),
    ],
)
def test_parse_item(
    text: str, name: str, price: str, members: list[str], quantity: int
) -> None:
    item = parse_item(text)

    assert item.name == name
    assert item.price == Decimal(price)
    assert list(item.assignees) == members
    assert all(weight == 1 for weight in item.assignees.values())
    assert item.quantity == quantity
    assert item.split_method is SplitMethod.EQUAL


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("Olive oil", "Invalid item 'Olive oil': expected NAME:PRICE:MEMBER,MEMBER"),
        ("Olive oil:6.00", "expected NAME:PRICE:MEMBER,MEMBER"),
        ("A:1:B:2:C", "expected NAME:PRICE:MEMBER,MEMBER"),
        ("Oil:abc:Alice", "Invalid price for item 'Oil': 'abc' is not a number"),
        ("Oil:6.00:Alice:two", "Invalid quantity for item 'Oil': 'two' is not a whole"),
        ("Oil:6.00:Alice:-1", "'-1' is not a whole number"),
        ("Oil:6.00:Alice:1.5", "'1.5' is not a whole number"),
        ("Oil:6.00:Alice:0", "must be at least 1"),
        ("Oil:6.00:", "Item 'Oil' needs at least one member"),
        ("Oil:6.00: , ", "Item 'Oil' needs at least one member"),
        ("Oil:0:Alice", "must not be zero"),
        (":6.00:Alice", "Item name must not be empty"),
        ("Oil:6.00:Alice,alice", "appears more than once"),
    ],
)
def test_parse_item_rejects_bad_input(text: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        parse_item(text)
