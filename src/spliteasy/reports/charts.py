"""PNG charts of balances and spending.

matplotlib takes a noticeable time to import, so it is imported inside the
functions only: the CLI starts quickly, and the rest of the library can be
used without loading it. The non-interactive ``Agg`` backend is selected so
charts render without a display (on servers and in CI), and every figure is
closed after saving so repeated calls do not leak memory.

Amounts stay ``Decimal`` everywhere except at the moment they are handed to
matplotlib, which only draws floats. Every label is formatted from the
original ``Decimal`` with :func:`~spliteasy.money.format_money`, so the
numbers printed on a chart are exact.

The colours follow one visual style for all charts: a light surface,
recessive grid lines, text in neutral ink rather than series colours, and
thin bars with a small gap between neighbours.
"""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from spliteasy.exceptions import ValidationError
from spliteasy.models import Expense
from spliteasy.money import format_money

if TYPE_CHECKING:
    from matplotlib.axes import Axes

SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3df"
BLUE = "#2a78d6"
ORANGE = "#eb6834"
POSITIVE = "#008300"
NEGATIVE = "#e34948"

_DPI = 150
_BAR_HEIGHT = 0.6
_ROW_HEIGHT_INCHES = 0.45


def plot_balances(
    balances: Mapping[str, Decimal], currency: str, out: Path | str
) -> Path:
    """Draws each member's net balance as a horizontal bar.

    Members who are owed money get a green bar to the right of the zero line,
    members who owe money a red bar to the left. Every bar is labelled with
    its signed amount, so the chart does not rely on colour alone.

    Args:
        balances: The net balance of each member, in display order.
        currency: The ISO 4217 code of the balances.
        out: The PNG file to write. Missing parent folders are created.

    Returns:
        The path of the saved PNG.

    Raises:
        ValidationError: If there are no balances to draw.
    """
    if not balances:
        raise ValidationError("There are no members to chart")
    members = list(balances)
    amounts = list(balances.values())

    with _figure(len(members)) as (fig, ax):
        positions = range(len(members))
        colors = [POSITIVE if amount >= 0 else NEGATIVE for amount in amounts]
        ax.barh(positions, _floats(amounts), height=_BAR_HEIGHT, color=colors)
        ax.axvline(0, color=TEXT_SECONDARY, linewidth=1)
        _label_bars(ax, amounts, currency, signed=True)
        _style_horizontal(ax, members, f"Balances ({currency})")
        _pad_both_sides(ax, amounts)
        ax.text(
            0.0,
            -0.12,
            "Positive: is owed money.  Negative: owes money.",
            transform=ax.transAxes,
            color=TEXT_SECONDARY,
            fontsize=8,
        )
        return _save(fig, out)


def plot_categories(
    expenses: Sequence[Expense], currency: str, out: Path | str
) -> Path:
    """Draws total spending per category, largest first.

    Amounts are converted to ``currency`` with each expense's frozen
    exchange rate.

    Args:
        expenses: The expenses to total.
        currency: The group currency that totals are shown in.
        out: The PNG file to write. Missing parent folders are created.

    Returns:
        The path of the saved PNG.

    Raises:
        ValidationError: If there are no expenses to draw.
    """
    if not expenses:
        raise ValidationError("There are no expenses to chart")
    totals: dict[str, Decimal] = {}
    for expense in expenses:
        amount = expense.base_amount(currency)
        totals[expense.category] = totals.get(expense.category, Decimal(0)) + amount
    ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    categories = [category.capitalize() for category, _ in ranked]
    amounts = [amount for _, amount in ranked]

    with _figure(len(categories)) as (fig, ax):
        ax.barh(
            range(len(categories)), _floats(amounts), height=_BAR_HEIGHT, color=BLUE
        )
        _label_bars(ax, amounts, currency, signed=False)
        _style_horizontal(ax, categories, f"Spending by category ({currency})")
        _pad_both_sides(ax, amounts)
        return _save(fig, out)


def plot_member_spending(
    summary: Mapping[str, Mapping[str, Decimal]], currency: str, out: Path | str
) -> Path:
    """Draws what each member paid next to what they owe.

    Args:
        summary: Per-member totals with at least the keys ``"paid"`` and
            ``"owed"``, as returned by
            :func:`~spliteasy.balances.member_summary`.
        currency: The ISO 4217 code of the totals.
        out: The PNG file to write. Missing parent folders are created.

    Returns:
        The path of the saved PNG.

    Raises:
        ValidationError: If there are no members to draw.
    """
    if not summary:
        raise ValidationError("There are no members to chart")
    members = list(summary)
    paid = [summary[member]["paid"] for member in members]
    owed = [summary[member]["owed"] for member in members]

    width = 0.36
    gap = 0.03
    with _figure(len(members), vertical=True) as (fig, ax):
        positions = list(range(len(members)))
        paid_bars = ax.bar(
            [p - (width + gap) / 2 for p in positions],
            _floats(paid),
            width=width,
            color=BLUE,
            label="Paid",
        )
        owed_bars = ax.bar(
            [p + (width + gap) / 2 for p in positions],
            _floats(owed),
            width=width,
            color=ORANGE,
            label="Owed",
        )
        for bars, values in ((paid_bars, paid), (owed_bars, owed)):
            ax.bar_label(
                bars,
                labels=[format_money(value, currency) for value in values],
                padding=3,
                fontsize=7,
                color=TEXT_SECONDARY,
            )
        ax.set_xticks(positions, members)
        ax.set_title(
            f"Paid vs owed per member ({currency})",
            loc="left",
            color=TEXT_PRIMARY,
            fontsize=11,
        )
        ax.yaxis.grid(True, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        ax.margins(y=0.15)
        # Above the plot, level with the title, so it never covers a bar.
        ax.legend(
            frameon=False,
            loc="lower right",
            bbox_to_anchor=(1.0, 1.0),
            ncol=2,
            labelcolor=TEXT_PRIMARY,
            fontsize=9,
        )
        _style_axes(ax)
        ax.tick_params(axis="y", labelleft=False, length=0)
        return _save(fig, out)


@contextmanager
def _figure(rows: int, *, vertical: bool = False) -> Iterator[tuple[Any, "Axes"]]:
    """Creates a styled figure sized for its content and always closes it.

    Args:
        rows: The number of bars or bar groups.
        vertical: Whether the bars are vertical (sizes the width instead of
            the height).

    Yields:
        The figure and its single axes.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if vertical:
        size = (max(6.0, 1.3 * rows + 2), 4.5)
    else:
        size = (8.0, max(2.5, _ROW_HEIGHT_INCHES * rows + 1.5))
    fig, ax = plt.subplots(figsize=size, facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    try:
        yield fig, ax
    finally:
        plt.close(fig)


def _floats(amounts: Sequence[Decimal]) -> list[float]:
    """Converts amounts to floats for drawing only."""
    return [float(amount) for amount in amounts]


def _label_bars(
    ax: "Axes", amounts: Sequence[Decimal], currency: str, *, signed: bool
) -> None:
    """Writes the formatted amount at the end of each horizontal bar."""
    for position, amount in enumerate(amounts):
        text = format_money(amount, currency)
        if signed and amount > 0:
            text = f"+{text}"
        ax.annotate(
            text,
            xy=(float(amount), position),
            xytext=(4 if amount >= 0 else -4, 0),
            textcoords="offset points",
            ha="left" if amount >= 0 else "right",
            va="center",
            fontsize=8,
            color=TEXT_PRIMARY,
        )


def _style_horizontal(ax: "Axes", labels: Sequence[str], title: str) -> None:
    """Applies the shared style to a horizontal bar chart."""
    ax.set_yticks(range(len(labels)), labels)
    ax.invert_yaxis()
    ax.set_title(title, loc="left", color=TEXT_PRIMARY, fontsize=11)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    _style_axes(ax)
    ax.tick_params(axis="x", labelbottom=False, length=0)


def _style_axes(ax: "Axes") -> None:
    """Hides the chart frame and makes tick labels recessive."""
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(colors=TEXT_SECONDARY, length=0, labelsize=9)


def _pad_both_sides(ax: "Axes", amounts: Sequence[Decimal]) -> None:
    """Widens the x-range so that value labels fit beside the bars."""
    values = _floats(amounts)
    low, high = min(min(values), 0.0), max(max(values), 0.0)
    span = (high - low) or 1.0
    left = low - 0.25 * span if low < 0 else 0.0
    ax.set_xlim(left, high + 0.25 * span if high > 0 else 0.25 * span)


def _save(fig: Any, out: Path | str) -> Path:
    """Saves a figure as PNG, creating parent folders, and returns the path."""
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, format="png", dpi=_DPI, bbox_inches="tight", facecolor=SURFACE)
    return path
