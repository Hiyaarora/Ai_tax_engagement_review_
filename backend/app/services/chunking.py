"""Page-aware chunking of a ParsedDocument into EvidenceChunks.

Rules, in priority order:
1. A chunk never spans two pages - the page number is the citation unit.
2. Paragraphs (and tables, as Markdown) are packed whole until ``max_chars`` would be exceeded.
3. Consecutive chunks on the same page overlap by the boundary paragraph when it is short
   (<= ``overlap_chars``) so a question and its answer are not split apart.
4. A single paragraph longer than ``max_chars`` is hard-split into ``max_chars`` pieces.

Sizes are in characters (~4 chars per token): 1000 chars is roughly 250 tokens - small enough
that a questionnaire section or one table is its own citable chunk.
"""

from __future__ import annotations

from app.azure.document_intelligence import ParsedDocument
from app.models.evidence import DocType, EvidenceChunk

DEFAULT_MAX_CHARS = 1000
DEFAULT_OVERLAP_CHARS = 200
_SEPARATOR = "\n\n"


def _split_oversize(paragraph: str, max_chars: int) -> list[str]:
    return [paragraph[i : i + max_chars] for i in range(0, len(paragraph), max_chars)]


def _pack_page(parts: list[str], *, max_chars: int, overlap_chars: int) -> list[str]:
    """Pack a page's text parts into chunk bodies."""
    units: list[str] = []
    for part in parts:
        units.extend(_split_oversize(part, max_chars) if len(part) > max_chars else [part])

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for unit in units:
        added = len(unit) + (len(_SEPARATOR) if current else 0)
        if current and current_len + added > max_chars:
            chunks.append(_SEPARATOR.join(current))
            tail = current[-1]
            carry = (
                tail
                if len(tail) <= overlap_chars
                and len(tail) + len(_SEPARATOR) + len(unit) <= max_chars
                else None
            )
            current = [carry] if carry else []
            current_len = len(carry) if carry else 0
            added = len(unit) + (len(_SEPARATOR) if current else 0)
        current.append(unit)
        current_len += added
    if current:
        chunks.append(_SEPARATOR.join(current))
    return chunks


def chunk_document(
    doc: ParsedDocument,
    *,
    engagement_id: str,
    doc_id: str,
    doc_type: DocType,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[EvidenceChunk]:
    chunks: list[EvidenceChunk] = []
    for page in doc.pages:
        parts = [b.text for b in page.blocks if b.text.strip()]
        for n, body in enumerate(
            _pack_page(parts, max_chars=max_chars, overlap_chars=overlap_chars)
        ):
            chunks.append(
                EvidenceChunk(
                    chunk_id=f"{doc_id}-p{page.page_number}-c{n}",
                    engagement_id=engagement_id,
                    doc_id=doc_id,
                    doc_type=doc_type,
                    source_name=doc.source_name,
                    page=page.page_number,
                    content=body,
                )
            )
    return chunks
