"""LLM-judged quality of flag explanations: Groundedness and Relevance (Azure AI Evaluation SDK).

Deterministic scoring says *which* flags were raised; these judges say whether each flag's
explanation is supported by the evidence it cites and answers the question a reviewer would ask.
Judges run keylessly against the same GPT-4.1-mini deployment. Optional: the deterministic scores
never depend on them.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from app.config import Settings
from app.models.review import ReviewResult

Evaluator = Callable[..., dict[str, Any]]


class FlagJudgement(BaseModel):
    case_id: str
    flag_id: str
    groundedness: float | None = None
    relevance: float | None = None
    groundedness_reason: str = ""
    relevance_reason: str = ""


def judge_rows(case_id: str, result: ReviewResult) -> list[dict[str, str]]:
    """One row per flag: the reviewer's question, the evidence the flag cites, and its analysis."""
    rows = []
    for flag in result.risk_flags:
        where = flag.state or "the engagement"
        evidence = [
            f"[{c.source_name} p.{c.page}] {c.quote}" for c in flag.retrieved_evidence if c.quote
        ]
        evidence += [f"[{f.tool}] {f.finding}" for f in flag.tool_findings]
        rows.append(
            {
                "case_id": case_id,
                "flag_id": flag.id,
                "query": f"Is there a potential nexus risk in {where}? ({flag.title})",
                "context": "\n".join(evidence) or "(no verified evidence)",
                "response": flag.explanation,
            }
        )
    return rows


def judge_flags(
    rows: list[dict[str, str]], *, groundedness: Evaluator, relevance: Evaluator
) -> list[FlagJudgement]:
    judgements = []
    for row in rows:
        g = groundedness(query=row["query"], context=row["context"], response=row["response"])
        r = relevance(query=row["query"], response=row["response"])
        judgements.append(
            FlagJudgement(
                case_id=row["case_id"],
                flag_id=row["flag_id"],
                groundedness=g.get("groundedness"),
                relevance=r.get("relevance"),
                groundedness_reason=str(g.get("groundedness_reason", "")),
                relevance_reason=str(r.get("relevance_reason", "")),
            )
        )
    return judgements


def build_evaluators(settings: Settings) -> tuple[Evaluator, Evaluator]:
    """Real judges on the project's chat deployment, authenticated with DefaultAzureCredential."""
    from azure.ai.evaluation import GroundednessEvaluator, RelevanceEvaluator

    from app.azure.credential import get_credential

    config = {
        "azure_endpoint": settings.foundry_resource_endpoint,
        "azure_deployment": settings.foundry_chat_deployment,
    }
    credential = get_credential()
    return (
        GroundednessEvaluator(config, credential=credential),
        RelevanceEvaluator(config, credential=credential),
    )
