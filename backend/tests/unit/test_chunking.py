from app.azure.document_intelligence import ParsedBlock, ParsedDocument, ParsedPage
from app.models.evidence import EvidenceChunk
from app.services.chunking import chunk_document


def _doc(pages: list[ParsedPage]) -> ParsedDocument:
    return ParsedDocument(source_name="q.pdf", model_id="prebuilt-layout", pages=pages)


def _page(number: int, paragraphs: list[str], tables: list[str] | None = None) -> ParsedPage:
    blocks = [ParsedBlock(kind="paragraph", text=p) for p in paragraphs]
    blocks += [ParsedBlock(kind="table", text=t) for t in tables or []]
    return ParsedPage(page_number=number, blocks=blocks)


META = {"engagement_id": "acme-2025", "doc_id": "doc1", "doc_type": "questionnaire"}


def test_small_page_becomes_one_chunk_with_metadata_and_stable_id():
    doc = _doc([_page(1, ["Nexus Questionnaire", "Inventory in Texas? Yes"])])

    chunks = chunk_document(doc, **META)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert isinstance(chunk, EvidenceChunk)
    assert chunk.chunk_id == "doc1-p1-c0"
    assert chunk.page == 1
    assert chunk.content == "Nexus Questionnaire\n\nInventory in Texas? Yes"
    assert (chunk.engagement_id, chunk.doc_id, chunk.doc_type, chunk.source_name) == (
        "acme-2025",
        "doc1",
        "questionnaire",
        "q.pdf",
    )


def test_chunks_never_cross_page_boundaries():
    doc = _doc([_page(1, ["a"]), _page(2, ["b"])])
    chunks = chunk_document(doc, **META)
    assert [(c.page, c.content) for c in chunks] == [(1, "a"), (2, "b")]


def test_long_page_is_split_at_paragraph_boundaries_within_max_chars():
    paragraphs = [f"Paragraph {i} " + "x" * 90 for i in range(10)]  # ~100 chars each
    doc = _doc([_page(1, paragraphs)])

    chunks = chunk_document(doc, **META, max_chars=350)

    assert len(chunks) > 1
    assert all(len(c.content) <= 350 for c in chunks)
    assert [c.chunk_id for c in chunks] == [f"doc1-p1-c{i}" for i in range(len(chunks))]
    # Every paragraph still appears somewhere.
    joined = "\n".join(c.content for c in chunks)
    assert all(p in joined for p in paragraphs)


def test_consecutive_chunks_on_a_page_overlap_by_the_boundary_paragraph():
    paragraphs = [f"P{i} " + "y" * 60 for i in range(6)]
    doc = _doc([_page(1, paragraphs)])

    chunks = chunk_document(doc, **META, max_chars=200, overlap_chars=80)

    first_tail = chunks[0].content.split("\n\n")[-1]
    assert chunks[1].content.startswith(first_tail)


def test_oversize_paragraph_is_hard_split():
    doc = _doc([_page(1, ["z" * 1000])])
    chunks = chunk_document(doc, **META, max_chars=400)
    assert len(chunks) == 3
    assert "".join(c.content for c in chunks) == "z" * 1000


def test_tables_are_included_as_markdown_text():
    table = "| State | HC |\n| --- | --- |\n| WA | 2 |"
    doc = _doc([_page(1, ["Locations"], [table])])
    chunks = chunk_document(doc, **META)
    assert "| WA | 2 |" in chunks[0].content


def test_empty_pages_produce_no_chunks():
    doc = _doc([_page(1, []), _page(2, ["only this"])])
    chunks = chunk_document(doc, **META)
    assert [c.page for c in chunks] == [2]
