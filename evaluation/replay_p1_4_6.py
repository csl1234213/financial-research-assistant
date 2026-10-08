"""Replay immutable provider artifacts through the production final-answer policy.

No provider is instantiated or called. Historical raw-answer replays and latest
final-report replays remain separate. Missing source text is never synthesized.
The optional Chroma snapshot is read-only and is labelled with capture time;
it is not represented as the original request's context.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.reasoning_models import Evidence  # noqa: E402
from core.answer_grounding import sanitize_answer  # noqa: E402
from core.answer_policy import finalize_grounded_answer  # noqa: E402

CASE_IDS = ("ZH-013", "EN-016", "EN-019", "ZH-019", "ZH-008")
RESULTS = ROOT / "evaluation/results"
HISTORICAL = RESULTS / "p1_3_5_real_provider_semantic_recheck"
LATEST = RESULTS / "p1_4_5_real_provider_5q_20260915"
REFERENCE = RESULTS / "formal_20260914_p0_quality_sprint1_1_final/reference_chunks.json"
OUTPUT = RESULTS / "p1_4_6_offline_repair"
SAFE_METADATA = {
    "source", "company", "chunk_id", "quarter", "page", "section", "table_context",
    "document_reporting_period", "fact_period", "table_column_period", "evidence_row_period",
    "parser_version", "chunker_version", "content_sha256", "source_authority",
    "embedding_model", "embedding_revision", "semantic_support", "semantic_support_reason",
}


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def reference_index(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        chunk_id: {"content": content, "metadata": metadata or {}, "origin": "FROZEN_REFERENCE_EXACT_ID"}
        for chunk_id, content, metadata in zip(data["ids"], data["documents"], data["metadatas"], strict=True)
    }


def extract_final_answer(report: str) -> str:
    """Extract the historical API answer; reject an unknown wrapper."""
    start = re.search(r"^## (?:Answer \(LLM Answer\)|回答（LLM 模型回答）)\s*$", report, re.M)
    if not start:
        raise ValueError("ANSWER_BOUNDARY_MISSING")
    end = re.search(r"^## (?:Agent Evidence Analysis|智能体证据分析)\s*$", report[start.end():], re.M)
    if not end:
        raise ValueError("EVIDENCE_BOUNDARY_MISSING")
    answer = report[start.end():start.end() + end.start()].strip()
    if not answer:
        raise ValueError("ANSWER_EMPTY")
    return answer


def fetch_chroma_snapshot(ids: list[str]) -> dict[str, Any]:
    if not ids:
        return {"captured_at": datetime.now(timezone.utc).isoformat(), "chunks": {}, "missing_ids": []}
    program = '''import json, os, sys
import chromadb
from datetime import datetime, timezone
requested = json.loads(sys.stdin.read())
client = chromadb.HttpClient(host=os.environ.get("CHROMA_HOST", "chromadb"),
                            port=int(os.environ.get("CHROMA_PORT", "8000")))
found = {}
for entry in client.list_collections():
    name = entry if isinstance(entry, str) else entry.name
    result = client.get_collection(name).get(ids=requested, include=["documents", "metadatas"])
    for i, chunk_id in enumerate(result["ids"]):
        candidate = {"content": result["documents"][i], "metadata": result["metadatas"][i],
                     "origin": "CURRENT_CHROMA_EXACT_ID", "collection": name}
        if chunk_id in found and found[chunk_id]["content"] != candidate["content"]:
            raise RuntimeError("AMBIGUOUS_CHUNK_ID")
        found[chunk_id] = candidate
print(json.dumps({"captured_at": datetime.now(timezone.utc).isoformat(), "chunks": found,
                  "missing_ids": sorted(set(requested) - set(found))}))
'''
    process = subprocess.run(
        ["docker", "compose", "exec", "-T", "backend", "python", "-c", program],
        input=json.dumps(ids), capture_output=True, text=True, encoding="utf-8",
        cwd=ROOT, timeout=60, check=False,
    )
    if process.returncode:
        raise RuntimeError("READ_ONLY_CHROMA_SNAPSHOT_FAILED")
    data = json.loads(process.stdout)
    for chunk in data["chunks"].values():
        chunk["metadata"] = {key: value for key, value in (chunk.get("metadata") or {}).items()
                             if key in SAFE_METADATA}
    data["capture_semantics"] = "CURRENT_SNAPSHOT_NOT_ORIGINAL_REQUEST_CONTEXT"
    return data


def build_evidence(
    row: dict[str, Any], reference: dict[str, Any], snapshot: dict[str, Any], *, historical: bool,
) -> tuple[list[Evidence], list[dict[str, Any]], list[str]]:
    embedded = {str(item.get("chunk_id")): item for item in row.get("final_context", [])
                if isinstance(item, dict)} if isinstance(row.get("final_context"), list) else {}
    # Preserve original citation positions, including empty missing records.
    citations = row.get("final_citations", [])
    evidence, provenance, missing = [], [], []
    for index, citation in enumerate(citations, 1):
        chunk_id = str(citation.get("chunk_id", ""))
        exact = reference.get(chunk_id)
        original = embedded.get(chunk_id, {})
        if historical and original.get("content"):
            selected = {"content": original["content"], "metadata": exact.get("metadata", {}) if exact else {},
                        "origin": "HISTORICAL_CAPTURED_CONTEXT"}
        else:
            selected = exact or (snapshot.get(chunk_id) if not historical else None)
        metadata = {key: value for key, value in citation.items() if key in SAFE_METADATA}
        if selected:
            metadata.update({key: value for key, value in (selected.get("metadata") or {}).items()
                             if key in SAFE_METADATA})
        metadata["chunk_id"] = chunk_id
        content = selected.get("content") if selected else None
        if not content:
            missing.append(chunk_id)
        company = metadata.get("company") or original.get("company") or ""
        evidence.append(Evidence(str(content or ""), str(citation.get("source", "")), str(company),
                                 metadata=metadata))
        provenance.append({"rank": index, "chunk_id": chunk_id,
                           "origin": selected.get("origin") if selected else "MISSING_EXACT_ID",
                           "content_sha256": hashlib.sha256(str(content).encode()).hexdigest() if content else None})
    return evidence, provenance, missing


def replay(row: dict[str, Any], answer: str, evidence: list[Evidence]) -> dict[str, Any]:
    question = row["question"]
    final = finalize_grounded_answer(question, answer, evidence)
    # Recheck only the final user answer, not diagnostics or copied evidence.
    checked = sanitize_answer(question, final.answer, final.grounded.evidence)
    statuses = final.plan.as_dict(final.ledger, final.answer)
    required = statuses["required"]
    return {
        "question": question,
        "input_answer": answer,
        "prepared_answer": final.prepared_answer,
        "final_answer": final.answer,
        "raw_claim_dispositions": dict(Counter(claim.disposition for claim in final.raw_grounding.claims)),
        "final_claim_dispositions": dict(Counter(claim.disposition for claim in checked.claims)),
        "final_unsupported_numeric": checked.unsupported_count,
        "final_supported_numeric": checked.supported_count,
        "final_derivable_numeric": checked.derivable_count,
        "idempotent_sanitization": checked.answer == final.answer,
        "required_fact_plan": statuses,
        "required_fact_coverage": sum(bool(item["answer_present"]) for item in required) / len(required)
            if required else None,
        "evidence_available_for_all_required_facts": bool(required) and all(item["available"] for item in required),
        "added_fact_ids": list(final.added_fact_ids),
        "scope_removed_lines": list(final.removed_lines),
        "final_citations": [{"rank": index, "chunk_id": item.metadata.get("chunk_id"),
                             "source": item.source, "company": item.company}
                            for index, item in enumerate(final.grounded.evidence, 1)],
        "required_fact_unit_period_audit": [
            {"fact_id": fact.fact_id, "company": fact.company, "metric_id": fact.metric_id,
             "period": fact.fact_period, "period_type": fact.period_type, "unit": fact.unit,
             "currency": fact.currency, "normalized_value": str(fact.normalized_value),
             "source": fact.document, "chunk_id": fact.chunk_id}
            for fact in final.ledger.facts
            if any(fact.fact_id in requirement["fact_ids"] for requirement in required)
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-current-chroma", action="store_true")
    parser.add_argument("--snapshot", type=Path, help="Previously captured read-only snapshot; no Docker required")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if os.environ.get("ALLOW_REAL_PROVIDER", "false").casefold() not in {"false", "0", "no", "off"}:
        raise RuntimeError("REAL_PROVIDER_MUST_BE_DISABLED")
    output = args.output.resolve()
    if not output.is_relative_to(OUTPUT.resolve()):
        raise ValueError("OUTPUT_MUST_BE_UNDER_P1_4_6_OFFLINE_REPAIR")
    output.mkdir(parents=True, exist_ok=False)
    reference = reference_index(_read(REFERENCE))
    latest_rows = {case_id: _read(LATEST / f"{case_id}.json") for case_id in CASE_IDS}
    wanted = sorted({str(citation["chunk_id"]) for row in latest_rows.values()
                     for citation in row["final_citations"]} - set(reference))
    snapshot = _read(args.snapshot) if args.snapshot else (
        fetch_chroma_snapshot(wanted) if args.snapshot_current_chroma else
        {"captured_at": None, "chunks": {}, "missing_ids": wanted,
         "capture_semantics": "SNAPSHOT_NOT_REQUESTED"})
    _write(output / "evidence_snapshot.json", snapshot)
    cases = []
    for mode, source in (("HISTORICAL_RAW_REPLAY", HISTORICAL), ("FINAL_REPORT_REPLAY", LATEST)):
        for case_id in CASE_IDS:
            path = source / f"{case_id}.json"
            row = _read(path)
            historical = mode == "HISTORICAL_RAW_REPLAY"
            raw = row.get("raw_llm_answer")
            answer = raw if historical else extract_final_answer(row["final_api_report"])
            if not isinstance(answer, str) or not answer.strip():
                cases.append({"id": case_id, "mode": mode, "status": "BLOCKED_RAW_ANSWER_MISSING"})
                continue
            evidence, provenance, missing = build_evidence(row, reference, snapshot["chunks"], historical=historical)
            result = replay(row, answer, evidence)
            result.update({"id": case_id, "mode": mode, "source_artifact": str(path.relative_to(ROOT)),
                           "source_artifact_sha256": _sha(path),
                           "latest_raw_available": bool(raw) if not historical else None,
                           "context_provenance": provenance, "missing_evidence_ids": missing,
                           "complete_original_context": historical and not missing,
                           "status": "PARTIAL_MISSING_EVIDENCE" if missing else "REPLAYED"})
            _write(output / f"{mode.lower()}_{case_id}.json", result)
            cases.append({key: result[key] for key in (
                "id", "mode", "status", "final_unsupported_numeric", "final_supported_numeric",
                "required_fact_coverage", "evidence_available_for_all_required_facts", "missing_evidence_ids",
            )})
    summary = {
        "real_provider_calls": 0, "evaluator_calls": 0, "api_cost": 0,
        "policy_entrypoint": "core.answer_policy.finalize_grounded_answer",
        "scope": "OFFLINE_FINAL_ANSWER_POLICY_REPLAY_NOT_NEW_MODEL_GENERATION",
        "historical_reported_unsupported_count": 80,
        "historical_80_status": "UNVERIFIED_HISTORICAL_REPORT_METRIC_INCLUDES_WRAPPER_EVIDENCE",
        "latest_raw_5q_replay": "UNAVAILABLE_RAW_NOT_CAPTURED",
        "reference_sha256": _sha(REFERENCE),
        "current_snapshot_capture_time": snapshot.get("captured_at"),
        "cases": cases,
    }
    _write(output / "summary.json", summary)
    print(json.dumps({"real_provider_calls": 0, "cases": cases}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
