"""check_economic_nexus_thresholds - compare per-state sales with the reference thresholds.

The threshold table is SYNTHETIC / ILLUSTRATIVE (see reference_data/thresholds.json). The tool
reports the comparison and its basis; it never decides whether tax is owed.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.models.engagement import EngagementData
from app.tools.sales_by_state import analyze_sales_by_state

THRESHOLDS_PATH = Path(__file__).resolve().parent / "reference_data" / "thresholds.json"

Rule = Literal["sales", "sales_or_transactions", "sales_and_transactions"]


class StateThreshold(BaseModel):
    name: str
    sales_threshold: float
    transaction_threshold: int | None
    rule: Rule


class ThresholdTable(BaseModel):
    notice: str
    measurement_period: str
    states: dict[str, StateThreshold]


@lru_cache
def load_thresholds(path: Path = THRESHOLDS_PATH) -> ThresholdTable:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return ThresholdTable(
        notice=raw["_notice"], measurement_period=raw["measurement_period"], states=raw["states"]
    )


class StateNexusCheck(BaseModel):
    state: str
    state_name: str | None
    revenue_usd: float
    transactions: int
    is_home_state: bool
    threshold_available: bool
    sales_threshold_usd: float | None
    transaction_threshold: int | None
    rule: Rule | None
    threshold_met: bool | None = Field(
        description="None when no threshold is available for the state."
    )
    basis: str
    source: Literal["tool:check_economic_nexus_thresholds"] = "tool:check_economic_nexus_thresholds"


class NexusThresholdResult(BaseModel):
    engagement_id: str
    tax_year: int
    measurement_period: str
    thresholds_notice: str
    states: list[StateNexusCheck]
    states_meeting_threshold: list[str]
    source: Literal["tool:check_economic_nexus_thresholds"] = "tool:check_economic_nexus_thresholds"


def _evaluate(revenue: float, transactions: int, t: StateThreshold) -> tuple[bool, str]:
    sales_met = revenue >= t.sales_threshold
    sales_op = ">=" if sales_met else "<"
    sales_basis = f"revenue {revenue:,.2f} {sales_op} {t.sales_threshold:,.0f}"
    if t.rule == "sales" or t.transaction_threshold is None:
        return sales_met, sales_basis
    txn_met = transactions >= t.transaction_threshold
    txn_op = ">=" if txn_met else "<"
    txn_basis = f"transactions {transactions} {txn_op} {t.transaction_threshold}"
    if t.rule == "sales_or_transactions":
        return sales_met or txn_met, f"{sales_basis}; {txn_basis} (either suffices)"
    return sales_met and txn_met, f"{sales_basis}; {txn_basis} (both required)"


def check_economic_nexus_thresholds(
    data: EngagementData, table: ThresholdTable | None = None
) -> NexusThresholdResult:
    table = table or load_thresholds()
    sales = analyze_sales_by_state(data)
    checks: list[StateNexusCheck] = []
    for s in sales.states:
        t = table.states.get(s.state)
        if t is None:
            checks.append(
                StateNexusCheck(
                    state=s.state,
                    state_name=None,
                    revenue_usd=s.revenue_usd,
                    transactions=s.transactions,
                    is_home_state=s.is_home_state,
                    threshold_available=False,
                    sales_threshold_usd=None,
                    transaction_threshold=None,
                    rule=None,
                    threshold_met=None,
                    basis="no threshold in the reference table for this state",
                )
            )
            continue
        met, basis = _evaluate(s.revenue_usd, s.transactions, t)
        checks.append(
            StateNexusCheck(
                state=s.state,
                state_name=t.name,
                revenue_usd=s.revenue_usd,
                transactions=s.transactions,
                is_home_state=s.is_home_state,
                threshold_available=True,
                sales_threshold_usd=t.sales_threshold,
                transaction_threshold=t.transaction_threshold,
                rule=t.rule,
                threshold_met=met,
                basis=basis,
            )
        )
    return NexusThresholdResult(
        engagement_id=data.engagement_id,
        tax_year=data.tax_year,
        measurement_period=table.measurement_period,
        thresholds_notice=table.notice,
        states=checks,
        states_meeting_threshold=[c.state for c in checks if c.threshold_met],
    )
