"""The review output contract.

``ReviewDraft`` is exactly what the agent must return (enforced by a strict JSON schema on the
Foundry side and re-validated here). ``ReviewResult`` is the draft after the citation guard, plus
backend-owned metadata. The model never sets ``engagement_id`` or ``human_review_required``.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

RiskLevel = Literal["low", "medium", "high"]
RiskCategory = Literal[
    "physical_presence", "economic_nexus", "registration", "data_inconsistency", "other"
]

DISCLAIMER = (
    "Decision support only - not tax advice. Generated from SYNTHETIC data by an AI agent; "
    "every flag requires review by a qualified professional before any action is taken."
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Citation(_Strict):
    """A reference to a passage the agent actually retrieved via search_evidence."""

    chunk_id: str = Field(description="chunk_id exactly as returned by search_evidence.")
    source_name: str
    page: int
    quote: str = Field(description="Short verbatim excerpt (<= 300 chars) supporting the claim.")


class ToolFinding(_Strict):
    """A deterministic result the agent relied on, attributed to the tool that produced it."""

    tool: str = Field(description="Tool name, e.g. analyze_sales_by_state.")
    finding: str = Field(description="The specific figure or fact, e.g. 'TX revenue 620,000.00'.")


class RiskFlag(_Strict):
    id: str = Field(description="Stable slug, e.g. TX-PHYSICAL-PRESENCE.")
    title: str
    state: str | None = Field(description="Two-letter US state code (e.g. TX) or null.")
    category: RiskCategory
    risk_level: RiskLevel
    explanation: str = Field(description="AI analysis: why this may be a risk. Not a fact source.")
    retrieved_evidence: list[Citation]
    tool_findings: list[ToolFinding]
    recommended_human_action: str

    @field_validator("state")
    @classmethod
    def _two_letter_code(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[A-Z]{2}", value):
            raise ValueError("state must be a two-letter code or null")
        return value


class ReviewDraft(_Strict):
    overall_summary: str
    overall_risk_level: RiskLevel
    risk_flags: list[RiskFlag]
    states_reviewed_without_flags: list[str] = Field(
        description="States considered and deliberately not flagged (with sales or presence)."
    )


class UnverifiedQuote(BaseModel):
    chunk_id: str
    quote: str


class TokenUsage(BaseModel):
    """Cost and latency of one agent/model run, for the UI and for evaluation later."""

    input_tokens: int = 0
    output_tokens: int = 0
    turns: int = 0
    duration_ms: int = 0
    tool_durations_ms: dict[str, int] = Field(default_factory=dict)


class CitationGuardReport(BaseModel):
    """What the backend changed in the agent's draft. Non-empty lists are worth a human's look."""

    dropped_citations: list[str] = Field(
        default_factory=list, description="chunk_ids never retrieved"
    )
    corrected_citations: list[str] = Field(
        default_factory=list, description="chunk_ids whose source/page were fixed from the index"
    )
    unverified_quotes: list[UnverifiedQuote] = Field(
        default_factory=list, description="quotes not found in the cited chunk (cleared)"
    )
    dropped_tool_findings: list[str] = Field(default_factory=list, description="tools never called")
    flags_without_evidence: list[str] = Field(default_factory=list)


class ReviewResult(ReviewDraft):
    model_config = ConfigDict(extra="forbid")

    review_id: str
    engagement_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    model: str
    agent_name: str
    tool_calls: list[str] = Field(description="Tool names invoked during this review, in order.")
    citation_guard: CitationGuardReport
    usage: TokenUsage = Field(default_factory=TokenUsage)
    human_review_required: Literal[True] = True
    disclaimer: str = DISCLAIMER


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON schema in the shape OpenAI 'strict' structured outputs require.

    Every object gets ``additionalProperties: false`` and lists *all* properties as required.
    """
    schema = model.model_json_schema()

    def close(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            for value in node.values():
                close(value)
        elif isinstance(node, list):
            for item in node:
                close(item)

    close(schema)
    return schema
