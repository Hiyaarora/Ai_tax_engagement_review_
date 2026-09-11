"""SQLite persistence for completed reviews - one table, the full result stored as JSON.

Deliberately minimal: stdlib ``sqlite3``, a few indexed columns for listing, and the validated
``ReviewResult`` as the payload. Swapping to Postgres later means changing this file only.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

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
"""


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

    def list_for_engagement(self, engagement_id: str) -> list[ReviewSummary]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT review_id, engagement_id, created_at, overall_risk_level, flag_count, model"
                " FROM reviews WHERE engagement_id = ? ORDER BY created_at DESC, review_id DESC",
                (engagement_id,),
            ).fetchall()
        return [ReviewSummary(**dict(row)) for row in rows]
