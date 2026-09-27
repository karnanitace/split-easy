import pytest

from spliteasy.exceptions import (
    AllocationError,
    CurrencyError,
    DuplicateError,
    ExpenseNotFoundError,
    GroupNotFoundError,
    InvalidAmountError,
    MemberNotFoundError,
    MoneyError,
    NotFoundError,
    SettlementError,
    SplitEasyError,
    SplitError,
    StorageError,
)

ALL_EXCEPTIONS = [
    MoneyError,
    InvalidAmountError,
    AllocationError,
    CurrencyError,
    SplitError,
    NotFoundError,
    GroupNotFoundError,
    MemberNotFoundError,
    ExpenseNotFoundError,
    DuplicateError,
    SettlementError,
    StorageError,
]


@pytest.mark.parametrize("exc_type", ALL_EXCEPTIONS)
def test_every_exception_is_a_spliteasy_error(exc_type: type[Exception]) -> None:
    assert issubclass(exc_type, SplitEasyError)


@pytest.mark.parametrize(
    "exc_type",
    [
        MoneyError,
        InvalidAmountError,
        AllocationError,
        CurrencyError,
        SplitError,
        DuplicateError,
    ],
)
def test_value_errors_are_catchable_as_value_error(
    exc_type: type[Exception],
) -> None:
    with pytest.raises(ValueError):
        raise exc_type("bad value")


@pytest.mark.parametrize("exc_type", [InvalidAmountError, AllocationError])
def test_money_errors_are_catchable_as_money_error(exc_type: type[Exception]) -> None:
    with pytest.raises(MoneyError):
        raise exc_type("bad amount")


@pytest.mark.parametrize(
    "exc_type", [GroupNotFoundError, MemberNotFoundError, ExpenseNotFoundError]
)
def test_not_found_errors_are_catchable_as_lookup_error(
    exc_type: type[NotFoundError],
) -> None:
    with pytest.raises(LookupError):
        raise exc_type("missing")
    with pytest.raises(NotFoundError):
        raise exc_type("missing")


@pytest.mark.parametrize("exc_type", [SettlementError, StorageError])
def test_non_value_errors_are_not_value_errors(exc_type: type[Exception]) -> None:
    assert not issubclass(exc_type, ValueError)


def test_not_found_error_stores_entity_identifier_and_message() -> None:
    error = NotFoundError("Group", "Italy Trip")

    assert error.entity == "Group"
    assert error.identifier == "Italy Trip"
    assert str(error) == "Group 'Italy Trip' not found"


@pytest.mark.parametrize(
    ("exc_type", "identifier", "entity", "message"),
    [
        (GroupNotFoundError, "Italy Trip", "Group", "Group 'Italy Trip' not found"),
        (MemberNotFoundError, "Alice", "Member", "Member 'Alice' not found"),
        (ExpenseNotFoundError, 42, "Expense", "Expense 42 not found"),
    ],
)
def test_not_found_subclasses_set_entity_automatically(
    exc_type: type[NotFoundError],
    identifier: object,
    entity: str,
    message: str,
) -> None:
    error = exc_type(identifier)

    assert error.entity == entity
    assert error.identifier == identifier
    assert str(error) == message
