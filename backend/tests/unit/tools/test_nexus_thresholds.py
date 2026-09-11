from datetime import date

import pytest

from app.models.engagement import EngagementData, Transaction
from app.tools.nexus_thresholds import (
    NexusThresholdResult,
    StateThreshold,
    ThresholdTable,
    check_economic_nexus_thresholds,
    load_thresholds,
)


def _data(rows: list[tuple[str, float, int]]) -> EngagementData:
    txns = []
    for state, amount, count in rows:
        for i in range(count):
            txns.append(
                Transaction(
                    transaction_id=f"{state}-{i}",
                    date=date(2025, 1, 1),
                    ship_to_state=state,
                    amount_usd=amount / count,
                    channel="website",
                )
            )
    return EngagementData(
        engagement_id="t-2025",
        company_name="T",
        home_state="CO",
        tax_year=2025,
        transactions=txns,
        questionnaire=[],
        locations=[],
    )


TABLE = ThresholdTable(
    notice="ILLUSTRATIVE",
    measurement_period="calendar year",
    states={
        "TX": StateThreshold(
            name="Texas", sales_threshold=500_000, transaction_threshold=None, rule="sales"
        ),
        "WA": StateThreshold(
            name="Washington",
            sales_threshold=100_000,
            transaction_threshold=200,
            rule="sales_or_transactions",
        ),
        "NY": StateThreshold(
            name="New York",
            sales_threshold=500_000,
            transaction_threshold=100,
            rule="sales_and_transactions",
        ),
    },
)


def _state(result: NexusThresholdResult, code: str):
    return next(s for s in result.states if s.state == code)


def test_sales_rule_met_only_when_revenue_reaches_threshold():
    r = check_economic_nexus_thresholds(_data([("TX", 500_000, 10)]), TABLE)
    assert _state(r, "TX").threshold_met is True
    r = check_economic_nexus_thresholds(_data([("TX", 499_999, 10)]), TABLE)
    assert _state(r, "TX").threshold_met is False


def test_or_rule_met_by_transactions_alone():
    tx = _state(check_economic_nexus_thresholds(_data([("WA", 5_000, 200)]), TABLE), "WA")
    assert tx.threshold_met is True
    assert "200 >= 200" in tx.basis


def test_and_rule_requires_both():
    assert (
        _state(
            check_economic_nexus_thresholds(_data([("NY", 600_000, 50)]), TABLE), "NY"
        ).threshold_met
        is False
    )
    assert (
        _state(
            check_economic_nexus_thresholds(_data([("NY", 600_000, 100)]), TABLE), "NY"
        ).threshold_met
        is True
    )


def test_state_without_a_threshold_entry_is_reported_as_unavailable_not_false():
    fl = _state(check_economic_nexus_thresholds(_data([("FL", 1_000_000, 5)]), TABLE), "FL")
    assert fl.threshold_available is False and fl.threshold_met is None


def test_result_carries_the_illustrative_notice_and_source():
    r = check_economic_nexus_thresholds(_data([("TX", 1, 1)]), TABLE)
    assert r.thresholds_notice == "ILLUSTRATIVE"
    assert r.source == "tool:check_economic_nexus_thresholds"


def test_acme_designed_outcomes(acme_data):
    r = check_economic_nexus_thresholds(acme_data, load_thresholds())
    met = {s.state for s in r.states if s.threshold_met}
    assert {"TX", "WA", "CO"} <= met  # CO is home state and also over its threshold
    assert "CA" not in met and "NY" not in met and "FL" not in met
    assert _state(r, "CO").is_home_state is True


def test_bundled_thresholds_file_validates():
    table = load_thresholds()
    assert "ILLUSTRATIVE" in table.notice.upper() or "SYNTHETIC" in table.notice.upper()
    assert set(table.states) == {"CA", "CO", "FL", "NY", "TX", "WA"}


def test_unknown_rule_is_rejected():
    with pytest.raises(ValueError):
        StateThreshold(name="X", sales_threshold=1, transaction_threshold=None, rule="bogus")
