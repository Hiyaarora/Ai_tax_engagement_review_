"""SQLite persistence for reviews - one row per review with a status, the result stored as JSON.

Lifecycle: ``queued -> running -> done | failed``. Only ``done`` rows carry a ``ReviewResult``.
Deliberately minimal: stdlib ``sqlite3``; swapping to Postgres later means changing this file only.
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
    status             TEXT NOT NULL DEFAULT 'done',
    error              TEXT,
    overall_risk_level TEXT,
    flag_count         INTEGER NOT NULL DEFAULT 0,
    model              TEXT,
    result_json        TEXT
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

# The first schema had no status column and NOT NULL result columns. SQLite cannot relax
# constraints in place, so an old table is rebuilt once on open: every existing row is a completed
# review, so it becomes status='done'.
_REBUILD_OLD_REVIEWS = """
CREATE TABLE reviews_new (
    review_id          TEXT PRIMARY KEY,
    engagement_id      TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'done',
    error              TEXT,
    overall_risk_level TEXT,
    flag_count         INTEGER NOT NULL DEFAULT 0,
    model              TEXT,
    result_json        TEXT
);
INSERT INTO reviews_new (review_id, engagement_id, created_at, status, error,
                         overall_risk_level, flag_count, model, result_json)
    SELECT review_id, engagement_id, created_at, 'done', NULL,
           overall_risk_level, flag_count, model, result_json FROM reviews;
DROP TABLE reviews;
ALTER TABLE reviews_new RENAME TO reviews;
CREATE INDEX IF NOT EXISTS reviews_engagement_idx ON reviews (engagement_id, created_at DESC);
"""

Decision = Literal["accepted", "rejected", "needs_more_info"]
ReviewStatus = Literal["queued", "running", "done", "failed"]


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
    status: ReviewStatus
    error: str | None = None
    overall_risk_level: str | None = None
    flag_count: int = 0
    model: str | None = None


class ReviewRecord(BaseModel):
    """A review at any point in its lifecycle; ``result`` is present only when ``done``."""

    review_id: str
    engagement_id: str
    created_at: datetime
    status: ReviewStatus
    error: str | None = None
    result: ReviewResult | None = None


class ReviewRepository:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            info = {row["name"]: row for row in conn.execute("PRAGMA table_info(reviews)")}
            needs_rebuild = "status" not in info or info["overall_risk_level"]["notnull"] == 1
            if needs_rebuild:
                conn.executescript(_REBUILD_OLD_REVIEWS)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path)
        try:
            conn.row_factory = sqlite3.Row
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- lifecycle ------------------------------------------------------------------------------

    def create_pending(self, review_id: str, engagement_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO reviews (review_id, engagement_id, created_at, status)"
                " VALUES (?, ?, ?, 'queued')",
                (review_id, engagement_id, datetime.now(UTC).isoformat()),
            )

    def mark_running(self, review_id: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE reviews SET status = 'running' WHERE review_id = ?", (review_id,))

    def mark_failed(self, review_id: str, error: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE reviews SET status = 'failed', error = ? WHERE review_id = ?",
                (error, review_id),
            )

    def save(self, result: ReviewResult) -> None:
        """Store a completed result (creates the row if the review was never queued)."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO reviews"
                " (review_id, engagement_id, created_at, status, error, overall_risk_level,"
                "  flag_count, model, result_json)"
                " VALUES (?, ?, ?, 'done', NULL, ?, ?, ?, ?)",
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

    # --- reads ----------------------------------------------------------------------------------

    def get(self, review_id: str) -> ReviewResult | None:
        """The completed result, or None if the review is missing or not done."""
        record = self.get_record(review_id)
        return record.result if record else None

    def get_record(self, review_id: str) -> ReviewRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT review_id, engagement_id, created_at, status, error, result_json"
                " FROM reviews WHERE review_id = ?",
                (review_id,),
            ).fetchone()
        if not row:
            return None
        result = (
            ReviewResult.model_validate_json(row["result_json"]) if row["result_json"] else None
        )
        return ReviewRecord(
            review_id=row["review_id"],
            engagement_id=row["engagement_id"],
            created_at=row["created_at"],
            status=row["status"],
            error=row["error"],
            result=result,
        )

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
                "SELECT review_id, engagement_id, created_at, status, error, overall_risk_level,"
                " flag_count, model"
                " FROM reviews WHERE engagement_id = ? ORDER BY created_at DESC, review_id DESC",
                (engagement_id,),
            ).fetchall()
        return [ReviewSummary(**dict(row)) for row in rows]
