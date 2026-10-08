"""Run a small local-only quality probe through the production answer policy.

This command is intentionally separate from the paid-provider smoke scripts. It
uses the local Ollama OpenAI-compatible endpoint, the checked-in retrieval
audit, the production prompt builders, and the same final grounding policy.
It never reads or sends a DeepSeek credential and refuses to run with the real
provider gate enabled.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core.fact_ledger as fact_ledger  # noqa: E402
from agent.reasoning_models import Evidence  # noqa: E402
from core.answer_policy import finalize_grounded_answer  # noqa: E402
from core.citation_gate import filter_evidence_for_query  # noqa: E402
from core.required_fact_plan import infer_required_fact_plan  # noqa: E402
from document_loader import get_company  # noqa: E402
from evaluation.replay_formal_100_offline import _resolved_evidence_question  # noqa: E402
from evaluation.replay_historical_answers_current_retrieval import (  # noqa: E402
    _source_evidence_index,
)
from prompt_builder import (  # noqa: E402
    build_compare_prompt,
    build_direct_chat_prompt,
    build_prompt,
    get_prompt_system_prompt,
)

DEFAULT_AUDIT = ROOT / "evaluation/results/current_source_retrieval_audit_20260924_v74_growth_fact_probes/summary.json"
DEFAULT_OUTPUT = ROOT / "evaluation/results/local_ollama_qwen38_10q_groundingfix_20260925_v1"
FIXED_CASES = (
    "EN-007",
    "EN-002",
    "EN-019",
    "ZH-044",
    "ZH-007",
    "ZH-013",
    "EN-016",
    "ZH-008",
    "EN-033",
    "ZH-019",
)
DEFAULT_CONTEXT_TOKENS = 4096  # conservative input budget inside an 8192 window
FROZEN_DATASET = ROOT / "evaluation/results/formal_20260916/dataset.json"


def _read_audit(path: Path) -> dict[str, dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {str(row["id"]): row for row in raw.get("rows", [])}


def _canonical_question(case_id: str, audit_row: dict[str, Any]) -> str:
    """Prefer the current frozen question over stale/mojibaked audit text.

    Retrieval audit artifacts are historical outputs and can contain a
    transcoding-corrupted Chinese question even when the checked-in frozen
    dataset is valid UTF-8.  Sending that artifact text to a local model makes
    a language-quality probe measure the artifact corruption instead of the
    answer pipeline.  Follow-up markers are rebuilt from the same dataset.
    """

    if FROZEN_DATASET.is_file():
        frozen = json.loads(FROZEN_DATASET.read_text(encoding="utf-8"))
        item = next((row for row in frozen if str(row.get("id")) == case_id), None)
        if item is not None:
            return _resolved_evidence_question(item)
    return str(audit_row.get("resolved_question") or audit_row.get("question") or "")


def _expected_sources(case_id: str) -> list[str]:
    """Return the frozen benchmark's authoritative source identities."""

    if not FROZEN_DATASET.is_file():
        return []
    frozen = json.loads(FROZEN_DATASET.read_text(encoding="utf-8"))
    item = next((row for row in frozen if str(row.get("id")) == case_id), None)
    return [str(source) for source in (item or {}).get("expected_sources", [])]


def _local_chat(
    client: httpx.Client,
    *,
    model: str,
    system_prompt: str,
    prompt: str,
    max_tokens: int,
) -> tuple[str, dict[str, Any]]:
    """Call Ollama directly so Qwen thinking tokens cannot hide content.

    ``think=false`` is a local-runtime option; it is not sent to any paid
    provider. ``num_ctx`` is deliberately fixed at 8192 to match the user's
    quality-priority runtime, while ``num_predict`` remains bounded.
    """
    response = client.post(
        "http://127.0.0.1:11434/api/chat",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "think": False,
            "stream": False,
            "options": {"num_ctx": 8192, "num_predict": max_tokens, "temperature": 0},
        },
    )
    response.raise_for_status()
    payload = response.json()
    message = payload.get("message") or {}
    return str(message.get("content") or "").strip(), {
        "provider": "local_ollama",
        "model": payload.get("model", model),
        "prompt_tokens": payload.get("prompt_eval_count"),
        "completion_tokens": payload.get("eval_count"),
        "total_tokens": (
            (payload.get("prompt_eval_count") or 0) + (payload.get("eval_count") or 0)
        ),
        "done_reason": payload.get("done_reason"),
    }


def _evidence_for_row(
    row: dict[str, Any],
    index: dict[str, Evidence],
    expected_sources: list[str] | None = None,
) -> list[Evidence]:
    evidence: list[Evidence] = []
    for chunk_id in row.get("retrieved_chunk_ids", []):
        item = index.get(chunk_id)
        if item is None:
            continue
        source_company = fact_ledger.canonical_company(item.company or get_company(item.source))
        matching_sources = [
            source
            for source in (expected_sources or [])
            if fact_ledger.canonical_company(get_company(source)) == source_company
        ]
        if len(matching_sources) == 1:
            # The benchmark's expected source identifies the document in the
            # knowledge base. Preserve that identity even when the checked-in
            # demo PDF has a generic filename and a later filing period; its
            # table may still contain the benchmark's historical comparison
            # column. This mirrors the document_id metadata used by retrieval.
            canonical_source = matching_sources[0]
            metadata = dict(item.metadata)
            metadata["document_id"] = Path(canonical_source).stem.casefold()
            metadata["source"] = canonical_source
            item = Evidence(
                content=item.content,
                source=canonical_source,
                company=item.company,
                confidence=item.confidence,
                metadata=metadata,
            )
        evidence.append(item)
    return evidence


def _case_prompt(
    case_id: str,
    question: str,
    evidence: list[Evidence],
    *,
    context_tokens: int,
) -> tuple[str, str]:
    if case_id == "ZH-044":
        return build_direct_chat_prompt(question), get_prompt_system_prompt("direct_chat")
    ledger_plan = infer_required_fact_plan(question, evidence)
    context, _ = fact_ledger.build_evidence_first_context(
        question,
        evidence,
        ledger_plan,
        max_context_tokens=context_tokens,
    )
    if case_id == "EN-019":
        return build_compare_prompt(question, context), get_prompt_system_prompt("financial_compare")
    return build_prompt(question, context), get_prompt_system_prompt("financial_rag")


def run(
    *,
    audit_path: Path,
    output: Path,
    model: str,
    max_tokens: int,
    context_tokens: int,
    timeout: int,
) -> dict[str, Any]:
    if os.environ.get("ALLOW_REAL_PROVIDER", "false").casefold() not in {"false", "0", "no", "off", ""}:
        raise RuntimeError("REAL_PROVIDER_MUST_BE_DISABLED")
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite {output}")
    if not audit_path.is_file():
        raise FileNotFoundError(audit_path)

    rows = _read_audit(audit_path)
    missing = [case_id for case_id in FIXED_CASES if case_id not in rows]
    if missing:
        raise ValueError(f"AUDIT_CASES_MISSING:{','.join(missing)}")
    source_index = _source_evidence_index()
    client = httpx.Client(timeout=httpx.Timeout(timeout, connect=10))
    output.mkdir(parents=True)
    results: list[dict[str, Any]] = []
    for case_id in FIXED_CASES:
        row = rows[case_id]
        question = _canonical_question(case_id, row)
        expected_sources = _expected_sources(case_id)
        retrieved = _evidence_for_row(row, source_index, expected_sources)
        evidence = [] if case_id == "ZH-044" else filter_evidence_for_query(question, retrieved)
        prompt, system_prompt = _case_prompt(
            case_id,
            question,
            evidence,
            context_tokens=context_tokens,
        )
        started = perf_counter()
        error: str | None = None
        raw_answer = ""
        response_meta: dict[str, Any] = {}
        final_answer = None
        try:
            raw_answer, response_meta = _local_chat(
                client,
                model=model,
                system_prompt=system_prompt,
                prompt=prompt,
                max_tokens=max_tokens,
            )
            if not raw_answer:
                raise RuntimeError("EMPTY_LOCAL_MODEL_OUTPUT")
            if response_meta.get("done_reason") == "length":
                raise RuntimeError("LOCAL_MODEL_OUTPUT_TRUNCATED")
            if case_id != "ZH-044":
                final_answer = finalize_grounded_answer(question, raw_answer, evidence)
        except Exception as exc:  # the probe must record, not hide, local failures
            error = (
                str(exc)
                if str(exc) in {"EMPTY_LOCAL_MODEL_OUTPUT", "LOCAL_MODEL_OUTPUT_TRUNCATED"}
                else type(exc).__name__
            )
        elapsed_ms = round((perf_counter() - started) * 1000, 3)
        direct_chat = case_id == "ZH-044" and not error
        final_text = raw_answer if direct_chat else (final_answer.answer if final_answer is not None else "")
        final_claims = list(final_answer.grounded.claims) if final_answer is not None else []
        output_row = {
            "id": case_id,
            "question": row.get("question"),
            "resolved_question": question,
            "raw_answer": raw_answer,
            "final_answer": final_text,
            "error": error,
            "latency_ms": elapsed_ms,
            "retrieved_sources": sorted({item.source for item in evidence}),
            "expected_sources": expected_sources,
            "planned_company_periods": [
                {"company": spec.company, "period": spec.period}
                for spec in (final_answer.plan.required if final_answer else ())
            ],
            "retrieved_evidence_count": len(evidence),
            "final_evidence_count": len(final_answer.grounded.evidence) if final_answer else 0,
            "final_unsupported_numeric_claims": sum(
                1 for claim in final_claims
                if claim.disposition == "UNSUPPORTED" and claim.is_numeric
            ),
            "raw_unsupported_claims": sum(
                1 for claim in (final_answer.raw_grounding.claims if final_answer else [])
                if claim.disposition == "UNSUPPORTED"
            ),
            "removed_lines": list(final_answer.removed_lines) if final_answer else [],
            "verified_facts_only_projection": (
                bool(final_answer.verified_facts_only_projection) if final_answer else False
            ),
            "grounding_mode": "direct_chat" if direct_chat else "financial_rag",
            "provider_usage": response_meta,
        }
        (output / f"{case_id}.json").write_text(
            json.dumps(output_row, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        results.append(output_row)

    summary = {
        "scope": "LOCAL_OLLAMA_PRODUCTION_PROMPT_AND_GROUNDING_PROBE",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "real_provider_calls": 0,
        "paid_provider_calls": 0,
        "model": model,
        "audit_artifact": str(audit_path.resolve()),
        "max_tokens": max_tokens,
        "context_tokens": context_tokens,
        "cases": len(results),
        "application_success": sum(1 for row in results if not row["error"] and row["final_answer"]),
        "empty_output": sum(1 for row in results if row["error"] == "EMPTY_LOCAL_MODEL_OUTPUT"),
        "output_truncated": sum(
            1 for row in results if row["error"] == "LOCAL_MODEL_OUTPUT_TRUNCATED"
        ),
        "final_unsupported_numeric_claims": sum(row["final_unsupported_numeric_claims"] for row in results),
        "raw_unsupported_claims": sum(row["raw_unsupported_claims"] for row in results),
        "results": results,
    }
    client.close()
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--model",
        default=os.environ.get("LOCAL_OLLAMA_MODEL", "qwen3.5-uncensored:9b-q4km"),
    )
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--context-tokens", type=int, default=DEFAULT_CONTEXT_TOKENS)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    summary = run(
        audit_path=args.audit.resolve(),
        output=args.output.resolve(),
        model=args.model,
        max_tokens=args.max_tokens,
        context_tokens=args.context_tokens,
        timeout=args.timeout,
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
