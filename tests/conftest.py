"""Shared test helpers.

:func:`invoke` runs the ``spliteasy`` CLI in-process and returns its output
as plain text. Typer and rich add ANSI colour codes in some environments (for
example on GitHub Actions, where Typer forces coloured output), which would
split words such as ``--paid-by`` apart and break ``in`` assertions. The
helper strips all styling and uses a wide terminal so that long lines are
not wrapped, so tests behave the same locally and in CI.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest
from rich.text import Text
from typer.testing import CliRunner, Result

WIDE_TERMINAL = {"COLUMNS": "200"}

_runner = CliRunner()


def pytest_configure(config: pytest.Config) -> None:
    """Makes the whole test session use a wide terminal.

    Rich reads ``COLUMNS`` once, when a console is created, and the CLI
    modules create their consoles when they are first imported. Setting it
    here, before any test module is imported, keeps output unwrapped even if
    the surrounding terminal is narrow.
    """
    os.environ.update(WIDE_TERMINAL)


def unstyle(text: str) -> str:
    """Removes ANSI escape codes (colours, bold, ...) from text."""
    return Text.from_ansi(text).plain


@dataclass(frozen=True)
class CliResult:
    """The outcome of a CLI invocation, with all output as plain text.

    Attributes:
        exit_code: The command's exit code.
        output: Everything written to stdout and stderr, without styling.
        stdout: Everything written to stdout, without styling.
        stderr: Everything written to stderr, without styling.
        result: The original Typer result, for anything not covered above.
    """

    exit_code: int
    output: str
    stdout: str
    stderr: str
    result: Result


def invoke(
    db_path: Path | None,
    *args: str,
    input: str | None = None,
    env: Mapping[str, str] | None = None,
) -> CliResult:
    """Runs the CLI and returns its unstyled output.

    Args:
        db_path: The database passed with ``--db``, or ``None`` to pass no
            ``--db`` option.
        *args: The command-line arguments after ``--db``.
        input: Text fed to the command's standard input, for prompts.
        env: Extra environment variables for the command.

    Returns:
        The exit code and the plain-text output.
    """
    # Imported here rather than at the top so that the CLI's consoles are
    # created only after pytest_configure has set the terminal width.
    from spliteasy.cli.app import app

    db_args = ["--db", str(db_path)] if db_path is not None else []
    result = _runner.invoke(
        app,
        [*db_args, *args],
        input=input,
        env={**WIDE_TERMINAL, **(env or {})},
    )
    return CliResult(
        exit_code=result.exit_code,
        output=unstyle(result.output),
        stdout=unstyle(result.stdout),
        stderr=unstyle(result.stderr),
        result=result,
    )
