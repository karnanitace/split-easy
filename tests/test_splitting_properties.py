"""Property-based tests for the split strategies and compute_shares."""

from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from spliteasy.models import Expense, Group, Member, SplitMethod
from spliteasy.money import minor_unit, to_money
from spliteasy.splitting import compute_shares, get_strategy

NAMES = [
    "Alice",
    "Bob",
    "Carol",
    "Dave",
    "Eve",
    "Frank",
    "Grace",
    "Heidi",
    "Ivan",
    "Judy",
]
CENT = Decimal("0.01")
VALUE_METHODS = [SplitMethod.EXACT, SplitMethod.PERCENTAGE, SplitMethod.SHARES]
ALL_METHODS = [SplitMethod.EQUAL, *VALUE_METHODS]

cents = st.integers(min_value=1, max_value=10_000_000)
member_lists = st.lists(st.sampled_from(NAMES), min_size=1, max_size=10, unique=True)
exchange_rates = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal(200),
    places=6,
    allow_nan=False,
    allow_infinity=False,
)


def from_cents(amount: int) -> Decimal:
    """Converts an integer number of cents to a Decimal with two places."""
    return Decimal(amount).scaleb(-2)


def partition(draw: st.DrawFn, whole: int, parts: int) -> list[int]:
    """Splits ``whole`` into ``parts`` non-negative integers using cut points."""
    cuts = sorted(
        draw(
            st.lists(
                st.integers(min_value=0, max_value=whole),
                min_size=parts - 1,
                max_size=parts - 1,
            )
        )
    )
    bounds = [0, *cuts, whole]
    return [upper - lower for lower, upper in zip(bounds, bounds[1:], strict=False)]


@st.composite
def equal_flags(draw: st.DrawFn, members: list[str]) -> dict[str, Decimal]:
    """Draws an inclusion flag per member, with at least one member included."""
    flags = draw(st.lists(st.booleans(), min_size=len(members), max_size=len(members)))
    if not any(flags):
        flags[0] = True
    return {
        member: Decimal(int(flag)) for member, flag in zip(members, flags, strict=True)
    }


@st.composite
def share_weights(draw: st.DrawFn, members: list[str]) -> dict[str, Decimal]:
    """Draws a non-negative weight per member, with at least one above zero."""
    weights = draw(
        st.lists(
            st.one_of(
                st.integers(min_value=0, max_value=100).map(Decimal),
                st.decimals(
                    min_value=0,
                    max_value=100,
                    places=2,
                    allow_nan=False,
                    allow_infinity=False,
                ),
            ),
            min_size=len(members),
            max_size=len(members),
        )
    )
    if all(weight == 0 for weight in weights):
        weights[0] = Decimal(1)
    return dict(zip(members, weights, strict=True))


@st.composite
def percentages(draw: st.DrawFn, members: list[str]) -> dict[str, Decimal]:
    """Draws percentages that sum to exactly 100, from basis points."""
    basis_points = partition(draw, 10_000, len(members))
    return {
        member: Decimal(points).scaleb(-2)
        for member, points in zip(members, basis_points, strict=True)
    }


@st.composite
def exact_amounts(
    draw: st.DrawFn, members: list[str], total_cents: int
) -> dict[str, Decimal]:
    """Draws exact amounts that sum to the total, from random cut points."""
    parts = partition(draw, total_cents, len(members))
    return {
        member: from_cents(part) for member, part in zip(members, parts, strict=True)
    }


@st.composite
def split_cases(
    draw: st.DrawFn, methods: list[SplitMethod] = ALL_METHODS
) -> tuple[SplitMethod, Decimal, dict[str, Decimal]]:
    """Draws a split method, a total and matching values for a set of members."""
    method = draw(st.sampled_from(methods))
    members = draw(member_lists)
    total_cents = draw(cents)
    if method is SplitMethod.EQUAL:
        values = draw(equal_flags(members))
    elif method is SplitMethod.SHARES:
        values = draw(share_weights(members))
    elif method is SplitMethod.PERCENTAGE:
        values = draw(percentages(members))
    else:
        values = draw(exact_amounts(members, total_cents))
    return method, from_cents(total_cents), values


@given(split_cases())
def test_split_sums_exactly_to_total(
    case: tuple[SplitMethod, Decimal, dict[str, Decimal]],
) -> None:
    """Property 1: split() results sum exactly to the rounded total."""
    method, total, values = case

    result = get_strategy(method).split(total, values)

    assert sum(result.values()) == to_money(total)


@given(split_cases())
def test_split_is_within_one_cent_of_raw_amount(
    case: tuple[SplitMethod, Decimal, dict[str, Decimal]],
) -> None:
    """Property 2: every rounded amount is less than one cent from its raw amount."""
    method, total, values = case
    strategy = get_strategy(method)

    raw = strategy.raw_split(to_money(total), values)
    result = strategy.split(total, values)

    assert all(abs(result[member] - raw[member]) < CENT for member in values)


@given(split_cases())
def test_split_keeps_input_members_in_order(
    case: tuple[SplitMethod, Decimal, dict[str, Decimal]],
) -> None:
    """Property 4: the result keys are exactly the input members, in order."""
    method, total, values = case

    result = get_strategy(method).split(total, values)

    assert list(result) == list(values)


@given(cents, member_lists)
def test_equal_split_amounts_differ_by_at_most_one_cent(
    total_cents: int, members: list[str]
) -> None:
    """Property 5: for EQUAL, any two members' amounts differ by at most one cent."""
    values = dict.fromkeys(members, Decimal(1))

    amounts = get_strategy(SplitMethod.EQUAL).split(from_cents(total_cents), values)

    assert max(amounts.values()) - min(amounts.values()) <= CENT


@given(
    split_cases(),
    exchange_rates,
    st.sampled_from(["EUR", "JPY"]),
)
def test_compute_shares_sums_to_base_amount(
    case: tuple[SplitMethod, Decimal, dict[str, Decimal]],
    rate: Decimal,
    group_currency: str,
) -> None:
    """Property 3: compute_shares sums exactly to base_amount for any rate."""
    method, total, values = case
    group, expense = build_expense(method, total, values, rate, group_currency)

    shares = compute_shares(expense, group)

    assert sum(share.amount for share in shares) == expense.base_amount(group.currency)
    unit_exponent = minor_unit(group.currency).as_tuple().exponent
    assert all(share.amount.as_tuple().exponent == unit_exponent for share in shares)


@given(split_cases(), exchange_rates)
def test_compute_shares_keeps_input_members_in_order(
    case: tuple[SplitMethod, Decimal, dict[str, Decimal]], rate: Decimal
) -> None:
    """Property 4: compute_shares returns the input members, in order."""
    method, total, values = case
    group, expense = build_expense(method, total, values, rate, "EUR")

    shares = compute_shares(expense, group)

    expected = (
        [member for member, flag in values.items() if flag > 0]
        if method is SplitMethod.EQUAL
        else list(values)
    )
    assert [share.member for share in shares] == expected


def build_expense(
    method: SplitMethod,
    total: Decimal,
    values: dict[str, Decimal],
    rate: Decimal,
    group_currency: str,
) -> tuple[Group, Expense]:
    """Builds a group of all names and an expense in EUR for a split case.

    EQUAL flags become the participant list, because an expense stores
    participants rather than flags.
    """
    group = Group(
        name="Trip",
        currency=group_currency,
        members=[Member(name) for name in NAMES],
    )
    members = list(values)
    if method is SplitMethod.EQUAL:
        participants = [member for member, flag in values.items() if flag > 0]
        expense = Expense(
            description="Test",
            amount=total,
            payer=members[0],
            rate_to_base=rate,
            participants=participants,
        )
    else:
        expense = Expense(
            description="Test",
            amount=total,
            payer=members[0],
            rate_to_base=rate,
            split_method=method,
            split_values=values,
        )
    return group, expense
