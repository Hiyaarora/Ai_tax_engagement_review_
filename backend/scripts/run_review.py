"""Run one live review from the command line and print the result.

Usage (from backend/):  uv run python -m scripts.run_review [--engagement acme-2025] [--json]
Requires az login and a configured backend/.env. Decision support only - not tax advice.
"""

from __future__ import annotations

import argparse
import time

from app.api.dependencies import build_review_service
from app.config import get_settings
from app.models.review import ReviewResult


def render(result: ReviewResult) -> str:
    lines = [
        f"review {result.review_id}  engagement={result.engagement_id}  model={result.model}",
        f"overall risk: {result.overall_risk_level.upper()}",
        f"tools called: {', '.join(result.tool_calls)}",
        f"citation guard: {result.citation_guard.model_dump(exclude_defaults=True) or 'clean'}",
        "",
        result.overall_summary,
        "",
    ]
    for flag in result.risk_flags:
        lines.append(f"[{flag.risk_level.upper():6}] {flag.id} - {flag.title} ({flag.category})")
        lines.append(f"    analysis: {flag.explanation}")
        for f in flag.tool_findings:
            lines.append(f"    computed:  {f.tool}: {f.finding}")
        for c in flag.retrieved_evidence:
            quote = f' "{c.quote}"' if c.quote else ""
            lines.append(f"    evidence:  {c.source_name} p.{c.page} [{c.chunk_id}]{quote}")
        lines.append(f"    action:    {flag.recommended_human_action}")
        lines.append("")
    lines.append(
        f"reviewed without flags: {', '.join(result.states_reviewed_without_flags) or '-'}"
    )
    lines.append(f"\n{result.disclaimer}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engagement", default="acme-2025")
    parser.add_argument("--json", action="store_true", help="print raw ReviewResult JSON")
    args = parser.parse_args(argv)

    service = build_review_service(get_settings())
    started = time.perf_counter()
    result = service.run_review(args.engagement)
    elapsed = time.perf_counter() - started
    print(result.model_dump_json(indent=2) if args.json else render(result))
    print(f"\n({elapsed:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
