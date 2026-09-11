"""The one synthetic engagement used for demos, evals and the Milestone 3 tools.

Everything here is invented. The numbers are chosen so the documents disagree with each other in
specific, explainable ways (see the tests) - that is what gives the review agent something to find.
"""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TextIO

ENGAGEMENT_ID = "acme-2025"
TAX_YEAR = 2025


@dataclass(frozen=True)
class Company:
    name: str
    home_state: str
    industry: str
    disclaimer: str


COMPANY = Company(
    name="Acme Widgets LLC",
    home_state="CO",
    industry="Direct-to-consumer and wholesale industrial widgets",
    disclaimer=(
        "SYNTHETIC DATA - NOT A REAL CLIENT. Generated for a demo of an AI review tool. "
        "Decision support only, not tax advice."
    ),
)


@dataclass(frozen=True)
class QuestionnaireItem:
    id: str
    section: str
    question: str
    answer: str
    note: str = ""


def questionnaire() -> list[QuestionnaireItem]:
    return [
        QuestionnaireItem(
            "home_state",
            "General",
            "In which state is the company headquartered?",
            "Colorado",
            "Denver office, incorporated in Colorado.",
        ),
        QuestionnaireItem(
            "sales_channels",
            "General",
            "Through which channels does the company sell?",
            "Own website, wholesale distributors, one online marketplace",
        ),
        QuestionnaireItem(
            "inventory_tx",
            "Physical presence",
            "Does the company hold inventory in Texas?",
            "Yes",
            "Inventory is stored at a third-party logistics (3PL) warehouse in Dallas, Texas.",
        ),
        QuestionnaireItem(
            "inventory_other",
            "Physical presence",
            "Does the company hold inventory in any other state outside Colorado?",
            "No",
        ),
        QuestionnaireItem(
            "employees_outside_co",
            "Physical presence",
            "Does the company have employees who work from a location outside Colorado?",
            "No",
            "All employees work from the Denver headquarters.",
        ),
        QuestionnaireItem(
            "contractors",
            "Physical presence",
            "Does the company use independent contractors outside Colorado?",
            "Yes",
            "One sales contractor visits customers in Texas roughly monthly.",
        ),
        QuestionnaireItem(
            "registered_co",
            "Registrations",
            "Is the company registered to collect sales tax in Colorado?",
            "Yes",
        ),
        QuestionnaireItem(
            "registered_tx",
            "Registrations",
            "Is the company registered to collect sales tax in Texas?",
            "No",
            "Management believes the 3PL arrangement does not require registration.",
        ),
        QuestionnaireItem(
            "registered_other",
            "Registrations",
            "Is the company registered to collect sales tax in any other state?",
            "No",
        ),
        QuestionnaireItem(
            "marketplace",
            "Registrations",
            "Does the online marketplace collect sales tax on the company's behalf?",
            "Yes",
            "Marketplace sales are roughly 10% of revenue.",
        ),
    ]


@dataclass(frozen=True)
class EmployeeLocation:
    city: str
    state: str
    site_type: str
    headcount: int
    note: str = ""


def employee_locations() -> list[EmployeeLocation]:
    return [
        EmployeeLocation("Denver", "CO", "Headquarters (owned office)", 38),
        EmployeeLocation(
            "Seattle", "WA", "Remote employees (home offices)", 2, "Two engineers hired in 2025."
        ),
        EmployeeLocation(
            "Dallas", "TX", "3PL warehouse (no employees)", 0, "Operated by third-party provider."
        ),
        EmployeeLocation(
            "Austin", "TX", "Independent contractor", 0, "Not an employee; monthly customer visits."
        ),
    ]


@dataclass(frozen=True)
class Transaction:
    transaction_id: str
    date: date
    ship_to_state: str
    amount_usd: float
    channel: str


# (transaction count, total revenue) per state; the generator fits random amounts to these totals.
_SALES_PLAN: dict[str, tuple[int, float]] = {
    "CO": (1400, 1_250_000.00),
    "TX": (900, 620_000.00),
    "CA": (420, 310_000.00),
    "WA": (250, 130_000.00),
    "NY": (60, 80_000.00),
    "FL": (45, 40_000.00),
}
_CHANNELS = ("website", "wholesale", "marketplace")


def sales_transactions() -> list[Transaction]:
    """Deterministic (seeded) transaction list matching ``_SALES_PLAN`` exactly."""
    rng = random.Random(20250101)
    rows: list[Transaction] = []
    start = date(TAX_YEAR, 1, 1)
    for state, (count, total) in _SALES_PLAN.items():
        weights = [rng.uniform(0.5, 1.5) for _ in range(count)]
        scale = total / sum(weights)
        amounts = [round(w * scale, 2) for w in weights]
        amounts[-1] = round(amounts[-1] + (total - sum(amounts)), 2)  # absorb rounding drift
        for amount in amounts:
            rows.append(
                Transaction(
                    transaction_id="",
                    date=start + timedelta(days=rng.randrange(365)),
                    ship_to_state=state,
                    amount_usd=amount,
                    channel=rng.choices(_CHANNELS, weights=(6, 3, 1))[0],
                )
            )
    rows.sort(key=lambda t: (t.date, t.ship_to_state, t.amount_usd))
    return [
        Transaction(f"TXN-{i + 1:05d}", t.date, t.ship_to_state, t.amount_usd, t.channel)
        for i, t in enumerate(rows)
    ]


@dataclass
class StateTotal:
    revenue: float
    transactions: int


def sales_by_state(rows: list[Transaction]) -> dict[str, StateTotal]:
    totals: dict[str, StateTotal] = {}
    for row in rows:
        entry = totals.setdefault(row.ship_to_state, StateTotal(0.0, 0))
        entry.revenue = round(entry.revenue + row.amount_usd, 2)
        entry.transactions += 1
    return totals


def write_sales_csv(rows: list[Transaction], out: TextIO) -> None:
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["transaction_id", "date", "ship_to_state", "amount_usd", "channel"])
    for row in rows:
        writer.writerow(
            [
                row.transaction_id,
                row.date.isoformat(),
                row.ship_to_state,
                f"{row.amount_usd:.2f}",
                row.channel,
            ]
        )
