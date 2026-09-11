"""Loads an engagement's structured data from ``<root>/engagements/<engagement_id>/``.

Layout of one engagement directory:
    engagement.json     company_name, home_state, tax_year
    sales.csv           transaction_id,date,ship_to_state,amount_usd,channel ('#' = comment)
    questionnaire.json  [{id, section, question, answer, note}]
    locations.json      [{city, state, site_type, headcount, note}]
    *.pdf / *.docx      documents to index as evidence

The id is validated against a strict pattern and resolved *inside* the root, so a tool can only ever
read the engagement it was given - never another engagement or an arbitrary file.
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

    def _dir_for(self, engagement_id: str) -> Path:
        if not _ID.match(engagement_id):
            raise EngagementNotFoundError(engagement_id)
        directory = (self._engagements_dir / engagement_id).resolve()
        if directory.parent != self._engagements_dir or not directory.is_dir():
            raise EngagementNotFoundError(engagement_id)
        return directory

    def document_paths(self, engagement_id: str) -> list[Path]:
        directory = self._dir_for(engagement_id)
        return sorted(p for p in directory.iterdir() if p.suffix.lower() in INDEXABLE_SUFFIXES)

    def load(self, engagement_id: str) -> EngagementData:
        directory = self._dir_for(engagement_id)
        meta = json.loads((directory / "engagement.json").read_text(encoding="utf-8"))
        return EngagementData(
            engagement_id=engagement_id,
            company_name=meta["company_name"],
            home_state=meta["home_state"],
            tax_year=meta["tax_year"],
            transactions=_read_sales(directory / "sales.csv"),
            questionnaire=[
                QuestionnaireAnswer(**row)
                for row in json.loads(
                    (directory / "questionnaire.json").read_text(encoding="utf-8")
                )
            ],
            locations=[
                EmployeeLocation(**row)
                for row in json.loads((directory / "locations.json").read_text(encoding="utf-8"))
            ],
        )


def _read_sales(path: Path) -> list[Transaction]:
    with path.open(encoding="utf-8", newline="") as f:
        rows = csv.DictReader(line for line in f if not line.startswith("#"))
        return [Transaction(**row) for row in rows]  # type: ignore[arg-type]
