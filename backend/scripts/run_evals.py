"""Evaluate the review agent against the golden set.

Usage (from backend/):
  uv run python -m scripts.run_evals                      # live: every case, deterministic scores
  uv run python -m scripts.run_evals --judge              # + LLM-judged groundedness/relevance
  uv run python -m scripts.run_evals --judge --upload     # + push judge run to Foundry Evaluations
  uv run python -m scripts.run_evals --cases acme-baseline tx-registered
  uv run python -m scripts.run_evals --replay evals/results/<run>   # offline re-score

Results land in evals/results/<timestamp>/ (report.md, summary.json, scores.json, *.result.json).
Live runs create throwaway engagements through the normal upload/process path and delete them.
"""

from __future__ import annotations

import argparse
import logging
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from evals.cases import load_cases
from evals.judges import FlagJudgement, judge_flags, judge_rows
from evals.runner import (
    load_case_passages,
    load_case_results,
    replay,
    run_case_live,
    write_report,
)
from evals.scoring import score_review

RESULTS_ROOT = Path(__file__).resolve().parents[1] / "evals" / "results"


def _upload_to_foundry(rows: list[dict[str, str]], out_dir: Path) -> str | None:
    """Run the same judges through the Evaluation SDK so the run appears in Foundry."""
    import json

    from azure.ai.evaluation import evaluate

    from app.config import get_settings
    from evals.judges import build_evaluators

    settings = get_settings()
    data_path = out_dir / "judge_rows.jsonl"
    data_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    groundedness, relevance = build_evaluators(settings)
    result = evaluate(
        data=str(data_path),
        evaluators={"groundedness": groundedness, "relevance": relevance},
        evaluation_name=f"fd-tax-review {out_dir.name}",
        azure_ai_project=settings.foundry_project_endpoint,
        output_path=str(out_dir / "foundry_evaluation.json"),
    )
    url = result.get("studio_url") if isinstance(result, dict) else None
    return str(url) if url else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", nargs="*", help="case ids to run (default: all)")
    parser.add_argument("--replay", type=Path, help="re-score saved results in this directory")
    parser.add_argument("--judge", action="store_true", help="LLM-judge flag explanations")
    parser.add_argument("--upload", action="store_true", help="push judge run to Foundry")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    for noisy in ("azure", "httpx", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if args.replay:
        summary, _, report = replay(args.replay)
        print(report)
        return 0 if summary.passed == summary.cases else 1

    out_dir = RESULTS_ROOT / datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    cases = [c for c in load_cases() if not args.cases or c.case_id in args.cases]
    with tempfile.TemporaryDirectory() as workdir:
        for case in cases:
            print(f"== {case.case_id}: {case.description}")
            run_case_live(case, out_dir, workdir=Path(workdir))

    results = load_case_results(out_dir)
    by_id = {c.case_id: c for c in cases}
    scores = [score_review(by_id[cid], result) for cid, result in results.items()]

    judgements: list[FlagJudgement] = []
    if args.judge:
        from app.config import get_settings
        from evals.judges import build_evaluators

        groundedness, relevance = build_evaluators(get_settings())
        rows = [
            row
            for cid, result in results.items()
            for row in judge_rows(cid, result, load_case_passages(out_dir, cid))
        ]
        judgements = judge_flags(rows, groundedness=groundedness, relevance=relevance)
        if args.upload:
            url = _upload_to_foundry(rows, out_dir)
            print(f"Foundry evaluation: {url or 'uploaded (no URL returned)'}")

    summary, report = write_report(out_dir, scores, judgements)
    print(report)
    print(f"results: {out_dir}")
    return 0 if summary.passed == summary.cases else 1


if __name__ == "__main__":
    raise SystemExit(main())
