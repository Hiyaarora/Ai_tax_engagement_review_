"""Azure AI Document Intelligence wrapper (``prebuilt-layout``).

Turns a PDF/DOCX into a page-aware ``ParsedDocument`` so later stages can chunk with page numbers
for citations. Tables are rendered as Markdown so they stay retrievable as text.

Note: the F0 (free) tier only analyzes the first 2 pages of each document.
"""

from __future__ import annotations

import io
from collections import defaultdict
from typing import Self

from azure.ai.documentintelligence import (
    DocumentIntelligenceAdministrationClient,
    DocumentIntelligenceClient,
)
from azure.ai.documentintelligence.models import AnalyzeResult, BoundingRegion, DocumentTable
from pydantic import BaseModel

from app.azure.credential import get_credential
from app.config import Settings

LAYOUT_MODEL_ID = "prebuilt-layout"


class ParsedTable(BaseModel):
    row_count: int
    column_count: int
    markdown: str


class ParsedPage(BaseModel):
    page_number: int
    paragraphs: list[str]
    tables: list[ParsedTable]

    @property
    def text(self) -> str:
        """Page content as plain text: paragraphs first, then tables, blank-line separated."""
        parts = [*self.paragraphs, *(table.markdown for table in self.tables)]
        return "\n\n".join(parts)


class ParsedDocument(BaseModel):
    source_name: str
    model_id: str
    pages: list[ParsedPage]

    @property
    def page_count(self) -> int:
        return len(self.pages)


def _page_of(bounding_regions: list[BoundingRegion] | None) -> int:
    """Page number of an element; layout output always places paragraphs/tables on a page."""
    if not bounding_regions:
        return 1
    return int(bounding_regions[0].page_number)


def _table_to_markdown(table: DocumentTable) -> str:
    grid = [["" for _ in range(table.column_count)] for _ in range(table.row_count)]
    for cell in table.cells:
        grid[cell.row_index][cell.column_index] = (cell.content or "").replace("\n", " ").strip()
    rows = ["| " + " | ".join(row) + " |" for row in grid]
    separator = "| " + " | ".join("---" for _ in range(table.column_count)) + " |"
    return "\n".join([rows[0], separator, *rows[1:]]) if rows else ""


def parse_analyze_result(result: AnalyzeResult, *, source_name: str) -> ParsedDocument:
    """Normalise the SDK's flat AnalyzeResult into pages. Pure function - no I/O."""
    paragraphs_by_page: dict[int, list[str]] = defaultdict(list)
    for paragraph in result.paragraphs or []:
        if paragraph.content:
            paragraphs_by_page[_page_of(paragraph.bounding_regions)].append(paragraph.content)

    tables_by_page: dict[int, list[ParsedTable]] = defaultdict(list)
    for table in result.tables or []:
        tables_by_page[_page_of(table.bounding_regions)].append(
            ParsedTable(
                row_count=table.row_count,
                column_count=table.column_count,
                markdown=_table_to_markdown(table),
            )
        )

    pages = [
        ParsedPage(
            page_number=page.page_number,
            paragraphs=paragraphs_by_page.get(page.page_number, []),
            tables=tables_by_page.get(page.page_number, []),
        )
        for page in result.pages or []
    ]
    return ParsedDocument(source_name=source_name, model_id=result.model_id, pages=pages)


class DocumentIntelligenceService:
    def __init__(
        self,
        client: DocumentIntelligenceClient,
        admin_client: DocumentIntelligenceAdministrationClient | None = None,
        endpoint: str = "",
    ) -> None:
        self._client = client
        self._admin_client = admin_client
        self.endpoint = endpoint

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        endpoint = settings.azure_document_intelligence_endpoint
        credential = get_credential()
        return cls(
            client=DocumentIntelligenceClient(endpoint, credential),
            admin_client=DocumentIntelligenceAdministrationClient(endpoint, credential),
            endpoint=endpoint,
        )

    def analyze_layout(self, content: bytes, *, source_name: str) -> ParsedDocument:
        """Run prebuilt-layout on raw file bytes (PDF, DOCX, images) and return parsed pages."""
        poller = self._client.begin_analyze_document(
            LAYOUT_MODEL_ID, io.BytesIO(content), content_type="application/octet-stream"
        )
        return parse_analyze_result(poller.result(), source_name=source_name)

    def ping(self) -> None:
        """Cheap authenticated call used by the connectivity check. Raises on failure."""
        if self._admin_client is None:
            raise RuntimeError("admin client not configured")
        self._admin_client.get_resource_details()
