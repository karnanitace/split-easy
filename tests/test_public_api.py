import importlib
import subprocess
import sys

import pytest

import spliteasy


@pytest.mark.parametrize("name", spliteasy.__all__)
def test_every_public_name_is_importable(name: str) -> None:
    module = importlib.import_module("spliteasy")

    assert getattr(module, name) is not None


def test_key_names_are_public() -> None:
    from spliteasy import Expense, Group, allocate

    assert {"Group", "Expense", "allocate"} <= set(spliteasy.__all__)
    assert callable(allocate)
    assert Group.__module__ == "spliteasy.models"
    assert Expense.__module__ == "spliteasy.models"


@pytest.mark.parametrize(
    ("name", "module"),
    [
        ("GroupService", "spliteasy.services"),
        ("Ledger", "spliteasy.models"),
        ("ItemizedSplit", "spliteasy.splitting"),
        ("compute_balances", "spliteasy.balances"),
        ("member_summary", "spliteasy.balances"),
        ("settle_greedy", "spliteasy.settlement"),
        ("apply_transfers", "spliteasy.settlement"),
        ("Repository", "spliteasy.storage.base"),
        ("SQLiteRepository", "spliteasy.storage.sqlite"),
        ("plot_balances", "spliteasy.reports.charts"),
        ("plot_categories", "spliteasy.reports.charts"),
        ("plot_member_spending", "spliteasy.reports.charts"),
        ("ValidationError", "spliteasy.exceptions"),
    ],
)
def test_public_names_come_from_their_modules(name: str, module: str) -> None:
    assert name in spliteasy.__all__
    assert getattr(spliteasy, name).__module__ == module


def test_importing_the_package_does_not_import_matplotlib() -> None:
    code = "import sys, spliteasy; print('matplotlib' in sys.modules)"

    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "False"


def test_library_workflow_through_public_api() -> None:
    from spliteasy import GroupService, SQLiteRepository, format_money

    with GroupService(SQLiteRepository(":memory:")) as service:
        service.create_group("Flat", members=["Alice", "Bob"])
        service.add_expense("Flat", "Groceries", "20.00", "Alice")
        [transfer] = service.suggest_settlement("Flat")

    assert str(transfer) == "Bob -> Alice: 10.00"
    assert format_money(transfer.amount) == "10.00 €"


def test_all_has_no_duplicates() -> None:
    assert len(spliteasy.__all__) == len(set(spliteasy.__all__))


@pytest.mark.parametrize(
    "name", ["normalize_name", "distribute_remainder", "normalize_currency"]
)
def test_internal_helpers_are_not_public(name: str) -> None:
    assert name not in spliteasy.__all__


def test_star_import_exposes_exactly_all() -> None:
    namespace: dict[str, object] = {}

    exec("from spliteasy import *", namespace)

    assert set(namespace) - {"__builtins__"} == set(spliteasy.__all__)


def test_version_is_available_but_not_in_all() -> None:
    assert spliteasy.__version__ == "0.1.0"
    assert "__version__" not in spliteasy.__all__
