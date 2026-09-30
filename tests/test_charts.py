import subprocess
import sys
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest

from spliteasy.cli.app import ChartType, default_chart_path
from spliteasy.demo import ITALY_TRIP, create_demo_data
from spliteasy.exceptions import ValidationError
from spliteasy.models import Expense
from spliteasy.reports.charts import (
    plot_balances,
    plot_categories,
    plot_member_spending,
)
from spliteasy.services import GroupService
from spliteasy.storage import SQLiteRepository
from tests.conftest import invoke

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def assert_png(path: Path) -> None:
    assert path.is_file()
    assert path.stat().st_size > 1000
    assert path.read_bytes().startswith(PNG_SIGNATURE)


@pytest.fixture
def service() -> Iterator[GroupService]:
    group_service = GroupService(SQLiteRepository(":memory:"))
    create_demo_data(group_service)
    yield group_service
    group_service.close()


@pytest.fixture(autouse=True)
def no_open_figures() -> Iterator[None]:
    """Every chart function must close its figure."""
    yield
    import matplotlib.pyplot as plt

    assert plt.get_fignums() == []


# Chart functions


def test_plot_balances_creates_png(service: GroupService, tmp_path: Path) -> None:
    out = tmp_path / "balances.png"

    saved = plot_balances(service.balances(ITALY_TRIP), "EUR", out)

    assert saved == out
    assert_png(out)


def test_plot_categories_creates_png(service: GroupService, tmp_path: Path) -> None:
    expenses = service.get_ledger(ITALY_TRIP).expenses

    saved = plot_categories(expenses, "EUR", tmp_path / "categories.png")

    assert_png(saved)


def test_plot_member_spending_creates_png(
    service: GroupService, tmp_path: Path
) -> None:
    saved = plot_member_spending(
        service.summary(ITALY_TRIP), "EUR", tmp_path / "members.png"
    )

    assert_png(saved)


def test_charts_accept_string_paths_and_create_folders(
    service: GroupService, tmp_path: Path
) -> None:
    out = tmp_path / "nested" / "folder" / "chart.png"

    saved = plot_balances(service.balances("Flat"), "EUR", str(out))

    assert saved == out
    assert_png(out)


def test_balances_with_all_zero_values(tmp_path: Path) -> None:
    zero = Decimal("0.00")

    saved = plot_balances({"Alice": zero, "Bob": zero}, "EUR", tmp_path / "zero.png")

    assert_png(saved)


def test_charts_in_zero_decimal_currency(tmp_path: Path) -> None:
    summary = {
        "Aiko": {"paid": Decimal("12000"), "owed": Decimal("8000")},
        "Ben": {"paid": Decimal("4000"), "owed": Decimal("8000")},
    }

    assert_png(plot_member_spending(summary, "JPY", tmp_path / "jpy.png"))
    assert_png(
        plot_balances(
            {"Aiko": Decimal("4000"), "Ben": Decimal("-4000")},
            "JPY",
            tmp_path / "jpy-balances.png",
        )
    )


def test_categories_are_totalled_in_group_currency(tmp_path: Path) -> None:
    expenses = [
        Expense(description="Fondue", amount="100", payer="A", currency="CHF",
                rate_to_base="1.06", category="food"),
        Expense(description="Pizza", amount="20", payer="A", category="food"),
    ]  # fmt: skip

    assert_png(plot_categories(expenses, "EUR", tmp_path / "mixed.png"))


@pytest.mark.parametrize(
    ("draw", "data"),
    [
        (plot_balances, {}),
        (plot_categories, []),
        (plot_member_spending, {}),
    ],
)
def test_empty_data_raises_validation_error(
    draw: object, data: object, tmp_path: Path
) -> None:
    out = tmp_path / "empty.png"

    with pytest.raises(ValidationError, match="no .* to chart"):
        draw(data, "EUR", out)  # type: ignore[operator]

    assert not out.exists()


def test_matplotlib_is_not_imported_at_startup() -> None:
    code = (
        "import sys, spliteasy, spliteasy.cli.app, spliteasy.reports.charts; "
        "print('matplotlib' in sys.modules)"
    )

    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "False"


# CLI


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "charts.db"
    assert invoke(path, "demo", "--yes").exit_code == 0
    return path


@pytest.mark.parametrize("chart_type", ["balances", "categories", "members"])
def test_chart_command_writes_png(
    db_path: Path, tmp_path: Path, chart_type: str
) -> None:
    out = tmp_path / f"{chart_type}.png"

    result = invoke(
        db_path, "chart", "Italy Trip", "--type", chart_type, "--out", str(out)
    )

    assert result.exit_code == 0, result.output
    assert f"Saved chart to {out.resolve()}" in result.output
    assert_png(out)


def test_chart_command_default_file_name(
    db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    result = invoke(db_path, "chart", "italy trip", "-t", "categories")

    assert result.exit_code == 0, result.output
    assert_png(tmp_path / "italy-trip-categories.png")


def test_chart_command_defaults_to_balances(
    db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert invoke(db_path, "chart", "Flat").exit_code == 0
    assert_png(tmp_path / "flat-balances.png")


def test_chart_command_unknown_type_is_a_usage_error(db_path: Path) -> None:
    result = invoke(db_path, "chart", "Flat", "--type", "pie")

    assert result.exit_code == 2
    assert "'pie' is not one of" in result.output


def test_chart_command_missing_group_is_an_error(db_path: Path) -> None:
    result = invoke(db_path, "chart", "Nowhere")

    assert result.exit_code == 1
    assert "Group 'Nowhere' not found" in result.stderr


def test_chart_command_group_without_expenses_is_an_error(
    db_path: Path, tmp_path: Path
) -> None:
    invoke(db_path, "group", "create", "Empty", "-m", "Alice")

    result = invoke(
        db_path, "chart", "Empty", "-t", "categories", "-o", str(tmp_path / "x.png")
    )

    assert result.exit_code == 1
    assert "There are no expenses to chart" in result.stderr


@pytest.mark.parametrize(
    ("group", "chart_type", "expected"),
    [
        ("Italy Trip", ChartType.BALANCES, "italy-trip-balances.png"),
        ("Flat", ChartType.MEMBERS, "flat-members.png"),
        ("  Zoë's Flat #2 ", ChartType.CATEGORIES, "zoe-s-flat-2-categories.png"),
        ("!!!", ChartType.BALANCES, "group-balances.png"),
    ],
)
def test_default_chart_path(group: str, chart_type: ChartType, expected: str) -> None:
    assert default_chart_path(group, chart_type) == Path(expected)
