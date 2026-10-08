"""Offline audit CLI. Never connects to a provider, database or index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import fitz

from document_compatibility.adapters import OCRAdapter
from document_compatibility.engine import inspect_pdf
from document_compatibility.policy import DEFAULT_POLICY, POLICIES


def ocr_probe(directory: Path) -> dict:
    """Rasterized neutral fixtures exercise the installed real Tesseract engine."""
    directory.mkdir(parents=True, exist_ok=True)
    results = {}
    for mixed in (False, True):
        path = directory / f"compatibility-{'mixed' if mixed else 'scanned'}.pdf"
        with fitz.open() as native:
            page = native.new_page(width=500, height=300)
            for y, text in (
                (60, "Annual financial statement"),
                (100, "Total assets 12345.67"),
                (140, "Revenue 45678.90"),
            ):
                page.insert_text((30, y), text, fontsize=20)
            image = page.get_pixmap(dpi=180).tobytes("png")
            with fitz.open() as scanned:
                if mixed:
                    p = scanned.new_page(width=500, height=300)
                    p.insert_text((30, 60), "Native financial report narrative.", fontsize=14)
                p = scanned.new_page(width=500, height=300)
                p.insert_image(p.rect, stream=image)
                scanned.save(path)
        _, report = inspect_pdf(path, ocr=OCRAdapter())
        text = " ".join(b.text for b in report.blocks)
        results[path.stem] = {
            "state": report.state,
            "amount_preserved": "12345.67" in text,
            "ocr_pages": report.counters["OCR_PAGES"],
            "native_numeric_overwrites": report.counters["NATIVE_NUMERIC_OVERWRITE_COUNT"],
            "failures": [str(f.failure_class) for f in report.failures],
        }
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path, nargs="?")
    parser.add_argument("--policy", choices=tuple(POLICIES), default=DEFAULT_POLICY.version)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--ocr", action="store_true")
    parser.add_argument("--ocr-probe-directory", type=Path)
    args = parser.parse_args()
    if args.ocr_probe_directory:
        result = ocr_probe(args.ocr_probe_directory)
    elif args.path:
        inventory, report = inspect_pdf(args.path, policy=POLICIES[args.policy], ocr=OCRAdapter() if args.ocr else None)
        result = report.to_dict()
        result["trace_type"] = "DOCUMENT_COMPATIBILITY_TRACE"
        result["raw_inventory"] = {
            "native_spans": [vars(s) for s in inventory.native_spans],
            "ocr_spans": [vars(s) for s in inventory.ocr_spans],
            "table_candidates": inventory.table_candidates,
            "table_cells": inventory.table_cells,
        }
        document = inventory.parsed_document
        result["verified_rows"] = (
            sum(row.verification_status.value == "VERIFIED" for row in document.financial_table_rows) if document else 0
        )
    else:
        parser.error("a PDF path or --ocr-probe-directory is required")
    payload = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
        print(str(args.output.resolve()))
    else:
        print(payload)


if __name__ == "__main__":
    main()
