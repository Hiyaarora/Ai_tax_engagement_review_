from azure.ai.documentintelligence.models import (
    AnalyzeResult,
    DocumentPage,
    DocumentParagraph,
    DocumentTable,
    DocumentTableCell,
)

from app.azure.document_intelligence import (
    LAYOUT_MODEL_ID,
    DocumentIntelligenceService,
    ParsedDocument,
    parse_analyze_result,
)
from app.config import Settings


def _layout_result() -> AnalyzeResult:
    """A minimal two-page layout result shaped like the real prebuilt-layout output."""
    return AnalyzeResult(
        api_version="2024-11-30",
        model_id=LAYOUT_MODEL_ID,
        content="Nexus Questionnaire\nDo you hold inventory in Texas? Yes\nOffice locations",
        pages=[DocumentPage(page_number=1, unit="inch"), DocumentPage(page_number=2, unit="inch")],
        paragraphs=[
            DocumentParagraph(
                content="Nexus Questionnaire",
                role="title",
                bounding_regions=[{"pageNumber": 1, "polygon": []}],
            ),
            DocumentParagraph(
                content="Do you hold inventory in Texas? Yes",
                bounding_regions=[{"pageNumber": 1, "polygon": []}],
            ),
            DocumentParagraph(
                content="Office locations",
                bounding_regions=[{"pageNumber": 2, "polygon": []}],
            ),
        ],
        tables=[
            DocumentTable(
                row_count=2,
                column_count=2,
                bounding_regions=[{"pageNumber": 2, "polygon": []}],
                cells=[
                    DocumentTableCell(row_index=0, column_index=0, content="State"),
                    DocumentTableCell(row_index=0, column_index=1, content="Headcount"),
                    DocumentTableCell(row_index=1, column_index=0, content="TX"),
                    DocumentTableCell(row_index=1, column_index=1, content="12"),
                ],
            )
        ],
    )


def test_parse_groups_paragraphs_by_page():
    doc = parse_analyze_result(_layout_result(), source_name="questionnaire.pdf")
    assert isinstance(doc, ParsedDocument)
    assert doc.source_name == "questionnaire.pdf"
    assert doc.page_count == 2
    assert doc.pages[0].page_number == 1
    assert doc.pages[0].paragraphs == [
        "Nexus Questionnaire",
        "Do you hold inventory in Texas? Yes",
    ]
    assert doc.pages[1].paragraphs == ["Office locations"]


def test_parse_renders_tables_as_markdown_on_their_page():
    doc = parse_analyze_result(_layout_result(), source_name="q.pdf")
    assert doc.pages[0].tables == []
    assert len(doc.pages[1].tables) == 1
    assert doc.pages[1].tables[0].markdown == "| State | Headcount |\n| --- | --- |\n| TX | 12 |"


def test_page_text_joins_paragraphs_and_tables():
    doc = parse_analyze_result(_layout_result(), source_name="q.pdf")
    assert (
        doc.pages[1].text == "Office locations\n\n| State | Headcount |\n| --- | --- |\n| TX | 12 |"
    )


def test_parse_handles_result_with_no_paragraphs_or_tables():
    result = AnalyzeResult(
        api_version="2024-11-30",
        model_id=LAYOUT_MODEL_ID,
        content="",
        pages=[DocumentPage(page_number=1, unit="inch")],
    )
    doc = parse_analyze_result(result, source_name="empty.pdf")
    assert doc.page_count == 1
    assert doc.pages[0].text == ""


class _FakePoller:
    def __init__(self, result: AnalyzeResult) -> None:
        self._result = result

    def result(self) -> AnalyzeResult:
        return self._result


class _FakeAnalysisClient:
    """Stands in for DocumentIntelligenceClient; records the call, returns a canned result."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def begin_analyze_document(self, model_id, body, **kwargs):
        self.calls.append({"model_id": model_id, "body": body, **kwargs})
        return _FakePoller(_layout_result())


def test_service_analyze_layout_uses_prebuilt_layout_with_raw_bytes():
    client = _FakeAnalysisClient()
    service = DocumentIntelligenceService(client=client)  # type: ignore[arg-type]

    doc = service.analyze_layout(b"%PDF-1.7 ...", source_name="questionnaire.pdf")

    assert doc.page_count == 2
    assert client.calls[0]["model_id"] == LAYOUT_MODEL_ID
    assert client.calls[0]["body"].read() == b"%PDF-1.7 ..."
    assert client.calls[0]["content_type"] == "application/octet-stream"


def test_service_from_settings_targets_configured_endpoint():
    settings = Settings(
        _env_file=None,
        azure_document_intelligence_endpoint="https://example.cognitiveservices.azure.com/",
    )
    service = DocumentIntelligenceService.from_settings(settings)
    assert service.endpoint == "https://example.cognitiveservices.azure.com/"
