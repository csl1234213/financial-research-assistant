"""Replay frozen model answers with current source retrieval, without a provider.

The replay uses the current-source audit's retrieved chunk ids, strips stale
historical citation ranks, and sends each frozen raw answer through the same
production grounding/finalization policy used by runtime. It is a deterministic
repair diagnostic, not a new semantic grade.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.reasoning_models import Evidence  # noqa: E402
from core.answer_grounding import sanitize_answer  # noqa: E402
from core.answer_policy import finalize_grounded_answer, no_evidence_response  # noqa: E402
from core.fact_ledger import FactLedger, canonical_company  # noqa: E402
from core.financial_grounding import extract_normalized_numbers  # noqa: E402
from core.query_scope import QueryScope, classify_query_scope  # noqa: E402
from core.required_fact_plan import RequiredFactSpec, answer_contains_fact  # noqa: E402
from document_loader import get_company, get_document_period, load_pdf_chunks  # noqa: E402
from evaluation.replay_formal_100_offline import _main_answer  # noqa: E402
from retrieval.periods import extract_metrics, extract_periods  # noqa: E402

DEFAULT_SOURCE = ROOT / "evaluation/results/formal_20260916"
DEFAULT_AUDIT = ROOT / "evaluation/results/current_source_retrieval_audit_20260918_v21/summary.json"
DEFAULT_OUTPUT = ROOT / "evaluation/results/current_retrieval_historical_replay_20260918_v1"
DOCUMENTS = (
    ROOT / "demo/documents/Tesla_sample.pdf",
    ROOT / "demo/documents/Apple_sample.pdf",
    ROOT / "demo/documents/NVIDIA_sample.pdf",
)
_CITATION_RANK = re.compile(r"\s*\[Evidence\s+\d+\]", re.IGNORECASE)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _source_evidence_index() -> dict[str, Evidence]:
    """Reconstruct evidence metadata for chunk ids in the current-source audit."""
    evidence: dict[str, Evidence] = {}
    for path in DOCUMENTS:
        chunks = load_pdf_chunks(path, ocr_enabled=False)
        reporting_period = get_document_period(chunks)
        company = get_company(path.name)
        for index, chunk in enumerate(chunks):
            chunk_id = f"audit_{path.stem}_{index}"
            text = str(chunk.text or "")
            table_context = str(getattr(chunk, "table_context", "") or "")
            metadata = {
                "tenant_id": 7,
                "company": company,
                "source": path.name,
                "page": chunk.page,
                "section": chunk.section,
                "quarter": reporting_period,
                "periods": "|".join(extract_periods(f"{table_context}\n{text}")),
                "metrics": "|".join(extract_metrics(text)),
                "table_context": table_context,
                "content_type": chunk.content_type,
                "source_locator": chunk.source_locator or "",
                "source_format": chunk.source_format,
                "source_authority": "tenant_upload",
                "chunk_id": chunk_id,
            }
            evidence[chunk_id] = Evidence(
                content=text,
                source=path.name,
                company=company,
                confidence=1.0,
                metadata=metadata,
            )
    return evidence


def _projected_source_facts(
    targets: list[dict[str, Any]], answer: str, ledger: FactLedger
) -> set[str]:
    projected: set[str] = set()
    for target in targets:
        company = canonical_company(str(target.get("company") or ""))
        metric_id = str(target.get("metric_id") or "")
        period = str(target.get("period") or "")
        growth_basis = str(target["growth_basis"]) if target.get("growth_basis") else None
        expected_value = Decimal(str(target.get("normalized_value")))
        expected_currency = target.get("currency")
        exact_facts = tuple(
            fact
            for fact in ledger.lookup(
                company=company,
                metric_id=metric_id,
                period=period,
                growth_basis=growth_basis,
            )
            if fact.normalized_value == expected_value
            and (not expected_currency or fact.currency == expected_currency)
        )
        if exact_facts and answer_contains_fact(
            answer,
            RequiredFactSpec(
                company,
                metric_id,
                period,
                "current-source audit target",
                str(target["accounting_basis"]) if target.get("accounting_basis") else None,
                growth_basis,
            ),
            FactLedger(exact_facts),
        ):
            projected.add(str(target.get("key") or ""))
    return projected


def run(source: Path, audit_path: Path, output: Path) -> dict[str, Any]:
    if os.environ.get("ALLOW_REAL_PROVIDER", "false").casefold() not in {"false", "0", "no", "off"}:
        raise RuntimeError("REAL_PROVIDER_MUST_BE_DISABLED")
    source, audit_path, output = source.resolve(), audit_path.resolve(), output.resolve()
    if output.exists():
        raise FileExistsError("REFUSING_TO_OVERWRITE_EXISTING_REPLAY_ARTIFACT")
    for path in (
        source / "evaluation_100_results.jsonl",
        source / "semantic_reviews.jsonl",
        audit_path,
        *DOCUMENTS,
    ):
        if not path.is_file():
            raise FileNotFoundError(path.name)

    historical_rows = _read_jsonl(source / "evaluation_100_results.jsonl")
    review_by_id = {
        str(item.get("id")): item for item in _read_jsonl(source / "semantic_reviews.jsonl")
    }
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit_rows = {str(item.get("id")): item for item in audit.get("rows", [])}
    source_index = _source_evidence_index()

    rows: list[dict[str, Any]] = []
    for historical in historical_rows:
        question_id = str(historical.get("id") or "")
        audit_row = audit_rows.get(question_id)
        if audit_row is None:
            raise ValueError(f"CURRENT_SOURCE_AUDIT_ROW_MISSING:{question_id}")
        chunk_ids = [str(value) for value in audit_row.get("retrieved_chunk_ids", [])]
        evidence = [source_index[chunk_id] for chunk_id in chunk_ids if chunk_id in source_index]
        if len(evidence) != len(chunk_ids):
            raise ValueError(f"CURRENT_SOURCE_CHUNK_MISSING:{question_id}")

        raw_answer = _main_answer(str(historical.get("actual_answer", "")))
        # Historical [Evidence N] ranks refer to an old context, not the
        # current-source audit's retrieved order. Strip them before grounding
        # so no stale rank can silently cite the wrong current chunk.
        citationless_answer = _CITATION_RANK.sub("", raw_answer)
        question = str(audit_row.get("resolved_question") or historical.get("question") or "")
        if not evidence:
            citationless_answer = no_evidence_response(question)
        finalized = finalize_grounded_answer(question, citationless_answer, evidence)
        # ``finalize_grounded_answer`` is the production boundary.  General
        # concept questions intentionally bypass filing grounding and keep
        # explanatory examples (for example ``$100 - $60 = 40%``) as direct
        # chat.  Re-running those answers through the financial citation gate
        # would misclassify the examples as unsupported claims and make this
        # replay disagree with the API contract.
        checked = (
            finalized.grounded
            if classify_query_scope(question) is QueryScope.GENERAL_CONCEPT
            else sanitize_answer(
                question,
                finalized.answer,
                finalized.grounded.evidence,
                require_qualitative_citations=True,
            )
        )
        raw_unsupported = [
            claim for claim in finalized.raw_grounding.claims
            if claim.disposition == "UNSUPPORTED"
        ]
        raw_unsupported_numeric = sum(
            bool(extract_normalized_numbers(claim.text)) for claim in raw_unsupported
        )
        checked_unsupported = [
            claim for claim in checked.claims if claim.disposition == "UNSUPPORTED"
        ]
        targets = list(audit_row.get("source_fact_targets", []))
        projected = _projected_source_facts(targets, finalized.answer, finalized.ledger)
        final_ranks = sorted({
            int(value)
            for value in re.findall(r"\[Evidence\s+(\d+)\]", finalized.answer, re.IGNORECASE)
            if 1 <= int(value) <= len(finalized.grounded.evidence)
        })
        final_citations = [
            {
                "rank": rank,
                "chunk_id": str(finalized.grounded.evidence[rank - 1].metadata.get("chunk_id", "")),
                "source": finalized.grounded.evidence[rank - 1].source,
                "page": finalized.grounded.evidence[rank - 1].metadata.get("page"),
            }
            for rank in final_ranks
        ]
        review = review_by_id.get(question_id, {})
        rows.append({
            "id": question_id,
            "question": historical.get("question"),
            "historical_grade": review.get("answer_grade", historical.get("answer_grade")),
            "historical_failure_modes": review.get("failure_modes", []),
            "raw_answer": raw_answer,
            "answer_after_current_retrieval_grounding": finalized.answer,
            "verified_facts_only_projection": finalized.verified_facts_only_projection,
            "final_claim_dispositions": dict(Counter(claim.disposition for claim in checked.claims)),
            "raw_unsupported_claims": len(raw_unsupported),
            "raw_unsupported_numeric_claims": raw_unsupported_numeric,
            "raw_unsupported_qualitative_claims": len(raw_unsupported) - raw_unsupported_numeric,
            "raw_unsupported_claim_texts": [claim.text for claim in raw_unsupported],
            "final_unsupported_numeric_claims": sum(
                bool(extract_normalized_numbers(claim.text)) for claim in checked_unsupported
            ),
            "final_unsupported_qualitative_claims": len(checked_unsupported) - sum(
                bool(extract_normalized_numbers(claim.text)) for claim in checked_unsupported
            ),
            "source_fact_targets": len(targets),
            "source_facts_projected": len(projected),
            "missing_source_fact_keys": sorted(
                str(target.get("key") or "") for target in targets
                if str(target.get("key") or "") not in projected
            ),
            "removed_lines": list(finalized.removed_lines),
            "added_fact_ids": list(finalized.added_fact_ids),
            "final_citations": final_citations,
        })

    pairs: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        language, _, suffix = str(row["id"]).partition("-")
        pairs.setdefault(suffix, {})[language] = row
    parity = []
    for suffix, pair in sorted(pairs.items()):
        if set(pair) != {"EN", "ZH"}:
            continue
        en = {str(value) for value in pair["EN"]["missing_source_fact_keys"]}
        zh = {str(value) for value in pair["ZH"]["missing_source_fact_keys"]}
        parity.append({
            "pair": suffix,
            "english_only_missing_facts": sorted(en - zh),
            "chinese_only_missing_facts": sorted(zh - en),
        })

    historical_grades = Counter(str(row.get("historical_grade") or "UNKNOWN") for row in rows)
    total_targets = sum(int(row["source_fact_targets"]) for row in rows)
    projected_targets = sum(int(row["source_facts_projected"]) for row in rows)
    summary = {
        "scope": "CURRENT_RETRIEVAL_HISTORICAL_RAW_ANSWER_GROUNDING_REPLAY_NOT_SEMANTIC_REGRADE",
        "real_provider_calls": 0,
        "evaluator_calls": 0,
        "api_cost_usd": 0,
        "questions": len(rows),
        "historical_grade_counts_unchanged": dict(historical_grades),
        "source_fact_targets": total_targets,
        "source_facts_projected": projected_targets,
        "source_fact_projection_coverage": projected_targets / total_targets if total_targets else None,
        "final_unsupported_numeric_claims": sum(int(row["final_unsupported_numeric_claims"]) for row in rows),
        "final_unsupported_qualitative_claims": sum(
            int(row["final_unsupported_qualitative_claims"]) for row in rows
        ),
        "raw_unsupported_numeric_claims": sum(int(row["raw_unsupported_numeric_claims"]) for row in rows),
        "raw_unsupported_qualitative_claims": sum(
            int(row["raw_unsupported_qualitative_claims"]) for row in rows
        ),
        "verified_facts_only_projected_answers": sum(
            bool(row["verified_facts_only_projection"]) for row in rows
        ),
        "english_chinese_pairs": len(parity),
        "pairs_with_source_fact_projection_difference": sum(
            bool(pair["english_only_missing_facts"] or pair["chinese_only_missing_facts"])
            for pair in parity
        ),
        "parity_semantics": "exact source-fact projection only; not semantic answer equivalence",
        "rows": rows,
        "bilingual_fact_projection": parity,
    }
    output.mkdir(parents=True)
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    compact_rows = []
    for row in rows:
        saved = dict(row)
        saved.pop("raw_answer", None)
        saved.pop("answer_after_current_retrieval_grounding", None)
        compact_rows.append(saved)
    (output / "questions.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in compact_rows),
        encoding="utf-8",
    )
    printable = {key: value for key, value in summary.items() if key not in {"rows", "bilingual_fact_projection"}}
    print(json.dumps(printable, ensure_ascii=False, indent=2))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    run(args.source, args.audit, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
