"""SQLite persistence for completed reviews - one table, the full result stored as JSON.

Deliberately minimal: stdlib ``sqlite3``, a few indexed columns for listing, and the validated
``ReviewResult`` as the payload. Swapping to Postgres later means changing this file only.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.models.review import ReviewResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews (
    review_id          TEXT PRIMARY KEY,
    engagement_id      TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    overall_risk_level TEXT NOT NULL,
    flag_count         INTEGER NOT NULL,
    model              TEXT NOT NULL,
    result_json        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS reviews_engagement_idx ON reviews (engagement_id, created_at DESC);
CREATE TABLE IF NOT EXISTS flag_decisions (
    review_id     TEXT NOT NULL REFERENCES reviews (review_id),
    flag_id       TEXT NOT NULL,
    decision      TEXT NOT NULL,
    reviewer_note TEXT NOT NULL DEFAULT '',
    decided_at    TEXT NOT NULL,
    PRIMARY KEY (review_id, flag_id)
);
"""

Decision = Literal["accepted", "rejected", "needs_more_info"]


class UnknownFlagError(LookupError):
    pass


class FlagDecision(BaseModel):
    """A human reviewer's decision on one flag - the required last step of every review."""

    review_id: str
    flag_id: str
    decision: Decision
    reviewer_note: str = ""
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReviewSummary(BaseModel):
    review_id: str
    engagement_id: str
    created_at: datetime
    overall_risk_level: str
    flag_count: int
    model: str


class ReviewRepository:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path)
        try:
            conn.row_factory = sqlite3.Row
            yield conn
            conn.commit()
        finally:
            conn.close()

    def save(self, result: ReviewResult) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO reviews VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    result.review_id,
                    result.engagement_id,
                    result.created_at.isoformat(),
                    result.overall_risk_level,
                    len(result.risk_flags),
                    result.model,
                    result.model_dump_json(),
                ),
            )

    def get(self, review_id: str) -> ReviewResult | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT result_json FROM reviews WHERE review_id = ?", (review_id,)
            ).fetchone()
        return ReviewResult.model_validate_json(row["result_json"]) if row else None

    def save_decision(self, decision: FlagDecision) -> None:
        review = self.get(decision.review_id)
        if review is None or decision.flag_id not in {f.id for f in review.risk_flags}:
            raise UnknownFlagError(f"{decision.review_id}/{decision.flag_id}")
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO flag_decisions VALUES (?, ?, ?, ?, ?)",
                (
                    decision.review_id,
                    decision.flag_id,
                    decision.decision,
                    decision.reviewer_note,
                    decision.decided_at.isoformat(),
                ),
            )

    def list_decisions(self, review_id: str) -> list[FlagDecision]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT review_id, flag_id, decision, reviewer_note, decided_at"
                " FROM flag_decisions WHERE review_id = ? ORDER BY flag_id",
                (review_id,),
            ).fetchall()
        return [FlagDecision(**dict(row)) for row in rows]

    def list_for_engagement(self, engagement_id: str) -> list[ReviewSummary]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT review_id, engagement_id, created_at, overall_risk_level, flag_count, model"
                " FROM reviews WHERE engagement_id = ? ORDER BY created_at DESC, review_id DESC",
                (engagement_id,),
            ).fetchall()
        return [ReviewSummary(**dict(row)) for row in rows]
