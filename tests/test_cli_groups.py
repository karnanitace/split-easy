from pathlib import Path

import pytest

from spliteasy.services import GroupService
from spliteasy.storage import SQLiteRepository
from spliteasy.storage.sqlite import DB_ENV_VAR
from tests.conftest import invoke


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "cli.db"


def create_flat(db_path: Path) -> None:
    result = invoke(db_path, "group", "create", "Flat", "-m", "Alice", "-m", "Bob")
    assert result.exit_code == 0, result.output


def stored_groups(db_path: Path) -> list[str]:
    with GroupService(SQLiteRepository(db_path)) as service:
        return service.list_groups()


def stored_members(db_path: Path, group: str) -> list[str]:
    with GroupService(SQLiteRepository(db_path)) as service:
        return service.get_ledger(group).group.member_names


# group create


def test_group_create(db_path: Path) -> None:
    result = invoke(
        db_path,
        "group",
        "create",
        "Italy Trip",
        "--currency",
        "chf",
        "--member",
        "Alice",
    )

    assert result.exit_code == 0
    assert "Created group Italy Trip (CHF) with members: Alice" in result.output
    assert stored_groups(db_path) == ["Italy Trip"]


def test_group_create_without_members(db_path: Path) -> None:
    result = invoke(db_path, "group", "create", "Flat")

    assert result.exit_code == 0
    assert "(EUR) with members: -" in result.output


def test_group_create_duplicate_is_an_error(db_path: Path) -> None:
    create_flat(db_path)

    result = invoke(db_path, "group", "create", "FLAT")

    assert result.exit_code == 1
    assert "Error: A group named 'FLAT' already exists" in result.stderr
    assert "Traceback" not in result.output


def test_group_create_invalid_currency_is_an_error(db_path: Path) -> None:
    result = invoke(db_path, "group", "create", "Flat", "--currency", "EURO")

    assert result.exit_code == 1
    assert "Invalid currency code 'EURO'" in result.stderr
    assert stored_groups(db_path) == []


# group list


def test_group_list(db_path: Path) -> None:
    create_flat(db_path)
    invoke(db_path, "group", "create", "Trip", "--currency", "JPY")

    result = invoke(db_path, "group", "list")

    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert any(
        "Flat" in line and "EUR" in line and "Alice, Bob" in line for line in lines
    )
    assert any("Trip" in line and "JPY" in line for line in lines)


def test_group_list_counts_expenses(db_path: Path) -> None:
    create_flat(db_path)
    with GroupService(SQLiteRepository(db_path)) as service:
        service.add_expense("Flat", "Pizza", "20", "Alice")
        service.add_expense("Flat", "Taxi", "10", "Bob")

    result = invoke(db_path, "group", "list")

    flat_line = next(line for line in result.output.splitlines() if "Flat" in line)
    assert flat_line.rstrip(" |").endswith("2")


def test_group_list_when_empty(db_path: Path) -> None:
    result = invoke(db_path, "group", "list")

    assert result.exit_code == 0
    assert "No groups yet" in result.output


def test_output_uses_only_ascii(db_path: Path) -> None:
    create_flat(db_path)

    result = invoke(db_path, "group", "list")

    assert result.output.isascii()


# group show


def test_group_show(db_path: Path) -> None:
    create_flat(db_path)
    with GroupService(SQLiteRepository(db_path)) as service:
        service.add_expense("Flat", "Rent", "1000", "Alice")
        service.add_expense("Flat", "Fondue", "96", "Bob", currency="CHF", rate="1.06")

    result = invoke(db_path, "group", "show", "flat")

    assert result.exit_code == 0
    assert "Flat (EUR)" in result.output
    assert "Members:     Alice, Bob" in result.output
    assert "Expenses:    2" in result.output
    assert "Total spent: 1,101.76 €" in result.output


def test_group_show_missing_group_is_an_error(db_path: Path) -> None:
    result = invoke(db_path, "group", "show", "Nowhere")

    assert result.exit_code == 1
    assert "Error: Group 'Nowhere' not found" in result.stderr


# group delete


def test_group_delete_with_yes(db_path: Path) -> None:
    create_flat(db_path)

    result = invoke(db_path, "group", "delete", "flat", "--yes")

    assert result.exit_code == 0
    assert "Deleted group Flat." in result.output
    assert stored_groups(db_path) == []


def test_group_delete_asks_for_confirmation(db_path: Path) -> None:
    create_flat(db_path)

    result = invoke(db_path, "group", "delete", "Flat", input="y\n")

    assert result.exit_code == 0
    assert "Delete group 'Flat' with all of its expenses and payments?" in result.output
    assert stored_groups(db_path) == []


def test_group_delete_declined_keeps_group(db_path: Path) -> None:
    create_flat(db_path)

    result = invoke(db_path, "group", "delete", "Flat", input="n\n")

    assert result.exit_code == 1
    assert stored_groups(db_path) == ["Flat"]


def test_group_delete_missing_group_is_an_error(db_path: Path) -> None:
    result = invoke(db_path, "group", "delete", "Nowhere", "--yes")

    assert result.exit_code == 1
    assert "Group 'Nowhere' not found" in result.stderr


# member add / remove


def test_member_add(db_path: Path) -> None:
    create_flat(db_path)

    result = invoke(db_path, "member", "add", "flat", "Carol", "Dave")

    assert result.exit_code == 0
    assert "Added Carol, Dave to Flat." in result.output
    assert stored_members(db_path, "Flat") == ["Alice", "Bob", "Carol", "Dave"]


def test_member_add_duplicate_is_an_error(db_path: Path) -> None:
    create_flat(db_path)

    result = invoke(db_path, "member", "add", "Flat", "Carol", "alice")

    assert result.exit_code == 1
    assert "'Alice' already exists" in result.stderr
    assert stored_members(db_path, "Flat") == ["Alice", "Bob"]


def test_member_remove(db_path: Path) -> None:
    create_flat(db_path)

    result = invoke(db_path, "member", "remove", "flat", "BOB")

    assert result.exit_code == 0
    assert "Removed Bob from Flat." in result.output
    assert stored_members(db_path, "Flat") == ["Alice"]


def test_member_remove_with_balance_is_an_error(db_path: Path) -> None:
    create_flat(db_path)
    with GroupService(SQLiteRepository(db_path)) as service:
        service.add_expense("Flat", "Pizza", "20", "Alice")

    result = invoke(db_path, "member", "remove", "Flat", "Bob")

    assert result.exit_code == 1
    assert "Cannot remove 'Bob'" in result.stderr


def test_member_remove_unknown_member_is_an_error(db_path: Path) -> None:
    create_flat(db_path)

    result = invoke(db_path, "member", "remove", "Flat", "Zed")

    assert result.exit_code == 1
    assert "Member 'Zed' not found" in result.stderr


# Global options


def test_db_can_come_from_environment_variable(db_path: Path) -> None:
    result = invoke(None, "group", "create", "Flat", env={DB_ENV_VAR: str(db_path)})

    assert result.exit_code == 0
    assert stored_groups(db_path) == ["Flat"]


def test_version_does_not_create_a_database(tmp_path: Path) -> None:
    db_path = tmp_path / "never.db"

    result = invoke(db_path, "version")

    assert result.exit_code == 0
    assert not db_path.exists()


def test_database_file_is_released_after_command(db_path: Path) -> None:
    create_flat(db_path)

    db_path.unlink()

    assert not db_path.exists()
