"""analyze_sales_by_state - revenue and transaction counts by ship-to state. Pure Python, no LLM."""

from __future__ import annotations

from collections import defaultdict
from typing import Literal

from pydantic import BaseModel

from app.models.engagement import EngagementData


class StateSales(BaseModel):
    state: str
    revenue_usd: float
    transactions: int
    marketplace_revenue_usd: float
    share_of_revenue: float
    is_home_state: bool
    source: Literal["tool:analyze_sales_by_state"] = "tool:analyze_sales_by_state"


class SalesByStateResult(BaseModel):
    engagement_id: str
    tax_year: int
    home_state: str
    total_revenue_usd: float
    total_transactions: int
    states: list[StateSales]
    source: Literal["tool:analyze_sales_by_state"] = "tool:analyze_sales_by_state"


def analyze_sales_by_state(data: EngagementData) -> SalesByStateResult:
    revenue: dict[str, float] = defaultdict(float)
    marketplace: dict[str, float] = defaultdict(float)
    count: dict[str, int] = defaultdict(int)
    for t in data.transactions:
        revenue[t.ship_to_state] += t.amount_usd
        count[t.ship_to_state] += 1
        if t.channel == "marketplace":
            marketplace[t.ship_to_state] += t.amount_usd

    total = round(sum(revenue.values()), 2)
    states = [
        StateSales(
            state=state,
            revenue_usd=round(revenue[state], 2),
            transactions=count[state],
            marketplace_revenue_usd=round(marketplace[state], 2),
            share_of_revenue=(revenue[state] / total) if total else 0.0,
            is_home_state=(state == data.home_state),
        )
        for state in revenue
    ]
    states.sort(key=lambda s: (-s.revenue_usd, s.state))
    return SalesByStateResult(
        engagement_id=data.engagement_id,
        tax_year=data.tax_year,
        home_state=data.home_state,
        total_revenue_usd=total,
        total_transactions=len(data.transactions),
        states=states,
    )
