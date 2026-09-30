from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from spliteasy.cli.app import app
from spliteasy.demo import DEMO_GROUPS, ITALY_TRIP, create_demo_data
from spliteasy.models import SplitMethod
from spliteasy.services import GroupService
from spliteasy.storage import SQLiteRepository

runner = CliRunner()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "demo.db"


@pytest.fixture
def service(db_path: Path) -> Iterator[GroupService]:
    group_service = GroupService(SQLiteRepository(db_path))
    yield group_service
    group_service.close()


def test_demo_creates_both_groups_with_zero_sum_balances(
    service: GroupService,
) -> None:
    names = create_demo_data(service)

    assert names == ["Flat", "Italy Trip"]
    assert service.list_groups() == ["Flat", "Italy Trip"]
    for name in names:
        balances = service.balances(name)
        assert sum(balances.values()) == 0
        assert any(balance != 0 for balance in balances.values())


def test_flat_group_contents(service: GroupService) -> None:
    create_demo_data(service)

    ledger = service.get_ledger("Flat")

    assert ledger.group.member_names == ["John", "Steve"]
    assert ledger.group.currency == "EUR"
    assert len(ledger.payments) == 1
    rent = next(e for e in ledger.expenses if e.category == "rent")
    assert rent.split_method is SplitMethod.EXACT
    assert sum(1 for e in ledger.expenses if e.category == "groceries") >= 2


def test_italy_trip_contents(service: GroupService) -> None:
    create_demo_data(service)

    ledger = service.get_ledger(ITALY_TRIP)
    expenses = ledger.expenses

    assert ledger.group.member_names == ["John", "Steve", "Clark", "Dan"]
    assert len(expenses) == 12
    assert {e.split_method for e in expenses} == {
        SplitMethod.EQUAL,
        SplitMethod.EXACT,
        SplitMethod.PERCENTAGE,
        SplitMethod.SHARES,
    }
    assert {e.category for e in expenses} == {
        "food",
        "transport",
        "accommodation",
        "entertainment",
    }
    chf = [e for e in expenses if e.currency == "CHF"]
    assert len(chf) >= 2
    assert all(e.rate_to_base != 1 for e in chf)


def test_demo_replaces_existing_groups(service: GroupService) -> None:
    create_demo_data(service)
    service.add_expense("Flat", "Extra", "10", "John")
    service.create_group("Other")

    create_demo_data(service)

    assert service.list_groups() == ["Flat", "Italy Trip", "Other"]
    assert "Extra" not in [e.description for e in service.list_expenses("Flat")]


def test_demo_gives_the_same_balances_every_time(service: GroupService) -> None:
    create_demo_data(service)
    first = service.balances(ITALY_TRIP)

    create_demo_data(service)

    assert service.balances(ITALY_TRIP) == first


# CLI


def test_demo_command_prints_balances_settlement_and_hints(db_path: Path) -> None:
    result = runner.invoke(app, ["--db", str(db_path), "demo"])

    assert result.exit_code == 0, result.output
    assert "Created demo groups: Flat, Italy Trip" in result.output
    assert "Balances" in result.output
    assert "Suggested settlement for Italy Trip:" in result.output
    assert " -> " in result.output
    assert "Try next:" in result.output
    assert "spliteasy group list" in result.output


def test_demo_command_settlement_matches_service(db_path: Path) -> None:
    result = runner.invoke(app, ["--db", str(db_path), "demo"])

    with GroupService(SQLiteRepository(db_path)) as service:
        transfers = service.suggest_settlement(ITALY_TRIP)
        balances = service.balances(ITALY_TRIP)
    assert transfers
    for transfer in transfers:
        assert f"{transfer.debtor} -> {transfer.creditor}:" in result.output
    assert sum(balances.values()) == Decimal(0)


def test_demo_command_asks_before_replacing(db_path: Path) -> None:
    runner.invoke(app, ["--db", str(db_path), "demo"])

    declined = runner.invoke(app, ["--db", str(db_path), "demo"], input="n\n")
    accepted = runner.invoke(app, ["--db", str(db_path), "demo"], input="y\n")
    forced = runner.invoke(app, ["--db", str(db_path), "demo", "--yes"])

    assert declined.exit_code == 1
    assert "Replace the existing groups Flat, Italy Trip" in declined.output
    assert accepted.exit_code == 0
    assert forced.exit_code == 0
    assert "Replace" not in forced.output


def test_demo_command_does_not_ask_when_groups_are_new(db_path: Path) -> None:
    with GroupService(SQLiteRepository(db_path)) as service:
        service.create_group("Unrelated")

    result = runner.invoke(app, ["--db", str(db_path), "demo"])

    assert result.exit_code == 0
    assert "Replace" not in result.output


def test_demo_group_names_constant() -> None:
    assert DEMO_GROUPS == ("Flat", "Italy Trip")
