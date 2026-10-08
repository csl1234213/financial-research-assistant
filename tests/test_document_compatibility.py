from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import fitz
import pytest

from core.financial_facts import FinancialDocumentContext, financial_facts_from_rows
from document_compatibility.adapters import (
    OCRAdapter,
    classify,
    extract_inventory,
    normalized,
)
from document_compatibility.engine import audit_document, build_chunks, compare_policies, inspect_pdf
from document_compatibility.models import (
    DiscardRecord,
    DocumentBlock,
    DocumentState,
    ExtractionInventory,
    FailureClass,
    FailureSignature,
    FormatFamily,
    PageFeatures,
    SourceSpan,
    stable_id,
)
from document_compatibility.policy import DEFAULT_POLICY, POLICIES, ParserCapabilityRegistry, ParserPolicyEngine
from document_loader import chunk_document

FIXTURES = Path(__file__).parent / "fixtures"
MANIFEST = json.loads((FIXTURES / "compatibility" / "manifest.json").read_text(encoding="utf-8"))["fixtures"]


def sample(document="alpha"):
    span = SourceSpan(stable_id(document, "asset"), 1, "Total assets 1,234.56", (10, 20, 200, 40))
    features = (PageFeatures(1, has_native=True, width=300, height=400),)
    profile = classify(document, features, span.text, ())
    block = DocumentBlock(
        stable_id(document, "block"),
        document,
        1,
        "TEXT",
        span.text,
        span.bbox,
        "NATIVE_PDF",
        "pymupdf-native",
        "fixture",
        DEFAULT_POLICY.version,
        source_ids=(span.span_id,),
    )
    return ExtractionInventory(document, profile, features, (span,), (), (block,))


def cross_page(document):
    inventory = sample(document)
    first_span = replace(inventory.native_spans[0], text="Metric | 2025 | 2024")
    second_span = SourceSpan(stable_id(document, "next"), 2, "Total assets | 100 | 90", (10, 20, 200, 40))
    first = replace(
        inventory.canonical_blocks[0],
        block_type="TABLE",
        text=first_span.text,
        table_header=first_span.text,
        table_columns=(30, 100, 170),
        section="Balance sheet",
    )
    second = replace(
        first,
        block_id=stable_id(document, "next-block"),
        page=2,
        text=second_span.text,
        source_ids=(second_span.span_id,),
        table_header="",
        continuation=True,
    )
    features = (inventory.page_features[0], replace(inventory.page_features[0], page=2))
    return replace(
        inventory,
        page_features=features,
        native_spans=(first_span, second_span),
        canonical_blocks=(first, second),
        profile=classify(document, features, first.text + second.text, ()),
    )


def scanned_pdf(path, *, mixed=False):
    with fitz.open() as source:
        page = source.new_page(width=500, height=300)
        page.insert_text((30, 60), "Annual financial statement", fontsize=20)
        page.insert_text((30, 100), "Total assets 12345.67", fontsize=20)
        page.insert_text((30, 140), "Revenue 45678.90", fontsize=20)
        image = page.get_pixmap(dpi=180).tobytes("png")
        with fitz.open() as target:
            if mixed:
                p = target.new_page(width=500, height=300)
                p.insert_text((30, 60), "Native report text and balance sheet overview.", fontsize=14)
            p = target.new_page(width=500, height=300)
            p.insert_image(p.rect, stream=image)
            target.save(path)


def run_case(case, tmp_path, policy=DEFAULT_POLICY):
    name = case["fixture_id"]
    if name.startswith("real-"):
        from tests.test_document_compatibility_structure import run_structural_case

        return run_structural_case(name, tmp_path, policy)
    if name == "cas-native-statements-001":
        return inspect_pdf(FIXTURES / "moutai-standard-statements-2025.pdf", policy=policy)[1]
    if name in {"scanned-page", "mixed-page"}:
        path = tmp_path / f"{name}.pdf"
        scanned_pdf(path, mixed=name == "mixed-page")
        return inspect_pdf(path, policy=policy)[1]
    inventory = sample(name)
    if name.startswith("orphan-text"):
        inventory = replace(
            inventory,
            native_spans=(replace(inventory.native_spans[0], text="Research overview and operational narrative."),),
            canonical_blocks=(),
        )
    elif name.startswith("critical-row-loss"):
        inventory = replace(inventory, canonical_blocks=())
    elif name.startswith("cross-page-table"):
        inventory = cross_page(name)
    elif name == "multicolumn-ambiguous":
        features = (replace(inventory.page_features[0], column_count=2, reading_order_confidence=0.2),)
        inventory = replace(inventory, page_features=features, profile=classify(name, features, "Report", ()))
    elif name == "merged-cell-ambiguous":
        features = (replace(inventory.page_features[0], table_structure_confidence=0.2),)
        inventory = replace(inventory, page_features=features, profile=classify(name, features, "Report", ()))
    elif name == "serialization-loss":
        return audit_document(inventory, serialized={}, policy=policy)
    elif name == "chunk-loss":
        return audit_document(inventory, chunks=(), policy=policy)
    elif name == "native-ocr-number-conflict":
        ocr = replace(inventory.native_spans[0], span_id="ocr", text="Total assets 1,23456", source="OCR")
        block = replace(
            inventory.canonical_blocks[0], block_id="ocr-block", text=ocr.text, source="OCR", source_ids=(ocr.span_id,)
        )
        inventory = replace(inventory, ocr_spans=(ocr,), canonical_blocks=(*inventory.canonical_blocks, block))
    elif name == "unknown-format":
        inventory = replace(inventory, profile=replace(inventory.profile, format_families=(FormatFamily.UNKNOWN,)))
    elif name == "unknown-failure":
        inventory = replace(inventory, parser_failures=(FailureSignature("UNREGISTERED_PATTERN", 1),))
    return audit_document(inventory, policy=policy)


@pytest.mark.parametrize("case", MANIFEST, ids=lambda case: case["fixture_id"])
def test_entire_compatibility_corpus(case, tmp_path):
    report = run_case(case, tmp_path)
    assert report.state == case["expected_quality_status"], report.failures
    detected = {f.failure_class for f in (*report.failures_before, *report.failures)}
    assert set(case["failure_classes_tested"]) <= detected
    assert not report.counters["NATIVE_NUMERIC_OVERWRITE_COUNT"]
    assert not report.counters["UNKNOWN_FORMAT_READY_COUNT"]
    assert not report.counters["UNKNOWN_FAILURE_READY_COUNT"]
    if report.state == DocumentState.READY:
        assert not report.failures
        text = "\n".join(block.text + block.table_header for block in report.blocks)
        assert all(expected in text for expected in case["critical_expected_content"])


def test_cross_document_failure_uses_identical_detector_and_recovery():
    reports = [audit_document(cross_page(document)) for document in ("issuer-a", "issuer-b")]
    assert all(r.state == DocumentState.READY for r in reports)
    assert all(r.failures_before[0].failure_class == FailureClass.CROSS_PAGE_TABLE_HEADER_LOSS for r in reports)
    assert {r.blocks[1].provenance[0].recovery_policy for r in reports} == {"cross_page_table_header_loss"}
    assert all(r.blocks[1].provenance[0].source_ids for r in reports)


def test_incompatible_continuation_cannot_inherit_header():
    inventory = cross_page("mismatch")
    blocks = (inventory.canonical_blocks[0], replace(inventory.canonical_blocks[1], table_columns=(20, 200)))
    report = audit_document(replace(inventory, canonical_blocks=blocks))
    assert report.state == DocumentState.QUARANTINED
    assert report.blocks[1].table_header == ""


def test_recovered_native_block_has_no_duplicates_and_policy_comparison():
    inventory = replace(sample(), canonical_blocks=())
    old = audit_document(inventory, policy=POLICIES["financial-pdf-v1-observe"])
    new = audit_document(inventory)
    assert old.state == DocumentState.QUARANTINED
    assert new.state == DocumentState.READY
    assert len(new.blocks) == 1
    assert new.blocks[0].provenance[0].source_ids == (inventory.native_spans[0].span_id,)
    assert compare_policies(old, new)["promote"]
    again = audit_document(replace(inventory, canonical_blocks=new.blocks))
    assert len(again.blocks) == 1


def test_false_discard_reason_and_forged_consumption_cannot_hide_loss():
    inventory = sample()
    block = inventory.canonical_blocks[0]
    report = audit_document(inventory, chunks=(), discards=(DiscardRecord(block.block_id, "HEADER_FOOTER"),))
    assert report.state == DocumentState.QUARANTINED
    assert report.counters["UNEXPLAINED_DROPPED_BLOCKS"] == 1
    chunks, _ = build_chunks(inventory.canonical_blocks)
    forged = replace(chunks[0], text="Entirely unrelated narrative")
    assert audit_document(inventory, chunks=(forged,)).state == DocumentState.QUARANTINED


def test_numeric_corruption_with_same_source_id_is_not_accepted():
    inventory = sample()
    block = replace(inventory.canonical_blocks[0], text="Total assets 123.456")
    report = audit_document(replace(inventory, canonical_blocks=(block,)))
    # The original source is recovered, but corrupted native output must not be promoted.
    assert any(f.failure_class == FailureClass.CRITICAL_FINANCIAL_CONTENT_LOSS for f in report.failures_before)
    assert report.state == DocumentState.QUARANTINED


def test_policy_mutation_without_version_bump_is_rejected():
    with pytest.raises(ValueError, match="policy"):
        audit_document(sample(), policy=replace(DEFAULT_POLICY, minimum_reading_confidence=0.1))


def test_page_policy_and_unsupported_layout_region():
    inventory = sample()
    page = replace(inventory.page_features[0], ocr_required=True, has_native=False)
    registry = ParserCapabilityRegistry(ocr_available=True)
    plan = ParserPolicyEngine().plan(inventory.profile, page, registry)
    assert plan.recovery == "OCR_PAGE"
    assert (
        ParserPolicyEngine().plan(inventory.profile, replace(page, has_native=True), registry).recovery == "OCR_REGION"
    )


def test_real_rows_and_facts_are_unchanged_by_offline_layer():
    inventory, report = inspect_pdf(FIXTURES / "moutai-standard-statements-2025.pdf")
    document = inventory.parsed_document
    assert document is not None
    assert len(document.pages) == 71
    assert sum(p.blank for p in inventory.page_features) == 55
    assert sum(r.verification_status.value == "VERIFIED" for r in document.financial_table_rows) == 595
    assert set(r for c in chunk_document(document) for r in c.financial_table_rows) == set(
        document.financial_table_rows
    )
    context = FinancialDocumentContext(
        fiscal_year_start="2025-01-01",
        fiscal_year_end="2025-12-31",
        fiscal_calendar_source="regression fixture explicit calendar",
    )
    assert len(financial_facts_from_rows(document.financial_table_rows, context=context)) == 98
    assert report.state == DocumentState.READY
    assert report.counters["ORPHAN_SPANS"] == 0


def test_raw_bbox_and_adapter_ids_are_deterministic(tmp_path):
    path = tmp_path / "native.pdf"
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((30, 50), "Total assets 12345.67")
        doc.save(path)
    first = extract_inventory(path, DEFAULT_POLICY)
    second = extract_inventory(path, DEFAULT_POLICY)
    assert first.native_spans == second.native_spans
    assert first.canonical_blocks == second.canonical_blocks


def test_real_ocr_scanned_and_mixed_when_engine_available(tmp_path):
    try:
        tessdata = fitz.get_tessdata()
    except (RuntimeError, ImportError):
        pytest.skip("host has no OCR engine data; isolated Docker OCR runner covers this gate")
    if not (Path(tessdata) / "eng.traineddata").exists():
        pytest.skip("eng traineddata unavailable")
    for mixed in (False, True):
        path = tmp_path / f"scan-{mixed}.pdf"
        scanned_pdf(path, mixed=mixed)
        inventory, report = inspect_pdf(path, ocr=OCRAdapter(tessdata=tessdata))
        assert report.state == DocumentState.READY, report.failures
        assert report.counters["OCR_PAGES"] == 1
        assert "12345.67" in normalized(" ".join(b.text for b in report.blocks))
        assert not inventory.parsed_document or inventory.native_spans


def test_same_missing_content_recovered_from_two_real_native_documents(tmp_path):
    recovered_policies = set()
    for issuer in ("Alpha", "Beta"):
        path = tmp_path / f"{issuer}.pdf"
        with fitz.open() as doc:
            p = doc.new_page()
            p.insert_text((30, 50), f"{issuer} annual overview")
            p.insert_text((30, 130), "Total assets 12345.67")
            doc.save(path)
        inventory = extract_inventory(path, DEFAULT_POLICY)
        broken = replace(
            inventory, canonical_blocks=tuple(b for b in inventory.canonical_blocks if "12345.67" not in b.text)
        )
        report = audit_document(broken)
        assert report.state == DocumentState.READY
        assert any(f.failure_class == FailureClass.CRITICAL_FINANCIAL_CONTENT_LOSS for f in report.failures_before)
        recovered_policies.update(p.recovery_policy for b in report.blocks for p in b.provenance)
        assert sum("12345.67" in b.text for b in report.blocks) == 1
    assert recovered_policies == {"critical_financial_content_loss"}


def test_real_cross_page_table_adapter_routes_header_recovery(tmp_path):
    policies = set()
    for label in ("Alpha", "Beta"):
        path = tmp_path / f"table-{label}.pdf"
        with fitz.open() as doc:
            for number in range(2):
                page = doc.new_page(width=500, height=400)
                page.insert_text(
                    (30, 40), f"Financial Schedule {label}" + (" (continued)" if number else ""), fontsize=16
                )
                rows = [["Metric", "2025", "2024"], ["Assets", "100", "90"], ["Liabilities", "40", "30"]]
                if number:
                    rows = [["Equipment", "60", "50"], ["Inventory", "20", "15"], ["Cash", "20", "25"]]
                xs, ys = (30, 180, 300, 420), (80, 110, 140, 170)
                for x in xs:
                    page.draw_line((x, ys[0]), (x, ys[-1]))
                for y in ys:
                    page.draw_line((xs[0], y), (xs[-1], y))
                for row_index, row in enumerate(rows):
                    for col_index, value in enumerate(row):
                        page.insert_text((xs[col_index] + 5, ys[row_index] + 20), value, fontsize=11)
            doc.save(path)
        _, report = inspect_pdf(path)
        assert report.state == DocumentState.READY, report.failures
        assert any(f.failure_class == FailureClass.CROSS_PAGE_TABLE_HEADER_LOSS for f in report.failures_before)
        policies.update(p.recovery_policy for b in report.blocks for p in b.provenance)
        assert any("2025" in c.text and "Equipment" in c.text for c in report.chunks)
    assert "cross_page_table_header_loss" in policies


def test_complete_corpus_required_for_canary_promotion(tmp_path):
    from document_compatibility.promotion import CorpusFixture, FinancialDocumentCompatibilityCorpus, promotion_decision

    corpus = FinancialDocumentCompatibilityCorpus(
        tuple(
            CorpusFixture(
                f["fixture_id"],
                tuple(f["format_families"]),
                tuple(f["capabilities_tested"]),
                tuple(f["failure_classes_tested"]),
                f["expected_quality_status"],
                tuple(f["critical_expected_content"]),
            )
            for f in MANIFEST
        )
    )
    reports = {f["fixture_id"]: run_case(f, tmp_path) for f in MANIFEST}
    document = reports["cas-native-statements-001"]
    assert corpus.evaluate(reports) == ()
    kwargs = dict(
        verified_rows_before=595, verified_rows_after=595, facts_before=98, facts_after=98, route_regressions=0
    )
    assert promotion_decision(document, corpus, reports, reports, **kwargs).promote
    incomplete = dict(reports)
    incomplete.pop("chunk-loss")
    assert not promotion_decision(document, corpus, reports, incomplete, **kwargs).promote
    assert not promotion_decision(document, corpus, reports, reports, **{**kwargs, "facts_after": 97}).promote
    assert not promotion_decision(document, corpus, reports, reports, **{**kwargs, "route_regressions": None}).promote


def test_entire_corpus_policy_comparison(tmp_path):
    for case in MANIFEST:
        old = run_case(case, tmp_path, POLICIES["financial-pdf-v1-observe"])
        new = run_case(case, tmp_path)
        # Rasterized fixture PDFs have volatile PDF creation IDs; comparisons use
        # the logical fixture identity, never two unrelated production documents.
        if case["fixture_id"] in {"scanned-page", "mixed-page"} or case["fixture_id"].startswith("real-"):
            old = replace(old, document_id=new.document_id)
        result = compare_policies(old, new)
        if case.get("expected_previous_quality_status"):
            # New detectors intentionally reject known-unsafe historical READY.
            # The deployment gate must still demand review of that policy change.
            assert old.state == case["expected_previous_quality_status"]
            assert result["regressions"] == ["quality_status"]
            assert not result["promote"]
        else:
            assert not result["regressions"], (case["fixture_id"], result)
        assert result["old_policy_version"] != result["new_policy_version"]


def test_unknown_source_reference_cannot_pass():
    inventory = sample()
    block = replace(inventory.canonical_blocks[0], source_ids=("invented-source",))
    report = audit_document(replace(inventory, canonical_blocks=(block,)))
    assert report.state == DocumentState.QUARANTINED
    assert FailureClass.PROVENANCE_LOSS in {f.failure_class for f in report.failures}


def test_signature_store_is_explicit_and_versioned():
    from document_compatibility.policy import FailureSignatureRegistry

    records = FailureSignatureRegistry().records()
    assert len(records) == 3
    assert all(r["required_features"] and r["parser"] and r["recovery_version"] for r in records)
    assert all(len(r["regression_fixtures"]) == 2 for r in records)
    assert all(set(r["regression_fixtures"]) <= {c["fixture_id"] for c in MANIFEST} for r in records)


def test_chunk_cannot_append_untraceable_claims():
    inventory = sample()
    chunks, _ = build_chunks(inventory.canonical_blocks)
    corrupt = replace(chunks[0], text=chunks[0].text + " Invented revenue 999999")
    report = audit_document(inventory, chunks=(corrupt,))
    assert report.state == DocumentState.QUARANTINED
    assert FailureClass.PROVENANCE_LOSS in {f.failure_class for f in report.failures}
