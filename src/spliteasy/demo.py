"""Demo data that shows what SplitEasy can do.

:func:`create_demo_data` fills a repository with two realistic groups through
the :class:`~spliteasy.services.GroupService`, so every expense is validated
and split exactly as if a user had entered it:

* **Flat**: two flatmates with rent (exact split), internet (equal), several
  grocery trips, four itemised receipts (Kaufland twice, Lidl and dm) with
  discounts, bottle deposits and a percentage-split item, and one payment
  already made.
* **Italy Trip**: four friends with twelve expenses in food, transport,
  accommodation and entertainment, using all four split methods and two
  expenses in Swiss francs converted at a fixed rate.

All dates are fixed, so the demo gives the same balances every time.
"""

from datetime import date
from decimal import Decimal

from spliteasy.exceptions import ExpenseNotFoundError
from spliteasy.models import (
    Adjustment,
    AdjustmentKind,
    DistributionMode,
    LineItem,
    SplitMethod,
)
from spliteasy.services import GroupService

FLAT = "Flat"
ITALY_TRIP = "Italy Trip"
DEMO_GROUPS = (FLAT, ITALY_TRIP)
"""Names of the groups created by :func:`create_demo_data`."""

RECEIPT_EXAMPLE = ("Kaufland", date(2026, 9, 8))
"""Description and date of the itemised receipt shown as an example."""


def create_demo_data(service: GroupService) -> list[str]:
    """Creates the demo groups, replacing them if they already exist.

    Args:
        service: The service to create the groups with.

    Returns:
        The names of the created groups.

    Raises:
        StorageError: If the groups cannot be saved.
    """
    existing = {name.casefold() for name in service.list_groups()}
    for name in DEMO_GROUPS:
        if name.casefold() in existing:
            service.delete_group(name)

    _create_flat(service)
    _create_italy_trip(service)
    return list(DEMO_GROUPS)


def _create_flat(service: GroupService) -> None:
    """Creates the "Flat" group: two flatmates sharing a month of costs."""
    service.create_group(FLAT, currency="EUR", members=["John", "Steve"])

    # John has the bigger room, so he pays more of the rent.
    service.add_expense(
        FLAT,
        "Rent September",
        "1200.00",
        "John",
        split=SplitMethod.EXACT,
        split_values={"John": "700.00", "Steve": "500.00"},
        category="rent",
        date=date(2026, 9, 1),
    )
    service.add_expense(
        FLAT,
        "Internet",
        "39.99",
        "Steve",
        category="utilities",
        date=date(2026, 9, 3),
    )
    groceries = [
        ("Lidl", "54.30", "John", date(2026, 9, 5)),
        ("Rewe", "32.85", "Steve", date(2026, 9, 12)),
        ("Aldi", "47.12", "John", date(2026, 9, 19)),
        ("Edeka", "28.40", "Steve", date(2026, 9, 26)),
    ]
    for shop, amount, payer, day in groceries:
        service.add_expense(
            FLAT, f"Groceries {shop}", amount, payer, category="groceries", date=day
        )

    # Each item is shared only by the people who use it. The deposit for
    # Steve's returned bottles lowers his part, and the coupon is spread in
    # proportion to what each person bought.
    service.add_expense(
        FLAT,
        "Kaufland",
        "17.00",
        "Steve",
        split=SplitMethod.ITEMIZED,
        items=[
            LineItem.for_members("Olive oil", "6.00", ["John", "Steve"]),
            LineItem.for_members("Protein bars", "2.50", ["John"], quantity=2),
            LineItem.for_members("Yogurt", "4.00", ["John"]),
            LineItem.for_members("Coffee", "5.00", ["Steve"]),
            LineItem.for_members(
                "Bottle deposit return", "-0.25", ["Steve"], quantity=4
            ),
        ],
        adjustments=[
            Adjustment(
                kind=AdjustmentKind.DISCOUNT,
                amount=Decimal("2.00"),
                description="Coupon",
            )
        ],
        category="groceries",
        date=date(2026, 9, 15),
    )

    _add_flat_receipts(service)

    service.record_payment(
        FLAT,
        "Steve",
        "John",
        "450.00",
        date=date(2026, 9, 2),
        note="Part of the rent (bank transfer)",
    )


def _add_flat_receipts(service: GroupService) -> None:
    """Adds three itemised receipts from local shops to the "Flat" group.

    Product names are German, as on the receipts, spelled in plain ASCII
    (``oe``, ``ue``) so they display correctly in every terminal.
    """
    kaufland, kaufland_date = RECEIPT_EXAMPLE
    # The coffee is mostly Steve's; the Kaufland Card discount is spread in
    # proportion to what each person bought.
    service.add_expense(
        FLAT,
        kaufland,
        "30.00",
        "John",
        split=SplitMethod.ITEMIZED,
        items=[
            LineItem.for_members("Vollmilch 1L", "1.19", ["John", "Steve"], quantity=2),
            LineItem.for_members("Broetchen 10 Stueck", "2.49", ["John", "Steve"]),
            LineItem.for_members("Olivenoel", "6.49", ["John", "Steve"]),
            LineItem.for_members("Skyr", "1.49", ["Steve"], quantity=2),
            LineItem.for_members("Proteinriegel", "1.29", ["John"], quantity=3),
            LineItem(
                name="Kaffee 1kg",
                price=Decimal("12.99"),
                assignees={"John": Decimal(30), "Steve": Decimal(70)},
                split_method=SplitMethod.PERCENTAGE,
            ),
        ],
        adjustments=[
            Adjustment(
                kind=AdjustmentKind.DISCOUNT,
                amount=Decimal("1.20"),
                distribute=DistributionMode.PROPORTIONAL,
                description="Kaufland Card",
            )
        ],
        category="groceries",
        date=kaufland_date,
    )
    # John returned eight bottles (a negative item); the deposit on the new
    # six-pack of water is shared equally.
    service.add_expense(
        FLAT,
        "Lidl",
        "4.21",
        "Steve",
        split=SplitMethod.ITEMIZED,
        items=[
            LineItem.for_members("Mineralwasser 6x1,5L", "1.74", ["John", "Steve"]),
            LineItem.for_members("Bananen", "1.39", ["John"]),
            LineItem.for_members("Nudeln 500g", "0.79", ["John", "Steve"], quantity=2),
            LineItem.for_members("Pfandrueckgabe", "-0.25", ["John"], quantity=8),
        ],
        adjustments=[
            Adjustment(
                kind=AdjustmentKind.DEPOSIT,
                amount=Decimal("1.50"),
                distribute=DistributionMode.EQUAL,
                description="Pfand 6 bottles",
            )
        ],
        category="groceries",
        date=date(2026, 9, 10),
    )
    service.add_expense(
        FLAT,
        "dm",
        "7.60",
        "John",
        split=SplitMethod.ITEMIZED,
        items=[
            LineItem.for_members("Toilettenpapier", "3.95", ["John", "Steve"]),
            LineItem.for_members("Spuelmittel", "0.95", ["John", "Steve"]),
            LineItem.for_members("Zahnpasta", "1.45", ["John"]),
            LineItem.for_members("Duschgel", "1.25", ["Steve"]),
        ],
        category="household",
        date=date(2026, 9, 22),
    )


def receipt_example_id(service: GroupService) -> int:
    """Returns the id of the demo's example itemised receipt in "Flat".

    Args:
        service: A service on which :func:`create_demo_data` has been run.

    Returns:
        The expense id of the Kaufland receipt from :data:`RECEIPT_EXAMPLE`.

    Raises:
        ExpenseNotFoundError: If the demo receipt does not exist.
    """
    description, day = RECEIPT_EXAMPLE
    for expense in service.list_expenses(FLAT):
        if expense.description == description and expense.date == day:
            return expense.id  # type: ignore[return-value]
    raise ExpenseNotFoundError(description)


def _create_italy_trip(service: GroupService) -> None:
    """Creates the "Italy Trip" group: four friends travelling via Zurich."""
    members = ["John", "Steve", "Clark", "Dan"]
    service.create_group(ITALY_TRIP, currency="EUR", members=members)

    def add(
        description: str, amount: str, payer: str, day: int, **options: object
    ) -> None:
        service.add_expense(
            ITALY_TRIP,
            description,
            amount,
            payer,
            date=date(2026, 8, day),
            **options,  # type: ignore[arg-type]
        )

    # Two nights in Zurich, paid in Swiss francs. Clark and Dan arrived a
    # night later, so the hotel is split by nights stayed.
    add(
        "Hotel Zurich",
        "480.00",
        "John",
        9,
        split=SplitMethod.SHARES,
        split_values={"John": 2, "Steve": 2, "Clark": 1, "Dan": 1},
        currency="CHF",
        rate="1.07",
        category="accommodation",
    )
    add(
        "Train Zurich to Milan",
        "312.00",
        "Clark",
        10,
        currency="CHF",
        rate="1.06",
        category="transport",
    )
    add(
        "Apartment Florence",
        "840.00",
        "Steve",
        11,
        split=SplitMethod.SHARES,
        split_values={"John": 4, "Steve": 4, "Clark": 3, "Dan": 3},
        category="accommodation",
    )
    add("Pizza night", "96.50", "Dan", 11, category="food")
    add("Gelato", "18.60", "Steve", 12, category="food")
    add("Supermarket", "63.25", "John", 12, category="food")
    # Dan had a student discount.
    add(
        "Uffizi tickets",
        "100.00",
        "Clark",
        12,
        split=SplitMethod.EXACT,
        split_values={"John": 29, "Steve": 29, "Clark": 29, "Dan": 13},
        category="entertainment",
    )
    # Split by how many days each person drove.
    add(
        "Car rental",
        "360.00",
        "John",
        13,
        split=SplitMethod.PERCENTAGE,
        split_values={"John": 40, "Steve": 30, "Clark": 20, "Dan": 10},
        category="transport",
    )
    add(
        "Fuel",
        "78.40",
        "Dan",
        13,
        participants=["John", "Steve", "Clark"],
        category="transport",
    )
    # Steve skipped the wine tasting.
    add(
        "Chianti wine tasting",
        "140.00",
        "Clark",
        14,
        participants=["John", "Clark", "Dan"],
        category="entertainment",
    )
    add("Boat tour Cinque Terre", "120.00", "Dan", 15, category="entertainment")
    add(
        "Farewell dinner",
        "212.80",
        "Steve",
        16,
        split=SplitMethod.EXACT,
        split_values={
            "John": "55.40",
            "Steve": "48.90",
            "Clark": "60.10",
            "Dan": "48.40",
        },
        category="food",
    )
