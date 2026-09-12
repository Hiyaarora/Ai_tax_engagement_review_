"""Azure AI Document Intelligence wrapper (``prebuilt-layout``).

Turns a PDF/DOCX into a page-aware ``ParsedDocument`` so later stages can chunk with page numbers
for citations. Tables are rendered as Markdown so they stay retrievable as text.

Note: on the F0 (free) tier only the first 2 pages of each document are analyzed; S0 has no
such limit.
"""

from __future__ import annotations

import io
import re
from collections import defaultdict
from typing import Literal, Self

from azure.ai.documentintelligence import (
    DocumentIntelligenceAdministrationClient,
    DocumentIntelligenceClient,
)
from azure.ai.documentintelligence.models import (
    AnalyzeResult,
    BoundingRegion,
    DocumentSpan,
    DocumentTable,
)
from pydantic import BaseModel

from app.azure.credential import get_credential
from app.config import Settings

LAYOUT_MODEL_ID = "prebuilt-layout"

# Document Intelligence marks detected checkboxes inline; they are noise for retrieval.
_SELECTION_MARK = re.compile(r"\s*:(?:un)?selected:\s*")


class ParsedBlock(BaseModel):
    """One unit of page content in reading order: a paragraph, or a table rendered as Markdown."""

    kind: Literal["paragraph", "table"]
    text: str


class ParsedPage(BaseModel):
    page_number: int
    blocks: list[ParsedBlock]

    @property
    def paragraphs(self) -> list[str]:
        return [b.text for b in self.blocks if b.kind == "paragraph"]

    @property
    def tables(self) -> list[str]:
        return [b.text for b in self.blocks if b.kind == "table"]

    @property
    def text(self) -> str:
        """Page content as plain text in reading order, blank-line separated."""
        return "\n\n".join(b.text for b in self.blocks)


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


def _clean(text: str) -> str:
    return _SELECTION_MARK.sub(" ", text).strip()


def _offset(spans: list[DocumentSpan] | None) -> int:
    return spans[0].offset if spans else 0


def _inside_any(spans: list[DocumentSpan] | None, ranges: list[tuple[int, int]]) -> bool:
    """True if the element's first span starts inside one of the given (start, end) ranges."""
    if not spans:
        return False
    offset = spans[0].offset
    return any(start <= offset < end for start, end in ranges)


def _table_to_markdown(table: DocumentTable) -> str:
    grid = [["" for _ in range(table.column_count)] for _ in range(table.row_count)]
    for cell in table.cells:
        grid[cell.row_index][cell.column_index] = _clean((cell.content or "").replace("\n", " "))
    rows = ["| " + " | ".join(row) + " |" for row in grid]
    separator = "| " + " | ".join("---" for _ in range(table.column_count)) + " |"
    return "\n".join([rows[0], separator, *rows[1:]]) if rows else ""


def parse_analyze_result(result: AnalyzeResult, *, source_name: str) -> ParsedDocument:
    """Normalise the SDK's flat AnalyzeResult into pages. Pure function - no I/O.

    Layout output lists every table cell as a paragraph *and* inside the table; paragraphs whose
    span falls within a table are dropped so each fact is indexed once, with its row context.
    """
    table_ranges = [
        (span.offset, span.offset + span.length)
        for table in result.tables or []
        for span in table.spans or []
    ]
    # (page, reading-order offset, block)
    ordered: list[tuple[int, int, ParsedBlock]] = []
    for paragraph in result.paragraphs or []:
        if _inside_any(paragraph.spans, table_ranges):
            continue
        text = _clean(paragraph.content or "")
        if text:
            page_no = _page_of(paragraph.bounding_regions)
            ordered.append(
                (page_no, _offset(paragraph.spans), ParsedBlock(kind="paragraph", text=text))
            )
    for table in result.tables or []:
        page_no = _page_of(table.bounding_regions)
        block = ParsedBlock(kind="table", text=_table_to_markdown(table))
        ordered.append((page_no, _offset(table.spans), block))
    ordered.sort(key=lambda item: (item[0], item[1]))

    blocks_by_page: dict[int, list[ParsedBlock]] = defaultdict(list)
    for page_no, _, block in ordered:
        blocks_by_page[page_no].append(block)

    pages = [
        ParsedPage(page_number=page.page_number, blocks=blocks_by_page.get(page.page_number, []))
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
        timeout = settings.azure_timeout_seconds
        return cls(
            client=DocumentIntelligenceClient(endpoint, credential, read_timeout=timeout),
            admin_client=DocumentIntelligenceAdministrationClient(
                endpoint, credential, read_timeout=timeout
            ),
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
