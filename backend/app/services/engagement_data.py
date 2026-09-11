"""Loads an engagement's structured data from ``<root>/engagements/<engagement_id>/``.

Layout of one engagement directory:
    engagement.json     company_name, home_state, tax_year   (written by the backend on create)
    sales.csv           transaction_id,date,ship_to_state,amount_usd,channel ('#' = comment)
    questionnaire.json  [{id, section, question, answer, note}]
    locations.json      [{city, state, site_type, headcount, note}]
    *.pdf / *.docx      documents to index as evidence

Structured files are optional: a missing one loads as an empty list, and the tools say so in
their output. The id is validated against a strict pattern and resolved *inside* the root, so a
tool can only ever read the engagement it was given - never another engagement or an arbitrary file.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from app.models.engagement import (
    ENGAGEMENT_ID_PATTERN,
    EmployeeLocation,
    EngagementData,
    QuestionnaireAnswer,
    Transaction,
)
from app.services.ingestion import INDEXABLE_SUFFIXES

_ID = re.compile(ENGAGEMENT_ID_PATTERN)

SALES_FILE = "sales.csv"
QUESTIONNAIRE_FILE = "questionnaire.json"
LOCATIONS_FILE = "locations.json"
METADATA_FILE = "engagement.json"
SALES_COLUMNS = ("transaction_id", "date", "ship_to_state", "amount_usd", "channel")


class EngagementNotFoundError(LookupError):
    pass


class EngagementDataRepository:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._engagements_dir = self._root / "engagements"

    def list_ids(self) -> list[str]:
        if not self._engagements_dir.is_dir():
            return []
        return sorted(
            p.name for p in self._engagements_dir.iterdir() if p.is_dir() and _ID.match(p.name)
        )

    def _safe_path(self, engagement_id: str) -> Path:
        if not _ID.match(engagement_id):
            raise EngagementNotFoundError(engagement_id)
        directory = (self._engagements_dir / engagement_id).resolve()
        if directory.parent != self._engagements_dir:
            raise EngagementNotFoundError(engagement_id)
        return directory

    def directory(self, engagement_id: str) -> Path:
        """The engagement's directory (must exist)."""
        directory = self._safe_path(engagement_id)
        if not directory.is_dir():
            raise EngagementNotFoundError(engagement_id)
        return directory

    def write_metadata(
        self, engagement_id: str, *, company_name: str, home_state: str, tax_year: int
    ) -> Path:
        """Create the engagement directory with its metadata file. Returns the directory."""
        directory = self._safe_path(engagement_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / METADATA_FILE).write_text(
            json.dumps(
                {
                    "engagement_id": engagement_id,
                    "company_name": company_name,
                    "home_state": home_state,
                    "tax_year": tax_year,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return directory

    def document_paths(self, engagement_id: str) -> list[Path]:
        directory = self.directory(engagement_id)
        return sorted(p for p in directory.iterdir() if p.suffix.lower() in INDEXABLE_SUFFIXES)

    def load(self, engagement_id: str) -> EngagementData:
        directory = self.directory(engagement_id)
        meta = json.loads((directory / METADATA_FILE).read_text(encoding="utf-8"))
        return EngagementData(
            engagement_id=engagement_id,
            company_name=meta["company_name"],
            home_state=meta["home_state"],
            tax_year=meta["tax_year"],
            transactions=read_sales(directory / SALES_FILE),
            questionnaire=read_questionnaire(directory / QUESTIONNAIRE_FILE),
            locations=read_locations(directory / LOCATIONS_FILE),
        )


def read_sales(path: Path) -> list[Transaction]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        rows = csv.DictReader(line for line in f if not line.startswith("#"))
        missing = [c for c in SALES_COLUMNS if c not in (rows.fieldnames or [])]
        if missing:
            raise ValueError(f"missing columns {missing}")
        return [Transaction(**row) for row in rows]  # type: ignore[arg-type]


def read_questionnaire(path: Path) -> list[QuestionnaireAnswer]:
    if not path.is_file():
        return []
    return [QuestionnaireAnswer(**row) for row in json.loads(path.read_text(encoding="utf-8"))]


def read_locations(path: Path) -> list[EmployeeLocation]:
    if not path.is_file():
        return []
    return [EmployeeLocation(**row) for row in json.loads(path.read_text(encoding="utf-8"))]
