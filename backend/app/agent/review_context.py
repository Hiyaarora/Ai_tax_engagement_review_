"""Per-review state owned by the backend, never by the model.

The context fixes *which* engagement a run is about and records what the run actually retrieved
and computed, so the citation guard can check every claim the agent makes against it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.engagement import EngagementData
from app.models.evidence import EvidenceHit


@dataclass
class ReviewContext:
    engagement_id: str
    data: EngagementData
    retrieved: dict[str, EvidenceHit] = field(default_factory=dict)  # chunk_id -> hit
    tool_calls: list[str] = field(default_factory=list)

    def record_hits(self, hits: list[EvidenceHit]) -> None:
        for hit in hits:
            self.retrieved[hit.chunk_id] = hit
