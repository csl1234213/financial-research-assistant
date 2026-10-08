"""Provider-free local-model replay for historically failed benchmark rows.

This is a diagnostic, not a replacement for the frozen semantic review. It
regenerates answers with the current retrieval/context/grounding path using
only a local Ollama model and stores raw/final answers for human inspection.
It refuses to run when the paid-provider gate is enabled.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.answer_policy import finalize_grounded_answer  # noqa: E402
from core.citation_gate import filter_evidence_for_query  # noqa: E402
from core.fact_ledger import build_evidence_first_context  # noqa: E402
from core.query_scope import QueryScope, classify_query_scope  # noqa: E402
from core.required_fact_plan import infer_required_fact_plan  # noqa: E402
from evaluation.local_ollama_quality_probe import (  # noqa: E402
    _canonical_question,
    _evidence_for_row,
    _local_chat,
    _read_audit,
    _source_evidence_index,
)
from prompt_builder import (  # noqa: E402
    build_compare_prompt,
    build_direct_chat_prompt,
    build_prompt,
    get_prompt_system_prompt,
)

DEFAULT_AUDIT = ROOT / "evaluation/results/current_source_retrieval_audit_20260924_v37/summary.json"
DEFAULT_OUTPUT = ROOT / "evaluation/results/local_ollama_historical_regrade_20260924_v1"
DEFAULT_SOURCE = ROOT / "evaluation/results/formal_20260916/semantic_reviews.jsonl"
DEFAULT_IDS = (
    "EN-006,EN-007,EN-010,EN-011,EN-014,EN-021,EN-022,EN-032,EN-035,EN-036,"
    "EN-037,EN-040,EN-045,EN-046,EN-048,ZH-002,ZH-006,ZH-009,ZH-010,ZH-014,"
    "ZH-021,ZH-022,ZH-023,ZH-025,ZH-027,ZH-028,ZH-030,ZH-034,ZH-036,ZH-037,"
    "ZH-040,ZH-046,ZH-048,ZH-050"
)


def _review_index(path: Path) -> dict[str, dict[str, Any]]:
    return {
        str(item["id"]): item
        for item in (
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }


def _is_chinese(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text or ""))


def _build_prompt(question: str, evidence: list[Any], *, context_tokens: int) -> tuple[str, str]:
    if not evidence:
        return build_direct_chat_prompt(question), get_prompt_system_prompt("direct_chat")
    plan = infer_required_fact_plan(question, evidence)
    context, _ = build_evidence_first_context(
        question,
        evidence,
        plan,
        max_context_tokens=context_tokens,
    )
    scope = classify_query_scope(question)
    if scope is QueryScope.COMPARE:
        return build_compare_prompt(question, context), get_prompt_system_prompt("financial_compare")
    return build_prompt(question, context), get_prompt_system_prompt("financial_rag")


def run(
    *,
    audit: Path,
    reviews: Path,
    output: Path,
    ids: tuple[str, ...],
    model: str,
    max_tokens: int,
    context_tokens: int,
    timeout: int,
) -> dict[str, Any]:
    if os.environ.get("ALLOW_REAL_PROVIDER", "false").casefold() not in {
        "false", "0", "no", "off", "",
    }:
        raise RuntimeError("REAL_PROVIDER_MUST_BE_DISABLED")
    if output.exists():
        raise FileExistsError(f"REFUSING_TO_OVERWRITE:{output}")
    rows = _read_audit(audit)
    review_rows = _review_index(reviews)
    missing = [item for item in ids if item not in rows]
    if missing:
        raise ValueError(f"AUDIT_ROWS_MISSING:{','.join(missing)}")
    source_index = _source_evidence_index()
    client = httpx.Client(timeout=httpx.Timeout(timeout, connect=10))
    output.mkdir(parents=True)
    results: list[dict[str, Any]] = []
    try:
        for case_id in ids:
            row = rows[case_id]
            question = _canonical_question(case_id, row)
            retrieved = _evidence_for_row(row, source_index)
            evidence = filter_evidence_for_query(question, retrieved)
            # GENERAL_CONCEPT turns are direct chat by contract.  Historical
            # retrieval artifacts may still contain filing chunks from an
            # earlier run; do not let those stale chunks route a definition
            # question into financial RAG during local replay.
            if classify_query_scope(question) is QueryScope.GENERAL_CONCEPT:
                evidence = []
            prompt, system_prompt = _build_prompt(
                question,
                evidence,
                context_tokens=context_tokens,
            )
            raw = ""
            meta: dict[str, Any] = {}
            error: str | None = None
            final = None
            try:
                if not evidence:
                    # Mirror the production path: no Provider call is made
                    # when the citation gate has no eligible evidence, but
                    # the user still receives the deterministic, localized
                    # insufficiency response from the final answer policy.
                    raw = ""
                    meta = {"provider": "not_called_no_evidence"}
                    final = finalize_grounded_answer(question, "", evidence)
                    final_text = final.answer
                else:
                    raw, meta = _local_chat(
                        client,
                        model=model,
                        system_prompt=system_prompt,
                        prompt=prompt,
                        max_tokens=max_tokens,
                    )
                    if not raw:
                        raise RuntimeError("EMPTY_LOCAL_MODEL_OUTPUT")
                    if meta.get("done_reason") == "length":
                        raise RuntimeError("LOCAL_MODEL_OUTPUT_TRUNCATED")
                    final = finalize_grounded_answer(question, raw, evidence)
                    final_text = final.answer
            except Exception as exc:  # record local failures without hiding them
                error = str(exc) if str(exc) in {
                    "EMPTY_LOCAL_MODEL_OUTPUT",
                    "LOCAL_MODEL_OUTPUT_TRUNCATED",
                } else type(exc).__name__
                final_text = ""
            result = {
                "id": case_id,
                "question": row.get("question"),
                "resolved_question": question,
                "historical_grade": review_rows.get(case_id, {}).get("answer_grade"),
                "historical_reason": review_rows.get(case_id, {}).get("reason"),
                "retrieved_sources": sorted({item.source for item in evidence}),
                "retrieved_evidence_count": len(evidence),
                "raw_answer": raw,
                "final_answer": final_text,
                "error": error,
                "language_question": "zh" if _is_chinese(question) else "en",
                "provider_usage": meta,
                "final_unsupported_numeric_claims": sum(
                    1
                    for claim in (final.grounded.claims if final else ())
                    if claim.disposition == "UNSUPPORTED" and getattr(claim, "is_numeric", False)
                ),
                "final_unsupported_claims": sum(
                    1
                    for claim in (final.grounded.claims if final else ())
                    if claim.disposition == "UNSUPPORTED"
                ),
                "removed_lines": list(final.removed_lines) if final else [],
                "required_fact_plan": (
                    final.plan.as_dict(final.ledger, final.answer) if final else None
                ),
                "final_evidence_count": len(final.grounded.evidence) if final else 0,
                "verified_facts_only_projection": bool(
                    final.verified_facts_only_projection if final else False
                ),
            }
            (output / f"{case_id}.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            results.append(result)
            print(
                f"LOCAL_REPLAY {case_id}: evidence={len(evidence)} "
                f"final_unsupported_numeric={result['final_unsupported_numeric_claims']} "
                f"error={error or 'none'}",
                flush=True,
            )
    finally:
        client.close()
    summary = {
        "scope": "LOCAL_OLLAMA_HISTORICAL_FAILED_CASE_REPLAY",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "context_tokens": context_tokens,
        "max_tokens": max_tokens,
        "real_provider_calls": 0,
        "paid_provider_calls": 0,
        "cases": len(results),
        "application_success": sum(1 for item in results if not item["error"]),
        "local_errors": dict(Counter(item["error"] for item in results if item["error"])),
        "final_unsupported_numeric_claims": sum(
            item["final_unsupported_numeric_claims"] for item in results
        ),
        "final_unsupported_claims": sum(item["final_unsupported_claims"] for item in results),
        "historical_grades": dict(Counter(item["historical_grade"] for item in results)),
        "results": [
            {
                key: value
                for key, value in item.items()
                if key not in {"raw_answer", "final_answer"}
            }
            for item in results
        ],
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--reviews", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--ids", default=DEFAULT_IDS)
    parser.add_argument("--model", default=os.environ.get("LOCAL_OLLAMA_MODEL", "qwen3.5-uncensored:9b-q4km"))
    parser.add_argument("--max-tokens", type=int, default=1536)
    parser.add_argument("--context-tokens", type=int, default=6144)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    ids = tuple(dict.fromkeys(item.strip() for item in args.ids.split(",") if item.strip()))
    summary = run(
        audit=args.audit.resolve(),
        reviews=args.reviews.resolve(),
        output=args.output.resolve(),
        ids=ids,
        model=args.model,
        max_tokens=args.max_tokens,
        context_tokens=args.context_tokens,
        timeout=args.timeout,
    )
    print(json.dumps({key: value for key, value in summary.items() if key != "results"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
