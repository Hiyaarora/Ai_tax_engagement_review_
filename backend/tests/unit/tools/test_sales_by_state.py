from datetime import date

from app.models.engagement import EngagementData, Transaction
from app.tools.sales_by_state import SalesByStateResult, analyze_sales_by_state


def test_acme_totals_match_the_designed_plan(acme_data):
    result = analyze_sales_by_state(acme_data)

    assert isinstance(result, SalesByStateResult)
    assert result.engagement_id == "acme-2025" and result.tax_year == 2025
    by_state = {s.state: s for s in result.states}
    assert by_state["TX"].revenue_usd == 620_000.00 and by_state["TX"].transactions == 900
    assert by_state["WA"].revenue_usd == 130_000.00 and by_state["WA"].transactions == 250
    assert by_state["CA"].revenue_usd == 310_000.00
    assert by_state["NY"].transactions == 60
    assert result.total_revenue_usd == 2_430_000.00
    assert result.total_transactions == 3075


def test_states_sorted_by_revenue_desc_with_share_and_home_flag(acme_data):
    result = analyze_sales_by_state(acme_data)
    assert [s.state for s in result.states] == ["CO", "TX", "CA", "WA", "NY", "FL"]
    co = result.states[0]
    assert co.is_home_state is True
    assert round(co.share_of_revenue, 4) == round(1_250_000 / 2_430_000, 4)
    assert result.states[1].is_home_state is False


def test_marketplace_revenue_reported_separately_per_state():
    data = EngagementData(
        engagement_id="t-2025",
        company_name="T",
        home_state="CO",
        tax_year=2025,
        transactions=[
            Transaction(
                transaction_id="1",
                date=date(2025, 1, 1),
                ship_to_state="TX",
                amount_usd=100,
                channel="website",
            ),
            Transaction(
                transaction_id="2",
                date=date(2025, 1, 2),
                ship_to_state="TX",
                amount_usd=50,
                channel="marketplace",
            ),
        ],
        questionnaire=[],
        locations=[],
    )
    tx = analyze_sales_by_state(data).states[0]
    assert tx.revenue_usd == 150 and tx.marketplace_revenue_usd == 50
    assert tx.source == "tool:analyze_sales_by_state"
