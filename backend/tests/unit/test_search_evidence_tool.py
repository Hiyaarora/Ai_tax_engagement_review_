from app.models.evidence import EvidenceHit
from app.tools.search_evidence import SearchEvidenceArgs, SearchEvidenceTool


class _FakeEmbeddings:
    def embed(self, texts):
        return [[0.5, 0.5] for _ in texts]


class _FakeSearch:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def hybrid_search(self, query, query_vector, *, engagement_id, doc_types=None, top_k=5):
        self.calls.append(
            {
                "query": query,
                "vector": query_vector,
                "engagement_id": engagement_id,
                "doc_types": doc_types,
                "top_k": top_k,
            }
        )
        return [
            EvidenceHit(
                chunk_id="q-p1-c0",
                doc_id="q",
                doc_type="questionnaire",
                source_name="q.pdf",
                page=1,
                excerpt="Inventory in Texas? Yes",
                score=0.03,
            )
        ]


def test_tool_embeds_query_then_runs_scoped_hybrid_search():
    search = _FakeSearch()
    tool = SearchEvidenceTool(embeddings=_FakeEmbeddings(), search=search)  # type: ignore[arg-type]

    hits = tool.run(
        SearchEvidenceArgs(query="inventory in Texas", doc_types=["questionnaire"], top_k=3),
        engagement_id="acme-2025",
    )

    assert search.calls == [
        {
            "query": "inventory in Texas",
            "vector": [0.5, 0.5],
            "engagement_id": "acme-2025",
            "doc_types": ["questionnaire"],
            "top_k": 3,
        }
    ]
    assert hits[0].chunk_id == "q-p1-c0"


def test_args_bound_top_k_and_require_query():
    import pytest

    with pytest.raises(ValueError):
        SearchEvidenceArgs(query="", top_k=3)
    with pytest.raises(ValueError):
        SearchEvidenceArgs(query="x", top_k=50)
    assert SearchEvidenceArgs(query="x").top_k == 5
