"""Small adapters around installed parsers; native and OCR inventories stay separate."""

from __future__ import annotations

import logging
import re
import threading
import unicodedata
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from typing import Protocol

import fitz

from document_loader import (
    PARSER_VERSION,
    DocumentProcessingError,
    _column_reading_order,
    _extract_text_regions,
    _find_reliable_table_header,
    parse_pdf,
)

from .models import (
    BBox,
    DocumentBlock,
    DocumentFingerprint,
    DocumentProfile,
    ExtractionInventory,
    FailureClass,
    FailureSignature,
    FormatFamily,
    PageFeatures,
    ReadingOrderConstraint,
    SourceSpan,
    stable_id,
)
from .policy import ParserCapability, ParserCapabilityRegistry, ParserPolicy
from .structural_audit import (
    CONTEXT_PATTERNS,
    cell_geometry,
    context_requirements,
    inherited_context_requirements,
    inline_source_order,
    merged_numeric_failures,
)


def normalized(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"(?<=\w)-\s*\n(?=\w)", "", text)
    return re.sub(r"\s+", "", text).casefold()


def area(box: BBox) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def overlap(left: BBox, right: BBox) -> float:
    intersection = (max(left[0], right[0]), max(left[1], right[1]), min(left[2], right[2]), min(left[3], right[3]))
    return area(intersection) / max(area(left), 1e-9)


def union_area(boxes: list[BBox]) -> float:
    """Exact rectangle union, so overlapping native/table regions are not double counted."""
    xs = sorted({x for box in boxes for x in (box[0], box[2])})
    total = 0.0
    for left, right in zip(xs, xs[1:]):
        intervals = sorted((b[1], b[3]) for b in boxes if b[0] < right and b[2] > left and area(b))
        covered = 0.0
        end = float("-inf")
        for bottom, top in intervals:
            covered += max(0, top - max(bottom, end))
            end = max(end, top)
        total += (right - left) * covered
    return total


class ParserAdapter(Protocol):
    parser_id: str
    parser_version: str
    capabilities: ParserCapability

    def supports(self, features: PageFeatures) -> bool: ...
    def parse_page(self, page: fitz.Page, document_id: str) -> tuple[SourceSpan, ...]: ...
    def parse_region(self, page: fitz.Page, document_id: str, bbox: BBox) -> tuple[SourceSpan, ...]: ...


class NativePDFAdapter:
    parser_id = "pymupdf-native"

    def __init__(self):
        self.capabilities = ParserCapabilityRegistry().get(self.parser_id)
        self.parser_version = self.capabilities.parser_version

    def supports(self, features: PageFeatures) -> bool:
        return features.has_native or features.blank

    def parse_page(self, page: fitz.Page, document_id: str) -> tuple[SourceSpan, ...]:
        return self.parse_region(page, document_id, tuple(page.rect))

    def parse_region(self, page: fitz.Page, document_id: str, bbox: BBox) -> tuple[SourceSpan, ...]:
        spans = []
        for block in page.get_text("dict", clip=fitz.Rect(bbox))["blocks"]:
            for line in block.get("lines", ()):
                for span in line["spans"]:
                    text = span["text"]
                    if text.strip():
                        box = tuple(float(x) for x in span["bbox"])
                        spans.append(
                            SourceSpan(
                                stable_id(document_id, page.number + 1, box, text, self.parser_id),
                                page.number + 1,
                                text,
                                box,
                            )
                        )
        return tuple(spans)


class OCRAdapter(NativePDFAdapter):
    parser_id = "tesseract"

    def __init__(self, *, language: str = "eng", dpi: int = 150, tessdata: str | None = None):
        self.capabilities = ParserCapabilityRegistry(ocr_available=True).get(self.parser_id)
        self.parser_version = self.capabilities.parser_version
        self.language, self.dpi, self.tessdata = language, dpi, tessdata

    def supports(self, features: PageFeatures) -> bool:
        return features.ocr_required

    def parse_region(self, page: fitz.Page, document_id: str, bbox: BBox) -> tuple[SourceSpan, ...]:
        # A clipped in-memory page limits OCR work and retains original page coordinates.
        clip = fitz.Rect(bbox)
        with fitz.open() as region_pdf:
            target = region_pdf.new_page(width=clip.width, height=clip.height)
            target.show_pdf_page(target.rect, page.parent, page.number, clip=clip)
            textpage = target.get_textpage_ocr(
                language=self.language,
                dpi=self.dpi,
                full=True,
                tessdata=self.tessdata,
            )
            spans = []
            for block in target.get_text("dict", textpage=textpage)["blocks"]:
                for line in block.get("lines", ()):
                    words = [span for span in line["spans"] if span["text"].strip()]
                    if not words:
                        continue
                    # Preserve a physical line, rather than indexing isolated OCR
                    # words that lose the relationship between label and value.
                    text = " ".join(word["text"].strip() for word in words)
                    box = (min(word["bbox"][0] for word in words) + clip.x0,
                           min(word["bbox"][1] for word in words) + clip.y0,
                           max(word["bbox"][2] for word in words) + clip.x0,
                           max(word["bbox"][3] for word in words) + clip.y0)
                    spans.append(SourceSpan(
                        stable_id(document_id, page.number + 1, box, text, "ocr"),
                        page.number + 1, text, box, "OCR", "tesseract",
                    ))
            return tuple(spans)


class TablePDFAdapter(NativePDFAdapter):
    parser_id = "pymupdf-table"

    def supports(self, features: PageFeatures) -> bool:
        return features.has_native and features.table_density > 0

    def parse_region(self, page: fitz.Page, document_id: str, bbox: BBox) -> tuple[SourceSpan, ...]:
        result = []
        for table_index, table in enumerate(page.find_tables(clip=fitz.Rect(bbox), strategy="lines").tables):
            for row_index, (values, row) in enumerate(zip(table.extract(), table.rows)):
                for column_index, (value, box) in enumerate(zip(values, row.cells)):
                    if value and box:
                        result.append(
                            SourceSpan(
                                stable_id(document_id, page.number + 1, table_index, row_index, column_index),
                                page.number + 1,
                                value,
                                tuple(box),
                                "TABLE_PARSER",
                                self.parser_id,
                            )
                        )
        return tuple(result)


class LayoutPDFAdapter(NativePDFAdapter):
    parser_id = "existing-layout"

    def supports(self, features: PageFeatures) -> bool:
        return features.has_native and features.column_count > 1

    def parse_page(self, page: fitz.Page, document_id: str) -> tuple[SourceSpan, ...]:
        return tuple(
            SourceSpan(
                stable_id(document_id, page.number + 1, region.bbox, self.parser_id),
                page.number + 1,
                region.text,
                region.bbox,
                "LAYOUT",
                self.parser_id,
            )
            for region in _extract_text_regions(page)
        )

    def parse_region(self, page: fitz.Page, document_id: str, bbox: BBox) -> tuple[SourceSpan, ...]:
        raise NotImplementedError("existing layout helper supports complete pages only")


class _ParserAuditHandler(logging.Handler):
    """Observe legacy swallowed exceptions without changing production parser behavior."""

    def __init__(self):
        super().__init__()
        self.owner = threading.get_ident()
        self.failures = []

    def emit(self, record):
        if record.thread != self.owner:
            return
        message = record.getMessage()
        if (
            "extraction skipped" in message
            or "materialization failed" in message
            or ("candidate rejected" in message and "reason=" in message)
        ):
            page = re.search(r"page=(\d+)", message)
            self.failures.append(
                FailureSignature(
                    FailureClass.TABLE_STRUCTURE_LOSS,
                    int(page.group(1)) if page else 0,
                    features=(("parser_event", message),),
                )
            )


def classify(document_id: str, pages: tuple[PageFeatures, ...], text: str, statements: tuple[str, ...]):
    count = max(len(pages), 1)
    native = sum(p.has_native for p in pages)
    scanned = sum(p.ocr_required and not p.has_native for p in pages)
    mixed = sum(p.has_native and p.ocr_required for p in pages)
    source_format = (
        "PDF_MIXED"
        if (native and scanned) or mixed
        else "PDF_NATIVE"
        if native
        else "PDF_SCANNED"
        if scanned
        else "UNKNOWN"
    )
    language = tuple(
        label
        for label, match in (
            ("zh-CN", re.search(r"[\u4e00-\u9fff]", text)),
            ("en", re.search(r"\b[A-Za-z]{3,}\b", text)),
        )
        if match
    )
    hints = tuple(
        label
        for label, match in (
            ("CAS", re.search(r"企业会计准则|合并资产负债表", text)),
            ("US_GAAP", re.search(r"U\.?S\.?\s+GAAP|generally accepted accounting principles", text, re.I)),
            ("IFRS", re.search(r"\bIFRS\b|International Financial Reporting Standards", text, re.I)),
        )
        if match
    )
    family = {
        "PDF_NATIVE": FormatFamily.NATIVE_TEXT_PDF,
        "PDF_SCANNED": FormatFamily.SCANNED_PDF,
        "PDF_MIXED": FormatFamily.HYBRID_PDF,
        "UNKNOWN": FormatFamily.UNKNOWN,
    }
    families = [family[source_format]]
    if "CAS" in hints:
        if re.search(r"半年度报告|中期报告", text):
            families.append(FormatFamily.CAS_INTERIM_REPORT)
        elif re.search(r"年度报告|年\s*1\s*[—–-]\s*12\s*月", text):
            families.append(FormatFamily.CAS_ANNUAL_REPORT)
    for label, pattern in ((FormatFamily.SEC_10K, r"FORM\s+10-K"), (FormatFamily.SEC_10Q, r"FORM\s+10-Q")):
        if re.search(pattern, text, re.I):
            families.append(label)
    if "IFRS" in hints and re.search(r"annual report", text, re.I):
        families.append(FormatFamily.IFRS_ANNUAL_REPORT)
    if any(p.column_count > 1 for p in pages):
        families.append(FormatFamily.MULTICOLUMN_REPORT)
    if any(p.complex_table or p.table_structure_confidence < 1 for p in pages):
        families.append(FormatFamily.COMPLEX_TABLE_REPORT)
    fingerprint = DocumentFingerprint(
        document_id,
        len(pages),
        native / count,
        scanned / count,
        mixed / count,
        sum(p.table_density for p in pages) / count,
        sum(p.column_count > 1 for p in pages) / count,
        sum(p.ocr_required for p in pages) / count,
        language,
        hints,
        statements,
        "HIGH" if any(p.layout_complexity == "HIGH" for p in pages) else "LOW",
        sum(p.native_text_quality for p in pages) / count,
        None,
        source_format,
    )
    return DocumentProfile(fingerprint, tuple(families), ("classification uses source content and page geometry",))


def extract_inventory(path: Path, policy: ParserPolicy) -> ExtractionInventory:
    document_id = stable_id(path.read_bytes().hex())
    adapter = NativePDFAdapter()
    native, features, failures = [], [], []
    reading_constraints, requirements = [], []
    # Existing P1.3 stays unchanged. A failure is retained even if native recovery succeeds.
    started = perf_counter()
    observer = _ParserAuditHandler()
    parser_logger = logging.getLogger("document_loader")
    previous_level = parser_logger.level
    parser_logger.addHandler(observer)
    parser_logger.setLevel(logging.INFO)
    try:
        parsed = parse_pdf(path, ocr_enabled=False, document_id=document_id)
    except Exception as exc:
        parsed = None
        if not (isinstance(exc, DocumentProcessingError) and "no extractable text" in str(exc)):
            failures.append(
                FailureSignature(
                    FailureClass.PAGE_PARSE_FAILURE,
                    0,
                    features=(("exception_type", type(exc).__name__),),
                )
            )
    finally:
        parser_logger.removeHandler(observer)
        parser_logger.setLevel(previous_level)
    failures.extend(observer.failures)
    parse_time = perf_counter() - started
    started = perf_counter()
    with fitz.open(path) as pdf:
        for page in pdf:
            page_number = page.number + 1
            try:
                spans = adapter.parse_page(page, document_id)
                native.extend(spans)
                images = [tuple(item["bbox"]) for item in page.get_image_info()]
                parsed_page = parsed.pages[page.number] if parsed else None
                tables = parsed_page.table_candidates if parsed_page else ()
                image_ratio = min(1, union_area(images) / max(area(tuple(page.rect)), 1))
                blocks = page.get_text("blocks", sort=True)
                prose = [b for b in blocks if len(b) >= 7 and b[6] == 0 and len(b[4].strip()) > 50]
                left = [b for b in prose if b[2] < page.rect.width * 0.6]
                right = [b for b in prose if b[0] > page.rect.width * 0.4]
                multicolumn = len(left) >= 2 and len(right) >= 2 and not tables
                ordered = _column_reading_order(prose, page.rect, page_words=page.get_text("words"))
                if policy.audit_geometry_context and multicolumn and ordered:
                    ordered_ids = tuple(
                        dict.fromkeys(
                            span.span_id
                            for region in ordered
                            for span in inline_source_order(tuple(
                                source for source in spans
                                if overlap(source.bbox, tuple(region[:4])) > 0.5
                                and normalized(source.text) in normalized(str(region[4]))
                            ))
                        )
                    )
                    reading_constraints.append(ReadingOrderConstraint(page_number, ordered_ids))
                covered_images = all(
                    union_area([s.bbox for s in spans if overlap(s.bbox, image) > 0.5]) / max(area(image), 1) > 0.1
                    for image in images
                )
                needs_ocr = bool(images) and image_ratio > 0.1 and (not spans or not covered_images)
                text = "".join(s.text for s in spans)
                quality = 1 - text.count("\ufffd") / max(len(text), 1)
                features.append(
                    PageFeatures(
                        page_number,
                        len(text) / max(area(tuple(page.rect)), 1),
                        image_ratio,
                        min(1, union_area([t.bbox for t in tables]) / max(area(tuple(page.rect)), 1)),
                        2 if multicolumn else 1,
                        "HIGH" if multicolumn else "LOW",
                        quality,
                        needs_ocr,
                        1.0,
                        0.9 if ordered else 0.0 if multicolumn else 1.0,
                        not spans and not images,
                        bool(spans),
                        None,
                        page.rect.width,
                        page.rect.height,
                    )
                )
            except Exception as exc:
                features.append(PageFeatures(page_number, native_text_quality=0, reading_order_confidence=0))
                failures.append(
                    FailureSignature(
                        FailureClass.PAGE_PARSE_FAILURE,
                        page_number,
                        features=(("exception_type", type(exc).__name__),),
                    )
                )
    canonical = []
    if parsed:
        for page in parsed.pages:
            for index, block in enumerate(page.blocks):
                source_ids = tuple(
                    span.span_id
                    for span in native
                    if span.page == page.number
                    and normalized(span.text) in normalized(block.text)
                    and all(
                        token in re.findall(r"\d+(?:,\d+)*(?:\.\d+)?", block.text)
                        for token in re.findall(r"\d+(?:,\d+)*(?:\.\d+)?", span.text)
                    )
                    and (block.bbox is None or overlap(span.bbox, block.bbox) > 0.5)
                )
                canonical.append(
                    DocumentBlock(
                        stable_id(document_id, page.number, index, block.text),
                        document_id,
                        page.number,
                        "TABLE" if block.content_type == "table" else "TITLE" if block.is_heading else "TEXT",
                        block.text,
                        block.bbox,
                        "TABLE_PARSER" if block.financial_table_row else "NATIVE_PDF",
                        "pymupdf-table" if block.financial_table_row else "pymupdf-native",
                        PARSER_VERSION,
                        policy.version,
                        reading_order=index,
                        source_ids=source_ids,
                        section=block.section,
                    )
                )
            # Preserve candidate grids as blocks too. A continuation is declared
            # only from an explicit source title, never merely a similar number.
            for table in page.table_candidates:
                rows = [[value or "" for value in row.cells] for row in table.rows]
                header_index = _find_reliable_table_header(rows)
                geometry = cell_geometry(table, tuple(span for span in native if span.page == page.number)
                                         if policy.prove_native_merged_regions else ())
                block_id = stable_id(document_id, page.number, "candidate", table.table_index)
                local_context = ()
                if policy.audit_geometry_context:
                    table_failures = merged_numeric_failures(table, geometry, header_index, parsed.financial_table_rows)
                    failures.extend(table_failures)
                    if any(c.row_span > 1 or c.column_span > 1 for c in geometry):
                        features = [
                            replace(
                                p,
                                complex_table=True,
                                layout_complexity="HIGH",
                                table_structure_confidence=min(
                                    p.table_structure_confidence, 0.5 if table_failures else 1.0
                                ),
                            )
                            if p.page == page.number
                            else p
                            for p in features
                        ]
                    header_bottom = (
                        max(cell.bbox[3] for cell in geometry if cell.row <= header_index)
                        if header_index is not None
                        else None
                    )
                    previous_bottom = max(
                        (other.bbox[3] for other in page.table_candidates if other.bbox[3] <= table.bbox[1]),
                        default=0,
                    )
                    local_context = context_requirements(block_id, table, native, header_bottom, previous_bottom)
                    requirements.extend(local_context)
                headings = [
                    b
                    for b in page.blocks
                    if b.bbox
                    and 0 <= table.bbox[1] - b.bbox[3] <= 100
                    and len(b.text.strip()) < 180
                    and not re.search(r"\d", b.text)
                    and not CONTEXT_PATTERNS[FailureClass.UNIT_CONTEXT_LOSS].search(b.text)
                ]
                title = headings[-1].text if headings else ""
                continuing = bool(re.search(r"continued|续表", title, re.I))
                section = re.sub(r"\(?continued\)?|[（(]?续表[）)]?", "", title, flags=re.I).strip()
                columns = next(
                    (
                        tuple((box[0] + box[2]) / 2 for box in row.cell_bboxes if box)
                        for row in table.rows
                        if len(row.cell_bboxes) >= 2 and all(row.cell_bboxes)
                    ),
                    (),
                )
                text = "\n".join(" | ".join(row) for row in rows)
                ids = tuple(
                    s.span_id
                    for s in native
                    if s.page == page.number
                    and overlap(s.bbox, table.bbox) > 0.5
                    and normalized(s.text) in normalized(text)
                    and all(
                        token in re.findall(r"\d+(?:,\d+)*(?:\.\d+)?", text)
                        for token in re.findall(r"\d+(?:,\d+)*(?:\.\d+)?", s.text)
                    )
                )
                if text.strip():
                    canonical.append(
                        DocumentBlock(
                            block_id,
                            document_id,
                            page.number,
                            "TABLE",
                            text,
                            table.bbox,
                            "TABLE_PARSER",
                            "pymupdf-table",
                            PARSER_VERSION,
                            policy.version,
                            source_ids=ids,
                            table_header=" | ".join(rows[header_index]) if header_index is not None else "",
                            table_columns=columns,
                            continuation=continuing,
                            section=section,
                            table_cells=geometry,
                            context_text="\n".join(dict.fromkeys(c.text for c in local_context)),
                            context_source_ids=tuple(dict.fromkeys(c.source_id for c in local_context)),
                        )
                    )
    statements = tuple(sorted({c.statement_type for c in parsed.financial_table_contexts})) if parsed else ()
    text = "\n".join(s.text for s in native)
    profile = classify(document_id, tuple(features), text, statements)
    if policy.audit_geometry_context:
        requirements = inherited_context_requirements(canonical, requirements, normalized)
    return ExtractionInventory(
        document_id,
        profile,
        tuple(features),
        tuple(native),
        (),
        tuple(canonical),
        tuple(failures),
        sum(len(p.table_candidates) for p in parsed.pages) if parsed else 0,
        sum(len(r.cells) for p in parsed.pages for t in p.table_candidates for r in t.rows) if parsed else 0,
        parsed,
        {"PRIMARY_PARSE_TIME": parse_time, "FINGERPRINT_TIME": perf_counter() - started},
        tuple(requirements),
        tuple(reading_constraints),
    )
