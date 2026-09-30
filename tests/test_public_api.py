import importlib

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
