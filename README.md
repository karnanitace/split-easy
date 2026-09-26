# SplitEasy

[![CI](https://github.com/karnanitace/split-easy/actions/workflows/ci.yml/badge.svg)](https://github.com/karnanitace/split-easy/actions/workflows/ci.yml)

SplitEasy is a Python command-line tool and importable library for tracking
shared expenses in groups such as roommates or friends on a trip. It records
who paid for what and how each expense is split. It then works out every
member's balance and suggests the minimum number of payments needed to settle
up. Money is always handled as `Decimal`, so no cents are lost to rounding.

## Features

SplitEasy is under active development. Features are marked **(planned)** until
they are implemented.

- **(planned)** Groups and members, stored in a local SQLite database
- **(planned)** Five ways to split an expense: equal, exact amounts,
  percentages, shares (weights) and itemised
- **(planned)** Itemised grocery receipts imported from YAML files
- **(planned)** Multiple currencies, with the exchange rate frozen when an
  expense is entered
- **(planned)** Expense categories
- **(planned)** Running balances and a record of payments between members
- **(planned)** Settlement suggestions: a fast greedy algorithm and an optimal
  algorithm for small groups
- **(planned)** Reports: summaries, charts, and Markdown, PDF and CSV export
- **(planned)** A Python API for using SplitEasy as a library

## Installation

SplitEasy requires Python 3.10 or newer and uses
[uv](https://docs.astral.sh/uv/) to manage the environment.

```bash
git clone https://github.com/karnanitace/split-easy.git
cd split-easy
uv venv
uv pip install -e .
```

To also install the development tools (pytest, hypothesis and ruff):

```bash
uv pip install -e ".[dev]"
```

## Quick start

```bash
uv run -m spliteasy --help     # list the available commands
uv run -m spliteasy version    # print the installed version
```

After installation, the `spliteasy` command is also available inside the
virtual environment, so `uv run spliteasy version` works too.

## Usage

*Coming soon.* This section will describe the CLI commands for managing groups,
adding expenses, recording payments, settling up and exporting reports.

## Using SplitEasy as a Python library

*Coming soon.* This section will show how to use the `GroupService` API from
Python code.

## Architecture

SplitEasy has five layers, and each layer depends only on the layers below it:

1. **Foundation:** data models and `Decimal` money helpers
2. **Domain:** split strategies, balances, settlement, currencies and categories
3. **Persistence and reporting:** a repository interface with a SQLite
   implementation, plus summaries, charts and exports
4. **Application:** the `GroupService` facade used by both the CLI and library
   users
5. **Interface:** a thin CLI built with typer and rich, and the only layer that
   prints

See [docs/architecture.md](docs/architecture.md) for the full design, including
the data model, the database schema and the settlement algorithms.

## Running tests and linting

Install the development tools first (see [Installation](#installation)). Then:

```bash
uv run pytest                  # run the test suite
uv run ruff check .            # lint
uv run ruff format --check .   # check formatting
uv run ruff format .           # apply formatting
```

The same checks run on GitHub Actions for Python 3.10, 3.11 and 3.12 on every
push and pull request to `main`.

## License

SplitEasy is released under the [MIT License](LICENSE).
Copyright (c) 2026 Nitesh Karna.
