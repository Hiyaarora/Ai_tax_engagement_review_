"""Review orchestration: engagement data -> agent run -> validated, guarded, persisted result."""

from __future__ import annotations

import re
import secrets

from pydantic import ValidationError

from app.agent.citation_guard import apply_citation_guard
from app.agent.foundry_agent import FoundryAgentRunner
from app.agent.prompts import build_review_prompt
from app.agent.review_context import ReviewContext
from app.agent.tool_registry import ToolRegistry
from app.db.reviews import ReviewRepository, ReviewSummary
from app.models.review import ReviewDraft, ReviewResult
from app.services.engagement_data import EngagementDataRepository

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


class ReviewParseError(ValueError):
    pass


def parse_draft(text: str) -> ReviewDraft:
    """Validate the agent's final message. Accepts a bare JSON object or a ```json fence."""
    match = _FENCE.match(text)
    payload = match.group(1) if match else text
    try:
        return ReviewDraft.model_validate_json(payload)
    except ValidationError as exc:
        raise ReviewParseError(f"agent output did not match ReviewDraft: {exc}") from exc


class ReviewService:
    def __init__(
        self,
        engagements: EngagementDataRepository,
        registry: ToolRegistry,
        runner: FoundryAgentRunner,
        reviews: ReviewRepository,
    ) -> None:
        self._engagements = engagements
        self._registry = registry
        self._runner = runner
        self._reviews = reviews

    def run_review(self, engagement_id: str) -> ReviewResult:
        data = self._engagements.load(engagement_id)  # raises EngagementNotFoundError
        ctx = ReviewContext(engagement_id=engagement_id, data=data)
        document_names = [p.name for p in self._engagements.document_paths(engagement_id)]

        outcome = self._runner.run(
            build_review_prompt(data, document_names),
            dispatch=lambda name, args: self._registry.dispatch(name, args, ctx),
        )
        draft = parse_draft(outcome.output_text)
        guarded, report = apply_citation_guard(draft, ctx)

        result = ReviewResult(
            **guarded.model_dump(),
            review_id=f"rev_{secrets.token_hex(6)}",
            engagement_id=engagement_id,
            model=outcome.model,
            agent_name=self._runner.agent_name,
            tool_calls=list(ctx.tool_calls),
            citation_guard=report,
        )
        self._reviews.save(result)
        return result

    def get_review(self, review_id: str) -> ReviewResult | None:
        return self._reviews.get(review_id)

    def list_reviews(self, engagement_id: str) -> list[ReviewSummary]:
        return self._reviews.list_for_engagement(engagement_id)
