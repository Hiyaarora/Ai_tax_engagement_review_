"""Review orchestration: engagement data -> agent run -> validated, guarded, persisted result.

Reviews run in the background: ``start_review`` queues a row and returns its id immediately;
``execute_review`` (called from a FastAPI BackgroundTask or the CLI) does the work and records
``running -> done | failed``. The UI polls ``get_record``.
"""

from __future__ import annotations

import logging
import re
import secrets

from pydantic import ValidationError

from app.agent.citation_guard import apply_citation_guard
from app.agent.foundry_agent import FoundryAgentRunner
from app.agent.prompts import build_review_prompt
from app.agent.review_context import ReviewContext
from app.agent.tool_registry import ToolRegistry
from app.db.reviews import FlagDecision, ReviewRecord, ReviewRepository, ReviewSummary
from app.models.review import ReviewDraft, ReviewResult
from app.services.engagement_data import EngagementDataRepository

log = logging.getLogger(__name__)

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

    # --- lifecycle ------------------------------------------------------------------------------

    def start_review(self, engagement_id: str) -> str:
        """Queue a review. Raises EngagementNotFoundError before anything is written."""
        self._engagements.directory(engagement_id)
        review_id = f"rev_{secrets.token_hex(6)}"
        self._reviews.create_pending(review_id, engagement_id)
        return review_id

    def execute_review(self, review_id: str) -> None:
        """Run a queued review to completion, recording success or failure. Never raises."""
        record = self._reviews.get_record(review_id)
        if record is None:
            log.error("execute_review: unknown review %s", review_id)
            return
        self._reviews.mark_running(review_id)
        try:
            result = self._run(record.engagement_id, review_id)
        except Exception as exc:  # noqa: BLE001 - status is the error channel here
            log.exception("review %s failed", review_id)
            self._reviews.mark_failed(review_id, f"{type(exc).__name__}: {exc}")
            return
        self._reviews.save(result)

    def run_review(self, engagement_id: str) -> ReviewResult:
        """Synchronous convenience for the CLI: queue, execute, and return the result or raise."""
        review_id = self.start_review(engagement_id)
        self._reviews.mark_running(review_id)
        try:
            result = self._run(engagement_id, review_id)
        except Exception as exc:
            self._reviews.mark_failed(review_id, f"{type(exc).__name__}: {exc}")
            raise
        self._reviews.save(result)
        return result

    def _run(self, engagement_id: str, review_id: str) -> ReviewResult:
        data = self._engagements.load(engagement_id)
        ctx = ReviewContext(engagement_id=engagement_id, data=data)
        document_names = [p.name for p in self._engagements.document_paths(engagement_id)]

        outcome = self._runner.run(
            build_review_prompt(data, document_names),
            dispatch=lambda name, args: self._registry.dispatch(name, args, ctx),
        )
        draft = parse_draft(outcome.output_text)
        guarded, report = apply_citation_guard(draft, ctx)
        return ReviewResult(
            **guarded.model_dump(),
            review_id=review_id,
            engagement_id=engagement_id,
            model=outcome.model,
            agent_name=self._runner.agent_name,
            tool_calls=list(ctx.tool_calls),
            citation_guard=report,
        )

    # --- reads / decisions ----------------------------------------------------------------------

    def get_record(self, review_id: str) -> ReviewRecord | None:
        return self._reviews.get_record(review_id)

    def get_review(self, review_id: str) -> ReviewResult | None:
        return self._reviews.get(review_id)

    def list_reviews(self, engagement_id: str) -> list[ReviewSummary]:
        return self._reviews.list_for_engagement(engagement_id)

    def delete_for_engagement(self, engagement_id: str) -> int:
        return self._reviews.delete_for_engagement(engagement_id)

    def list_decisions(self, review_id: str) -> list[FlagDecision]:
        return self._reviews.list_decisions(review_id)

    def decide_flag(self, decision: FlagDecision) -> FlagDecision:
        self._reviews.save_decision(decision)  # raises UnknownFlagError
        return decision
