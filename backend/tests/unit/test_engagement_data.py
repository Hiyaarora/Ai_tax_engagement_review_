import json
from pathlib import Path

import pytest

from app.models.engagement import EngagementData
from app.services.engagement_data import EngagementDataRepository, EngagementNotFoundError


def _write_engagement(root: Path, engagement_id: str) -> Path:
    d = root / "engagements" / engagement_id
    d.mkdir(parents=True)
    (d / "engagement.json").write_text(
        json.dumps(
            {
                "engagement_id": engagement_id,
                "company_name": "Acme",
                "home_state": "CO",
                "tax_year": 2025,
            }
        )
    )
    (d / "sales.csv").write_text(
        "# SYNTHETIC comment line\n"
        "transaction_id,date,ship_to_state,amount_usd,channel\n"
        "TXN-1,2025-01-05,TX,100.50,website\n"
        "TXN-2,2025-02-05,TX,200.00,wholesale\n"
        "TXN-3,2025-03-05,CA,50.00,website\n"
    )
    (d / "questionnaire.json").write_text(
        json.dumps(
            [
                {
                    "id": "inventory_tx",
                    "section": "Physical presence",
                    "question": "Inventory in Texas?",
                    "answer": "Yes",
                    "note": "3PL",
                },
            ]
        )
    )
    (d / "locations.json").write_text(
        json.dumps(
            [{"city": "Denver", "state": "CO", "site_type": "HQ", "headcount": 38, "note": ""}]
        )
    )
    return d


def test_load_reads_metadata_sales_questionnaire_and_locations(tmp_path: Path):
    _write_engagement(tmp_path, "acme-2025")
    repo = EngagementDataRepository(tmp_path)

    data = repo.load("acme-2025")

    assert isinstance(data, EngagementData)
    assert data.engagement_id == "acme-2025"
    assert data.company_name == "Acme" and data.home_state == "CO" and data.tax_year == 2025
    assert [t.transaction_id for t in data.transactions] == ["TXN-1", "TXN-2", "TXN-3"]
    assert data.transactions[0].amount_usd == 100.50
    assert data.questionnaire[0].id == "inventory_tx"
    assert data.locations[0].headcount == 38


def test_unknown_engagement_raises(tmp_path: Path):
    repo = EngagementDataRepository(tmp_path)
    with pytest.raises(EngagementNotFoundError):
        repo.load("nope-2025")


@pytest.mark.parametrize("bad_id", ["../acme-2025", "acme/2025", "acme 2025", "", "a" * 65])
def test_ids_that_could_escape_the_root_are_rejected(tmp_path: Path, bad_id: str):
    _write_engagement(tmp_path, "acme-2025")
    repo = EngagementDataRepository(tmp_path)
    with pytest.raises(EngagementNotFoundError):
        repo.load(bad_id)


def test_list_engagements(tmp_path: Path):
    _write_engagement(tmp_path, "acme-2025")
    _write_engagement(tmp_path, "beta-2025")
    assert EngagementDataRepository(tmp_path).list_ids() == ["acme-2025", "beta-2025"]


def test_document_paths_only_lists_indexable_files_in_the_engagement_dir(tmp_path: Path):
    d = _write_engagement(tmp_path, "acme-2025")
    (d / "questionnaire.pdf").write_bytes(b"%PDF")
    (d / "locations.docx").write_bytes(b"PK")
    docs = EngagementDataRepository(tmp_path).document_paths("acme-2025")
    assert [p.name for p in docs] == ["locations.docx", "questionnaire.pdf"]
