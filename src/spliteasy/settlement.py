"""Suggest transfers that settle a group's balances.

**The problem.** After expenses and payments, every member of a group has a
net balance (see :mod:`spliteasy.balances`): positive if the member is owed
money, negative if they owe money, with all balances summing to zero.
Settling up means finding transfers from debtors to creditors that bring every
balance to zero, ideally with as few transfers as possible.

**The greedy approach.** :func:`settle_greedy` keeps the creditors and the
debtors in two heaps, ordered by the size of their balance. It repeatedly
matches the largest creditor with the largest debtor, suggests a transfer of
the smaller of the two amounts, and puts whichever of them still has a
non-zero balance back into its heap. Ties are broken by member name, so the
same balances always give the same transfers.

**At most n - 1 transfers.** Every transfer brings at least one member to
zero, and the last transfer brings two members to zero. With ``n`` members
whose balance is not zero, greedy therefore needs at most ``n - 1``
transfers, in ``O(n log n)`` time.

**The true minimum is NP-hard.** Greedy is not always optimal. For balances
``A +6, B +4, C -4, D -3, E -3`` it needs four transfers, while three are
enough (``C -> B 4``, ``D -> A 3``, ``E -> A 3``). Fewer than ``n - 1``
transfers are possible exactly when some proper subset of the balances sums to
zero, and deciding that is a form of the NP-complete Subset Sum problem. An
optimal algorithm for small groups (dynamic programming over zero-sum
subsets of members) is planned as future work.
"""

import heapq
from collections.abc import Iterable, Mapping
from decimal import Decimal

from spliteasy.exceptions import SettlementError
from spliteasy.models import Transfer


def settle_greedy(balances: Mapping[str, Decimal]) -> list[Transfer]:
    """Suggests transfers that settle all balances, using the greedy method.

    Members with a zero balance are ignored. The largest creditor is matched
    with the largest debtor until everyone is settled; ties are broken by
    member name in alphabetical order, so the result is deterministic.

    Args:
        balances: The net balance of each member, as money amounts that sum
            to zero. Positive means the member is owed money.

    Returns:
        The suggested transfers, in the order they were found. The list is
        empty if every balance is already zero. There are at most ``n - 1``
        transfers for ``n`` members with a non-zero balance.

    Raises:
        SettlementError: If the balances do not sum to zero.

    Examples:
        >>> transfers = settle_greedy(
        ...     {"Alice": Decimal("8.00"), "Bob": Decimal("-8.00")}
        ... )
        >>> [str(transfer) for transfer in transfers]
        ['Bob -> Alice: 8.00']
    """
    _check_sum_is_zero(balances)

    # heapq is a min-heap, so amounts are negated to pop the largest first;
    # the name breaks ties alphabetically.
    creditors = [(-amount, name) for name, amount in balances.items() if amount > 0]
    debtors = [(amount, name) for name, amount in balances.items() if amount < 0]
    heapq.heapify(creditors)
    heapq.heapify(debtors)

    transfers: list[Transfer] = []
    while creditors and debtors:
        negated_credit, creditor = heapq.heappop(creditors)
        negative_debt, debtor = heapq.heappop(debtors)
        credit, debt = -negated_credit, -negative_debt
        amount = min(credit, debt)
        transfers.append(Transfer(debtor, creditor, amount))
        if credit > amount:
            heapq.heappush(creditors, (-(credit - amount), creditor))
        if debt > amount:
            heapq.heappush(debtors, (-(debt - amount), debtor))
    return transfers


def apply_transfers(
    balances: Mapping[str, Decimal], transfers: Iterable[Transfer]
) -> dict[str, Decimal]:
    """Returns the balances after the given transfers have been paid.

    Paying a transfer increases the debtor's balance and decreases the
    creditor's balance by its amount. Names are matched ignoring case.

    Args:
        balances: The net balance of each member.
        transfers: The transfers to apply.

    Returns:
        A new dict with the updated balance of each member, in the order of
        ``balances``.

    Raises:
        SettlementError: If a transfer names a member that is not in
            ``balances``.
    """
    result = dict(balances)
    keys = {name.casefold(): name for name in result}

    def resolve(name: str) -> str:
        try:
            return keys[name.casefold()]
        except KeyError:
            raise SettlementError(
                f"Transfer names {name!r}, who has no balance"
            ) from None

    for transfer in transfers:
        result[resolve(transfer.debtor)] += transfer.amount
        result[resolve(transfer.creditor)] -= transfer.amount
    return result


def _check_sum_is_zero(balances: Mapping[str, Decimal]) -> None:
    """Checks that a set of balances sums to exactly zero.

    Args:
        balances: The net balance of each member.

    Raises:
        SettlementError: If the balances do not sum to zero.
    """
    total = sum(balances.values(), Decimal(0))
    if total != 0:
        raise SettlementError(f"Balances must sum to zero to be settled, got {total}")
