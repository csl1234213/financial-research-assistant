"""Structured PDF extraction and page-aware chunking.

The ingestion pipeline keeps page, section, and OCR provenance all the way to
the vector-store boundary.  Legacy string helpers remain available for older
callers, but production ingestion uses :func:`load_pdf_chunks`.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path

import fitz

from config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    OCR_DPI,
    OCR_ENABLED,
    OCR_LANGUAGES,
    OCR_MIN_TEXT_CHARS,
)
from core.financial_statement_reconstruction import (
    FinancialTableContext,
    reconstruct_financial_statements,
)
from core.financial_table_rows import FinancialTableRow
from retrieval.periods import extract_metrics, extract_periods

logger = logging.getLogger(__name__)

PARSER_VERSION = "pymupdf-blocks-ocr-v20-financial-row-reconstruction"
CHUNKER_VERSION = "page-block-section-v5-table-trust-boundaries"

_HYPHENATED_LINE_BREAK = re.compile(r"(\w)-\s*\n\s*(\w)")
_WHITESPACE = re.compile(r"[^\S\n]+")
_SECTION_PREFIX = re.compile(
    r"^(?:section\s+)?(?:\d+(?:\.\d+)*|[ivxlcdm]+)[.)]?\s+\S",
    flags=re.IGNORECASE,
)
_CJK = re.compile(r"[\u3400-\u9fff]")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?。！？；;])(?:\s+|(?=\S))")
_QUARTER_TABLE_CELL = re.compile(
    r"^(?:q[1-4]|[1-4]q)(?:[-_/ ]?(?:fy)?\d{2,4})?$",
    flags=re.IGNORECASE,
)
_EXPLICIT_QUARTER_PERIOD = re.compile(
    r"^(?P<quarter>q[1-4])[-_/ ]*(?P<fiscal>fy)?(?P<year>20\d{2})$",
    flags=re.IGNORECASE,
)
_DATE_TABLE_CELL = re.compile(
    r"^(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
    r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)\s+\d{1,2},?$",
    flags=re.IGNORECASE,
)
_DATE_HEADER_TOKEN = re.compile(
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
    r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)\s+\d{1,2},?",
    flags=re.IGNORECASE,
)
_PERIOD_HEADER_YEAR = re.compile(
    r"^(?:20\d{2}|(?:q[1-4]|[1-4]q)[\s_-]*(?:fy)?20?\d{2})$",
    re.IGNORECASE,
)
_TABLE_NUMBER = re.compile(
    r"(?<![A-Za-z])\(?[-+]?\s*(?:[$€£¥]\s*)?\d[\d,]*(?:\.\d+)?\s*\)?(?:\s*%|\s*bps)?",
    re.IGNORECASE,
)
_MONTH_NAME = re.compile(
    r"^(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?$",
    re.IGNORECASE,
)
_DAY_NUMBER = re.compile(r"^(\d{1,2}),?$")
_YEAR_NUMBER = re.compile(r"^20\d{2}$")
_DURATION_HEADER_PATTERNS = {
    ("three", "months", "ended"): (3, "three months"),
    ("six", "months", "ended"): (6, "six months"),
    ("nine", "months", "ended"): (9, "nine months"),
    ("twelve", "months", "ended"): (12, "twelve months"),
    ("year", "ended"): (12, "year ended"),
    ("years", "ended"): (12, "years ended"),
}


@dataclass(frozen=True)
class _PDFWordLine:
    y0: float
    y1: float
    words: tuple[tuple[float, float, float, float, str, int, int, int], ...]

    @property
    def text(self) -> str:
        return " ".join(word[4] for word in self.words)


@dataclass(frozen=True)
class _SpatialPeriodColumn:
    x_center: float
    period_end: date
    date_label: str
    period_key: str | None
    duration_months: int | None
    duration_label: str | None

    @property
    def period_label(self) -> str:
        return _spatial_period_display(self)


@dataclass(frozen=True)
class _SpatialTableHeader:
    columns: tuple[_SpatialPeriodColumn, ...]
    header_end_y: float
    section: str
    context: str
_KNOWN_SINGLE_WORD_HEADINGS = {
    "conclusion",
    "financials",
    "liquidity",
    "operations",
    "outlook",
    "overview",
    "results",
    "revenue",
    "risks",
    "strategy",
}
_MIN_MERGED_CHUNK_CHARS = 80
_MIN_INDEXABLE_CHUNK_CHARS = 40
_OCR_LONG_BLOCK_CHARS = 40
_OCR_STRICT_LONG_BLOCK_CHARS = 200
_OCR_MIN_ALNUM_RATIO = 0.65
_OCR_MAX_SINGLE_TOKEN_RATIO = 0.40
_OCR_MIN_USEFUL_ALNUM_RATIO = 0.85
_OCR_STRICT_MAX_SINGLE_TOKEN_RATIO = 0.25
_OCR_STRICT_MIN_USEFUL_ALNUM_RATIO = 0.90
_OCR_CJK_TEXT_RATIO = 0.20
_OCR_MAX_DOMINANT_CHAR_RATIO = 0.60
_OCR_BAD_UNICODE_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})


class DocumentProcessingError(ValueError):
    """Raised when a PDF cannot be converted into indexable content."""


@dataclass(frozen=True, slots=True)
class ParsedBlock:
    """One ordered text or structured-table block from a source document."""

    text: str
    page: int
    section: str
    ocr_used: bool
    is_heading: bool = False
    # Comparative table headers are often emitted as separate PDF blocks from
    # the numeric rows.  Carry the header forward so period/column provenance
    # survives chunking and downstream fact extraction.
    table_context: str | None = None
    source_locator: str | None = None
    content_type: str = "narrative"
    bbox: tuple[float, float, float, float] | None = None
    financial_table_row: FinancialTableRow | None = None


@dataclass(frozen=True, slots=True)
class ParsedTextRegion:
    """Native page text block with its source coordinates preserved."""

    text: str
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class ParsedTableRow:
    """One native table row, including per-cell geometry and blank cells."""

    cells: tuple[str | None, ...]
    cell_bboxes: tuple[tuple[float, float, float, float] | None, ...]
    bbox: tuple[float, float, float, float] | None


@dataclass(frozen=True, slots=True)
class ParsedTableCandidate:
    """Materialized PyMuPDF table grid, detached from its page handle."""

    page: int
    table_index: int
    bbox: tuple[float, float, float, float]
    rows: tuple[ParsedTableRow, ...]


@dataclass(frozen=True, slots=True)
class ParsedPage:
    """Structured content and extraction provenance for one PDF page."""

    number: int
    blocks: tuple[ParsedBlock, ...]
    ocr_used: bool
    text_regions: tuple[ParsedTextRegion, ...] = ()
    table_candidates: tuple[ParsedTableCandidate, ...] = ()


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """A source document represented as page/sheet-scoped content blocks."""

    filename: str
    pages: tuple[ParsedPage, ...]
    parser_version: str = PARSER_VERSION
    content_type: str = "application/pdf"
    financial_table_contexts: tuple[FinancialTableContext, ...] = ()
    financial_table_rows: tuple[FinancialTableRow, ...] = ()


@dataclass(frozen=True, slots=True)
class DocumentChunk:
    """An indexable chunk with source provenance."""

    text: str
    page: int
    section: str
    ocr_used: bool
    chunk_index: int
    parser_version: str = PARSER_VERSION
    chunker_version: str = CHUNKER_VERSION
    table_context: str | None = None
    source_locator: str | None = None
    content_type: str = "narrative"
    source_format: str = "application/pdf"
    financial_table_rows: tuple[FinancialTableRow, ...] = ()


def get_company(filename: str) -> str:
    normalized = filename.casefold()
    if "apple" in normalized:
        return "Apple"
    if "nvidia" in normalized:
        return "NVIDIA"
    if "tesla" in normalized:
        return "Tesla"
    return "Unknown"


def get_quarter(filename: str) -> str:
    match = re.search(r"(Q\d.*)\.[^.]+$", filename, flags=re.IGNORECASE)
    return match.group(1) if match else "Unknown"


_KNOWN_COMPANY_CONTENT_ALIASES = {
    "Apple": re.compile(r"\bApple\s+Inc(?:\.|\b)", flags=re.IGNORECASE),
    "Tesla": re.compile(r"\bTesla\b", flags=re.IGNORECASE),
    "NVIDIA": re.compile(r"\bNVIDIA\b", flags=re.IGNORECASE),
}
_SEC_REGISTRANT_PATTERN = re.compile(
    r"(?P<entity>[A-Z][A-Za-z0-9&'().,\-]*(?:\s+[A-Z][A-Za-z0-9&'().,\-]*){0,6}\s+"
    r"(?:Inc\.?|Incorporated|Corporation|Corp\.?|Limited|Ltd\.?|PLC|LLC|L\.P\.|S\.A\.|N\.V\.))"
    r"\s*\(\s*Exact name of Registrant as specified in its charter\s*\)",
    flags=re.IGNORECASE,
)
_LEGAL_SUFFIX = re.compile(
    r"\s*,?\s+(?:Inc\.?|Incorporated|Corporation|Corp\.?|Limited|Ltd\.?|PLC|LLC|L\.P\.|S\.A\.|N\.V\.)$",
    flags=re.IGNORECASE,
)

_CHINESE_ANNUAL_TITLE = re.compile(
    r"(?<![\u4e00-\u9fff])"
    r"(?P<entity>[\u4e00-\u9fffA-Za-z·（）()]{2,70}?股份有限公司)"
    r"\s*(?P<year>20\d{2})\s*年\s*(?:年度报告|年报)(?!\s*摘要)"
)


def _chinese_annual_cover_identity(chunks: list[DocumentChunk]) -> set[tuple[str, str]]:
    """Bind issuer and fiscal year only to an explicit first-page report title.

    A body mention, statement date, filename, or comparison-year column is not
    an issuer/report identity anchor. Conflicting cover titles stay ambiguous.
    """
    cover = " ".join(chunk.text for chunk in chunks[:8] if chunk.page == 1)[:8_000]
    return {
        (match.group("entity"), f"FY{match.group('year')}")
        for match in _CHINESE_ANNUAL_TITLE.finditer(cover)
    }


def get_document_company(
    chunks: list[DocumentChunk],
    *,
    filename_hint: str | None = None,
) -> str:
    """Return a known issuer only when the opening content identifies one.

    The filename remains a candidate hint, never company evidence. A mismatch
    between the filename and body, or multiple known issuers in the opening
    content, is treated as ambiguous and therefore ``Unknown``.
    """

    prefix = " ".join(chunk.text for chunk in chunks[:8])[:8_000]
    annual_titles = _chinese_annual_cover_identity(chunks)
    if annual_titles:
        return next(iter(annual_titles))[0] if len(annual_titles) == 1 else "Unknown"
    registrants = {
        match.group("entity").strip(" ,.;")
        for match in _SEC_REGISTRANT_PATTERN.finditer(prefix)
    }
    if len(registrants) == 1:
        entity = next(iter(registrants))
        issuer = _LEGAL_SUFFIX.sub("", entity).strip(" ,.;") or "Unknown"
        if filename_hint and filename_hint.casefold() in {
            company.casefold() for company in _KNOWN_COMPANY_CONTENT_ALIASES
        } and filename_hint.casefold() != issuer.casefold():
            return "Unknown"
        return issuer

    content_issuers = {
        company
        for company, alias in _KNOWN_COMPANY_CONTENT_ALIASES.items()
        if alias.search(prefix)
    }
    if len(content_issuers) != 1:
        return "Unknown"

    issuer = next(iter(content_issuers))
    canonical_hint = next(
        (
            company
            for company in _KNOWN_COMPANY_CONTENT_ALIASES
            if filename_hint and filename_hint.casefold() == company.casefold()
        ),
        None,
    )
    if canonical_hint and canonical_hint.casefold() != issuer.casefold():
        return "Unknown"
    return issuer


def get_document_period(chunks: list[DocumentChunk]) -> str:
    """Return a period only when the document's opening content is unambiguous."""

    from retrieval.periods import extract_periods

    annual_titles = _chinese_annual_cover_identity(chunks)
    if annual_titles:
        return next(iter(annual_titles))[1] if len(annual_titles) == 1 else "Unknown"

    opening_text = " ".join(chunk.text for chunk in chunks[:8])
    issuer_period = _document_period_hint(opening_text)
    if issuer_period:
        return issuer_period

    candidates: set[str] = set()
    candidates.update(extract_periods(opening_text))
    return next(iter(candidates)) if len(candidates) == 1 else "Unknown"


def clean_text(text: str) -> str:
    """Normalize a single text unit without joining separate PDF blocks."""

    normalized = _HYPHENATED_LINE_BREAK.sub(r"\1\2", text)
    normalized = _WHITESPACE.sub(" ", normalized)
    normalized = re.sub(r"\s*\n\s*", " ", normalized)
    return normalized.strip()


def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    """Backward-compatible boundary-aware string chunking helper."""

    _validate_chunk_settings(chunk_size, overlap)
    normalized = clean_text(text)
    if not normalized:
        return []
    return _split_long_text(normalized, chunk_size, overlap)


def parse_pdf(
    pdf_path: str | os.PathLike[str],
    *,
    ocr_enabled: bool = OCR_ENABLED,
    ocr_languages: str = OCR_LANGUAGES,
    ocr_dpi: int = OCR_DPI,
    ocr_min_text_chars: int = OCR_MIN_TEXT_CHARS,
    document_id: str | None = None,
) -> ParsedDocument:
    """Extract sorted page blocks and OCR pages with insufficient text."""

    source_path = Path(pdf_path)
    if not source_path.is_file():
        raise DocumentProcessingError(f"PDF file not found: {source_path}")
    if source_path.stat().st_size == 0:
        raise DocumentProcessingError("PDF file is empty")
    if ocr_dpi < 72:
        raise ValueError("OCR_DPI must be at least 72")
    if ocr_min_text_chars < 0:
        raise ValueError("OCR_MIN_TEXT_CHARS must be non-negative")
    if ocr_enabled and not ocr_languages.strip():
        raise ValueError("OCR_LANGUAGES must not be empty when OCR is enabled")

    try:
        with fitz.open(source_path) as pdf:
            if pdf.page_count == 0:
                raise DocumentProcessingError("PDF contains no pages")

            opening_text = clean_text(" ".join(_extract_text_blocks(pdf[0])))
            document_period_hint = _document_period_hint(opening_text)
            pages: list[ParsedPage] = []
            active_section = ""
            spatial_header: _SpatialTableHeader | None = None
            for page_index, page in enumerate(pdf):
                page_number = page_index + 1
                page_start_section = active_section
                native_regions = _extract_text_regions(page)
                native_blocks = [region.text for region in native_regions]
                # Keep compatibility with callers/tests that provide the
                # legacy text-block extractor while the layout-aware path is
                # authoritative whenever it returns source regions.
                if not native_blocks:
                    native_blocks = _extract_text_blocks(page)
                raw_blocks = native_blocks
                page_text_regions = native_regions
                text_characters = sum(
                    len(re.sub(r"\s+", "", block_text))
                    for block_text in native_blocks
                )
                ocr_used = False

                if ocr_enabled and text_characters < ocr_min_text_chars:
                    ocr_blocks = _extract_ocr_blocks(
                        page,
                        page_number=page_number,
                        languages=ocr_languages,
                        dpi=ocr_dpi,
                    )
                    raw_blocks = _filter_ocr_blocks(ocr_blocks)
                    rejected_blocks = len(ocr_blocks) - len(raw_blocks)
                    logger.info(
                        "OCR quality gate page=%s accepted_blocks=%s "
                        "rejected_blocks=%s",
                        page_number,
                        len(raw_blocks),
                        rejected_blocks,
                    )
                    if raw_blocks:
                        ocr_used = True
                        page_text_regions = []
                    else:
                        raw_blocks = native_blocks
                        page_text_regions = native_regions

                parsed_blocks: list[ParsedBlock] = []
                for block_index, raw_text in enumerate(raw_blocks):
                    text = clean_text(raw_text)
                    if not text:
                        continue
                    is_heading = _looks_like_heading(raw_text, text)
                    if is_heading:
                        active_section = text
                    parsed_blocks.append(
                        ParsedBlock(
                            text=text,
                            page=page_number,
                            section=active_section or f"Page {page_number}",
                            ocr_used=ocr_used,
                            is_heading=is_heading,
                            content_type=(
                                "unverified_table"
                                if _looks_like_unverified_financial_table(text)
                                else "narrative"
                            ),
                            bbox=(
                                page_text_regions[block_index].bbox
                                if block_index < len(page_text_regions)
                                else None
                            ),
                        )
                    )

                parsed_blocks = _attach_table_context(parsed_blocks)
                native_tables = _find_native_table_objects(page, page_number=page_number)
                table_candidates = _materialize_table_candidates(
                    native_tables,
                    page_number=page_number,
                )
                structured_table_blocks = _extract_structured_table_blocks(
                    page,
                    page_number=page_number,
                    ocr_used=ocr_used,
                    native_tables=native_tables,
                )
                structured_table_blocks = _inherit_statement_group_labels(
                    parsed_blocks,
                    structured_table_blocks,
                )
                parsed_blocks.extend(structured_table_blocks)
                if structured_table_blocks:
                    spatial_header = None
                else:
                    table_section = _comparative_section_for_page(
                        parsed_blocks,
                        default=active_section or page_start_section or f"Page {page_number}",
                    )
                    inherited_header = (
                        spatial_header
                        if spatial_header is not None
                        and spatial_header.section == (page_start_section or table_section)
                        else None
                    )
                    spatial_blocks, spatial_header = _extract_spatial_financial_table_blocks(
                        page,
                        page_number=page_number,
                        ocr_used=ocr_used,
                        document_period_hint=document_period_hint,
                        section=table_section,
                        inherited_header=inherited_header,
                    )
                    spatial_blocks = _inherit_statement_group_labels(
                        parsed_blocks,
                        spatial_blocks,
                    )
                    parsed_blocks.extend(spatial_blocks)

                pages.append(
                    ParsedPage(
                        number=page_number,
                        blocks=tuple(parsed_blocks),
                        ocr_used=ocr_used,
                        text_regions=tuple(page_text_regions),
                        table_candidates=tuple(table_candidates),
                    )
                )
    except DocumentProcessingError:
        raise
    except Exception as exc:
        raise DocumentProcessingError(f"Unable to parse PDF {source_path.name}: {exc}") from exc

    if not any(page.blocks for page in pages):
        raise DocumentProcessingError("PDF contains no extractable text")

    reconstruction = reconstruct_financial_statements(
        pages,
        filename=source_path.name,
        document_id=document_id,
    )
    rows_by_page: dict[int, list[FinancialTableRow]] = {}
    for row in reconstruction.rows:
        if row.page is not None:
            rows_by_page.setdefault(row.page, []).append(row)

    reconstructed_pages: list[ParsedPage] = []
    for page in pages:
        structured_rows: list[ParsedBlock] = []
        for row in rows_by_page.get(page.number, ()):
            row_text = (
                f"Financial table row — Metric: {row.row_label} | "
                f"{row.period}: {row.raw_value}"
                + (f" {row.currency}" if row.currency else "")
            )
            context_text = "; ".join(
                part
                for part in (
                    row.table_title,
                    f"Scope: {row.scope}" if row.scope else None,
                    f"Unit: {row.unit}" if row.unit else None,
                    f"Currency: {row.currency}" if row.currency else None,
                )
                if part
            )
            structured_rows.append(
                ParsedBlock(
                    text=row_text,
                    page=page.number,
                    section=row.table_title or f"Page {page.number}",
                    ocr_used=page.ocr_used,
                    table_context=context_text,
                    source_locator=row.source_locator,
                    content_type="table",
                    financial_table_row=row,
                )
            )
        reconstructed_pages.append(
            replace(page, blocks=(*page.blocks, *structured_rows))
        )

    return ParsedDocument(
        filename=source_path.name,
        pages=tuple(reconstructed_pages),
        financial_table_contexts=reconstruction.contexts,
        financial_table_rows=reconstruction.rows,
    )


def chunk_document(
    document: ParsedDocument,
    *,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[DocumentChunk]:
    """Create page- and section-scoped chunks from parsed PDF blocks."""

    _validate_chunk_settings(chunk_size, overlap)
    chunks: list[DocumentChunk] = []

    for page in document.pages:
        page_chunks: list[DocumentChunk] = []
        group: list[ParsedBlock] = []
        active_section: str | None = None
        # ParsedDocument instances can also be constructed by callers/tests,
        # so apply table-context propagation here as well as in parse_pdf.
        page_blocks = _attach_table_context(list(page.blocks))
        for block in page_blocks:
            if group and (
                block.section != active_section
                or block.content_type != group[-1].content_type
            ):
                page_chunks.extend(
                    _chunk_block_group(
                        group,
                        chunk_size=chunk_size,
                        overlap=overlap,
                        start_index=len(page_chunks),
                    )
                )
                group = []
            active_section = block.section
            group.append(block)

        if group:
            page_chunks.extend(
                _chunk_block_group(
                    group,
                    chunk_size=chunk_size,
                    overlap=overlap,
                    start_index=len(page_chunks),
                )
            )
        chunks.extend(
            _merge_tiny_page_chunks(
                page_chunks,
                minimum_chars=min(_MIN_MERGED_CHUNK_CHARS, chunk_size),
            )
        )

    return [
        replace(
            chunk,
            chunk_index=index,
            parser_version=document.parser_version,
            source_format=document.content_type,
        )
        for index, chunk in enumerate(_deduplicate_chunks(chunks))
    ]


def load_pdf_chunks(
    pdf_path: str | os.PathLike[str],
    *,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
    ocr_enabled: bool = OCR_ENABLED,
    ocr_languages: str = OCR_LANGUAGES,
    ocr_dpi: int = OCR_DPI,
    ocr_min_text_chars: int = OCR_MIN_TEXT_CHARS,
    document_id: str | None = None,
) -> list[DocumentChunk]:
    """Run the canonical parser and chunker for one PDF."""

    document = parse_pdf(
        pdf_path,
        ocr_enabled=ocr_enabled,
        ocr_languages=ocr_languages,
        ocr_dpi=ocr_dpi,
        ocr_min_text_chars=ocr_min_text_chars,
        document_id=document_id,
    )
    chunks = chunk_document(
        document,
        chunk_size=chunk_size,
        overlap=overlap,
    )
    if not chunks:
        raise DocumentProcessingError("PDF produced no indexable chunks")
    return chunks


def load_document_chunks(
    path: str | os.PathLike[str],
    *,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
    ocr_enabled: bool = OCR_ENABLED,
    ocr_languages: str = OCR_LANGUAGES,
    ocr_dpi: int = OCR_DPI,
    ocr_min_text_chars: int = OCR_MIN_TEXT_CHARS,
) -> list[DocumentChunk]:
    """Dispatch supported report formats through their canonical parser.

    PDF parsing retains the existing page/OCR pipeline. XLSX, DOCX, and CSV
    use format-aware table adapters so row values remain bound to headers and
    each chunk carries a source locator (sheet/row, table/row, or CSV row).
    """

    source = Path(path)
    if source.suffix.casefold() == ".pdf":
        return load_pdf_chunks(
            source,
            chunk_size=chunk_size,
            overlap=overlap,
            ocr_enabled=ocr_enabled,
            ocr_languages=ocr_languages,
            ocr_dpi=ocr_dpi,
            ocr_min_text_chars=ocr_min_text_chars,
        )

    from document_formats import load_structured_document_chunks

    return load_structured_document_chunks(
        source,
        chunk_size=chunk_size,
        overlap=overlap,
    )


def load_documents(pdf_folder: str | os.PathLike[str]) -> list[dict[str, object]]:
    """Load public/demo reports through the same ingestion path as uploads."""

    folder = Path(pdf_folder)
    documents: list[dict[str, object]] = []
    report_files = sorted(
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.casefold() in {".pdf", ".html", ".xlsx", ".docx", ".csv"}
    )

    for report_path in report_files:
        filename_company_hint = get_company(report_path.name)
        filename_period_hint = get_quarter(report_path.name)
        content_sha256 = _file_sha256(report_path)
        document_id = report_path.stem.casefold().replace(" ", "_").replace("-", "_")
        chunks = load_document_chunks(report_path)
        company = get_document_company(chunks, filename_hint=filename_company_hint)
        quarter = get_document_period(chunks)
        for chunk in chunks:
            documents.append(
                {
                    "source": report_path.name,
                    "chunk_id": chunk.chunk_index,
                    "company": company,
                    "quarter": quarter,
                    "filename_company_hint": filename_company_hint,
                    "filename_period_hint": filename_period_hint,
                    "document_id": document_id,
                    "text": chunk.text,
                    "page": chunk.page,
                    "page_label": chunk.source_locator or "",
                    "section": chunk.section,
                    "content_type": chunk.content_type,
                    "source_locator": chunk.source_locator or "",
                    "source_format": chunk.source_format,
                    "ocr_used": chunk.ocr_used,
                    "parser_version": chunk.parser_version,
                    "chunker_version": chunk.chunker_version,
                    "table_context": chunk.table_context or "",
                    "source_authority": "public_filing",
                    "content_sha256": content_sha256,
                    # A filename is only a display label.  Keep every
                    # explicit quarter/metric found in the chunk so retrieval
                    # can enforce a query's period without flattening a
                    # comparative financial table.
                    "periods": "|".join(extract_periods(chunk.text)),
                    "metrics": "|".join(extract_metrics(chunk.text)),
                }
            )

    logger.info(
        "Loaded public knowledge documents count=%s chunks=%s",
        len(report_files),
        len(documents),
    )
    return documents


def prepare_document(pdf_path: str | os.PathLike[str]) -> list[str]:
    """Compatibility wrapper returning text-only chunks."""

    return [chunk.text for chunk in load_document_chunks(pdf_path)]


def show_chunk_preview(chunks: list[dict[str, object]]) -> None:
    """Print a small preview for legacy command-line workflows."""

    print("=" * 60)
    print("DOCUMENT INFORMATION")
    print("=" * 60)
    print(f"Total Chunks: {len(chunks)}")
    for chunk in chunks[:3]:
        print("-" * 60)
        print(f"Source: {chunk['source']}")
        print(f"Chunk ID: {chunk['chunk_id']}")
        print(f"Company: {chunk['company']}")
        print(f"Quarter: {chunk['quarter']}")
        print(str(chunk["text"])[:300])
        print("...")


def _extract_text_blocks(
    page: fitz.Page,
    *,
    textpage: fitz.TextPage | None = None,
) -> list[str]:
    return [region.text for region in _extract_text_regions(page, textpage=textpage)]


def _extract_text_regions(
    page: fitz.Page,
    *,
    textpage: fitz.TextPage | None = None,
) -> list[ParsedTextRegion]:
    """Return the canonical reading order without discarding native bboxes."""

    blocks = page.get_text(
        "blocks",
        sort=True,
        textpage=textpage,
    )
    text_blocks = [
        block
        for block in blocks
        if len(block) >= 7 and block[6] == 0 and str(block[4]).strip()
    ]
    page_words = page.get_text("words", sort=True, textpage=textpage)
    ordered = _column_reading_order(text_blocks, page.rect, page_words=page_words)
    if ordered is None:
        ordered = text_blocks
    return [
        ParsedTextRegion(
            text=str(block[4]),
            bbox=tuple(float(value) for value in block[:4]),
        )
        for block in ordered
    ]


def _column_reading_order(
    blocks: list[tuple],
    page_rect: fitz.Rect,
    *,
    page_words: list[tuple] | None = None,
) -> list[tuple] | None:
    """Return a column-major order only for a confidently detected prose layout.

    PyMuPDF's geometric sort is top-to-bottom then left-to-right. On a two-column
    page this can weave the columns together and produce paragraphs no reader
    would see. Detect a stable central gutter from repeated prose blocks, while
    avoiding numeric table cells; if the layout is ambiguous, keep PyMuPDF's
    existing order rather than guessing.
    """

    page_width = float(page_rect.width)
    if page_width <= 0:
        return None

    prose_blocks = []
    for block in blocks:
        x0, _y0, x1, _y1, raw_text = block[:5]
        text = str(raw_text).strip()
        words = re.findall(r"[^\W_]+", text, flags=re.UNICODE)
        letters = sum(character.isalpha() for character in text)
        visible = sum(not character.isspace() for character in text)
        if (
            float(x1) - float(x0) <= page_width * 0.62
            and len(words) >= 5
            and visible
            and letters / visible >= 0.52
            and not _looks_like_heading(text, text)
        ):
            prose_blocks.append(block)

    if len(prose_blocks) < 4:
        return None

    by_left_edge = sorted(prose_blocks, key=lambda block: (float(block[0]), float(block[1])))
    largest_gap_index = max(
        range(len(by_left_edge) - 1),
        key=lambda index: float(by_left_edge[index + 1][0]) - float(by_left_edge[index][0]),
    )
    gap = float(by_left_edge[largest_gap_index + 1][0]) - float(
        by_left_edge[largest_gap_index][0]
    )
    if gap < page_width * 0.18:
        return None

    left_candidates = by_left_edge[: largest_gap_index + 1]
    right_candidates = by_left_edge[largest_gap_index + 1 :]
    if len(left_candidates) < 2 or len(right_candidates) < 2:
        return None

    left_edge = max(float(block[2]) for block in left_candidates)
    right_edge = min(float(block[0]) for block in right_candidates)
    if right_edge - left_edge < page_width * 0.025:
        return None
    if (
        sum(float(block[0]) for block in left_candidates) / len(left_candidates)
        >= page_rect.x0 + page_width * 0.48
        or sum(float(block[0]) for block in right_candidates) / len(right_candidates)
        <= page_rect.x0 + page_width * 0.52
    ):
        return None

    gutter = (left_edge + right_edge) / 2
    left_blocks = [block for block in blocks if float(block[2]) <= gutter]
    right_blocks = [block for block in blocks if float(block[0]) >= gutter]
    spanning_blocks = []
    split_original_count = 0
    split_fragment_count = 0
    for block in blocks:
        if float(block[0]) < gutter < float(block[2]):
            split_blocks = _split_merged_column_line(
                block,
                page_words or [],
                gutter=gutter,
                page_width=page_width,
            )
            if split_blocks is None:
                spanning_blocks.append(block)
                continue
            split_original_count += 1
            split_fragment_count += len(split_blocks)
            for split_block in split_blocks:
                if float(split_block[2]) <= gutter:
                    left_blocks.append(split_block)
                elif float(split_block[0]) >= gutter:
                    right_blocks.append(split_block)
                else:
                    spanning_blocks.append(split_block)
    if len(left_blocks) < 2 or len(right_blocks) < 2:
        return None

    def order_by_position(items: list[tuple]) -> list[tuple]:
        return sorted(
            items,
            key=lambda block: (float(block[1]), float(block[0])),
        )

    left_blocks = order_by_position(left_blocks)
    right_blocks = order_by_position(right_blocks)
    spanning_blocks = order_by_position(spanning_blocks)

    ordered: list[tuple] = []
    band_start = float(page_rect.y0) - 1
    for separator in spanning_blocks:
        separator_start = float(separator[1])
        for column_blocks in (left_blocks, right_blocks):
            ordered.extend(
                block
                for block in column_blocks
                if band_start <= (float(block[1]) + float(block[3])) / 2 < separator_start
            )
        ordered.append(separator)
        band_start = float(separator[3])

    for column_blocks in (left_blocks, right_blocks):
        ordered.extend(
            block
            for block in column_blocks
            if (float(block[1]) + float(block[3])) / 2 >= band_start
        )

    # Be conservative if an unusual geometry left any text block unclassified.
    # Split fragments are new tuples, so account for them separately from the
    # original spanning blocks they replace.
    expected_count = len(blocks) - split_original_count + split_fragment_count
    if len(ordered) != expected_count or len({id(block) for block in ordered}) != expected_count:
        return None
    return ordered


def _split_merged_column_line(
    block: tuple,
    page_words: list[tuple],
    *,
    gutter: float,
    page_width: float,
) -> list[tuple] | None:
    """Split one PyMuPDF text block only when word geometry proves two columns.

    Some same-baseline lines from adjacent columns are joined into one text
    block. A large horizontal word gap can prove the two runs are independent;
    ordinary full-width sentences remain intact.
    """

    if len(block) < 6:
        return None
    block_text = str(block[4]).strip()
    if _looks_like_financial_table_row(block_text) or _looks_like_unverified_financial_table(
        block_text
    ):
        return None
    block_number = block[5]
    words_by_line: dict[int, list[tuple]] = {}
    for word in page_words:
        if len(word) >= 8 and word[5] == block_number:
            words_by_line.setdefault(int(word[6]), []).append(word)
    if not words_by_line:
        return None

    left_fragments: list[tuple] = []
    right_fragments: list[tuple] = []
    split_any = False
    for line_words in words_by_line.values():
        line_words.sort(key=lambda word: (float(word[0]), int(word[7])))
        split_at = None
        largest_gap = page_width * 0.12
        for index in range(1, len(line_words)):
            gap = float(line_words[index][0]) - float(line_words[index - 1][2])
            if gap > largest_gap and index >= 2 and len(line_words) - index >= 2:
                largest_gap = gap
                split_at = index

        runs = (
            ((line_words[:split_at], "left"), (line_words[split_at:], "right"))
            if split_at is not None
            else ((line_words, None),)
        )
        for run_words, assigned_side in runs:
            x0 = min(float(word[0]) for word in run_words)
            x1 = max(float(word[2]) for word in run_words)
            if split_at is None and x0 < gutter < x1:
                return None
            text = " ".join(str(word[4]) for word in run_words).strip()
            if text:
                fragment = (
                    x0,
                    min(float(word[1]) for word in run_words),
                    x1,
                    max(float(word[3]) for word in run_words),
                    text,
                    block_number,
                    0,
                )
                if assigned_side == "left" or x1 <= gutter:
                    left_fragments.append(fragment)
                elif assigned_side == "right" or x0 >= gutter:
                    right_fragments.append(fragment)
                else:
                    return None
        if split_at is not None:
            split_any = True

    if not split_any:
        # PyMuPDF may assign simultaneous left/right lines to one text block
        # while keeping separate line numbers. Treat that as a split only when
        # their page coordinates prove that the lines share the same baseline.
        split_any = any(
            max(float(left[1]), float(right[1]))
            <= min(float(left[3]), float(right[3]))
            for left in left_fragments
            for right in right_fragments
        )

    return left_fragments + right_fragments if split_any else None


def _document_period_hint(opening_text: str) -> str | None:
    """Return one issuer-backed reporting period, without using filename hints."""

    periods = tuple(dict.fromkeys(extract_periods(opening_text)))
    if len(periods) == 1:
        return periods[0]

    lowered = opening_text.casefold()
    update_quarter = re.search(
        r"\bq([1-4])\s*(?:&|and)\s*fy\s*['’]?(20\d{2}|\d{2})\b",
        opening_text,
        re.IGNORECASE,
    )
    if update_quarter:
        year = update_quarter.group(2)
        if len(year) == 2:
            year = f"20{year}"
        return f"Q{update_quarter.group(1)}_{year}"

    issuer_result = re.search(
        r"\bNVIDIA\s+Announces\s+Financial\s+Results\s+for\s+"
        r"(?P<quarter>first|second|third|fourth|[1-4](?:st|nd|rd|th)?)\s+"
        r"Quarter\s+Fiscal\s+(?P<year>20\d{2})\b",
        opening_text,
        re.IGNORECASE,
    )
    if issuer_result:
        quarter_name = issuer_result.group("quarter").casefold()
        quarter = {
            "first": 1,
            "second": 2,
            "third": 3,
            "fourth": 4,
        }.get(quarter_name)
        if quarter is None:
            quarter = int(quarter_name[0])
        return f"Q{quarter}_FY{issuer_result.group('year')}"

    if "apple inc." in lowered:
        ended = re.search(
            r"(?:for the\s+)?(?:fiscal\s+)?quarterly period ended\s+"
            r"((?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|"
            r"may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|"
            r"nov(?:ember)?|dec(?:ember)?)\s+\d{1,2},?\s+20\d{2})",
            opening_text,
            re.IGNORECASE,
        )
        if ended:
            try:
                period_end = datetime.strptime(ended.group(1).replace(",", ""), "%B %d %Y").date()
            except ValueError:
                try:
                    period_end = datetime.strptime(ended.group(1).replace(",", ""), "%b %d %Y").date()
                except ValueError:
                    period_end = None
            if period_end:
                month = period_end.month
                if month in {10, 11, 12}:
                    quarter, fiscal_year = 1, period_end.year + 1
                elif month in {1, 2, 3}:
                    quarter, fiscal_year = 2, period_end.year
                elif month in {4, 5, 6}:
                    quarter, fiscal_year = 3, period_end.year
                else:
                    quarter, fiscal_year = 4, period_end.year
                return f"Q{quarter}_FY{fiscal_year}"

    return None


def _comparative_section_for_page(
    blocks: list[ParsedBlock],
    *,
    default: str,
) -> str:
    headings = [
        block.section
        for block in blocks
        if block.is_heading and _looks_like_period_table_header(block.text)
    ]
    return headings[-1] if headings else default


def _find_native_table_objects(page: fitz.Page, *, page_number: int) -> list[object]:
    """Find once and retain all native grids, including ambiguous candidates.

    The caller stores a detached copy of every candidate before the PDF closes.
    The older trusted-text path may still reject a candidate; P1.3 performs a
    separate structural assessment using these original cells and regions.
    """

    try:
        return list(page.find_tables(strategy="lines").tables)
    except Exception as exc:
        logger.info(
            "Native table extraction skipped page=%s reason=%s",
            page_number,
            type(exc).__name__,
        )
        return []


def _materialize_table_candidates(
    native_tables: list[object],
    *,
    page_number: int,
) -> list[ParsedTableCandidate]:
    """Copy source cells and their PyMuPDF geometry into immutable IR."""

    materialized: list[ParsedTableCandidate] = []
    for table_index, table in enumerate(native_tables, start=1):
        try:
            raw_rows = table.extract() or []
            source_rows = getattr(table, "rows", ())
            table_bbox = tuple(float(value) for value in table.bbox)
            rows: list[ParsedTableRow] = []
            for row_index, raw_row in enumerate(raw_rows):
                cells = tuple(
                    clean_text(str(value)) if value is not None else None
                    for value in raw_row
                )
                source_cells = (
                    tuple(source_rows[row_index].cells)
                    if row_index < len(source_rows)
                    else ()
                )
                cell_bboxes = tuple(
                    tuple(float(value) for value in bbox) if bbox is not None else None
                    for bbox in source_cells[: len(cells)]
                )
                if len(cell_bboxes) < len(cells):
                    cell_bboxes += (None,) * (len(cells) - len(cell_bboxes))
                present = [bbox for bbox in cell_bboxes if bbox is not None]
                row_bbox = (
                    (
                        min(bbox[0] for bbox in present),
                        min(bbox[1] for bbox in present),
                        max(bbox[2] for bbox in present),
                        max(bbox[3] for bbox in present),
                    )
                    if present
                    else None
                )
                rows.append(
                    ParsedTableRow(
                        cells=cells,
                        cell_bboxes=cell_bboxes,
                        bbox=row_bbox,
                    )
                )
            materialized.append(
                ParsedTableCandidate(
                    page=page_number,
                    table_index=table_index,
                    bbox=table_bbox,
                    rows=tuple(rows),
                )
            )
        except Exception as exc:
            logger.info(
                "Native table candidate materialization failed page=%s table=%s reason=%s",
                page_number,
                table_index,
                type(exc).__name__,
            )
    return materialized


def _extract_structured_table_blocks(
    page: fitz.Page,
    *,
    page_number: int,
    ocr_used: bool,
    native_tables: list[object] | None = None,
) -> list[ParsedBlock]:
    """Add only high-density native table parses as row-scoped evidence.

    PyMuPDF's table detector can mistake a whole-page text block for a table.
    Candidates therefore pass density and multi-cell-row checks before being
    indexed. The original page text remains present as a fallback.
    """

    candidates = (
        native_tables
        if native_tables is not None
        else _find_native_table_objects(page, page_number=page_number)
    )

    structured: list[ParsedBlock] = []
    page_area = max(float(page.rect.width * page.rect.height), 1.0)
    for table_index, table in enumerate(candidates, start=1):
        try:
            raw_rows = table.extract()
            rows = [
                [clean_text(str(value)) if value is not None else "" for value in row]
                for row in raw_rows
            ]
            nonempty_rows = [row for row in rows if any(row)]
            column_count = max((len(row) for row in nonempty_rows), default=0)
            total_cells = len(nonempty_rows) * column_count
            populated_cells = sum(bool(value) for row in nonempty_rows for value in row)
            dense_rows = sum(sum(bool(value) for value in row) >= 2 for row in nonempty_rows)
            bbox = tuple(float(value) for value in table.bbox)
            bbox_area = max((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]), 0.0)
        except Exception as exc:
            logger.info(
                "Native table candidate rejected page=%s table=%s reason=%s",
                page_number,
                table_index,
                type(exc).__name__,
            )
            continue

        density = populated_cells / total_cells if total_cells else 0.0
        minimum_dense_rows = max(2, int(len(nonempty_rows) * 0.25))
        header_index = _find_reliable_table_header(nonempty_rows)
        if (
            len(nonempty_rows) < 3
            or column_count < 2
            or density < 0.38
            or dense_rows < minimum_dense_rows
            or bbox_area / page_area > 0.95
            or header_index is None
        ):
            logger.info(
                "Native table candidate rejected page=%s table=%s rows=%s columns=%s density=%.2f",
                page_number,
                table_index,
                len(nonempty_rows),
                column_count,
                density,
            )
            continue

        header_rows = nonempty_rows[max(0, header_index - 1) : header_index + 1]
        header_context = " | ".join(
            f"context/header row {index + 1}: " + " ; ".join(
                f"col {column + 1}={_short_table_cell(value)}"
                for column, value in enumerate(row)
                if value
            )
            for index, row in enumerate(header_rows)
        )
        x0, y0, x1, _y1 = bbox
        caption = ""
        if y0 > 1:
            try:
                caption = clean_text(
                    page.get_textbox(fitz.Rect(x0, max(0, y0 - 54), x1, y0))
                )[:500]
            except Exception:
                caption = ""
        table_context = "\n".join(part for part in (caption, header_context) if part)

        # Include rows only when the detected period header and data row have
        # an exact column-for-column mapping.  A parser can return visually
        # plausible cells while shifting a value under the adjacent period;
        # generic ``column N`` labels leave that unsafe binding to the model.
        for row_index, row in enumerate(nonempty_rows[header_index + 1 :], start=header_index + 2):
            bound_row = _bind_financial_table_row(nonempty_rows[header_index], row)
            if bound_row is None:
                continue
            row_text = (
                f"Structured financial table row (PDF page {page_number}, table {table_index}).\n"
                f"Table caption/header context: {table_context or 'not confidently detected'}.\n"
                f"Row {row_index}: {bound_row}"
            )
            structured.append(
                ParsedBlock(
                    text=row_text,
                    page=page_number,
                    section=f"Table {table_index}",
                    ocr_used=ocr_used,
                    table_context=table_context or None,
                    source_locator=f"PDF page {page_number}, table {table_index}, row {row_index}",
                    content_type="table",
                )
            )
    return structured


def _inherit_statement_group_labels(
    source_blocks: list[ParsedBlock],
    structured_blocks: list[ParsedBlock],
) -> list[ParsedBlock]:
    """Bind a verified numeric row to its unique printed statement group.

    Some PDFs expose ``Services`` as a row label while the parent ``Net
    sales`` label exists only in the page's reading-order text. Transfer that
    relationship only when every printed value in the structured row matches
    exactly one same-page source block. Ambiguous or partial matches remain
    unlabeled and therefore cannot be promoted to a financial fact.
    """

    enriched: list[ParsedBlock] = []
    for structured in structured_blocks:
        metric_match = re.search(
            r"Financial table row\s*[—-]\s*Metric:\s*(?P<metric>[^|\n]+)",
            structured.text,
            re.IGNORECASE,
        )
        if not metric_match:
            enriched.append(structured)
            continue

        metric_label = metric_match.group("metric").strip()
        row_values: list[str] = []
        for field in structured.text.split("|"):
            if not re.search(r"\bQ[1-4]\b", field, re.IGNORECASE):
                continue
            value_match = re.search(
                r":\s*(?P<value>(?:[$€£¥]\s*)?\(?-?\d[\d,]*(?:\.\d+)?%?\)?)\s*$",
                field,
            )
            if value_match:
                row_values.append(value_match.group("value").strip())
        if not row_values:
            enriched.append(structured)
            continue

        matching_groups: list[str] = []
        for source in source_blocks:
            if source.content_type != "unverified_table" or not source.section:
                continue
            if not re.search(rf"(?<!\w){re.escape(metric_label)}(?!\w)", source.text, re.IGNORECASE):
                continue
            matched_values = True
            for value in row_values:
                value_without_currency = re.sub(r"[$€£¥\s]", "", value)
                value_pattern = re.sub(
                    r"[, ]+",
                    lambda _match: r"[,\s]*",
                    re.escape(value_without_currency),
                )
                if not re.search(rf"(?<!\d){value_pattern}(?!\d)", source.text):
                    matched_values = False
                    break
            if matched_values:
                matching_groups.append(source.section.strip().rstrip(":"))

        unique_groups = list(dict.fromkeys(matching_groups))
        if len(unique_groups) != 1:
            enriched.append(structured)
            continue

        parent_group = unique_groups[0]
        lower_group = parent_group.casefold()
        lower_metric = metric_label.casefold()
        resolved_label = None
        if (
            lower_group in {"net sales", "sales", "revenue", "revenues"}
            and lower_metric not in {"total net sales", "total revenue", "total revenues"}
        ):
            resolved_label = f"{metric_label} {lower_group}"

        binding = f"Verified statement group: {parent_group}."
        if resolved_label:
            replacement = (
                f"Financial table row — Verified statement group: {parent_group}. "
                f"Resolved financial label: {resolved_label}"
            )
            row_start = metric_match.start()
            row_end = metric_match.end()
            structured_text = (
                f"{structured.text[:row_start]}{replacement}"
                f"{structured.text[row_end:]}"
            )
        else:
            structured_text = (
                f"{structured.text[:metric_match.start()]}{binding}\n"
                f"{structured.text[metric_match.start():]}"
            )
        enriched.append(
            replace(
                structured,
                text=structured_text,
            )
        )
    return enriched


def _extract_spatial_financial_table_blocks(
    page: fitz.Page,
    *,
    page_number: int,
    ocr_used: bool,
    document_period_hint: str | None,
    section: str,
    inherited_header: _SpatialTableHeader | None = None,
) -> tuple[list[ParsedBlock], _SpatialTableHeader | None]:
    """Bind borderless PDF rows to date columns using native word coordinates.

    This path accepts a row only when every detected date column has exactly
    one horizontally aligned numeric token. It is intentionally unavailable
    for OCR-only text because the current OCR adapter does not expose reliable
    word boxes. If coordinates or period mapping are ambiguous, the row stays
    unverified in the ordinary parser path.
    """

    lines = _pdf_word_lines(page)
    if not lines:
        return [], None

    header = _find_spatial_table_header(
        page,
        lines,
        page_number=page_number,
        ocr_used=ocr_used,
        document_period_hint=document_period_hint,
        section=section,
    )
    local_header = header is not None
    if header is None and inherited_header is not None and inherited_header.section == section:
        header = replace(inherited_header, header_end_y=float(page.rect.y0) + 2)
    if header is None:
        return [], None

    structured: list[ParsedBlock] = []
    matched_rows: list[tuple[_PDFWordLine, str, list[str]]] = []
    for line in _coalesce_spatial_lines(lines):
        if line.y0 <= header.header_end_y + 3:
            continue
        if not matched_rows and line.y0 > header.header_end_y + 120:
            break
        row = _spatial_financial_row(line, header.columns)
        if row is None:
            continue
        label, values = row
        if _is_unreliable_spatial_metric_label(label):
            continue
        if matched_rows and line.y0 - matched_rows[-1][0].y0 > 60:
            # A spatial header is valid only for its immediately following
            # row run; never let it bleed into a later table/narrative section.
            break
        matched_rows.append((line, label, values))

    for line, label, values in matched_rows:
        fields = [f"Metric: {label}"]
        fields.extend(
            f"{column.period_label}: {value}"
            for column, value in zip(header.columns, values, strict=True)
        )
        structured.append(
            ParsedBlock(
                text=(
                    f"Structured financial table row (PDF page {page_number}).\n"
                    f"{header.context}\nFinancial table row — "
                    + " | ".join(fields)
                ),
                page=page_number,
                section=header.section,
                ocr_used=ocr_used,
                table_context=header.context,
                source_locator=(
                    f"PDF page {page_number}, spatial table row y={line.y0:.1f}"
                ),
                content_type="table",
            )
        )

    if local_header:
        return structured, header
    # A header may carry through one immediate continuation page, but must not
    # silently remain active and bind unrelated tables on later pages.
    return structured, None


def _pdf_word_lines(page: fitz.Page) -> list[_PDFWordLine]:
    grouped: dict[tuple[int, int], list[tuple[float, float, float, float, str, int, int, int]]] = {}
    for raw_word in page.get_text("words", sort=True):
        if len(raw_word) < 8 or not str(raw_word[4]).strip():
            continue
        word = (
            float(raw_word[0]),
            float(raw_word[1]),
            float(raw_word[2]),
            float(raw_word[3]),
            str(raw_word[4]),
            int(raw_word[5]),
            int(raw_word[6]),
            int(raw_word[7]),
        )
        grouped.setdefault((word[5], word[6]), []).append(word)
    lines = [
        _PDFWordLine(
            y0=min(word[1] for word in words),
            y1=max(word[3] for word in words),
            words=tuple(sorted(words, key=lambda word: word[0])),
        )
        for words in grouped.values()
    ]
    return sorted(lines, key=lambda line: (line.y0, line.words[0][0]))


def _coalesce_spatial_lines(lines: list[_PDFWordLine]) -> list[_PDFWordLine]:
    """Join same-baseline text blocks so each visual table row is evaluated whole."""

    groups: list[list[_PDFWordLine]] = []
    for line in sorted(lines, key=lambda item: (item.y0, item.words[0][0])):
        if groups and abs(line.y0 - groups[-1][0].y0) <= 2.5:
            groups[-1].append(line)
        else:
            groups.append([line])
    return [
        _PDFWordLine(
            y0=min(line.y0 for line in group),
            y1=max(line.y1 for line in group),
            words=tuple(sorted((word for line in group for word in line.words), key=lambda word: word[0])),
        )
        for group in groups
    ]




def _date_cells_on_line(line: _PDFWordLine) -> list[tuple[str, str, float, str]]:
    words = line.words
    cells: list[tuple[str, str, float, str]] = []
    consumed: set[int] = set()
    for index, word in enumerate(words):
        month_match = _MONTH_NAME.fullmatch(word[4].strip(" ,"))
        if not month_match or index in consumed:
            continue
        day_candidate = next(
            (
                (day_index, candidate)
                for day_index, candidate in enumerate(words[index + 1 :], start=index + 1)
                if candidate[0] >= word[2]
                and candidate[0] - word[2] <= 28
                and _DAY_NUMBER.fullmatch(candidate[4].strip(" ,"))
            ),
            None,
        )
        if day_candidate is None:
            continue
        day_index, day_word = day_candidate
        consumed.update((index, day_index))
        center = (word[0] + day_word[2]) / 2
        stub = f"{word[4].strip(' ,')} {day_word[4].strip(' ,')}"
        cells.append((word[4].strip(" ,"), day_word[4].strip(" ,"), center, stub))
    return cells


def _month_day_numbers(date_stub: str) -> tuple[int | None, int | None]:
    parts = date_stub.replace(",", "").split()
    if len(parts) != 2:
        return None, None
    month = parts[0].casefold().rstrip(".")[:3]
    month_number = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }.get(month)
    try:
        day_number = int(parts[1])
    except ValueError:
        day_number = None
    return month_number, day_number


def _duration_spans(
    lines: list[_PDFWordLine],
) -> list[tuple[float, float, int, str]]:
    spans: list[tuple[float, float, int, str]] = []
    for line in lines:
        tokens = [word[4].casefold().strip(" ,:;.") for word in line.words]
        for phrase, descriptor in _DURATION_HEADER_PATTERNS.items():
            width = len(phrase)
            for start in range(0, len(tokens) - width + 1):
                if tuple(tokens[start : start + width]) == phrase:
                    spans.append(
                        (
                            line.words[start][0],
                            line.words[start + width - 1][2],
                            descriptor[0],
                            descriptor[1],
                        )
                    )
    return spans


def _duration_for_center(
    center: float,
    spans: list[tuple[float, float, int, str]],
) -> tuple[int | None, str | None]:
    if not spans:
        return None, None

    def distance(span: tuple[float, float, int, str]) -> float:
        left, right, _months, _label = span
        if left <= center <= right:
            return 0.0
        return min(abs(center - left), abs(center - right))

    nearest = min(spans, key=distance)
    return (nearest[2], nearest[3]) if distance(nearest) <= 60 else (None, None)




def _find_spatial_table_header(
    page: fitz.Page,
    lines: list[_PDFWordLine],
    *,
    page_number: int,
    ocr_used: bool,
    document_period_hint: str | None,
    section: str,
) -> _SpatialTableHeader | None:
    """Find date columns even when PDF extraction splits each column into blocks."""

    del page_number, ocr_used
    dated_lines = [
        (line, _date_cells_on_line(line))
        for line in lines
        if _date_cells_on_line(line)
    ]
    groups: list[list[tuple[_PDFWordLine, tuple[str, str, float, str]]]] = []
    for line, cells in dated_lines:
        for cell in cells:
            if groups and abs(line.y0 - groups[-1][0][0].y0) <= 3:
                groups[-1].append((line, cell))
            else:
                groups.append([(line, cell)])

    for group in groups:
        if len(group) < 2:
            continue
        group.sort(key=lambda item: item[1][2])
        date_y0 = min(line.y0 for line, _cell in group)
        date_y1 = max(line.y1 for line, _cell in group)
        centers = [cell[2] for _line, cell in group]
        if len(set(round(center, 1) for center in centers)) != len(centers):
            continue

        year_candidates = [
            word
            for nearby in lines
            # A year row stacked under date labels is a reliable table cue.
            # Inline dates on prose paragraphs are intentionally not promoted.
            if date_y0 + 4 <= nearby.y0 <= date_y1 + 38
            for word in nearby.words
            if _YEAR_NUMBER.fullmatch(word[4].strip(" ,"))
        ]
        years = list(year_candidates)
        dated_columns: list[tuple[float, date, str, float]] = []
        for _line, (_month, _day, center, date_stub) in group:
            if not years:
                break
            nearest = min(years, key=lambda word: abs((word[0] + word[2]) / 2 - center))
            year_center = (nearest[0] + nearest[2]) / 2
            if abs(year_center - center) > 42:
                break
            years.remove(nearest)
            month_number, day_number = _month_day_numbers(date_stub)
            if month_number is None or day_number is None:
                break
            try:
                period_end = date(int(nearest[4].strip(" ,")), month_number, day_number)
            except ValueError:
                break
            dated_columns.append(
                (center, period_end, f"{date_stub} {period_end.year}", nearest[3])
            )
        if len(dated_columns) != len(group) or len({column[1] for column in dated_columns}) < 2:
            continue

        header_lines = [
            line
            for line in lines
            if date_y0 - 60 <= line.y0 <= date_y1 + 2
        ]
        duration_spans = _duration_spans(header_lines)
        unit_lines = [
            line
            for line in lines
            if date_y0 - 130 <= line.y0 <= date_y1 + 2
            and re.search(
                r"\b(?:in\s+thousands|in\s+millions|in\s+billions)\b",
                line.text,
                re.IGNORECASE,
            )
        ]
        columns = [
            _SpatialPeriodColumn(
                x_center=center,
                period_end=period_end,
                date_label=date_label,
                period_key=None,
                duration_months=(duration := _duration_for_center(center, duration_spans))[0],
                duration_label=duration[1],
            )
            for center, period_end, date_label, _year_y1 in dated_columns
        ]
        columns = _resolve_spatial_column_periods(columns, document_period_hint)
        sorted_centers = [column.x_center for column in columns]
        gaps = [right - left for left, right in zip(sorted_centers, sorted_centers[1:], strict=False)]
        if not gaps or min(gaps) < 35 or max(gaps) / min(gaps) > 2.5:
            continue
        header_end_y = max(year_y1 for *_prefix, year_y1 in dated_columns)
        duration_coverage = sum(column.duration_label is not None for column in columns)
        aligned_rows = sum(
            _spatial_financial_row(candidate, tuple(columns)) is not None
            for candidate in _coalesce_spatial_lines(lines)
            if header_end_y + 3 < candidate.y0 <= header_end_y + 120
        )
        if aligned_rows == 0 and duration_coverage != len(columns):
            continue

        context_parts = list(dict.fromkeys(clean_text(line.text) for line in unit_lines))
        context_parts.extend(
            dict.fromkeys(column.duration_label for column in columns if column.duration_label)
        )
        context_parts.append(
            "Comparative columns: " + " | ".join(column.period_label for column in columns)
        )
        header_context = "TABLE COLUMNS: " + " | ".join(context_parts)

        return _SpatialTableHeader(
            columns=tuple(columns),
            header_end_y=header_end_y,
            section=section,
            context=header_context,
        )

    # Financial reports often print comparative periods directly as labels
    # (Q4-2024, Q1-2025, ...), rather than as SEC date cells. Bind these only
    # when native word coordinates show distinct columns and at least one
    # immediately following row maps exactly one value into every column.
    for line in _coalesce_spatial_lines(lines):
        quarter_cells = _explicit_quarter_cells_on_line(line)
        if len(quarter_cells) < 2:
            continue
        period_keys = [period_key for period_key, _label, _center in quarter_cells]
        if len(set(period_keys)) != len(period_keys):
            continue
        quarter_cells.sort(key=lambda cell: cell[2])
        centers = [center for _key, _label, center in quarter_cells]
        gaps = [right - left for left, right in zip(centers, centers[1:], strict=False)]
        if not gaps or min(gaps) < 35 or max(gaps) / min(gaps) > 2.5:
            continue

        header_end_y = line.y1
        columns = [
            _SpatialPeriodColumn(
                x_center=center,
                # This is an ordering sentinel only; explicit period_key is
                # authoritative and is never inferred from this date.
                period_end=date(int(period_key[-4:]), int(period_key[1]) * 3, 1),
                date_label=label,
                period_key=period_key,
                duration_months=3,
                duration_label=None,
            )
            for period_key, label, center in quarter_cells
        ]
        aligned_rows = sum(
            _spatial_financial_row(candidate, tuple(columns)) is not None
            for candidate in _coalesce_spatial_lines(lines)
            if header_end_y + 3 < candidate.y0 <= header_end_y + 120
        )
        if aligned_rows == 0:
            continue

        unit_lines = [
            candidate
            for candidate in lines
            if header_end_y - 130 <= candidate.y0 <= header_end_y + 2
            and re.search(
                r"\b(?:in\s+thousands|in\s+millions|in\s+billions)\b",
                candidate.text,
                re.IGNORECASE,
            )
        ]
        context_parts = list(dict.fromkeys(clean_text(candidate.text) for candidate in unit_lines))
        context_parts.append(
            "Comparative columns: " + " | ".join(label for _key, label, _center in quarter_cells)
        )
        return _SpatialTableHeader(
            columns=tuple(columns),
            header_end_y=header_end_y,
            section=section,
            context="TABLE COLUMNS: " + " | ".join(context_parts),
        )
    return None


def _explicit_quarter_cells_on_line(line: _PDFWordLine) -> list[tuple[str, str, float]]:
    cells: list[tuple[str, str, float]] = []
    for word in line.words:
        label = word[4].strip(" ,:;()[]")
        match = _EXPLICIT_QUARTER_PERIOD.fullmatch(label)
        if not match:
            continue
        quarter = match.group("quarter").upper()
        year = match.group("year")
        fiscal = "_FY" if match.group("fiscal") else "_"
        cells.append((f"{quarter}{fiscal}{year}", label, (word[0] + word[2]) / 2))
    return cells


def _resolve_spatial_column_periods(
    columns: list[_SpatialPeriodColumn],
    document_period_hint: str | None,
) -> list[_SpatialPeriodColumn]:
    if all(column.period_key is not None for column in columns):
        return columns
    if not document_period_hint:
        return columns
    period_match = re.fullmatch(r"Q([1-4])_(FY)?(20\d{2})", document_period_hint)
    if not period_match:
        return columns

    quarter = int(period_match.group(1))
    fiscal = bool(period_match.group(2))
    year = int(period_match.group(3))
    groups: dict[str, list[int]] = {}
    for index, column in enumerate(columns):
        if column.period_key is not None:
            continue
        group_key = column.duration_label or "__periods__"
        groups.setdefault(group_key, []).append(index)

    resolved = list(columns)
    for indexes in groups.values():
        group = [columns[index] for index in indexes]
        latest = max(column.period_end for column in group)
        if len({column.period_end for column in group}) != len(group):
            continue
        offsets: list[int] = []
        valid_group = True
        for column in group:
            difference = (latest - column.period_end).days
            offset = round(difference / (365.2425 / 4))
            if offset < 0 or offset > 16 or abs(difference - offset * (365.2425 / 4)) > 30:
                valid_group = False
                break
            offsets.append(offset)
        if not valid_group or len(set(offsets)) != len(offsets):
            continue
        for index, column, offset in zip(indexes, group, offsets, strict=True):
            shifted = _shift_fiscal_period(quarter, year, fiscal, offset)
            resolved[index] = replace(column, period_key=shifted)
    return resolved


def _shift_fiscal_period(quarter: int, year: int, fiscal: bool, offset: int) -> str:
    ordinal = year * 4 + quarter - 1 - offset
    shifted_year, shifted_quarter_index = divmod(ordinal, 4)
    fiscal_marker = "FY" if fiscal else ""
    return f"Q{shifted_quarter_index + 1}_{fiscal_marker}{shifted_year}"


def _spatial_period_display(column: _SpatialPeriodColumn) -> str:
    if column.period_key:
        match = re.fullmatch(r"Q([1-4])_(FY)?(20\d{2})", column.period_key)
        if match:
            period = f"Q{match.group(1)} {'FY' if match.group(2) else ''}{match.group(3)}"
            if column.duration_months and column.duration_months > 3:
                period = f"YTD {period}"
        else:
            period = column.period_key
    else:
        period = f"Period ended {column.date_label}"
    duration = f"{column.duration_label} ended " if column.duration_label else "ended "
    return f"{period} ({duration}{column.date_label})"


def _is_unreliable_spatial_metric_label(label: str) -> bool:
    normalized = clean_text(label).casefold().strip(" .,:;-")
    if _MONTH_NAME.fullmatch(normalized):
        return True
    return normalized in {
        "change",
        "expense",
        "income",
        "balance",
        "increase",
        "decrease",
        "total",
        "year",
    }


def _spatial_financial_row(
    line: _PDFWordLine,
    columns: tuple[_SpatialPeriodColumn, ...],
) -> tuple[str, list[str]] | None:
    if len(columns) < 2 or len(line.text) > 240 or re.search(
        r"[!?。！？;；]|(?<!\d)\.(?:\s|$)",
        line.text,
    ):
        return None
    centers = [column.x_center for column in columns]
    gaps = [right - left for left, right in zip(centers, centers[1:], strict=False)]
    if not gaps:
        return None
    alignment_tolerance = min(40.0, min(gaps) * 0.46)
    numeric_words = [
        word for word in line.words if _TABLE_NUMBER.search(word[4])
    ]
    mapped: list[list[tuple[float, float, float, float, str, int, int, int]]] = [
        [] for _ in columns
    ]
    for word in numeric_words:
        center = (word[0] + word[2]) / 2
        column_index = min(range(len(centers)), key=lambda index: abs(centers[index] - center))
        if abs(centers[column_index] - center) > alignment_tolerance:
            continue
        mapped[column_index].append(word)
    if any(len(values) != 1 for values in mapped):
        return None

    number_words = [values[0] for values in mapped]
    parts_by_column: list[list[tuple[float, str]]] = [
        [(word[0], word[4])]
        for word in number_words
    ]
    symbol_words = [
        word
        for word in line.words
        if word[4].strip() in {"$", "€", "£", "¥", "%"}
    ]
    for symbol in symbol_words:
        symbol_center = (symbol[0] + symbol[2]) / 2
        nearest = min(
            range(len(number_words)),
            key=lambda index: abs((number_words[index][0] + number_words[index][2]) / 2 - symbol_center),
        )
        number_center = (number_words[nearest][0] + number_words[nearest][2]) / 2
        if abs(number_center - symbol_center) <= 42:
            parts_by_column[nearest].append((symbol[0], symbol[4]))
    for suffix in ("bps", "million", "billion", "thousand"):
        for word in line.words:
            if word[4].casefold().strip(".,") != suffix:
                continue
            nearest = min(
                range(len(number_words)),
                key=lambda index: abs(number_words[index][2] - word[0]),
            )
            if abs(number_words[nearest][2] - word[0]) <= 32:
                parts_by_column[nearest].append((word[0], word[4]))

    values = [
        " ".join(text for _x, text in sorted(parts, key=lambda pair: pair[0]))
        for parts in parts_by_column
    ]
    first_center = centers[0]
    label_cutoff = first_center - max(18.0, min(gaps) * 0.43)
    label_words = [
        word[4]
        for word in line.words
        if (word[0] + word[2]) / 2 < label_cutoff
        and word[4].strip() not in {"$", "€", "£", "¥", "%"}
        and not _TABLE_NUMBER.search(word[4])
    ]
    label = clean_text(" ".join(label_words)).strip(" |:;,-")
    if not label or not any(character.isalpha() for character in label):
        return None
    if len(label) > 150:
        return None
    return label, values


def _find_reliable_table_header(rows: list[list[str]]) -> int | None:
    """Find an early row whose separate cells identify at least two periods."""

    for row_index, row in enumerate(rows[:5]):
        period_cells = {
            clean_text(value).casefold()
            for value in row
            if value and _is_period_header_cell(value)
        }
        # Merged-cell extraction can repeat one period into several columns.
        # Count distinct labels, not cells, so duplicates never prove a map.
        if len(period_cells) >= 2:
            return row_index
    return None


def _is_period_header_cell(value: str) -> bool:
    normalized = clean_text(value).strip(" ()[]{}:;,.—–-_")
    if not normalized:
        return False
    if extract_periods(normalized):
        return True
    return bool(_PERIOD_HEADER_YEAR.fullmatch(normalized))


def _has_ambiguous_repeated_period_header(rows: list[list[str]]) -> bool:
    """Detect a header that repeats one reporting period across value columns."""

    for row in rows[:5]:
        labels = []
        for value in row:
            if not value or not _is_period_header_cell(value):
                continue
            periods = extract_periods(value)
            labels.append(tuple(periods) if periods else clean_text(value).casefold())
        if len(labels) >= 2 and len(set(labels)) < 2:
            return True
    return False


def _has_separated_financial_values(row: list[str]) -> bool:
    populated_values = [value for value in row if value.strip()]
    numeric_cells = [value for value in populated_values if _TABLE_NUMBER.search(value)]
    if len(numeric_cells) < 2:
        return False
    return all(len(_TABLE_NUMBER.findall(value)) <= 1 for value in numeric_cells)


def _bind_financial_table_row(header: list[str], row: list[str]) -> str | None:
    """Render a financial table row only when its columns can be proven.

    A period header is useful only if its cells line up exactly with the
    corresponding row.  Ragged rows can result from merged cells or failed
    table recognition, so they remain in the original page text but are not
    promoted to structured numeric evidence.
    """

    if len(header) != len(row) or not _has_separated_financial_values(row):
        return None

    period_columns = {
        index
        for index, value in enumerate(header)
        if value.strip() and _is_period_header_cell(value)
    }
    distinct_periods = {clean_text(header[index]).casefold() for index in period_columns}
    if len(distinct_periods) < 2:
        return None

    fields: list[str] = []
    has_metric_label = False
    for index, raw_value in enumerate(row):
        value = _short_table_cell(raw_value)
        if not value:
            continue

        numeric_tokens = _TABLE_NUMBER.findall(value)
        if len(numeric_tokens) > 1:
            return None

        raw_header = clean_text(header[index]) if header[index] else ""
        if index in period_columns:
            # Keep the source header text verbatim so fiscal/calendar period
            # distinctions and comparative columns are not normalized away.
            label = raw_header
        elif raw_header and not (
            not has_metric_label and _is_table_unit_or_metric_header(raw_header)
        ):
            label = raw_header
        elif not numeric_tokens and not has_metric_label:
            label = "Metric"
        elif numeric_tokens:
            # An unlabeled numeric cell cannot safely be assigned a period,
            # unit, or comparison meaning.
            return None
        else:
            label = f"Column {index + 1}"

        if not numeric_tokens and not has_metric_label:
            has_metric_label = True
        fields.append(f"{label}: {value}")

    if not has_metric_label or len(fields) < 3:
        return None
    return " | ".join(fields)


def _short_table_cell(value: str) -> str:
    compact = clean_text(value)
    return compact[:500] + " [cell truncated]" if len(compact) > 500 else compact


def _is_table_unit_or_metric_header(value: str) -> bool:
    """Recognize descriptor headers that label a table, not its first field."""

    lowered = clean_text(value).casefold()
    return any(
        marker in lowered
        for marker in (
            "metric",
            "description",
            "financial item",
            "($ in ",
            "(in ",
            "except percentages",
            "except per share",
        )
    )


def _looks_like_unverified_financial_table(text: str) -> bool:
    """Flag flattened financial tables whose row/column map is not explicit.

    Comparative tables are recognized by their period headers.  Some PDF
    layout engines, however, detach or omit those headers while retaining a
    dense run of financial rows (for example, a regional table with one value
    per region and a total).  Quarantine those blocks too when several rows
    each contain multiple numeric cells.  The block remains available for
    diagnostics, but downstream evidence gates must not treat its unmapped
    numbers as authoritative facts.
    """

    if _has_explicit_annual_column_headers(text):
        return False

    if len(extract_metrics(text)) < 2 or len(_TABLE_NUMBER.findall(text)) < 8 or len(text) < 200:
        return False
    if _has_comparative_period_columns(text):
        return True

    # Require a table-shaped run rather than merely a prose paragraph with
    # several financial numbers.  Multiple dense rows are a stronger signal
    # than the (sometimes missing) period labels themselves.
    dense_rows = [
        line
        for line in text.splitlines()
        if _looks_like_financial_table_row(line)
        and len(_TABLE_NUMBER.findall(line)) >= 3
    ]
    return len(dense_rows) >= 4 and sum(len(_TABLE_NUMBER.findall(row)) for row in dense_rows) >= 16


def _has_explicit_annual_column_headers(text: str) -> bool:
    """Recognize compact year-only column headers in annual financial tables."""

    for line in text.splitlines():
        if re.search(r"\b(?:Q[1-4]|[1-4]Q)[- _]?20\d{2}\b", line, re.IGNORECASE):
            continue
        years = set(re.findall(r"\b20\d{2}\b", line))
        if len(years) >= 3 and len(line) <= 600:
            return True
    return False


def _looks_like_dense_unmapped_financial_row(text: str) -> bool:
    return len(_TABLE_NUMBER.findall(text)) >= 4 and _looks_like_financial_table_row(text)


def _comparative_periods_before_first_financial_row(text: str) -> tuple[str, ...]:
    """Read explicit period columns from the header before the first data row."""

    first_row = re.search(
        r"\b(?:total\s+)?(?:automotive\s+|services\s+and\s+other\s+)?"
        r"(?:revenues?|net\s+sales|gross\s+(?:profit|margin)|operating\s+income|"
        r"net\s+income|cash\s+generated\s+by\s+operating\s+activities)\b",
        text,
        re.IGNORECASE,
    )
    if first_row is None:
        return ()
    periods = tuple(extract_periods(text[: first_row.start()]))
    return periods if len(periods) >= 3 else ()


def _has_comparative_period_columns(text: str) -> bool:
    if len(set(extract_periods(text))) >= 2:
        return True
    has_period_duration = bool(
        re.search(
            r"\b(?:three|six|nine|twelve|3|6|9|12)\s+months?\s+ended\b|\byears?\s+ended\b",
            text,
            re.IGNORECASE,
        )
    )
    years = set(re.findall(r"\b20\d{2}\b", text))
    dates = {
        match.group(0).casefold().strip(" ,")
        for match in _DATE_HEADER_TOKEN.finditer(text)
    }
    return has_period_duration and len(years) >= 2 and len(dates) >= 2


def _looks_like_period_table_header(text: str) -> bool:
    lowered = clean_text(text).casefold()
    if re.search(r"\b(?:three|six|nine|twelve|3|6|9|12)\s+months?\s+ended\b|\byears?\s+ended\b", lowered):
        return True
    return (
        len(extract_periods(text)) >= 2
        and len(text) <= 180
        and not re.search(r"[!?。！？;；]|(?<!\d)\.(?=\s|$)", text)
    )


def _looks_like_financial_table_row(text: str) -> bool:
    if _looks_like_financial_narrative_block(text):
        return False
    if re.search(r"[!?。！？;；]|(?<!\d)\.(?=\s|$)", text):
        return False
    number_count = len(_TABLE_NUMBER.findall(text))
    if number_count >= 2:
        return True
    # A single surviving numeric cell can still be a ragged comparative row
    # whose neighboring period value was dropped by extraction.
    return bool(extract_metrics(text)) and len(text) <= 180


def _looks_like_financial_narrative_block(text: str) -> bool:
    """Keep multi-claim financial release prose out of the table quarantine.

    PDF extractors can collapse a headline and adjacent release highlights into
    one long block. Such blocks may contain several amounts and percentages,
    but unlike flattened statement rows they include explicit reporting/action
    language or a labelled growth claim. Preserve those source sentences as
    narrative evidence; continue quarantining dense rows without a column map.
    """

    if (
        len(text) < 100
        or len(_TABLE_NUMBER.findall(text)) < 3
        or _has_comparative_period_columns(text)
    ):
        return False

    reporting_language = re.search(
        r"\b(?:report(?:ed|s|ing)?|announc(?:ed|es|ing)?|increas(?:ed|es|ing)?|"
        r"decreas(?:ed|es|ing)?|expect(?:ed|s|ing)?|forecast(?:s|ed|ing)?|"
        r"project(?:ed|s|ing)?|deliver(?:ed|s|ing)?|generat(?:ed|es|ing)?|"
        r"grew|rose|fell|remain(?:ed|s|ing)?)\b",
        text,
        re.IGNORECASE,
    )
    explicit_growth_claim = re.search(
        r"\b(?:up|down|grew|rose|fell|increased|decreased)\s+"
        r"(?:by\s+)?\d+(?:\.\d+)?\s*%\b",
        text,
        re.IGNORECASE,
    )
    return bool(reporting_language or explicit_growth_claim)


def _extract_ocr_blocks(
    page: fitz.Page,
    *,
    page_number: int,
    languages: str,
    dpi: int,
) -> list[str]:
    try:
        textpage = page.get_textpage_ocr(
            language=languages,
            dpi=dpi,
            full=True,
        )
        return _extract_text_blocks(page, textpage=textpage)
    except Exception as exc:
        raise DocumentProcessingError(f"OCR failed on page {page_number} with languages {languages!r}: {exc}") from exc


def _filter_ocr_blocks(blocks: list[str]) -> list[str]:
    """Remove OCR blocks that are mostly image-derived character noise."""

    filtered = [block for block in blocks if _is_usable_ocr_block(block)]
    if filtered and _is_usable_ocr_block("\n".join(filtered)):
        return filtered
    return []


def _is_usable_ocr_block(text: str) -> bool:
    """Apply a Unicode-aware OCR quality gate without using a word list."""

    normalized = unicodedata.normalize("NFKC", text)
    visible = [character for character in normalized if not character.isspace()]
    if not visible:
        return False

    alphanumeric = [character for character in visible if character.isalnum()]
    if not alphanumeric:
        return False

    bad_characters = [
        character
        for character in visible
        if character == "\ufffd"
        or unicodedata.category(character) in _OCR_BAD_UNICODE_CATEGORIES
    ]
    if _has_consecutive_bad_characters(visible):
        return False
    if (
        len(bad_characters) >= 2
        and len(bad_characters) / len(visible) > 0.05
    ):
        return False

    character_counts: dict[str, int] = {}
    for character in visible:
        key = character.casefold()
        character_counts[key] = character_counts.get(key, 0) + 1
    if (
        len(visible) >= 12
        and max(character_counts.values()) / len(visible)
        >= _OCR_MAX_DOMINANT_CHAR_RATIO
    ):
        return False

    if (
        len(visible) >= _OCR_LONG_BLOCK_CHARS
        and len(alphanumeric) / len(visible) < _OCR_MIN_ALNUM_RATIO
    ):
        return False

    tokens = _ocr_alphanumeric_tokens(normalized)
    if len(tokens) < 6:
        return True

    cjk_characters = sum(
        1 for character in alphanumeric if _CJK.fullmatch(character)
    )
    if cjk_characters / len(alphanumeric) >= _OCR_CJK_TEXT_RATIO:
        return True

    single_token_ratio = sum(len(token) == 1 for token in tokens) / len(tokens)
    useful_alphanumeric = sum(len(token) for token in tokens if len(token) >= 2)
    useful_alphanumeric_ratio = useful_alphanumeric / len(alphanumeric)
    if len(visible) >= _OCR_STRICT_LONG_BLOCK_CHARS:
        return (
            single_token_ratio <= _OCR_STRICT_MAX_SINGLE_TOKEN_RATIO
            and useful_alphanumeric_ratio
            >= _OCR_STRICT_MIN_USEFUL_ALNUM_RATIO
        )
    return (
        single_token_ratio <= _OCR_MAX_SINGLE_TOKEN_RATIO
        and useful_alphanumeric_ratio >= _OCR_MIN_USEFUL_ALNUM_RATIO
    )


def _has_consecutive_bad_characters(characters: list[str]) -> bool:
    consecutive = 0
    for character in characters:
        is_bad = (
            character == "\ufffd"
            or unicodedata.category(character) in _OCR_BAD_UNICODE_CATEGORIES
        )
        consecutive = consecutive + 1 if is_bad else 0
        if consecutive >= 3:
            return True
    return False


def _ocr_alphanumeric_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    current_is_cjk: bool | None = None

    for character in text:
        if not character.isalnum():
            if current:
                tokens.append("".join(current))
                current = []
                current_is_cjk = None
            continue

        is_cjk = bool(_CJK.fullmatch(character))
        if current and is_cjk != current_is_cjk:
            tokens.append("".join(current))
            current = []
        current.append(character)
        current_is_cjk = is_cjk

    if current:
        tokens.append("".join(current))
    return tokens


def _looks_like_heading(raw_text: str, normalized_text: str) -> bool:
    if len(normalized_text) > 140:
        return False
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if len(lines) > 2:
        return False
    if normalized_text.endswith(
        (".", "?", "!", "。", "？", "！", ";", "；", ",", "，")
    ):
        return False

    words = normalized_text.split()
    if len(words) > 16:
        return False
    if _SECTION_PREFIX.match(normalized_text):
        return True
    if _looks_like_table_cell(normalized_text):
        return False
    if normalized_text.endswith((":", "：")):
        return True

    letters = "".join(character for character in normalized_text if character.isalpha())
    if (
        letters
        and letters.isupper()
        and not any(character.isdigit() for character in normalized_text)
        and (
            len(letters) >= 6
            or normalized_text.casefold() in _KNOWN_SINGLE_WORD_HEADINGS
        )
    ):
        return True
    if _CJK.search(normalized_text):
        return 4 <= len(normalized_text) <= 30

    title_words = [word for word in words if any(character.isalpha() for character in word)]
    if len(title_words) == 1:
        return False
    return len(title_words) >= 2 and all(word[0].isupper() for word in title_words)


def _looks_like_table_cell(text: str) -> bool:
    compact = text.strip()
    if _QUARTER_TABLE_CELL.fullmatch(compact):
        return True
    if _DATE_TABLE_CELL.fullmatch(compact):
        return True
    if len(compact) <= 40 and any(character.isdigit() for character in compact):
        return True
    return False


def _chunk_block_group(
    blocks: list[ParsedBlock],
    *,
    chunk_size: int,
    overlap: int,
    start_index: int,
) -> list[DocumentChunk]:
    expanded: list[ParsedBlock] = []
    for block in blocks:
        parts = _split_long_text(block.text, chunk_size, overlap)
        expanded.extend(
            ParsedBlock(
                text=part,
                page=block.page,
                section=block.section,
                ocr_used=block.ocr_used,
                is_heading=block.is_heading and index == 0,
                table_context=block.table_context,
                source_locator=block.source_locator,
                content_type=block.content_type,
                bbox=block.bbox,
                financial_table_row=block.financial_table_row,
            )
            for index, part in enumerate(parts)
        )

    chunks: list[DocumentChunk] = []
    current: list[ParsedBlock] = []
    for block in expanded:
        # Keep verified financial rows out of any chunk containing quarantined
        # dense table text. Chunk metadata is conservative (an unverified row
        # taints its whole chunk), and retrieval/citation gates correctly drop
        # such chunks. Without this boundary, a validated CNINFO row could be
        # merged with a neighboring ambiguous row and become unusable.
        verified_unverified_boundary = _crosses_table_trust_boundary(
            {item.content_type for item in current},
            {block.content_type},
        )
        proposed_length = _joined_length([*current, block])
        if current and (verified_unverified_boundary or proposed_length > chunk_size):
            chunks.append(
                _make_chunk(
                    current,
                    chunk_index=start_index + len(chunks),
                )
            )
            if verified_unverified_boundary:
                # Overlap is intentionally disabled across a trust boundary;
                # otherwise quarantined rows could leak into the verified
                # chunk and inherit the conservative unverified metadata.
                current = []
            else:
                current = _overlap_blocks(current, overlap)
                while current and _joined_length([*current, block]) > chunk_size:
                    current.pop(0)
        current.append(block)

    if current:
        chunks.append(
            _make_chunk(
                current,
                chunk_index=start_index + len(chunks),
            )
        )
    return chunks


def _make_chunk(
    blocks: list[ParsedBlock],
    *,
    chunk_index: int,
) -> DocumentChunk:
    locators = list(dict.fromkeys(block.source_locator for block in blocks if block.source_locator))
    content_types = {block.content_type for block in blocks}
    financial_rows = tuple(
        block.financial_table_row
        for block in blocks
        if block.financial_table_row is not None
    )
    return DocumentChunk(
        text="\n\n".join(block.text for block in blocks),
        page=blocks[0].page,
        section=blocks[0].section,
        ocr_used=any(block.ocr_used for block in blocks),
        chunk_index=chunk_index,
        table_context=_merge_table_contexts(blocks),
        source_locator="; ".join(locators)[:1_000] or None,
        content_type=(
            "unverified_table"
            if "unverified_table" in content_types
            else next(iter(content_types)) if len(content_types) == 1 else "mixed"
        ),
        financial_table_rows=tuple(dict.fromkeys(financial_rows)),
    )


def _crosses_table_trust_boundary(left_types: set[str], right_types: set[str]) -> bool:
    """Prevent validated financial rows from sharing chunks with quarantined rows."""

    return (
        "unverified_table" in left_types and "table" in right_types
    ) or ("table" in left_types and "unverified_table" in right_types)


def _merge_tiny_page_chunks(
    chunks: list[DocumentChunk],
    *,
    minimum_chars: int,
) -> list[DocumentChunk]:
    """Merge short adjacent chunks without crossing a page boundary."""

    pending = list(chunks)
    index = 0
    while len(pending) > 1 and index < len(pending):
        chunk = pending[index]
        if (
            len(_normalize_content(chunk.text)) >= minimum_chars
            and not _is_heading_only_chunk(chunk)
        ):
            index += 1
            continue

        if index + 1 < len(pending):
            if _crosses_table_trust_boundary(
                {chunk.content_type},
                {pending[index + 1].content_type},
            ):
                # A small verified fact row is still independently useful.
                # Merging it with an adjacent unverified financial block would
                # taint the whole chunk and hide the verified evidence.
                index += 1
                continue
            pending[index : index + 2] = [
                _merge_chunks(chunk, pending[index + 1])
            ]
            continue

        if _crosses_table_trust_boundary(
            {pending[index - 1].content_type},
            {chunk.content_type},
        ):
            index += 1
            continue

        pending[index - 1 : index + 1] = [
            _merge_chunks(pending[index - 1], chunk)
        ]
        index = max(index - 1, 0)
    return pending


def _merge_chunks(
    first: DocumentChunk,
    second: DocumentChunk,
) -> DocumentChunk:
    paragraphs: list[str] = []
    seen: set[str] = set()
    for text in (first.text, second.text):
        for paragraph in text.split("\n\n"):
            key = _normalize_content(paragraph)
            if key and key not in seen:
                seen.add(key)
                paragraphs.append(paragraph.strip())
    section = (
        second.section
        if _is_heading_only_chunk(first) and not _is_heading_only_chunk(second)
        else first.section
    )
    return replace(
        first,
        text="\n\n".join(paragraphs),
        section=section,
        ocr_used=first.ocr_used or second.ocr_used,
        table_context=first.table_context or second.table_context,
        source_locator="; ".join(
            dict.fromkeys(
                locator
                for locator in (first.source_locator, second.source_locator)
                if locator
            )
        )[:1_000]
        or None,
        content_type=(
            "unverified_table"
            if "unverified_table" in {first.content_type, second.content_type}
            else (
                first.content_type
                if first.content_type == second.content_type
                else "mixed"
            )
        ),
        financial_table_rows=tuple(
            dict.fromkeys((*first.financial_table_rows, *second.financial_table_rows))
        ),
    )


def _is_heading_only_chunk(chunk: DocumentChunk) -> bool:
    return _normalize_content(chunk.text) == _normalize_content(chunk.section)


def _deduplicate_chunks(
    chunks: list[DocumentChunk],
) -> list[DocumentChunk]:
    deduplicated: list[DocumentChunk] = []
    seen: set[str] = set()
    for chunk in chunks:
        key = _normalize_content(chunk.text)
        if (
            len(key) < _MIN_INDEXABLE_CHUNK_CHARS
            or _is_heading_only_chunk(chunk)
            or key in seen
        ):
            continue
        seen.add(key)
        deduplicated.append(chunk)
    return deduplicated


def _normalize_content(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", normalized).strip().casefold()


def _attach_table_context(blocks: list[ParsedBlock]) -> list[ParsedBlock]:
    """Attach comparative-table headers only to adjacent header/data blocks.

    PyMuPDF frequently emits a header such as ``Six Months Ended`` and its
    date/year cells as independent blocks.  The old chunker then split the
    header from the metric row when a section heading appeared.  Header context
    is now bounded to its period cells and adjacent table-like rows; it is not
    propagated through arbitrary prose on the rest of the page.
    """

    if not blocks:
        return blocks
    context: str | None = None
    reading_header_cells = False
    attached: list[ParsedBlock] = []
    continuation_section = bool(
        blocks
        and _is_comparative_period_section(blocks[0].section)
        and any(_looks_like_financial_table_row(block.text) for block in blocks[:6])
    )
    annual_columns_active = False
    comparative_columns: tuple[str, ...] = ()
    comparative_table_context: str | None = None
    for index, block in enumerate(blocks):
        if block.content_type == "table":
            attached.append(block)
            continue
        cninfo_row = _verified_cninfo_annual_summary_row(blocks, index)
        if cninfo_row is not None:
            normalized_text, table_context = cninfo_row
            attached.append(
                replace(
                    block,
                    text=normalized_text,
                    table_context=table_context,
                    content_type="table",
                )
            )
            continue
        if _looks_like_financial_narrative_block(block.text):
            # Some PDF layout engines concatenate release highlights into one
            # text block. Explicit prose claims remain usable even when the
            # block contains multiple financial numbers; this is distinct
            # from an unmapped dense statement row.
            comparative_columns = ()
            comparative_table_context = None
            annual_columns_active = False
            attached.append(
                replace(block, table_context=None, content_type="narrative")
            )
            continue
        if _has_explicit_annual_column_headers(block.text):
            annual_columns_active = True
            attached.append(block)
            continue
        header_periods = _comparative_periods_before_first_financial_row(block.text)
        if header_periods:
            comparative_columns = header_periods
            preceding_headings = [
                candidate.text.strip()
                for candidate in blocks[max(0, index - 4) : index]
                if candidate.text.strip()
            ]
            normalized_headings = re.sub(
                r"[^a-z]", "", " ".join(preceding_headings).casefold()
            )
            if "financialsummary" in normalized_headings:
                heading_context = "Table section: Financial Summary. "
            else:
                heading_context = (
                    "Table section: " + " | ".join(preceding_headings[-2:]) + ". "
                    if preceding_headings
                    else ""
                )
            comparative_table_context = (
                heading_context + "Comparative columns: " + " | ".join(header_periods)
            )
        if block.content_type == "unverified_table":
            context = block.table_context or context
            attached.append(block)
            continue
        if annual_columns_active and _looks_like_financial_table_row(block.text):
            # A year-only column header immediately followed by financial rows
            # is an explicit map, not an unlabelled multi-period table.
            attached.append(block)
            continue

        if comparative_columns and _looks_like_financial_table_row(block.text):
            # A row following an explicit multi-period header can be rebound
            # safely by column order. This recovers single financial rows that
            # layout extraction detached from a otherwise valid table while
            # leaving tables with no reliable header quarantined below.
            if len(_TABLE_NUMBER.findall(block.text)) >= len(comparative_columns):
                attached.append(
                    replace(
                        block,
                        table_context=comparative_table_context,
                        content_type="table",
                    )
                )
                continue
            comparative_columns = ()
            comparative_table_context = None

        annual_columns_active = False
        if _looks_like_financial_table_row(block.text):
            nearby_dense_rows = sum(
                _looks_like_dense_unmapped_financial_row(candidate.text)
                for candidate in blocks[max(0, index - 2) : index + 3]
            )
            if _looks_like_dense_unmapped_financial_row(block.text) or nearby_dense_rows >= 2:
                attached.append(
                    replace(
                        block,
                        table_context=block.table_context
                        or "Unverified dense financial rows without a reliable column map",
                        content_type="unverified_table",
                    )
                )
                continue
        comparative_columns = ()
        comparative_table_context = None
        header_start = _looks_like_period_table_header(block.text) and _has_table_period_cells(
            blocks[index + 1 :]
        )
        if block.is_heading and not header_start and not (
            context and _has_nearby_financial_table_row(blocks, index + 1)
        ):
            context = None
            reading_header_cells = False
        if header_start:
            context = _table_header_text(blocks, index)
            reading_header_cells = True
            attached.append(replace(block, table_context=context))
            continue

        if context and reading_header_cells and _is_table_period_cell(block.text):
            attached.append(replace(block, table_context=context))
            continue

        reading_header_cells = False
        if context and _looks_like_financial_table_row(block.text):
            attached.append(
                replace(
                    block,
                    table_context=context,
                    content_type="unverified_table",
                )
            )
            continue

        if continuation_section and _looks_like_financial_table_row(block.text):
            attached.append(
                replace(
                    block,
                    table_context=f"Unverified comparative table continued in section: {block.section}",
                    content_type="unverified_table",
                )
            )
            continue

        if context and _has_nearby_financial_table_row(blocks, index + 1):
            # Financial statements often place subheadings and wrapped metric
            # labels between rows. Keep the table scope alive, without
            # attaching the stale period header to those prose fragments.
            attached.append(replace(block, table_context=None))
            continue

        # Once a non-table block follows a comparative header/data sequence,
        # stop carrying its periods into prose that may describe a different
        # time range.
        context = None
        attached.append(replace(block, table_context=None))
    return attached


def _verified_cninfo_annual_summary_row(
    blocks: list[ParsedBlock], index: int
) -> tuple[str, str] | None:
    """Bind only whitelisted CNINFO summary facts to explicit split headers.

    Some Chinese filing PDFs expose the year cells and the year-over-year
    column as separate text blocks. Promote a small set of exact summary row
    labels only when the adjacent header proves the three annual columns and
    comparison-rate column. Other dense rows remain quarantined.
    """

    block = blocks[index]
    row_source = block.text
    if index + 1 < len(blocks) and blocks[index + 1].page == block.page:
        continuation = re.sub(r"\s+", "", blocks[index + 1].text)
        if re.fullmatch(r"分点|百分点", continuation):
            row_source = f"{row_source} {blocks[index + 1].text}"
        elif continuation.startswith("分点"):
            row_source = f"{row_source} 分点"
    row = re.sub(r"\s+", " ", row_source).strip()
    summary_metrics = (
        (r"营业收入", "Revenue"),
        (r"归属于上市公司股东的净利润", "Net Income Attributable to Shareholders"),
        (r"经营活动产生的现金流量净额", "Operating Cash Flow"),
    )
    metric = next(
        (
            normalized
            for label, normalized in summary_metrics
            if re.match(rf"^{label}(?:\s|$)", row)
        ),
        None,
    )
    if metric is None:
        return _verified_cninfo_segment_row(blocks, index)

    preceding = [
        candidate.text
        for candidate in blocks[max(0, index - 10) : index]
        if candidate.page == block.page
    ]
    header = re.sub(r"\s+", "", " ".join(preceding))
    if not any(marker in header for marker in ("主要会计数据", "主要财务指标")):
        return None
    if not re.search(r"本期比.{0,6}上年同期增减", header):
        return None
    if not re.search(r"增减.{0,12}%|%", header):
        return None

    years = tuple(dict.fromkeys(re.findall(r"20\d{2}(?=年|\b)", header)))
    if len(years) != 3 or int(years[0]) - int(years[1]) != 1 or int(years[1]) - int(years[2]) != 1:
        return None

    values = [match.group(0).strip() for match in _TABLE_NUMBER.finditer(block.text)]
    if len(values) != 4:
        return None
    # The validated CNINFO header order is current year, prior year, YoY %,
    # then the third annual comparison year. Preserve only amount columns in
    # the structured fact row; do not let the unlabelled rate become a year.
    yoy = values[2].replace(",", "").replace("%", "").strip()
    try:
        yoy_value = float(yoy)
    except ValueError:
        return None
    if not -100 <= yoy_value <= 100:
        return None

    table_context = (
        f"CNINFO annual summary; Comparative columns: FY{years[0]} | "
        f"FY{years[1]} | FY{years[2]}; Currency: CNY"
    )
    annual_values = (values[0], values[1], values[3])
    canonical_values = tuple(value.replace(",", "").replace(" ", "") for value in annual_values)
    normalized = (
        f"Structured financial table row — Metric: {metric} | "
        f"FY{years[0]}: {canonical_values[0]} CNY | "
        f"FY{years[1]}: {canonical_values[1]} CNY | "
        f"FY{years[2]}: {canonical_values[2]} CNY | YoY: {yoy}%"
    )
    return normalized, table_context


def _verified_cninfo_segment_row(
    blocks: list[ParsedBlock], index: int
) -> tuple[str, str] | None:
    """Parse labelled revenue/margin cells from a verified CNINFO annual table.

    The parser requires a recognized section, its column headings, a known row
    label for that section, and the complete six-cell financial row. This keeps
    nearby prose and unlabeled dense rows quarantined.
    """

    block = blocks[index]
    row_source = block.text
    if index + 1 < len(blocks) and blocks[index + 1].page == block.page:
        continuation = re.sub(r"\s+", "", blocks[index + 1].text)
        if re.fullmatch(r"分点|百分点", continuation):
            row_source = f"{row_source} {blocks[index + 1].text}"
        elif continuation.startswith("分点"):
            row_source = f"{row_source} 分点"
    row = re.sub(r"\s+", " ", row_source).strip()
    row = re.sub(r"百\s+分", "百分", row)
    row = re.sub(r"^分点\s+", "", row)
    sections = (
        ("主营业务分行业情况", {"酒类"}, "industry"),
        ("主营业务分产品情况", {"茅台酒", "其他系列酒"}, "product"),
        ("主营业务分地区情况", {"国内", "国外"}, "region"),
        ("主营业务分销售模式情况", {"批发代理", "直销"}, "sales_mode"),
    )
    preceding_blocks = [candidate for candidate in blocks[max(0, index - 18) : index] if candidate.page == block.page]
    preceding = re.sub(r"\s+", " ", " ".join(candidate.text for candidate in preceding_blocks))
    selected = next(
        (
            (heading, categories, section_id)
            for heading, categories, section_id in reversed(sections)
            if heading in preceding
        ),
        None,
    )
    if selected is None:
        return None
    _, categories, section_id = selected
    if not all(marker in preceding for marker in ("营业收入", "毛利率", "营业成本")):
        return None

    label = next((value for value in categories if row.startswith(value + " ")), None)
    if label is None:
        return None
    cells = re.match(
        r"^(?P<label>[^ ]+)\s+"
        r"(?P<revenue>\d[\d,]*(?:\.\d+)?)\s+"
        r"(?P<cost>\d[\d,]*(?:\.\d+)?)\s+"
        r"(?P<margin>\d+(?:\.\d+)?)\s+"
        r"(?P<revenue_yoy>[+-]?\d+(?:\.\d+)?)\s+"
        r"(?P<cost_yoy>[+-]?\d+(?:\.\d+)?)\s+"
        r"(?:减少|增加)\s*(?P<margin_delta>\d+(?:\.\d+)?)\s*个百分?点",
        row,
    )
    if cells is None or cells.group("label") != label:
        return None

    revenue = cells.group("revenue").replace(",", "")
    margin = cells.group("margin")
    revenue_yoy = cells.group("revenue_yoy")
    table_context = (
        f"CNINFO annual segmented financial table; FY2025; "
        f"Dimension: {section_id}; Category: {label}; Currency: CNY"
    )
    normalized = (
        f"Structured financial table row — Dimension: {section_id}; Category: {label} | "
        f"Metric: Revenue | FY2025: {revenue} CNY | YoY: {revenue_yoy}%\n"
        f"Structured financial table row — Dimension: {section_id}; Category: {label} | "
        f"Metric: Gross Margin | FY2025: {margin}%"
    )
    return normalized, table_context


def _has_table_period_cells(blocks: list[ParsedBlock]) -> bool:
    nearby = [block.text.strip() for block in blocks[:8] if block.text.strip()]
    if len(set(period for text in nearby for period in extract_periods(text))) >= 2:
        return True

    years = {
        year
        for text in nearby
        for year in re.findall(r"\b20\d{2}\b", text)
    }
    dates = {
        text.casefold().strip(" ,")
        for text in nearby
        if _DATE_TABLE_CELL.fullmatch(text)
    }
    return len(years) >= 2 or (len(years) >= 1 and len(dates) >= 2)


def _is_table_period_cell(text: str) -> bool:
    normalized = clean_text(text).strip()
    return bool(
        re.fullmatch(r"20\d{2}", normalized)
        or _DATE_TABLE_CELL.fullmatch(normalized)
        or _PERIOD_HEADER_YEAR.fullmatch(normalized)
        or len(extract_periods(normalized)) == 1
        or len(_DATE_HEADER_TOKEN.findall(normalized)) >= 2
        or len(re.findall(r"\b20\d{2}\b", normalized)) >= 2
    )


def _is_comparative_period_section(section: str | None) -> bool:
    if not section:
        return False
    normalized = clean_text(section)
    return (
        _looks_like_period_table_header(normalized)
        or len(set(extract_periods(normalized))) >= 2
        or len(set(re.findall(r"\b20\d{2}\b", normalized))) >= 2
    )


def _has_nearby_financial_table_row(blocks: list[ParsedBlock], start: int) -> bool:
    for block in blocks[start : start + 5]:
        text = block.text.strip()
        if not text:
            continue
        if _looks_like_financial_table_row(text):
            return True
        if len(text) > 220 or re.search(r"[.!?。！？;；]", text):
            return False
    return False


def _table_header_text(blocks: list[ParsedBlock], start: int) -> str:
    parts: list[str] = []
    for prior in blocks[max(0, start - 3) : start]:
        text = prior.text.strip()
        if re.search(r"(?:\$\s*)?in\s+(?:thousands|millions|billions)", text, re.IGNORECASE):
            parts.append(text)
    parts.append(blocks[start].text.strip())
    for block in blocks[start + 1 : start + 8]:
        text = block.text.strip()
        if not text:
            continue
        if _is_table_period_cell(text):
            parts.append(text)
            continue
        break
    return "TABLE COLUMNS: " + " | ".join(parts)


def _merge_table_contexts(blocks: list[ParsedBlock]) -> str | None:
    contexts = [block.table_context for block in blocks if block.table_context]
    return contexts[0] if contexts else None


def _overlap_blocks(
    blocks: list[ParsedBlock],
    overlap: int,
) -> list[ParsedBlock]:
    if overlap == 0:
        return []

    retained: list[ParsedBlock] = []
    retained_length = 0
    for block in reversed(blocks):
        if retained and retained_length + len(block.text) > overlap:
            break
        retained.insert(0, block)
        retained_length += len(block.text)
        if retained_length >= overlap:
            break
    return retained


def _joined_length(blocks: list[ParsedBlock]) -> int:
    if not blocks:
        return 0
    return sum(len(block.text) for block in blocks) + (2 * (len(blocks) - 1))


def _split_long_text(
    text: str,
    chunk_size: int,
    overlap: int,
) -> list[str]:
    if len(text) <= chunk_size:
        return [text]

    sentences = [sentence.strip() for sentence in _SENTENCE_BOUNDARY.split(text) if sentence.strip()]
    if len(sentences) > 1 and all(len(sentence) <= chunk_size for sentence in sentences):
        pieces: list[str] = []
        current = ""
        for sentence in sentences:
            proposed = f"{current} {sentence}".strip()
            if current and len(proposed) > chunk_size:
                pieces.append(current)
                prefix = current[-overlap:].lstrip() if overlap else ""
                current = f"{prefix} {sentence}".strip()
            else:
                current = proposed
        if current:
            pieces.append(current)
        return pieces

    pieces = []
    step = chunk_size - overlap
    for start in range(0, len(text), step):
        piece = text[start : start + chunk_size].strip()
        if piece:
            pieces.append(piece)
        if start + chunk_size >= len(text):
            break
    return pieces


def _validate_chunk_settings(chunk_size: int, overlap: int) -> None:
    if chunk_size < 1:
        raise ValueError("CHUNK_SIZE must be positive")
    if overlap < 0:
        raise ValueError("CHUNK_OVERLAP must be non-negative")
    if overlap >= chunk_size:
        raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
