"""Run the golden set end to end, or re-score saved results offline.

Live mode builds each case as a throwaway engagement through the *normal* upload/process path,
runs the review agent, scores the result, saves it, and deletes the engagement again. Replay mode
re-scores saved results - no Azure needed - so scoring changes can be checked cheaply.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from app.models.review import ReviewResult
from evals.cases import EvalCase, load_cases, write_variant_files
from evals.judges import FlagJudgement
from evals.scoring import CaseScore, Summary, render_markdown, score_review, summarize

log = logging.getLogger(__name__)

RESULT_SUFFIX = ".result.json"
PASSAGES_SUFFIX = ".passages.json"


def save_case_result(out_dir: Path, case_id: str, result: ReviewResult) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{case_id}{RESULT_SUFFIX}"
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return path


def save_case_passages(out_dir: Path, case_id: str, passages: dict[str, str]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{case_id}{PASSAGES_SUFFIX}"
    path.write_text(json.dumps(passages, indent=2), encoding="utf-8")
    return path


def load_case_passages(out_dir: Path, case_id: str) -> dict[str, str]:
    path = out_dir / f"{case_id}{PASSAGES_SUFFIX}"
    if not path.is_file():
        return {}
    loaded: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def load_case_results(out_dir: Path) -> dict[str, ReviewResult]:
    cases = {c.case_id for c in load_cases()}
    results = {}
    for path in sorted(out_dir.glob(f"*{RESULT_SUFFIX}")):
        case_id = path.name[: -len(RESULT_SUFFIX)]
        if case_id in cases:
            results[case_id] = ReviewResult.model_validate_json(path.read_text(encoding="utf-8"))
    return results


def write_report(
    out_dir: Path,
    scores: list[CaseScore],
    judgements: list[FlagJudgement] | None = None,
) -> tuple[Summary, str]:
    summary = summarize(scores)
    report = render_markdown(summary, scores)
    if judgements:
        report += _render_judgements(judgements)
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    (out_dir / "summary.json").write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    (out_dir / "scores.json").write_text(
        json.dumps([s.model_dump() for s in scores], indent=2), encoding="utf-8"
    )
    if judgements:
        (out_dir / "judgements.json").write_text(
            json.dumps([j.model_dump() for j in judgements], indent=2), encoding="utf-8"
        )
    return summary, report


def _render_judgements(judgements: list[FlagJudgement]) -> str:
    scored = [j for j in judgements if j.groundedness is not None]
    if not scored:
        return ""
    mean_g = sum(j.groundedness or 0 for j in scored) / len(scored)
    mean_r = sum(j.relevance or 0 for j in scored) / len(scored)
    lines = [
        "",
        "## LLM-judged explanation quality (1-5)",
        "",
        f"- Mean groundedness: **{mean_g:.1f}** · mean relevance: **{mean_r:.1f}**"
        f" ({len(scored)} flags)",
        "",
        "| Case | Flag | Groundedness | Relevance |",
        "|---|---|---|---|",
    ]
    for j in judgements:
        lines.append(f"| {j.case_id} | {j.flag_id} | {j.groundedness} | {j.relevance} |")
    return "\n".join(lines) + "\n"


def replay(out_dir: Path) -> tuple[Summary, list[CaseScore], str]:
    """Score previously saved results. Offline."""
    by_id = {c.case_id: c for c in load_cases()}
    results = load_case_results(out_dir)
    scores = [score_review(by_id[case_id], result) for case_id, result in results.items()]
    summary, report = write_report(out_dir, scores)
    return summary, scores, report


def _cited_passages(settings: Any, result: ReviewResult) -> dict[str, str]:
    """Text of every chunk the review cites, read back from the index (before it is deleted)."""
    from app.azure.search import SearchService

    client = SearchService.from_settings(settings).search_client()
    passages: dict[str, str] = {}
    for flag in result.risk_flags:
        for citation in flag.retrieved_evidence:
            if citation.chunk_id in passages:
                continue
            try:
                document = client.get_document(key=citation.chunk_id, selected_fields=["content"])
                passages[citation.chunk_id] = str(document["content"])
            except Exception as exc:  # noqa: BLE001 - judging is best effort
                log.warning("could not fetch passage %s: %s", citation.chunk_id, exc)
    return passages


def run_case_live(case: EvalCase, out_dir: Path, *, workdir: Path) -> ReviewResult:
    """Build the case as a throwaway engagement, review it, save the result, delete it."""
    from app.api.dependencies import (
        build_engagement_service,
        build_processing_service,
        build_review_service,
    )
    from app.config import get_settings

    settings = get_settings()
    engagements = build_engagement_service(settings)
    processing = build_processing_service(settings)
    reviews = build_review_service(settings)

    detail = engagements.create(company_name=f"Eval {case.case_id}", home_state="CO", tax_year=2025)
    engagement_id = detail.engagement.engagement_id
    try:
        for path in write_variant_files(case, workdir / case.case_id):
            engagements.save_upload(
                engagement_id, path.name, path.read_bytes(), doc_type=None, allow_internal=True
            )
        started = time.perf_counter()
        processing.process_engagement(engagement_id)
        log.info("%s: indexed in %.0fs", case.case_id, time.perf_counter() - started)
        failed = [d for d in engagements.detail(engagement_id).documents if d.status == "failed"]
        if failed:
            raise RuntimeError(
                f"{case.case_id}: indexing failed for {[d.file_name for d in failed]}"
            )
        result = reviews.run_review(engagement_id)
        save_case_result(out_dir, case.case_id, result)
        save_case_passages(out_dir, case.case_id, _cited_passages(settings, result))
        return result
    finally:
        processing.delete_engagement_chunks(engagement_id)
        reviews.delete_for_engagement(engagement_id)
        engagements.delete(engagement_id)
