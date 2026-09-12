from pathlib import Path

from evals.cases import CASES, EvalCase, build_variant, load_cases
from scripts.synthetic.dataset import sales_by_state


def test_golden_set_loads_and_has_the_baseline_plus_variants():
    cases = load_cases()
    ids = [c.case_id for c in cases]
    assert ids[0] == "acme-baseline"
    assert {"tx-registered", "wa-under-threshold", "no-inventory-tx"} <= set(ids)
    assert all(isinstance(c, EvalCase) for c in cases)
    assert CASES == cases


def test_baseline_variant_equals_the_synthetic_dataset():
    case = next(c for c in load_cases() if c.case_id == "acme-baseline")
    data = build_variant(case)
    assert {q.id: q.answer for q in data.questionnaire}["registered_tx"] == "No"
    assert sales_by_state(data.transactions)["TX"].revenue == 620_000.00
    assert any(loc.state == "WA" and loc.headcount == 2 for loc in data.locations)


def test_tx_registered_variant_flips_only_the_registration_answer():
    case = next(c for c in load_cases() if c.case_id == "tx-registered")
    data = build_variant(case)
    answers = {q.id: q.answer for q in data.questionnaire}
    assert answers["registered_tx"] == "Yes" and answers["inventory_tx"] == "Yes"
    assert case.expected_flags == [] or all(f.state != "TX" for f in case.expected_flags)
    assert any(f.state == "TX" for f in case.forbidden_flags)


def test_wa_under_threshold_variant_changes_sales_and_removes_remote_employees():
    case = next(c for c in load_cases() if c.case_id == "wa-under-threshold")
    data = build_variant(case)
    wa = sales_by_state(data.transactions)["WA"]
    assert wa.revenue < 100_000 and wa.transactions < 200
    assert not any(loc.state == "WA" for loc in data.locations)
    assert {q.id: q.answer for q in data.questionnaire}["employees_outside_co"] == "No"
    assert any(f.state == "WA" for f in case.forbidden_flags)


def test_no_inventory_variant_keeps_economic_nexus_expectation():
    case = next(c for c in load_cases() if c.case_id == "no-inventory-tx")
    data = build_variant(case)
    assert {q.id: q.answer for q in data.questionnaire}["inventory_tx"] == "No"
    tx = next(f for f in case.expected_flags if f.state == "TX")
    assert "economic_nexus" in tx.categories_any


def test_variant_files_are_written_through_the_normal_generator(tmp_path: Path):
    from evals.cases import write_variant_files

    case = next(c for c in load_cases() if c.case_id == "wa-under-threshold")
    written = write_variant_files(case, tmp_path)
    names = sorted(p.name for p in written)
    assert names == [
        "locations.docx",
        "locations.json",
        "questionnaire.json",
        "questionnaire.pdf",
        "sales.csv",
        "salt_reference_guide.pdf",
    ]
    assert "Seattle" not in (tmp_path / "locations.json").read_text()
