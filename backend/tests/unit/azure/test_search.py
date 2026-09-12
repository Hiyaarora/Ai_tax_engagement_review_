from app.azure.search import SearchService
from app.config import Settings


class _FakeIndexClient:
    def __init__(self, names: list[str]) -> None:
        self._names = names
        self.stats_calls = 0

    def list_index_names(self):
        yield from self._names

    def get_service_statistics(self):
        self.stats_calls += 1
        return {"counters": {"documentCount": {"usage": 0}}}


def _service(client: _FakeIndexClient) -> SearchService:
    return SearchService(index_client=client, index_name="fd-evidence")  # type: ignore[arg-type]


def test_index_exists_true_when_index_listed():
    assert _service(_FakeIndexClient(["fd-evidence"])).index_exists() is True


def test_index_exists_false_when_index_missing():
    assert _service(_FakeIndexClient(["other"])).index_exists() is False


def test_ping_calls_service_statistics():
    client = _FakeIndexClient([])
    _service(client).ping()
    assert client.stats_calls == 1


def test_from_settings_targets_configured_endpoint_and_index():
    settings = Settings(
        _env_file=None,
        azure_search_endpoint="https://example.search.windows.net",
        azure_search_index_name="fd-evidence",
    )
    service = SearchService.from_settings(settings)
    assert service.endpoint == "https://example.search.windows.net"
    assert service.index_name == "fd-evidence"


# --- Stage 2: index definition, create, upsert, hybrid query ---------------------------------

from azure.search.documents.indexes.models import SearchIndex  # noqa: E402

from app.azure.embeddings import EMBEDDING_DIMENSIONS  # noqa: E402
from app.azure.search import build_index_definition  # noqa: E402
from app.models.evidence import EvidenceChunk, EvidenceHit  # noqa: E402


def test_index_definition_has_citation_fields_and_a_1536_dim_vector():
    index = build_index_definition("fd-evidence")
    assert isinstance(index, SearchIndex)
    assert index.name == "fd-evidence"
    fields = {f.name: f for f in index.fields}
    assert fields["chunk_id"].key is True
    assert fields["engagement_id"].filterable is True
    assert fields["doc_type"].filterable is True
    assert fields["page"].filterable is True
    assert fields["content"].searchable is True
    assert fields["content_vector"].vector_search_dimensions == EMBEDDING_DIMENSIONS
    assert index.vector_search is not None and index.vector_search.profiles


class _FakeSearchClient:
    def __init__(self) -> None:
        self.uploaded: list[dict] = []
        self.deleted: list[dict] = []
        self.search_calls: list[dict] = []
        self.existing: list[dict] = []

    def delete_documents(self, documents):
        self.deleted.extend(documents)
        return [type("R", (), {"succeeded": True, "key": d["chunk_id"]})() for d in documents]

    def upload_documents(self, documents):
        self.uploaded.extend(documents)
        return [type("R", (), {"succeeded": True, "key": d["chunk_id"]})() for d in documents]

    def search(self, search_text, **kwargs):
        self.search_calls.append({"search_text": search_text, **kwargs})
        if self.existing:
            return iter(self.existing)
        return iter(
            [
                {
                    "chunk_id": "doc1-p1-c0",
                    "doc_id": "doc1",
                    "doc_type": "questionnaire",
                    "source_name": "q.pdf",
                    "page": 1,
                    "content": "Inventory in Texas? Yes",
                    "@search.score": 0.031,
                }
            ]
        )


class _FakeIndexClientV2(_FakeIndexClient):
    def __init__(self, names: list[str]) -> None:
        super().__init__(names)
        self.created: list[SearchIndex] = []
        self.search_client = _FakeSearchClient()

    def create_or_update_index(self, index):
        self.created.append(index)
        return index

    def get_search_client(self, name):
        return self.search_client


def test_create_index_if_missing_creates_only_when_absent():
    absent = _FakeIndexClientV2([])
    assert _service(absent).create_index_if_missing() is True
    assert absent.created[0].name == "fd-evidence"

    present = _FakeIndexClientV2(["fd-evidence"])
    assert _service(present).create_index_if_missing() is False
    assert present.created == []


def _chunk(i: int) -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=f"doc1-p1-c{i}",
        engagement_id="acme-2025",
        doc_id="doc1",
        doc_type="questionnaire",
        source_name="q.pdf",
        page=1,
        content=f"chunk {i}",
    )


def test_upsert_chunks_pairs_each_chunk_with_its_vector():
    client = _FakeIndexClientV2(["fd-evidence"])
    count = _service(client).upsert_chunks([_chunk(0), _chunk(1)], [[0.1] * 3, [0.2] * 3])
    assert count == 2
    docs = client.search_client.uploaded
    assert docs[0]["chunk_id"] == "doc1-p1-c0" and docs[0]["content_vector"] == [0.1] * 3
    assert docs[1]["chunk_id"] == "doc1-p1-c1" and docs[1]["content_vector"] == [0.2] * 3
    assert docs[0]["engagement_id"] == "acme-2025"


def test_upsert_chunks_rejects_mismatched_lengths():
    import pytest

    with pytest.raises(ValueError):
        _service(_FakeIndexClientV2([])).upsert_chunks([_chunk(0)], [])


def test_hybrid_search_scopes_to_engagement_plus_shared_and_returns_hits():
    client = _FakeIndexClientV2(["fd-evidence"])

    hits = _service(client).hybrid_search(
        "inventory in Texas", [0.5] * 3, engagement_id="acme-2025", top_k=5
    )

    call = client.search_client.search_calls[0]
    assert call["search_text"] == "inventory in Texas"
    assert call["filter"] == "(engagement_id eq 'acme-2025' or engagement_id eq 'shared')"
    assert call["top"] == 5
    assert call["vector_queries"][0].vector == [0.5] * 3
    assert call["vector_queries"][0].fields == "content_vector"
    assert hits == [
        EvidenceHit(
            chunk_id="doc1-p1-c0",
            doc_id="doc1",
            doc_type="questionnaire",
            source_name="q.pdf",
            page=1,
            excerpt="Inventory in Texas? Yes",
            score=0.031,
        )
    ]


def test_hybrid_search_adds_doc_type_filter_when_given():
    client = _FakeIndexClientV2(["fd-evidence"])
    _service(client).hybrid_search(
        "q", [0.5] * 3, engagement_id="acme-2025", doc_types=["questionnaire", "reference"]
    )
    call = client.search_client.search_calls[0]
    assert call["filter"] == (
        "(engagement_id eq 'acme-2025' or engagement_id eq 'shared')"
        " and search.in(doc_type, 'questionnaire,reference', ',')"
    )


def test_hybrid_search_rejects_quote_in_engagement_id():
    import pytest

    with pytest.raises(ValueError):
        _service(_FakeIndexClientV2([])).hybrid_search("q", [0.1], engagement_id="a' or 1 eq 1")


def test_delete_document_chunks_removes_every_chunk_of_that_doc_in_that_engagement():
    client = _FakeIndexClientV2(["fd-evidence"])
    client.search_client.existing = [{"chunk_id": "doc1-p1-c0"}, {"chunk_id": "doc1-p2-c0"}]

    deleted = _service(client).delete_document_chunks(doc_id="doc1", engagement_id="acme-2025")

    assert deleted == 2
    assert client.search_client.search_calls[0]["filter"] == (
        "engagement_id eq 'acme-2025' and doc_id eq 'doc1'"
    )
    assert client.search_client.deleted == [{"chunk_id": "doc1-p1-c0"}, {"chunk_id": "doc1-p2-c0"}]


def test_recreate_index_deletes_then_creates():
    client = _FakeIndexClientV2(["fd-evidence"])
    client.deleted_indexes: list[str] = []  # type: ignore[attr-defined]
    client.delete_index = lambda name: client.deleted_indexes.append(name)  # type: ignore[attr-defined]

    _service(client).recreate_index()

    assert client.deleted_indexes == ["fd-evidence"]  # type: ignore[attr-defined]
    assert client.created[0].name == "fd-evidence"


def test_delete_engagement_chunks_removes_everything_under_the_engagement():
    client = _FakeIndexClientV2(["fd-evidence"])
    client.search_client.existing = [{"chunk_id": "a-p1-c0"}, {"chunk_id": "b-p1-c0"}]

    deleted = _service(client).delete_engagement_chunks("acme-2025")

    assert deleted == 2
    assert client.search_client.search_calls[0]["filter"] == "engagement_id eq 'acme-2025'"
    assert client.search_client.deleted == [{"chunk_id": "a-p1-c0"}, {"chunk_id": "b-p1-c0"}]
