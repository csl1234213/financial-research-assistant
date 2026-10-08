"""Provider-free P1.4 audit over the P1.3 reconstructed Moutai fixture."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from core.financial_metric_registry import (
    MetricMappingStatus,
    normalize_financial_table_row,
)
from core.financial_table_rows import VerificationStatus
from document_loader import parse_pdf


def build_audit(fixture: Path | None = None) -> dict[str, object]:
    source = fixture or (Path(__file__).parents[1] / "tests" / "fixtures" / "moutai-standard-statements-2025.pdf")
    document = parse_pdf(source, ocr_enabled=False, document_id="moutai-fixture-2025")
    verified = [row for row in document.financial_table_rows if row.verification_status == VerificationStatus.VERIFIED]
    normalized = [normalize_financial_table_row(row) for row in verified]

    def counters(items):
        return {status.value: sum(item.mapping_status == status for item in items) for status in MetricMappingStatus}

    by_statement: dict[str, list] = defaultdict(list)
    for item in normalized:
        by_statement[item.statement_type or "UNKNOWN"].append(item)

    seen: set[tuple[str, str | None, str, str | None, str | None]] = set()
    samples = []
    for item in normalized:
        key = (
            item.original_label,
            item.canonical_metric,
            item.mapping_status.value,
            item.statement_type,
            item.scope,
        )
        if key in seen:
            continue
        seen.add(key)
        samples.append(
            {
                "original_label": item.original_label,
                "normalized_label": item.normalized_label,
                "canonical_metric": item.canonical_metric,
                "mapping_status": item.mapping_status.value,
                "statement_type": item.statement_type,
                "scope": item.scope,
                "mapping_rule": item.mapping_rule,
                "page": item.row.page,
            }
        )

    labels_by_metric: dict[str, set[str]] = defaultdict(set)
    for item in normalized:
        if item.canonical_metric:
            labels_by_metric[item.canonical_metric].add(item.normalized_label)

    return {
        "fixture": str(source),
        "total_verified_rows": len(verified),
        "mapped_rows": sum(item.canonical_metric is not None for item in normalized),
        "mapping_coverage_percent": round(
            100 * sum(item.canonical_metric is not None for item in normalized) / len(verified), 2
        )
        if verified
        else 0.0,
        "mapping_counts": counters(normalized),
        "by_statement": {
            statement: {
                "total_verified_rows": len(items),
                "mapping_counts": counters(items),
                "mapped_rows": sum(item.canonical_metric is not None for item in items),
                "mapping_coverage_percent": round(
                    100 * sum(item.canonical_metric is not None for item in items) / len(items), 2
                )
                if items
                else 0.0,
            }
            for statement, items in sorted(by_statement.items())
        },
        "semantic_collision_candidates": {
            metric: sorted(labels) for metric, labels in sorted(labels_by_metric.items()) if len(labels) > 1
        },
        "unique_mapping_samples": samples,
    }


if __name__ == "__main__":
    print(json.dumps(build_audit(), ensure_ascii=False, indent=2))
