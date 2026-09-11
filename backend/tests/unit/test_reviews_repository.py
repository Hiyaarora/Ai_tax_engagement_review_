from pathlib import Path

from app.db.reviews import ReviewRepository
from app.models.review import CitationGuardReport, ReviewResult, RiskFlag


def _result(review_id: str, engagement_id: str = "acme-2025", level: str = "high") -> ReviewResult:
    return ReviewResult(
        review_id=review_id,
        engagement_id=engagement_id,
        model="gpt-4.1-mini",
        agent_name="FDprojectAgent",
        tool_calls=["analyze_sales_by_state"],
        citation_guard=CitationGuardReport(dropped_citations=["x"]),
        overall_summary="s",
        overall_risk_level=level,  # type: ignore[arg-type]
        risk_flags=[
            RiskFlag(
                id="TX-1",
                title="t",
                state="TX",
                category="physical_presence",
                risk_level="high",
                explanation="e",
                retrieved_evidence=[],
                tool_findings=[],
                recommended_human_action="a",
            )
        ],
        states_reviewed_without_flags=["CA"],
    )


def test_save_then_get_round_trips_the_full_result(tmp_path: Path):
    repo = ReviewRepository(tmp_path / "reviews.db")
    original = _result("rev_1")

    repo.save(original)
    loaded = repo.get("rev_1")

    assert loaded == original
    assert loaded is not None and loaded.citation_guard.dropped_citations == ["x"]


def test_get_unknown_returns_none(tmp_path: Path):
    assert ReviewRepository(tmp_path / "r.db").get("nope") is None


def test_list_for_engagement_is_newest_first_and_scoped(tmp_path: Path):
    repo = ReviewRepository(tmp_path / "r.db")
    repo.save(_result("rev_1", level="low"))
    repo.save(_result("rev_2", level="high"))
    repo.save(_result("rev_other", engagement_id="beta-2025"))

    summaries = repo.list_for_engagement("acme-2025")

    assert [s.review_id for s in summaries] == ["rev_2", "rev_1"]
    assert summaries[0].overall_risk_level == "high" and summaries[0].flag_count == 1
    assert summaries[0].created_at is not None


def test_repository_creates_parent_directory_and_is_reopenable(tmp_path: Path):
    path = tmp_path / "nested" / "dir" / "r.db"
    ReviewRepository(path).save(_result("rev_1"))
    assert ReviewRepository(path).get("rev_1") is not None


def test_flag_decisions_are_saved_per_review_and_flag_and_overwritable(tmp_path: Path):
    from app.db.reviews import FlagDecision

    repo = ReviewRepository(tmp_path / "r.db")
    repo.save(_result("rev_1"))

    repo.save_decision(
        FlagDecision(review_id="rev_1", flag_id="TX-1", decision="accepted", reviewer_note="ok")
    )
    repo.save_decision(
        FlagDecision(review_id="rev_1", flag_id="TX-1", decision="rejected", reviewer_note="no")
    )

    decisions = repo.list_decisions("rev_1")
    assert len(decisions) == 1
    assert decisions[0].decision == "rejected" and decisions[0].reviewer_note == "no"
    assert decisions[0].decided_at is not None
    assert repo.list_decisions("rev_other") == []


def test_decision_for_unknown_review_or_flag_is_rejected(tmp_path: Path):
    import pytest

    from app.db.reviews import FlagDecision, UnknownFlagError

    repo = ReviewRepository(tmp_path / "r.db")
    repo.save(_result("rev_1"))
    with pytest.raises(UnknownFlagError):
        repo.save_decision(FlagDecision(review_id="rev_1", flag_id="NOPE", decision="accepted"))
    with pytest.raises(UnknownFlagError):
        repo.save_decision(FlagDecision(review_id="rev_x", flag_id="TX-1", decision="accepted"))


def test_review_lifecycle_queued_running_done(tmp_path: Path):
    repo = ReviewRepository(tmp_path / "r.db")

    repo.create_pending("rev_9", "acme-2025")
    rec = repo.get_record("rev_9")
    assert rec is not None and rec.status == "queued" and rec.result is None

    repo.mark_running("rev_9")
    assert repo.get_record("rev_9").status == "running"  # type: ignore[union-attr]

    repo.save(_result("rev_9"))
    rec = repo.get_record("rev_9")
    assert rec.status == "done" and rec.result is not None and rec.error is None  # type: ignore[union-attr]
    assert repo.list_for_engagement("acme-2025")[0].status == "done"


def test_review_lifecycle_failed_keeps_error_and_no_result(tmp_path: Path):
    repo = ReviewRepository(tmp_path / "r.db")
    repo.create_pending("rev_9", "acme-2025")
    repo.mark_failed("rev_9", "AgentRunError: max_turns")
    rec = repo.get_record("rev_9")
    assert rec.status == "failed" and rec.error == "AgentRunError: max_turns"  # type: ignore[union-attr]
    assert repo.get("rev_9") is None  # no result to return
    summary = repo.list_for_engagement("acme-2025")[0]
    assert summary.status == "failed" and summary.flag_count == 0


def test_pending_review_is_listed_with_queued_status(tmp_path: Path):
    repo = ReviewRepository(tmp_path / "r.db")
    repo.create_pending("rev_q", "acme-2025")
    [summary] = repo.list_for_engagement("acme-2025")
    assert summary.status == "queued" and summary.overall_risk_level is None


def test_opening_a_pre_status_database_rebuilds_the_table_and_keeps_rows(tmp_path: Path):
    import sqlite3

    db = tmp_path / "old.db"
    with sqlite3.connect(db) as conn:  # the Milestone 3 schema: NOT NULL everywhere, no status
        conn.executescript(
            """
            CREATE TABLE reviews (
                review_id TEXT PRIMARY KEY, engagement_id TEXT NOT NULL, created_at TEXT NOT NULL,
                overall_risk_level TEXT NOT NULL, flag_count INTEGER NOT NULL, model TEXT NOT NULL,
                result_json TEXT NOT NULL
            );
            CREATE TABLE flag_decisions (
                review_id TEXT NOT NULL, flag_id TEXT NOT NULL, decision TEXT NOT NULL,
                reviewer_note TEXT NOT NULL DEFAULT '', decided_at TEXT NOT NULL,
                PRIMARY KEY (review_id, flag_id)
            );
            """
        )
        conn.execute(
            "INSERT INTO reviews VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "rev_old",
                "acme-2025",
                "2026-09-11T10:00:00+00:00",
                "high",
                1,
                "gpt-4.1-mini",
                _result("rev_old").model_dump_json(),
            ),
        )

    repo = ReviewRepository(db)

    old = repo.get_record("rev_old")
    assert old is not None and old.status == "done" and old.result is not None
    repo.create_pending("rev_new", "acme-2025")  # would violate the old NOT NULL constraints
    assert repo.get_record("rev_new").status == "queued"  # type: ignore[union-attr]
    assert ReviewRepository(db).get_record("rev_new") is not None  # migration is idempotent


def test_intermediate_schema_with_status_but_not_null_result_columns_is_rebuilt(tmp_path: Path):
    import sqlite3

    db = tmp_path / "mid.db"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            CREATE TABLE reviews (
                review_id TEXT PRIMARY KEY, engagement_id TEXT NOT NULL, created_at TEXT NOT NULL,
                overall_risk_level TEXT NOT NULL, flag_count INTEGER NOT NULL, model TEXT NOT NULL,
                result_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'done', error TEXT
            );
            """
        )
    repo = ReviewRepository(db)
    repo.create_pending("rev_new", "acme-2025")
    assert repo.get_record("rev_new").status == "queued"  # type: ignore[union-attr]
