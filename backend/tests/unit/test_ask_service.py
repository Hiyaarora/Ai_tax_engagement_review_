import json

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
    """Plays the model: optionally calls tools through ``dispatch`` first, then returns a draft."""

    deployment = "gpt-4.1-mini"

    def __init__(self, reply: dict | str, call_tools: list[str] | None = None) -> None:
        self.reply = reply
        self.call_tools = call_tools or []
        self.calls: list[dict] = []
        self.tool_outputs: dict[str, dict] = {}

    def complete_json(self, *, system, user, schema_name, schema, tools=None, dispatch=None, **_):
        self.calls.append({"system": system, "user": user, "tools": tools})
        for name in self.call_tools:
            assert dispatch is not None
            self.tool_outputs[name] = json.loads(dispatch(name, "{}"))
        return self.reply if isinstance(self.reply, str) else json.dumps(self.reply)


HIT = EvidenceHit(
    chunk_id="questionnaire-p1-c1",
    doc_id="questionnaire",
    doc_type="questionnaire",
    source_name="questionnaire.pdf",
    page=1,
    excerpt="| inventory_tx | Does the company hold inventory in Texas? | Yes | 3PL in Dallas. |",
    score=0.03,
)


def _service(chat: _FakeChat, hits: list[EvidenceHit] | None = None):
    search = _FakeSearch(hits if hits is not None else [HIT])
    tool = SearchEvidenceTool(embeddings=_FakeEmbeddings(), search=search)  # type: ignore[arg-type]
    service = AskService(
        engagements=EngagementDataRepository(SYNTHETIC_ROOT),
        search_evidence=tool,
        chat=chat,  # type: ignore[arg-type]
    )
    return service, search


def _draft(answer: str, citations=(), findings=(), found=True) -> dict:
    return {
        "answer": answer,
        "citations": list(citations),
        "tool_findings": list(findings),
        "found_in_documents": found,
    }


# (d) existing document-only question still works ------------------------------------------------


def test_document_only_question_returns_guarded_answer_with_passages():
    chat = _FakeChat(
        _draft(
            "Yes - inventory is held at a 3PL warehouse in Dallas, Texas.",
            citations=[
                {
                    "chunk_id": "questionnaire-p1-c1",
                    "quote": "Does the company hold inventory in Texas? Yes",
                },
                {"chunk_id": "made-up-p9-c9", "quote": "fabricated"},
            ],
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
    assert result.structured_evidence == [] and result.tool_calls == []
    assert search.calls[0]["engagement_id"] == "acme-2025"
    assert "questionnaire-p1-c1" in chat.calls[0]["user"]
    assert "SYNTHETIC" in chat.calls[0]["system"]


def test_model_is_offered_only_the_sales_tool():
    chat = _FakeChat(_draft("x"))
    service, _ = _service(chat)
    service.ask("acme-2025", "anything")
    assert [t["name"] for t in chat.calls[0]["tools"]] == ["analyze_sales_by_state"]
    assert chat.calls[0]["tools"][0]["type"] == "function"


# (a) direct sales question -----------------------------------------------------------------------


def test_direct_sales_question_uses_the_sales_tool_on_sales_csv():
    chat = _FakeChat(
        _draft(
            "Texas sales for 2025 total $620,000.00 across 900 transactions.",
            findings=[
                {"tool": "analyze_sales_by_state", "finding": "TX revenue 620,000.00"},
                {"tool": "analyze_sales_by_state", "finding": "TX transactions 900"},
            ],
        ),
        call_tools=["analyze_sales_by_state"],
    )
    service, _ = _service(chat, hits=[])

    result = service.ask("acme-2025", "What are the sales and transactions in Texas?")

    # The tool ran on the real committed sales.csv through the existing registry dispatch.
    states = chat.tool_outputs["analyze_sales_by_state"]["states"]
    tx = next(s for s in states if s["state"] == "TX")
    assert tx["revenue_usd"] == 620000.0 and tx["transactions"] == 900
    assert result.tool_calls == ["analyze_sales_by_state"]
    assert result.found_in_documents is True
    assert result.citations == [] and result.passages == []
    assert [e.finding for e in result.structured_evidence] == [
        "TX revenue 620,000.00",
        "TX transactions 900",
    ]


# (e) sales source is represented separately from document citations -------------------------------


def test_structured_evidence_is_attributed_to_sales_csv_not_a_document_chunk():
    chat = _FakeChat(
        _draft(
            "TX revenue is 620,000.00.",
            findings=[{"tool": "analyze_sales_by_state", "finding": "TX revenue 620,000.00"}],
        ),
        call_tools=["analyze_sales_by_state"],
    )
    service, _ = _service(chat, hits=[])
    result = service.ask("acme-2025", "What are the sales in Texas?")
    assert [e.model_dump() for e in result.structured_evidence] == [
        {
            "tool": "analyze_sales_by_state",
            "source": "sales.csv",
            "finding": "TX revenue 620,000.00",
        }
    ]
    assert result.citations == []  # never dressed up as a search chunk/page citation


# (b) mixed question: documents + sales -----------------------------------------------------------


def test_mixed_question_combines_document_citations_and_sales_findings():
    chat = _FakeChat(
        _draft(
            "Texas may carry potential nexus risk: a Dallas 3PL and $620,000 of sales.",
            citations=[{"chunk_id": "questionnaire-p1-c1", "quote": "3PL in Dallas"}],
            findings=[{"tool": "analyze_sales_by_state", "finding": "TX revenue 620,000.00"}],
        ),
        call_tools=["analyze_sales_by_state"],
    )
    service, _ = _service(chat)

    result = service.ask(
        "acme-2025", "Does Texas have potential nexus risk based on our sales and inventory?"
    )

    assert [c.chunk_id for c in result.citations] == ["questionnaire-p1-c1"]
    assert [e.source for e in result.structured_evidence] == ["sales.csv"]
    assert result.tool_calls == ["analyze_sales_by_state"]
    assert result.citation_guard.dropped_citations == []
    assert result.citation_guard.dropped_tool_findings == []


# (c) unrelated question must not invent sales data ------------------------------------------------


def test_sales_findings_are_dropped_when_the_tool_was_not_called():
    chat = _FakeChat(
        _draft(
            "Texas sales are about $1 million.",  # invented - the tool never ran
            findings=[{"tool": "analyze_sales_by_state", "finding": "TX revenue 1,000,000.00"}],
            found=True,  # the model's claim does not count
        )
    )
    service, _ = _service(chat, hits=[])

    result = service.ask("acme-2025", "What are the sales in Texas?")

    assert result.structured_evidence == []
    assert result.citation_guard.dropped_tool_findings == ["analyze_sales_by_state"]
    assert result.tool_calls == []
    assert result.found_in_documents is False  # nothing verified -> not found


def test_found_is_true_when_only_tool_figures_support_the_answer_even_if_model_says_otherwise():
    chat = _FakeChat(
        _draft(
            "TX revenue 620,000.00.",
            findings=[{"tool": "analyze_sales_by_state", "finding": "TX revenue 620,000.00"}],
            found=False,  # model read "documents" literally
        ),
        call_tools=["analyze_sales_by_state"],
    )
    service, _ = _service(chat, hits=[])
    assert service.ask("acme-2025", "Sales in Texas?").found_in_documents is True


def test_unrelated_question_with_no_passages_and_no_tool_reports_not_found():
    chat = _FakeChat(_draft("The documents do not cover cryptocurrency policy.", found=False))
    service, _ = _service(chat, hits=[])

    result = service.ask("acme-2025", "What is the policy on cryptocurrency payments?")

    assert result.found_in_documents is False
    assert result.citations == [] and result.structured_evidence == [] and result.passages == []


# errors / validation ----------------------------------------------------------------------------


def test_ask_rejects_blank_question_and_unknown_engagement():
    from app.services.engagement_data import EngagementNotFoundError

    service, _ = _service(_FakeChat(_draft("x")))
    with pytest.raises(ValueError):
        service.ask("acme-2025", "   ")
    with pytest.raises(EngagementNotFoundError):
        service.ask("ghost-2025", "question")


def test_unparseable_model_output_raises_ask_error():
    from app.services.ask_service import AskError

    service, _ = _service(_FakeChat("not json"))
    with pytest.raises(AskError):
        service.ask("acme-2025", "question")
