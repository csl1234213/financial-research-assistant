"""Offline completeness audit, bounded recovery and promotion decisions."""

from __future__ import annotations

import re
from dataclasses import replace
from difflib import SequenceMatcher
from pathlib import Path
from time import perf_counter

import fitz

from core.financial_metric_registry import FINANCIAL_METRIC_REGISTRY
from document_loader import _is_usable_ocr_block

from .adapters import OCRAdapter, extract_inventory, normalized, overlap, union_area
from .models import (
    CompatibilityReport,
    DiscardRecord,
    DocumentBlock,
    DocumentState,
    ExtractionInventory,
    FailureClass,
    FailureSignature,
    FormatFamily,
    PageQualityReport,
    RecoveryProvenance,
    SourceSpan,
    TracedChunk,
    stable_id,
)
from .policy import (
    DEFAULT_POLICY,
    POLICIES,
    DocumentQualityContractRegistry,
    FailureSignatureRegistry,
    ParserCapabilityRegistry,
    ParserPolicy,
    ParserPolicyEngine,
    RecoveryPolicyRegistry,
)
from .structural_audit import adjacent_table, detect_structure, reading_order_failures


def critical(text: str) -> bool:
    """Presence detection only; no metric identity/eligibility is changed."""
    key = normalized(text)
    return any(
        normalized(alias) in key
        for definition in FINANCIAL_METRIC_REGISTRY.definitions
        for alias in (*definition.aliases_zh, *definition.aliases_en)
        if alias
    )


def numbers(text: str) -> tuple[str, ...]:
    # A comma belongs to a numeric token only when followed by more digits.
    # Otherwise an inline marker such as "day2, allowing" is falsely orphaned.
    return tuple(re.findall(r"\d+(?:,\d+)*(?:\.\d+)?", text))


def represents(span: SourceSpan, block: DocumentBlock) -> bool:
    if span.page != block.page:
        return False
    geometric = block.bbox is not None and overlap(span.bbox, block.bbox) >= 0.5
    if span.span_id not in block.source_ids and not geometric:
        return False
    raw, rendered = normalized(span.text), normalized(block.text)
    if any(value not in numbers(block.text) for value in numbers(span.text)):
        return False
    if raw and raw in rendered:
        return True
    # Approximate text is permitted only with geometry and no numeric substitution.
    return bool(geometric and not numbers(span.text) and SequenceMatcher(None, raw, rendered).ratio() >= 0.96)


def _header_match(previous: DocumentBlock, current: DocumentBlock) -> bool:
    return adjacent_table(previous, current, normalized)


def detect(inventory: ExtractionInventory, blocks: tuple[DocumentBlock, ...], policy: ParserPolicy):
    sources = {s.span_id: s for s in (*inventory.native_spans, *inventory.ocr_spans)}
    failures = [
        f
        if isinstance(f.failure_class, FailureClass)
        else replace(
            f,
            failure_class=FailureClass.UNKNOWN_FAILURE,
            features=(*f.features, ("unregistered_failure", str(f.failure_class))),
        )
        for f in inventory.parser_failures
    ]
    if policy.audit_geometry_context:
        failures.extend(detect_structure(inventory, blocks, normalized))
    if FormatFamily.UNKNOWN in inventory.profile.format_families:
        failures.append(FailureSignature(FailureClass.UNKNOWN_DOCUMENT_PROFILE, 0))
    for page in inventory.page_features:
        if page.blank:
            continue
        if page.ocr_required and not any(s.page == page.page and s.text.strip() for s in inventory.ocr_spans):
            failures.append(FailureSignature(FailureClass.OCR_REQUIRED, page.page))
            if not page.has_native:
                failures.append(FailureSignature(FailureClass.NO_NATIVE_TEXT, page.page))
        if page.native_text_quality < 0.95:
            failures.append(FailureSignature(FailureClass.LAYOUT_LOSS, page.page))
        if page.reading_order_confidence < policy.minimum_reading_confidence:
            failures.append(FailureSignature(FailureClass.MULTICOLUMN_READING_ORDER_ERROR, page.page))
        if page.table_structure_confidence < 0.8:
            failures.append(FailureSignature(FailureClass.MERGED_CELL_AMBIGUITY, page.page))
    for span in (*inventory.native_spans, *inventory.ocr_spans):
        if not span.valid or not span.text.strip():
            continue
        if span.source == "OCR" and any(
            n.page == span.page and n.valid and overlap(span.bbox, n.bbox) > 0.5 for n in inventory.native_spans
        ):
            continue  # OCR verifier cannot replace a valid native region.
        if not any(represents(span, block) for block in blocks):
            is_critical = critical(span.text)
            failures.append(
                FailureSignature(
                    FailureClass.CRITICAL_FINANCIAL_CONTENT_LOSS if is_critical else FailureClass.ORPHAN_TEXT,
                    span.page,
                    (span.span_id,),
                    features=(("trusted_native_source", str(span.source == "NATIVE_PDF" and span.valid).lower()),),
                    critical=is_critical,
                )
            )
    for block in blocks:
        native_by_id = {s.span_id: s for s in inventory.native_spans}
        if any(
            sid in native_by_id and numbers(native_by_id[sid].text) and not represents(native_by_id[sid], block)
            for sid in block.source_ids
        ):
            failures.append(
                FailureSignature(
                    FailureClass.TABLE_COLUMN_SHIFT,
                    block.page,
                    block_ids=(block.block_id,),
                    critical=True,
                )
            )
        if block.continuation and not block.table_header:
            prior = next((b for b in blocks if _header_match(b, block)), None)
            failures.append(
                FailureSignature(
                    FailureClass.CROSS_PAGE_TABLE_HEADER_LOSS,
                    block.page,
                    block_ids=(block.block_id,),
                    features=tuple(
                        (key, str(prior is not None).lower())
                        for key in ("adjacent_page", "matching_columns", "same_section")
                    ),
                    critical=True,
                )
            )
        if block.text.strip() and (
            not block.source_ids
            or block.document_id != inventory.document_id
            or any(sid not in sources or sources[sid].page != block.page for sid in block.source_ids)
        ):
            failures.append(FailureSignature(FailureClass.PROVENANCE_LOSS, block.page, block_ids=(block.block_id,)))
        if block.recovered and (not block.provenance or not block.recovery_reason):
            failures.append(FailureSignature(FailureClass.PROVENANCE_LOSS, block.page, block_ids=(block.block_id,)))
    for contract in DocumentQualityContractRegistry().for_profile(inventory.profile):
        missing = set(contract.required_statements) - set(inventory.profile.fingerprint.financial_statement_presence)
        if missing:
            failures.append(
                FailureSignature(
                    FailureClass.TABLE_STRUCTURE_LOSS,
                    0,
                    features=(("missing_statements", ",".join(sorted(missing))),),
                    critical=True,
                )
            )
    return tuple(dict.fromkeys(failures))


def merge_numeric_conflicts(inventory, blocks, policy):
    result, conflicts = list(blocks), []
    for block in blocks:
        if block.source != "OCR" or block.bbox is None or not numbers(block.text):
            continue
        authoritative = [
            s
            for s in inventory.native_spans
            if s.page == block.page
            and s.valid
            and numbers(s.text)
            and overlap(s.bbox, block.bbox) > 0.5
            and numbers(s.text) != numbers(block.text)
        ]
        if not authoritative:
            continue
        result = [b for b in result if b.block_id != block.block_id]
        conflicts.append(
            FailureSignature(
                FailureClass.NATIVE_OCR_NUMERIC_CONFLICT,
                block.page,
                tuple(s.span_id for s in authoritative),
                (block.block_id,),
                critical=True,
            )
        )
        for span in authoritative:
            provenance = RecoveryProvenance(
                FailureClass.NATIVE_OCR_NUMERIC_CONFLICT,
                "retain-native",
                "1",
                "OCR",
                "NATIVE_PDF",
                "rejected conflicting OCR numeric candidate",
                (span.span_id, *block.source_ids),
                1.0,
            )
            existing = next((i for i, b in enumerate(result) if represents(span, b)), None)
            if existing is not None:
                result[existing] = replace(
                    result[existing],
                    recovered=True,
                    recovery_reason=FailureClass.NATIVE_OCR_NUMERIC_CONFLICT,
                    provenance=(*result[existing].provenance, provenance),
                )
            else:
                result.append(
                    DocumentBlock(
                        stable_id(span.span_id, "retain-native"),
                        inventory.document_id,
                        span.page,
                        "TEXT",
                        span.text,
                        span.bbox,
                        "NATIVE_PDF",
                        span.parser_id,
                        "native-inventory-v1",
                        policy.version,
                        source_ids=(span.span_id,),
                        recovered=True,
                        recovery_reason=FailureClass.NATIVE_OCR_NUMERIC_CONFLICT,
                        provenance=(provenance,),
                    )
                )
    return tuple(result), tuple(conflicts)


def recover(inventory, blocks, failures, policy):
    """Recover only known signatures from retained authoritative sources."""
    result = list(blocks)
    sources = {s.span_id: s for s in inventory.native_spans}
    signatures = FailureSignatureRegistry()
    registry = RecoveryPolicyRegistry()
    for failure in failures:
        if not signatures.supports(failure.failure_class, dict(failure.features)):
            continue
        recovery = registry.route(failure.failure_class)
        if recovery.action == "REGION_RECOVERY" and policy.recover_native_orphans:
            for source_id in failure.source_ids:
                span = sources.get(source_id)
                if not span or any(represents(span, b) for b in result):
                    continue
                provenance = RecoveryProvenance(
                    failure.failure_class,
                    recovery.policy_id,
                    recovery.version,
                    "PRIMARY_CANONICAL_MISSING",
                    span.source,
                    "retained native span restores missing region",
                    (source_id,),
                    1.0,
                )
                result.append(
                    DocumentBlock(
                        stable_id(inventory.document_id, source_id, "recovered"),
                        inventory.document_id,
                        span.page,
                        "TEXT",
                        span.text,
                        span.bbox,
                        "RECOVERED",
                        span.parser_id,
                        "native-inventory-v1",
                        policy.version,
                        source_ids=(source_id,),
                        recovered=True,
                        recovery_reason=failure.failure_class,
                        provenance=(provenance,),
                    )
                )
        elif recovery.action == "TABLE_CONTEXT_INHERITANCE" and policy.recover_headers:
            for index, block in enumerate(result):
                if block.block_id not in failure.block_ids:
                    continue
                prior = next((b for b in result if _header_match(b, block)), None)
                if prior:
                    required_context = tuple(r for r in inventory.context_requirements if r.block_id == block.block_id)
                    provenance = RecoveryProvenance(
                        failure.failure_class,
                        recovery.policy_id,
                        recovery.version,
                        block.source,
                        prior.source,
                        "adjacent table with same section and matching columns",
                        tuple(dict.fromkeys((*prior.source_ids, *(r.source_id for r in required_context)))),
                        1.0,
                    )
                    result[index] = replace(
                        block,
                        table_header=prior.table_header,
                        recovered=True,
                        parent_block_id=prior.block_id,
                        recovery_reason=failure.failure_class,
                        provenance=(*block.provenance, provenance),
                        context_text="\n".join(dict.fromkeys(r.text for r in required_context)),
                        context_source_ids=tuple(dict.fromkeys(r.source_id for r in required_context)),
                    )
    return tuple(result)


def rendered_block(block: DocumentBlock) -> str:
    prefix = []
    if block.context_text and normalized(block.context_text) not in normalized(block.text):
        prefix.append(block.context_text)
    if block.table_header and normalized(block.table_header) not in normalized(block.text):
        prefix.append(block.table_header)
    return "\n".join((*prefix, block.text))


def serialize_blocks(blocks: tuple[DocumentBlock, ...]) -> dict[str, str]:
    return {block.block_id: rendered_block(block) for block in blocks}


def build_chunks(blocks: tuple[DocumentBlock, ...], *, size: int = 900):
    if size <= 0:
        raise ValueError("chunk size must be positive")
    chunks, discards = [], []
    for block in blocks:
        text = rendered_block(block)
        if not block.text.strip():
            discards.append(DiscardRecord(block.block_id, "EMPTY"))
            continue
        if block.block_type == "FIGURE" and not block.text:
            discards.append(DiscardRecord(block.block_id, "NON_TEXT"))
            continue
        for index in range(0, len(text), size):
            chunks.append(
                TracedChunk(
                    stable_id(block.block_id, index),
                    block.page,
                    text[index : index + size],
                    (block.block_id,),
                    block.policy_version,
                )
            )
    return tuple(chunks), tuple(discards)


def audit_document(
    inventory: ExtractionInventory,
    *,
    policy: ParserPolicy = DEFAULT_POLICY,
    serialized: dict[str, str] | None = None,
    chunks: tuple[TracedChunk, ...] | None = None,
    discards: tuple[DiscardRecord, ...] | None = None,
) -> CompatibilityReport:
    if POLICIES.get(policy.version) != policy:
        raise ValueError("unregistered or mutated parser policy; register a new version")
    start = perf_counter()
    blocks = tuple(replace(b, policy_version=policy.version) for b in inventory.canonical_blocks)
    blocks, conflicts = merge_numeric_conflicts(inventory, blocks, policy)
    before = (*conflicts, *detect(inventory, blocks, policy))
    audit_time = perf_counter() - start
    start = perf_counter()
    blocks = recover(inventory, blocks, before, policy)
    recovery_time = perf_counter() - start
    failures = list(detect(inventory, blocks, policy))
    output = serialize_blocks(blocks) if serialized is None else serialized
    built_chunks, built_discards = build_chunks(blocks)
    chunks = built_chunks if chunks is None else chunks
    discards = built_discards if discards is None else discards
    block_map = {b.block_id: b for b in blocks}
    valid_discards = set()
    for discard in discards:
        block = block_map.get(discard.block_id)
        retained = block_map.get(discard.retained_block_id or "")
        # A reason string alone must never authorize dropping a financial row.
        if block and (
            (discard.reason == "EMPTY" and not block.text.strip())
            or (discard.reason == "NON_TEXT" and block.block_type == "FIGURE" and not block.text)
            or (
                discard.reason == "DUPLICATE"
                and retained
                and retained != block
                and retained.page == block.page
                and retained.bbox == block.bbox
                and retained.text == block.text
            )
        ):
            valid_discards.add(discard.block_id)
    for block in blocks:
        if normalized(output.get(block.block_id, "")) != normalized(rendered_block(block)):
            failures.append(
                FailureSignature(
                    FailureClass.SERIALIZATION_LOSS,
                    block.page,
                    block_ids=(block.block_id,),
                    critical=critical(block.text),
                )
            )
        consumed = "".join(c.text for c in chunks if block.block_id in c.source_block_ids and c.page == block.page)
        if block.block_id not in valid_discards and normalized(rendered_block(block)) not in normalized(consumed):
            failures.append(
                FailureSignature(
                    FailureClass.CHUNK_BLOCK_LOSS,
                    block.page,
                    block_ids=(block.block_id,),
                    critical=critical(block.text),
                )
            )
    for chunk in chunks:
        if not chunk.source_block_ids or any(b not in block_map for b in chunk.source_block_ids):
            failures.append(FailureSignature(FailureClass.PROVENANCE_LOSS, chunk.page))
            continue
        source_blocks = [block_map[bid] for bid in chunk.source_block_ids]
        source_text = "".join(rendered_block(block) for block in source_blocks)
        if (
            any(block.page != chunk.page for block in source_blocks)
            or chunk.policy_version != policy.version
            or normalized(chunk.text) not in normalized(source_text)
        ):
            failures.append(FailureSignature(FailureClass.PROVENANCE_LOSS, chunk.page))
    if policy.audit_geometry_context:
        projected = []
        for chunk in chunks:
            referenced = [block_map[bid] for bid in chunk.source_block_ids if bid in block_map]
            if not referenced:
                continue  # Missing ownership is rejected by the completeness gate above.
            # Each chunk has one rendered sequence. Repeating that whole text
            # once per source block creates false first-occurrence bindings.
            projected.append(replace(referenced[0], text=chunk.text, page=chunk.page,
                source_ids=tuple(dict.fromkeys(sid for block in referenced for sid in block.source_ids))))
        failures.extend(reading_order_failures(inventory, tuple(projected), normalized))
    failures = list(dict.fromkeys(failures))
    state = DocumentState.QUARANTINED if failures else DocumentState.READY
    if not blocks and any(f.failure_class == FailureClass.PAGE_PARSE_FAILURE for f in failures):
        state = DocumentState.FAILED
    policy_engine = ParserPolicyEngine()
    page_reports = []
    for page in inventory.page_features:
        page_failures = [f for f in failures if f.page in (0, page.page)]
        native = [s for s in inventory.native_spans if s.page == page.page]
        missing = [s for s in native if not any(represents(s, b) for b in blocks)]
        total_area = union_area([s.bbox for s in native])
        coverage = 1 - union_area([s.bbox for s in missing]) / total_area if total_area else 1.0
        plan = policy_engine.plan(inventory.profile, page, ParserCapabilityRegistry())
        page_reports.append(
            PageQualityReport(
                page.page,
                tuple(inventory.profile.format_families),
                policy.version,
                plan.primary,
                plan.shadow,
                len(native),
                sum(s.page == page.page for s in inventory.ocr_spans),
                sum(b.page == page.page for b in blocks),
                len(missing),
                sum(critical(s.text) for s in missing),
                coverage,
                tuple(s.bbox for s in missing),
                "FAIL"
                if any(f.failure_class == FailureClass.MULTICOLUMN_READING_ORDER_ERROR for f in page_failures)
                else "PASS"
                if page.reading_order_confidence >= policy.minimum_reading_confidence
                else "UNPROVEN",
                "FAIL"
                if any(
                    "TABLE" in f.failure_class
                    or "COLUMN" in f.failure_class
                    or f.failure_class
                    in {
                        FailureClass.MERGED_CELL_AMBIGUITY,
                        FailureClass.PERIOD_CONTEXT_LOSS,
                        FailureClass.UNIT_CONTEXT_LOSS,
                        FailureClass.SCOPE_CONTEXT_LOSS,
                    }
                    for f in page_failures
                )
                else "PASS",
                tuple(sorted({f.failure_class for f in page_failures})),
                bool(page_failures),
                "FAIL"
                if page_failures
                else "WARNING"
                if any(b.recovered and b.page == page.page for b in blocks)
                else "PASS",
            )
        )
    counters = {
        "RAW_SPANS": len(inventory.native_spans),
        "OCR_SPANS": len(inventory.ocr_spans),
        "CANONICAL_BLOCKS": len(blocks),
        "RECOVERED_BLOCKS": sum(b.recovered for b in blocks),
        "CHUNK_INPUT_BLOCKS": len(blocks),
        "CHUNK_CONSUMED_BLOCKS": len({bid for c in chunks for bid in c.source_block_ids}),
        "UNEXPLAINED_DROPPED_BLOCKS": sum(f.failure_class == FailureClass.CHUNK_BLOCK_LOSS for f in failures),
        "CRITICAL_ORPHANS": sum(p.critical_orphan_count for p in page_reports),
        "ORPHAN_SPANS": sum(p.orphan_count for p in page_reports),
        "SERIALIZATION_LOSS": sum(f.failure_class == FailureClass.SERIALIZATION_LOSS for f in failures),
        "RECOVERY_PROVENANCE_LOSS": sum(f.failure_class == FailureClass.PROVENANCE_LOSS for f in failures),
        "NATIVE_NUMERIC_OVERWRITE_COUNT": sum(
            bool(numbers(s.text))
            and s.valid
            and not any(represents(s, b) for b in blocks)
            and any(b.source == "OCR" and b.page == s.page and b.bbox and overlap(s.bbox, b.bbox) > 0.5 for b in blocks)
            for s in inventory.native_spans
        ),
        "UNKNOWN_FORMAT_READY_COUNT": int(
            state == DocumentState.READY and FormatFamily.UNKNOWN in inventory.profile.format_families
        ),
        "UNKNOWN_FAILURE_READY_COUNT": int(
            state == DocumentState.READY and any(f.failure_class == FailureClass.UNKNOWN_FAILURE for f in failures)
        ),
    }
    trace = [DocumentState.DOWNLOADED, DocumentState.FINGERPRINTED, DocumentState.PARSING, DocumentState.QUALITY_CHECK]
    if before:
        trace.extend((DocumentState.RECOVERY, DocumentState.QUALITY_CHECK))
    trace.append(state)
    return CompatibilityReport(
        inventory.document_id,
        inventory.profile,
        policy.version,
        state,
        tuple(page_reports),
        before,
        tuple(failures),
        blocks,
        chunks,
        discards,
        tuple(c.family for c in DocumentQualityContractRegistry().for_profile(inventory.profile)),
        counters,
        {"COVERAGE_AUDIT_TIME": audit_time, "RECOVERY_TIME": recovery_time},
        tuple(trace),
    )


def inspect_pdf(path: str | Path, *, policy=DEFAULT_POLICY, ocr: OCRAdapter | None = None):
    start = perf_counter()
    inventory = extract_inventory(Path(path), policy)
    ocr_spans, blocks = list(inventory.ocr_spans), list(inventory.canonical_blocks)
    failures = list(inventory.parser_failures)
    ocr_pages = regions = 0
    start = perf_counter()
    if ocr is not None and policy.permit_ocr:
        with fitz.open(path) as pdf:
            for features in inventory.page_features:
                if not features.ocr_required:
                    continue
                page = pdf[features.page - 1]
                boxes = [tuple(i["bbox"]) for i in page.get_image_info()] if features.has_native else [tuple(page.rect)]
                try:
                    for box in boxes:
                        candidates = ocr.parse_region(page, inventory.document_id, box)
                        ocr_spans.extend(candidates)
                        if not candidates or not _is_usable_ocr_block("\n".join(s.text for s in candidates)):
                            failures.append(
                                FailureSignature(
                                    FailureClass.RECOVERY_FAILED,
                                    features.page,
                                    features=(("region", str(box)), ("reason", "OCR empty or unusable")),
                                )
                            )
                            continue
                        for span in candidates:
                            # OCR never overwrites a native region, even if its spelling looks cleaner.
                            native_overlap = [
                                n
                                for n in inventory.native_spans
                                if (n.page == span.page and n.valid and overlap(span.bbox, n.bbox) > 0.5)
                            ]
                            if native_overlap and not any(
                                numbers(n.text) != numbers(span.text) for n in native_overlap if numbers(n.text)
                            ):
                                continue
                            provenance = RecoveryProvenance(
                                FailureClass.OCR_REQUIRED,
                                "ocr-region" if features.has_native else "ocr-page",
                                "1",
                                "IMAGE",
                                "OCR",
                                "targeted OCR of image-only source region",
                                (span.span_id,),
                                0.8,
                            )
                            blocks.append(
                                DocumentBlock(
                                    stable_id(span.span_id, "ocr-block"),
                                    inventory.document_id,
                                    span.page,
                                    "TEXT",
                                    span.text,
                                    span.bbox,
                                    "OCR",
                                    "tesseract",
                                    ocr.parser_version,
                                    policy.version,
                                    confidence=0.8,
                                    source_ids=(span.span_id,),
                                    recovered=True,
                                    recovery_reason=FailureClass.OCR_REQUIRED,
                                    provenance=(provenance,),
                                )
                            )
                    ocr_pages += 1
                    regions += len(boxes) if features.has_native else 0
                except Exception as exc:
                    failures.append(
                        FailureSignature(
                            FailureClass.RECOVERY_FAILED,
                            features.page,
                            features=(("exception_type", type(exc).__name__),),
                        )
                    )
    ocr_time = perf_counter() - start
    inventory = replace(
        inventory, ocr_spans=tuple(ocr_spans), canonical_blocks=tuple(blocks), parser_failures=tuple(failures)
    )
    report = audit_document(inventory, policy=policy)
    report.timings.update(inventory.timings)
    report.timings.update({"SHADOW_PARSE_TIME": 0.0, "OCR_TIME": ocr_time})
    report.counters.update({"OCR_PAGES": ocr_pages, "REGIONS_REPARSED": regions, "PAGES_REPARSED": ocr_pages})
    return inventory, report


def compare_policies(old: CompatibilityReport, new: CompatibilityReport) -> dict:
    if old.document_id != new.document_id:
        raise ValueError("policy comparison requires the same document")
    rank = {DocumentState.READY: 0, DocumentState.QUARANTINED: 1, DocumentState.FAILED: 2}
    regressions = []
    if rank[new.state] > rank[old.state]:
        regressions.append("quality_status")
    for counter in ("CRITICAL_ORPHANS", "UNEXPLAINED_DROPPED_BLOCKS", "RECOVERY_PROVENANCE_LOSS"):
        if new.counters[counter] > old.counters[counter]:
            regressions.append(counter)
    return {
        "old_policy_version": old.parsed_with_policy_version,
        "new_policy_version": new.parsed_with_policy_version,
        "regressions": regressions,
        "promote": not regressions and new.state == DocumentState.READY,
        "measurements": {
            "quality_status": [old.state, new.state],
            "critical_orphans": [old.counters["CRITICAL_ORPHANS"], new.counters["CRITICAL_ORPHANS"]],
            "chunk_count": [len(old.chunks), len(new.chunks)],
            "parser_failures": [len(old.failures), len(new.failures)],
            "recovery_count": [old.counters["RECOVERED_BLOCKS"], new.counters["RECOVERED_BLOCKS"]],
            "timings": [old.timings, new.timings],
        },
    }
