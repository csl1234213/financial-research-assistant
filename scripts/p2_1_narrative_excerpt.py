"""Build an auditable offline narrative excerpt without admitting quarantined tables."""

import argparse
import hashlib
import json
from pathlib import Path

import fitz

from document_compatibility.engine import inspect_pdf

EXPECTED_SHA = "474905deeaf0f875fc0a1b097a626c0c7852c427faadc5d7fc7816cbf45ea288"
PAGES = (8, 9, 21, 22, 23)


def build_excerpt(source: Path, target: Path):
    if hashlib.sha256(source.read_bytes()).hexdigest() != EXPECTED_SHA:
        raise ValueError("source annual report version changed; review before extraction")
    if source.resolve() == target.resolve():
        raise ValueError("excerpt must not overwrite original document")
    target.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open(source) as original, fitz.open() as excerpt:
        for page in range(1, max(PAGES) + 1):
            if page in PAGES:
                excerpt.insert_pdf(original, from_page=page - 1, to_page=page - 1)
            else:
                excerpt.new_page()
        excerpt.save(target)
    _, report = inspect_pdf(target)
    metadata = {
        "source_sha256": EXPECTED_SHA,
        "excerpt_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "source_pages": PAGES,
        "page_mapping": "identity; excluded pages are explicit blank placeholders",
        "scope": "NARRATIVE_EXCERPT_ONLY",
        "whole_report_quality": "QUARANTINED",
        "excerpt_quality": str(report.state),
        "blocks": len(report.blocks),
        "failures": [(str(f.failure_class), f.page) for f in report.failures],
    }
    target.with_suffix(".manifest.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    print(json.dumps(build_excerpt(args.source, args.target), indent=2))
