"""Typer application that defines the ``spliteasy`` command and its subcommands."""

import typer
from rich.console import Console

from spliteasy import __version__

app = typer.Typer(
    name="spliteasy",
    help=(
        "SplitEasy: track shared expenses in groups and settle up with the "
        "minimum number of payments."
    ),
    no_args_is_help=True,
)

console = Console()


@app.callback()
def main() -> None:
    """Track shared expenses in groups and settle up with minimal payments."""


@app.command()
def version() -> None:
    """Show the installed SplitEasy version."""
    console.print(f"SplitEasy {__version__}")
