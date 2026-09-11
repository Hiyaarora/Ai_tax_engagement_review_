import json
from pathlib import Path

import pytest

from app.models.evidence import EvidenceHit
from app.services.ask_service import AskResult, AskService
from app.services.engagement_data import EngagementDataRepository
from app.tools.search_evidence import SearchEvidenceTool
from tests.conftest import SYNTHETIC_ROOT


class _FakeEmbeddings:
    def embed(self, texts):
        return [[0.1] for _ in texts]


class _FakeSearch:
    def __init__(self, hits: list[EvidenceHit]) -> None:
        self.hits = hits
        self.calls: list[dict] = []

    def hybrid_search(self, query, query_vector, *, engagement_id, doc_types=None, top_k=5):
        self.calls.append({"query": query, "engagement_id": engagement_id, "top_k": top_k})
        return self.hits


class _FakeChat:
    deployment = "gpt-4.1-mini"

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[dict] = []

    def complete_json(self, *, system, user, schema_name, schema):
        self.calls.append({"system": system, "user": user, "schema_name": schema_name})
        return self.reply


HIT = EvidenceHit(
    chunk_id="questionnaire-p1-c1",
    doc_id="questionnaire",
    doc_type="questionnaire",
    source_name="questionnaire.pdf",
    page=1,
    excerpt="| inventory_tx | Does the company hold inventory in Texas? | Yes | 3PL in Dallas. |",
    score=0.03,
)


def _service(
    chat: _FakeChat, hits: list[EvidenceHit] | None = None
) -> tuple[AskService, _FakeSearch]:
    search = _FakeSearch(hits if hits is not None else [HIT])
    tool = SearchEvidenceTool(embeddings=_FakeEmbeddings(), search=search)  # type: ignore[arg-type]
    return AskService(
        engagements=EngagementDataRepository(SYNTHETIC_ROOT), search_evidence=tool, chat=chat
    ), search  # type: ignore[arg-type]


def test_ask_returns_guarded_answer_with_passages(tmp_path: Path):
    chat = _FakeChat(
        json.dumps(
            {
                "answer": "Yes - inventory is held at a 3PL warehouse in Dallas, Texas.",
                "citations": [
                    {
                        "chunk_id": "questionnaire-p1-c1",
                        "quote": "Does the company hold inventory in Texas? Yes",
                    },
                    {"chunk_id": "made-up-p9-c9", "quote": "fabricated"},
                ],
                "found_in_documents": True,
            }
        )
    )
    service, search = _service(chat)

    result = service.ask("acme-2025", "Does the company hold inventory in Texas?")

    assert isinstance(result, AskResult)
    assert result.answer.startswith("Yes - inventory")
    assert [c.chunk_id for c in result.citations] == ["questionnaire-p1-c1"]
    assert result.citations[0].source_name == "questionnaire.pdf" and result.citations[0].page == 1
    assert result.citation_guard.dropped_citations == ["made-up-p9-c9"]
    assert [p.chunk_id for p in result.passages] == ["questionnaire-p1-c1"]
    assert result.found_in_documents is True
    assert search.calls[0]["engagement_id"] == "acme-2025"
    # The model only ever sees passages labelled by chunk_id, plus the guardrails.
    assert "questionnaire-p1-c1" in chat.calls[0]["user"]
    assert (
        "SYNTHETIC" in chat.calls[0]["system"]
        and "not tax advice" in chat.calls[0]["system"].lower()
    )


def test_ask_with_no_passages_short_circuits_without_calling_the_model():
    chat = _FakeChat("{}")
    service, _ = _service(chat, hits=[])

    result = service.ask("acme-2025", "Anything about Nevada?")

    assert chat.calls == []
    assert result.found_in_documents is False and result.citations == [] and result.passages == []
    assert "no relevant passages" in result.answer.lower()


def test_ask_rejects_blank_question_and_unknown_engagement():
    from app.services.engagement_data import EngagementNotFoundError

    service, _ = _service(_FakeChat("{}"))
    with pytest.raises(ValueError):
        service.ask("acme-2025", "   ")
    with pytest.raises(EngagementNotFoundError):
        service.ask("ghost-2025", "question")


def test_unparseable_model_output_raises_ask_error():
    from app.services.ask_service import AskError

    service, _ = _service(_FakeChat("not json"))
    with pytest.raises(AskError):
        service.ask("acme-2025", "question")
