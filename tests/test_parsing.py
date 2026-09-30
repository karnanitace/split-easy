from decimal import Decimal

import pytest

from spliteasy.cli.parsing import parse_values
from spliteasy.exceptions import ValidationError


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
