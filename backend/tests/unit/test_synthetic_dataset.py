import csv
import io
import json
from pathlib import Path

from scripts.synthetic.dataset import (
    COMPANY,
    ENGAGEMENT_ID,
    employee_locations,
    questionnaire,
    sales_by_state,
    sales_transactions,
    write_sales_csv,
)

THRESHOLDS = Path("app/tools/reference_data/thresholds.json")


def test_engagement_and_company_are_clearly_synthetic():
    assert ENGAGEMENT_ID == "acme-2025"
    assert "SYNTHETIC" in COMPANY.disclaimer


def test_sales_totals_by_state_create_the_intended_flags():
    totals = sales_by_state(sales_transactions())
    thresholds = json.loads(THRESHOLDS.read_text())["states"]
    # Designed outcomes for the deterministic threshold tool:
    assert totals["TX"].revenue > thresholds["TX"]["sales_threshold"]  # exceeds
    assert totals["WA"].transactions > thresholds["WA"]["transaction_threshold"]  # exceeds by count
    assert totals["CA"].revenue < thresholds["CA"]["sales_threshold"]  # under
    assert totals["NY"].revenue < thresholds["NY"]["sales_threshold"]  # under
    assert set(totals) == {"CO", "TX", "CA", "WA", "NY", "FL"}


def test_sales_transactions_are_deterministic():
    assert sales_transactions() == sales_transactions()


def test_questionnaire_and_locations_contradict_on_out_of_state_employees():
    answers = {q.id: q.answer for q in questionnaire()}
    assert answers["inventory_tx"] == "Yes"
    assert answers["employees_outside_co"] == "No"
    assert answers["registered_tx"] == "No"
    states_with_employees = {loc.state for loc in employee_locations() if loc.headcount > 0}
    assert "WA" in states_with_employees  # contradicts "No" above -> a flag for the agent


def test_write_sales_csv_has_expected_columns_and_row_count():
    buffer = io.StringIO()
    write_sales_csv(sales_transactions(), buffer)
    rows = list(csv.DictReader(io.StringIO(buffer.getvalue())))
    assert list(rows[0]) == ["transaction_id", "date", "ship_to_state", "amount_usd", "channel"]
    assert len(rows) == len(sales_transactions())
