"""Evidence chunks: the unit that is indexed in Azure AI Search and cited by the agent."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DocType = Literal["questionnaire", "locations", "reference", "other"]

# Reference guidance is indexed once under this engagement id and is visible to every engagement.
SHARED_ENGAGEMENT_ID = "shared"


class EvidenceChunk(BaseModel):
    """One retrievable passage. ``chunk_id`` is the citation key the agent must use."""

    chunk_id: str = Field(pattern=r"^[A-Za-z0-9_\-=]+$")  # Azure AI Search key charset
    engagement_id: str
    doc_id: str
    doc_type: DocType
    source_name: str
    page: int
    content: str


class EvidenceHit(BaseModel):
    """A retrieved chunk plus its relevance score - what ``search_evidence`` returns."""

    chunk_id: str
    doc_id: str
    doc_type: DocType
    source_name: str
    page: int
    excerpt: str
    score: float
