from pathlib import Path

import pytest

from app.azure.document_intelligence import ParsedBlock, ParsedDocument, ParsedPage
from app.services.ingestion import IngestionResult, IngestionService, doc_id_for


class _FakeDI:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def analyze_layout(self, content: bytes, *, source_name: str) -> ParsedDocument:
        self.calls.append(source_name)
        return ParsedDocument(
            source_name=source_name,
            model_id="prebuilt-layout",
            pages=[
                ParsedPage(
                    page_number=1,
                    blocks=[ParsedBlock(kind="paragraph", text="Inventory in Texas? Yes")],
                ),
                ParsedPage(
                    page_number=2,
                    blocks=[ParsedBlock(kind="paragraph", text="Registered in Texas? No")],
                ),
            ],
        )


class _FakeEmbeddings:
    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.batches.append(texts)
        return [[float(len(t))] for t in texts]


class _FakeSearch:
    def __init__(self) -> None:
        self.upserts: list[tuple[list, list]] = []
        self.deletes: list[dict] = []

    def delete_document_chunks(self, *, doc_id: str, engagement_id: str) -> int:
        self.deletes.append({"doc_id": doc_id, "engagement_id": engagement_id})
        return 0

    def upsert_chunks(self, chunks, vectors) -> int:
        self.upserts.append((list(chunks), list(vectors)))
        return len(chunks)


def _service() -> tuple[IngestionService, _FakeDI, _FakeEmbeddings, _FakeSearch]:
    di, emb, search = _FakeDI(), _FakeEmbeddings(), _FakeSearch()
    return (
        IngestionService(document_intelligence=di, embeddings=emb, search=search),
        di,
        emb,
        search,
    )  # type: ignore[arg-type]


def test_ingest_pdf_parses_chunks_embeds_and_indexes(tmp_path: Path):
    pdf = tmp_path / "acme_nexus_questionnaire.pdf"
    pdf.write_bytes(b"%PDF-1.7 fake")
    service, di, emb, search = _service()

    result = service.ingest_file(pdf, engagement_id="acme-2025", doc_type="questionnaire")

    assert di.calls == ["acme_nexus_questionnaire.pdf"]
    assert result == IngestionResult(
        doc_id="acme_nexus_questionnaire",
        source_name="acme_nexus_questionnaire.pdf",
        engagement_id="acme-2025",
        doc_type="questionnaire",
        pages=2,
        chunks_indexed=2,
    )
    chunks, vectors = search.upserts[0]
    assert [c.chunk_id for c in chunks] == [
        "acme_nexus_questionnaire-p1-c0",
        "acme_nexus_questionnaire-p2-c0",
    ]
    assert emb.batches == [["Inventory in Texas? Yes", "Registered in Texas? No"]]
    assert vectors == [[23.0], [23.0]]


def test_ingest_embeds_in_batches(tmp_path: Path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF")
    service, _, emb, _ = _service()
    service.embed_batch_size = 1
    service.ingest_file(pdf, engagement_id="acme-2025", doc_type="questionnaire")
    assert len(emb.batches) == 2


def test_csv_is_rejected_as_structured_data(tmp_path: Path):
    csv = tmp_path / "sales.csv"
    csv.write_text("a,b\n1,2\n")
    service, di, _, _ = _service()
    with pytest.raises(ValueError, match="structured"):
        service.ingest_file(csv, engagement_id="acme-2025", doc_type="other")
    assert di.calls == []


def test_doc_id_is_a_safe_search_key():
    assert doc_id_for(Path("Acme Nexus (2025).pdf")) == "Acme_Nexus_2025"
    assert doc_id_for(Path("salt_reference_guide.pdf")) == "salt_reference_guide"


def test_ingest_deletes_stale_chunks_of_the_document_before_upserting(tmp_path: Path):
    pdf = tmp_path / "q.pdf"
    pdf.write_bytes(b"%PDF")
    service, _, _, search = _service()
    service.ingest_file(pdf, engagement_id="acme-2025", doc_type="questionnaire")
    assert search.deletes == [{"doc_id": "q", "engagement_id": "acme-2025"}]
