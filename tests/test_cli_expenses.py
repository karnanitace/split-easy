from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from spliteasy.cli.app import app
from spliteasy.cli.expense_cmds import balance_markup
from spliteasy.services import GroupService
from spliteasy.storage import SQLiteRepository

runner = CliRunner()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "cli.db"
    result = runner.invoke(
        app,
        ["--db", str(path), "group", "create", "Flat"]
        + ["-m", "Alice", "-m", "Bob", "-m", "Carol"],
    )
    assert result.exit_code == 0, result.output
    return path


def run(db_path: Path, *args: str, input: str | None = None) -> Result:
    return runner.invoke(app, ["--db", str(db_path), *args], input=input)


def ok(db_path: Path, *args: str) -> str:
    result = run(db_path, *args)
    assert result.exit_code == 0, result.output
    return result.output


def service(db_path: Path) -> GroupService:
    return GroupService(SQLiteRepository(db_path))


# Full scenario


def test_full_scenario_ends_settled_up(db_path: Path) -> None:
    ok(
        db_path,
        "expense", "add", "Flat", "Rent", "900", "--paid-by", "Alice",
        "--split", "shares", "--values", "Alice=2,Bob=1,Carol=1",
    )  # fmt: skip
    ok(db_path, "expense", "add", "Flat", "Groceries", "60", "-p", "Bob")
    ok(
        db_path,
        "expense", "add", "Flat", "Internet", "45", "-p", "Carol",
        "--split", "exact", "--values", "Alice=15,Bob=15,Carol=15",
    )  # fmt: skip

    balance = ok(db_path, "balance", "Flat")
    assert "415.00 €" in balance
    assert "-200.00 €" in balance
    assert "-215.00 €" in balance

    settle = ok(db_path, "settle", "Flat")
    assert settle.splitlines() == [
        "Carol -> Alice: 215.00 €",
        "Bob -> Alice: 200.00 €",
    ]

    paid = ok(
        db_path, "pay", "Flat", "--from", "Carol", "--to", "Alice", "--amount", "215"
    )
    assert "Recorded payment: Carol -> Alice: 215.00 €" in paid
    ok(db_path, "pay", "Flat", "--from", "bob", "--to", "alice", "--amount", "200.00")

    assert ok(db_path, "settle", "Flat").strip() == "Everyone is settled up."


# expense add


def test_expense_add_prints_shares_table(db_path: Path) -> None:
    output = ok(
        db_path, "expense", "add", "Flat", "Dinner", "100", "--paid-by", "Alice"
    )

    assert "Added expense #1: Dinner (100.00 €, paid by Alice)" in output
    lines = output.splitlines()
    assert any("Alice" in line and "33.34 €" in line for line in lines)
    assert any("Bob" in line and "33.33 €" in line for line in lines)
    assert any("Carol" in line and "33.33 €" in line for line in lines)


def test_expense_add_equal_among_some_members(db_path: Path) -> None:
    ok(
        db_path,
        "expense", "add", "Flat", "Pizza", "25", "-p", "Alice",
        "--among", "Alice", "--among", "bob",
    )  # fmt: skip

    with service(db_path) as svc:
        expense = svc.list_expenses("Flat")[0]
    assert expense.participants == ["Alice", "Bob"]
    assert [str(share.amount) for share in expense.shares] == ["12.50", "12.50"]


def test_expense_add_percentage_split(db_path: Path) -> None:
    output = ok(
        db_path,
        "expense", "add", "Flat", "Car", "50", "-p", "Bob",
        "--split", "PERCENTAGE", "--values", "Alice=60,Bob=40",
    )  # fmt: skip

    assert "30.00 €" in output
    assert "20.00 €" in output


def test_expense_add_all_options_are_stored(db_path: Path) -> None:
    ok(
        db_path,
        "expense", "add", "Flat", "Fondue", "96", "-p", "Carol",
        "--currency", "chf", "--rate", "1.06", "--category", "Food",
        "--date", "2026-09-01", "--note", "Zermatt",
    )  # fmt: skip

    with service(db_path) as svc:
        expense = svc.list_expenses("Flat")[0]
    assert expense.currency == "CHF"
    assert expense.rate_to_base == Decimal("1.06")
    assert expense.category == "food"
    assert expense.date.isoformat() == "2026-09-01"
    assert expense.note == "Zermatt"


def test_expense_add_foreign_currency_shows_conversion(db_path: Path) -> None:
    output = ok(
        db_path,
        "expense", "add", "Flat", "Fondue", "96", "-p", "Carol",
        "--currency", "CHF", "--rate", "1.06",
    )  # fmt: skip

    assert "96.00 CHF at rate 1.06 = 101.76 €" in output


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--currency", "CHF"], "An exchange rate is required for CHF -> EUR"),
        (["--split", "exact", "--values", "Alice40"], "expected NAME=VALUE"),
        (["--split", "exact", "--values", "Alice=abc"], "'abc' is not a number"),
        (["--split", "exact", "--values", "Alice=5"], "missing 25.00"),
        (["--split", "shares"], "needs split values"),
        (["--split", "itemized"], "An itemized expense needs at least one item"),
        (["--split", "weighted"], "Invalid split method 'weighted'"),
        (["--among", "Dave"], "Member 'Dave' not found"),
        (["--rate", "abc", "--currency", "CHF"], "is not a valid number"),
    ],
)
def test_expense_add_errors_exit_with_code_1(
    db_path: Path, args: list[str], message: str
) -> None:
    result = run(
        db_path, "expense", "add", "Flat", "Dinner", "30", "-p", "Alice", *args
    )

    assert result.exit_code == 1
    assert message in result.stderr
    assert "Traceback" not in result.output
    with service(db_path) as svc:
        assert svc.list_expenses("Flat") == []


def test_expense_add_requires_paid_by(db_path: Path) -> None:
    result = run(db_path, "expense", "add", "Flat", "Dinner", "30")

    assert result.exit_code == 2
    assert "--paid-by" in result.output


def test_expense_add_rejects_bad_date(db_path: Path) -> None:
    result = run(
        db_path, "expense", "add", "Flat", "Dinner", "30", "-p", "Alice",
        "--date", "01.09.2026",
    )  # fmt: skip

    assert result.exit_code == 2


# expense list


@pytest.fixture
def expenses_db(db_path: Path) -> Path:
    ok(
        db_path, "expense", "add", "Flat", "Rent", "900", "-p", "Alice",
        "--category", "rent", "--date", "2026-09-01",
    )  # fmt: skip
    ok(
        db_path, "expense", "add", "Flat", "Dinner", "40", "-p", "Bob",
        "--among", "Bob", "--among", "Carol", "--category", "food",
        "--date", "2026-08-30",
    )  # fmt: skip
    return db_path


def data_rows(output: str) -> list[list[str]]:
    rows = []
    for line in output.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 7 and cells[0].isdigit():
            rows.append(cells)
    return rows


def test_expense_list(expenses_db: Path) -> None:
    rows = data_rows(ok(expenses_db, "expense", "list", "flat"))

    assert rows == [
        ["2", "2026-08-30", "Dinner", "food", "Bob", "40.00 €", "EUR"],
        ["1", "2026-09-01", "Rent", "rent", "Alice", "900.00 €", "EUR"],
    ]


def test_expense_list_by_member(expenses_db: Path) -> None:
    rows = data_rows(ok(expenses_db, "expense", "list", "Flat", "--member", "alice"))

    assert [row[2] for row in rows] == ["Rent"]


def test_expense_list_by_category(expenses_db: Path) -> None:
    rows = data_rows(ok(expenses_db, "expense", "list", "Flat", "--category", "FOOD"))

    assert [row[2] for row in rows] == ["Dinner"]


def test_expense_list_when_empty(db_path: Path) -> None:
    assert "No expenses found." in ok(db_path, "expense", "list", "Flat")


def test_expense_list_unknown_member_is_an_error(expenses_db: Path) -> None:
    result = run(expenses_db, "expense", "list", "Flat", "--member", "Dave")

    assert result.exit_code == 1
    assert "Member 'Dave' not found" in result.stderr


# expense delete


def test_expense_delete_with_yes(expenses_db: Path) -> None:
    output = ok(expenses_db, "expense", "delete", "Flat", "1", "--yes")

    assert "Deleted expense #1 Rent (900.00 €)." in output
    rows = data_rows(ok(expenses_db, "expense", "list", "Flat"))
    assert [row[0] for row in rows] == ["2"]


def test_expense_delete_asks_for_confirmation(expenses_db: Path) -> None:
    declined = run(expenses_db, "expense", "delete", "Flat", "1", input="n\n")
    accepted = run(expenses_db, "expense", "delete", "Flat", "2", input="y\n")

    assert declined.exit_code == 1
    assert "Delete expense #1 Rent (900.00 €)?" in declined.output
    assert accepted.exit_code == 0
    rows = data_rows(ok(expenses_db, "expense", "list", "Flat"))
    assert [row[0] for row in rows] == ["1"]


def test_expense_delete_missing_id_is_an_error(expenses_db: Path) -> None:
    result = run(expenses_db, "expense", "delete", "Flat", "99", "--yes")

    assert result.exit_code == 1
    assert "Expense 99 not found" in result.stderr


# balance


def test_balance_table(expenses_db: Path) -> None:
    output = ok(expenses_db, "balance", "Flat")

    lines = output.splitlines()
    alice = next(line for line in lines if "Alice" in line)
    bob = next(line for line in lines if "Bob" in line)
    carol = next(line for line in lines if "Carol" in line)
    assert ["900.00 €", "300.00 €", "600.00 €"] == [
        cell.strip() for cell in alice.strip().strip("|").split("|")[1:]
    ]
    assert "-280.00 €" in bob
    assert "-320.00 €" in carol


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (Decimal("8.00"), "[green]8.00 €[/]"),
        (Decimal("-8.00"), "[red]-8.00 €[/]"),
        (Decimal("0.00"), "0.00 €"),
    ],
)
def test_balance_markup_colours(amount: Decimal, expected: str) -> None:
    text = expected.removeprefix("[green]").removeprefix("[red]").removesuffix("[/]")

    assert balance_markup(amount, text) == expected


# settle and pay


def test_settle_when_nothing_is_owed(db_path: Path) -> None:
    assert ok(db_path, "settle", "Flat").strip() == "Everyone is settled up."


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--from", "Bob", "--to", "bob", "--amount", "5"], "two different members"),
        (["--from", "Bob", "--to", "Dave", "--amount", "5"], "Member 'Dave' not found"),
        (["--from", "Bob", "--to", "Alice", "--amount", "0"], "greater than zero"),
        (["--from", "Bob", "--to", "Alice", "--amount", "x"], "not a valid number"),
    ],
)
def test_pay_errors_exit_with_code_1(
    db_path: Path, args: list[str], message: str
) -> None:
    result = run(db_path, "pay", "Flat", *args)

    assert result.exit_code == 1
    assert message in result.stderr


def test_pay_with_note_is_stored(db_path: Path) -> None:
    ok(db_path, "pay", "Flat", "--from", "Bob", "--to", "Alice", "--amount", "5",
       "--note", "cash")  # fmt: skip

    with service(db_path) as svc:
        payment = svc.get_ledger("Flat").payments[0]
    assert payment.note == "cash"
    assert payment.amount == Decimal("5.00")


def test_balance_and_settle_for_missing_group(db_path: Path) -> None:
    for command in ("balance", "settle"):
        result = run(db_path, command, "Nowhere")

        assert result.exit_code == 1
        assert "Group 'Nowhere' not found" in result.stderr


# Itemized expenses


KAUFLAND_ITEMS = [
    "--item", "Olive oil:6.00:Alice,Bob",
    "--item", "Protein bars:5.00:Alice",
    "--item", "Yogurt:4.00:Alice",
    "--item", "Coffee:5.00:Bob",
]  # fmt: skip


def test_expense_add_itemized_prints_breakdown(db_path: Path) -> None:
    output = ok(
        db_path, "expense", "add", "Flat", "Kaufland", "18", "-p", "Alice",
        *KAUFLAND_ITEMS, "--discount", "2",
    )  # fmt: skip

    rows = {
        cells[0]: cells[1:]
        for line in output.splitlines()
        if (cells := [c.strip() for c in line.strip().strip("|").split("|")])
        and len(cells) == 3
    }
    assert rows["Item"] == ["Alice", "Bob"]
    assert rows["Olive oil"] == ["3.00 €", "3.00 €"]
    assert rows["Protein bars"] == ["5.00 €", "-"]
    assert rows["Coffee"] == ["-", "5.00 €"]
    assert rows["Discount"] == ["-1.20 €", "-0.80 €"]
    assert rows["Total"] == ["10.80 €", "7.20 €"]
    assert output.replace("€", "").isascii()

    with service(db_path) as svc:
        expense = svc.list_expenses("Flat")[0]
    assert expense.split_method.value == "itemized"
    assert len(expense.items) == 4
    assert expense.adjustments[0].signed_amount == Decimal("-2")


def test_expense_add_itemized_with_quantity_and_deposit(db_path: Path) -> None:
    ok(
        db_path, "expense", "add", "Flat", "Rewe", "5.40", "-p", "Bob",
        "--item", "Water:0,49:Bob:6", "--item", "Deposit return:-0.25:Bob:6",
        "--item", "Bread:3.96:Alice,Bob,Carol",
    )  # fmt: skip

    with service(db_path) as svc:
        balances = svc.balances("Flat")
    assert balances == {
        "Alice": Decimal("-1.32"),
        "Bob": Decimal("2.64"),
        "Carol": Decimal("-1.32"),
    }


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (
            ["--item", "Oil:6.00:Alice"],
            "sum to 6.00 but the total is 30.00 (missing 24.00)",
        ),
        (["--item", "Oil"], "Invalid item 'Oil'"),
        (["--item", "Oil:30:Dave"], "Member 'Dave' not found"),
        (["--discount", "2"], "--discount can only be used together with --item"),
        (
            ["--item", "Oil:30:Alice", "--split", "exact"],
            "cannot be combined with --split",
        ),
        (
            ["--item", "Oil:30:Alice", "--among", "Bob"],
            "cannot be combined with --among",
        ),
        (["--item", "Oil:32:Alice", "--discount", "abc"], "is not a valid number"),
    ],
)
def test_expense_add_itemized_errors(
    db_path: Path, args: list[str], message: str
) -> None:
    result = run(
        db_path, "expense", "add", "Flat", "Dinner", "30", "-p", "Alice", *args
    )

    assert result.exit_code == 1
    assert message in result.stderr
    with service(db_path) as svc:
        assert svc.list_expenses("Flat") == []
