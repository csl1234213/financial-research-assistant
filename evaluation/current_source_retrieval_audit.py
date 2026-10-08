"""Audit current bilingual retrieval against the frozen 100-question corpus.

This audit uses only the checked-in public PDFs, the configured local embedding
model, the production HybridRetriever, and the production evidence/fact policy.
It does not call an answer-generation or evaluation provider.  It measures
whether current source evidence can be retrieved and deterministically
projected into the user's language; it is not a semantic answer re-grade.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# Force all model resolution to local caches for this provider-free audit.
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.planning.entity_extractor import extract_companies  # noqa: E402
from agent.reasoning_models import Evidence  # noqa: E402
from config import EMBEDDING_MODEL, EMBEDDING_MODEL_REVISION  # noqa: E402
from core.answer_policy import finalize_grounded_answer  # noqa: E402
from core.fact_ledger import FactLedger  # noqa: E402
from core.query_scope import QueryScope, classify_query_scope  # noqa: E402
from core.required_fact_plan import (  # noqa: E402
    _facts_for_spec,
    _preferred_fact,
    answer_contains_fact,
    infer_required_fact_plan,
)
from core.retrieval_probes import retrieval_probe_queries, retrieval_probe_top_k  # noqa: E402
from document_loader import PARSER_VERSION, get_company, get_document_period, load_pdf_chunks  # noqa: E402
from embedding import embed_passages, load_embedding_model  # noqa: E402
from evaluation.replay_formal_100_offline import _resolved_evidence_question  # noqa: E402
from retrieval.hybrid_retriever import HybridRetriever  # noqa: E402
from retrieval.periods import extract_metrics, extract_periods  # noqa: E402
from retrieval.retrieval_context import RetrievalContext  # noqa: E402
from storage.vector_models import SearchResult  # noqa: E402

DEFAULT_SOURCE = ROOT / "evaluation/results/formal_20260916"
DEFAULT_OUTPUT = ROOT / "evaluation/results/current_source_retrieval_audit_20260918_v4"
DOCUMENTS = (
    ROOT / "demo/documents/Tesla_sample.pdf",
    ROOT / "demo/documents/Apple_sample.pdf",
    ROOT / "demo/documents/NVIDIA_sample.pdf",
)
TOP_K_BY_SCOPE = {
    QueryScope.SUMMARY: 10,
    QueryScope.COMPARE: 8,
    QueryScope.FACT: 8,
    QueryScope.ANALYSIS: 10,
    QueryScope.RISK: 8,
}


class _InMemoryEmbeddingStore:
    """Small read-only store with Chroma-equivalent cosine rank ordering."""

    def __init__(self, rows: list[SearchResult], embeddings: Any):
        self.rows = rows
        self.embeddings = embeddings

    def similarity_search(self, *, query_embedding, top_k: int, tenant_id: int):
        if not self.rows:
            return []
        import numpy as np

        query = np.asarray(query_embedding, dtype=np.float32)
        similarities = self.embeddings @ query
        indexes = np.argsort(-similarities)[:top_k]
        results = []
        for index in indexes:
            row = self.rows[int(index)]
            if row.metadata.get("tenant_id") != tenant_id:
                continue
            metadata = dict(row.metadata)
            metadata["score_semantics"] = "similarity"
            results.append(SearchResult(
                document_id=row.document_id,
                chunk_id=row.chunk_id,
                score=float(similarities[index]),
                content=row.content,
                metadata=metadata,
            ))
        return results

    def lexical_corpus(self, tenant_id: int | None = None):
        if tenant_id is None:
            return list(self.rows)
        return [row for row in self.rows if row.metadata.get("tenant_id") == tenant_id]


def _source_fact_for_spec(spec, ledger: FactLedger, question: str):
    """Select an authoritative source value within the spec's full identity."""

    facts = _facts_for_spec(spec, ledger)
    if not facts:
        return None
    return _preferred_fact(
        facts,
        spec.metric_id,
        question=question,
        requested_period=spec.period,
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _load_dataset(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("FROZEN_DATASET_MUST_BE_A_LIST")
    if len(data) != 100 or len({str(item.get("id")) for item in data}) != 100:
        raise ValueError("EXPECTED_100_UNIQUE_FROZEN_QUESTIONS")
    return data


def _build_corpus(model) -> tuple[list[SearchResult], Any, dict[str, str]]:
    rows: list[SearchResult] = []
    source_hashes: dict[str, str] = {}
    for path in DOCUMENTS:
        source_hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        chunks = load_pdf_chunks(path, ocr_enabled=False)
        period = get_document_period(chunks)
        company = get_company(path.name)
        for index, chunk in enumerate(chunks):
            text = str(chunk.text or "")
            table_context = str(getattr(chunk, "table_context", "") or "")
            metadata = {
                "tenant_id": 7,
                "company": company,
                "source": path.name,
                "page": chunk.page,
                "section": chunk.section,
                "quarter": period,
                "periods": "|".join(extract_periods(f"{table_context}\n{text}")),
                "metrics": "|".join(extract_metrics(text)),
                "table_context": table_context,
                "content_type": chunk.content_type,
                "source_locator": chunk.source_locator or "",
                "source_format": chunk.source_format,
                "source_authority": "tenant_upload",
            }
            rows.append(SearchResult(
                document_id=path.stem,
                chunk_id=f"audit_{path.stem}_{index}",
                score=0.0,
                content=text,
                metadata=metadata,
            ))
    vectors = embed_passages(model, [row.content for row in rows], convert_to_tensor=False)
    import numpy as np

    return rows, np.asarray(vectors, dtype=np.float32), source_hashes


def _facts(plan: dict[str, Any], field: str) -> set[tuple[str, str, str]]:
    return {
        (
            str(item.get("company") or ""),
            str(item.get("metric_id") or "")
            + (f"_growth_{item['growth_basis']}" if item.get("growth_basis") else "")
            + (f"_{item['accounting_basis']}" if item.get("accounting_basis") else ""),
            str(item.get("period") or ""),
        )
        for item in plan.get("required", [])
        if item.get(field)
    }


def _project_question(
    row: dict[str, Any], retriever: HybridRetriever, store: _InMemoryEmbeddingStore,
    source_evidence: list[Evidence], source_ledger: FactLedger,
) -> dict[str, Any]:
    question = _resolved_evidence_question(row)
    scope = classify_query_scope(question)
    companies = extract_companies(question)
    top_k = TOP_K_BY_SCOPE.get(scope, 6)
    retrieval_context = RetrievalContext(
        question=question,
        company=companies[0] if len(companies) == 1 else None,
        top_k=top_k,
        tenant_id=7,
    )
    retrieved = retriever.retrieve(
        retrieval_context,
        store,
    )
    evidence = [
        Evidence(
            content=item.content,
            source=str(item.metadata.get("source", "")),
            company=str(item.metadata.get("company", "")),
            confidence=item.score,
            metadata={**item.metadata, "chunk_id": item.chunk_id},
        )
        for item in retrieved
    ]
    # Match the bounded deterministic probe fan-out used by the production
    # _retrieve_handler; a single top-K query is not the actual context path.
    seen_chunk_ids = {item.chunk_id for item in retrieved}
    for probe_query in retrieval_probe_queries(question, scope, evidence):
        probe_context = RetrievalContext(
            question=probe_query,
            company=companies[0] if len(companies) == 1 else None,
            top_k=retrieval_probe_top_k(question, probe_query),
            tenant_id=7,
        )
        for item in retriever.retrieve(probe_context, store):
            if item.chunk_id not in seen_chunk_ids:
                retrieved.append(item)
                seen_chunk_ids.add(item.chunk_id)
                evidence.append(Evidence(
                    content=item.content,
                    source=str(item.metadata.get("source", "")),
                    company=str(item.metadata.get("company", "")),
                    confidence=item.score,
                    metadata={**item.metadata, "chunk_id": item.chunk_id},
                ))
    chinese = bool(re.search(r"[\u3400-\u9fff]", row.get("question", "")))
    refusal = (
        "当前检索到的证据不足以确认该信息。"
        if chinese
        else "The retrieved passages are insufficient to establish this information."
    )
    finalized = finalize_grounded_answer(question, refusal, evidence)
    plan = finalized.plan.as_dict(finalized.ledger, finalized.answer)
    source_plan = infer_required_fact_plan(question, source_evidence, source_ledger)
    source_targets = []
    retrieved_target_keys: set[str] = set()
    projected_target_keys: set[str] = set()
    for spec in source_plan.required:
        source_fact = _source_fact_for_spec(spec, source_ledger, question)
        if source_fact is None:
            continue
        target = {
            "key": spec.key,
            "company": spec.company,
            "metric_id": spec.metric_id,
            "period": spec.period,
            "accounting_basis": spec.accounting_basis,
            "growth_basis": spec.growth_basis,
            "reason": spec.reason,
            "fact_id": source_fact.fact_id,
            "normalized_value": str(source_fact.normalized_value),
            "currency": source_fact.currency,
            "unit": source_fact.unit,
            "period_type": source_fact.period_type,
        }
        source_targets.append(target)
        retrieved_facts = finalized.ledger.lookup(
            company=spec.company,
            metric_id=spec.metric_id,
            period=spec.period,
            growth_basis=spec.growth_basis,
        )
        exact_retrieved = tuple(
            fact for fact in retrieved_facts
            if fact.normalized_value == source_fact.normalized_value
            and (not source_fact.currency or fact.currency == source_fact.currency)
        )
        if not exact_retrieved:
            continue
        retrieved_target_keys.add(spec.key)
        # Restrict the answer check to the authoritative source value. A
        # matching company/metric/period with the wrong number is not coverage.
        if answer_contains_fact(finalized.answer, spec, FactLedger(exact_retrieved)):
            projected_target_keys.add(spec.key)
    source_required_keys = {str(item["key"]) for item in source_targets}
    return {
        "id": row["id"],
        "language": row.get("language"),
        "question": row.get("question"),
        "resolved_question": question,
        "scope": scope.value,
        "top_k": top_k,
        "retrieved_sources": sorted({str(item.metadata.get("source", "")) for item in retrieved}),
        "retrieved_chunk_ids": [item.chunk_id for item in retrieved],
        "retrieved_unverified_table_count": sum(
            item.metadata.get("content_type") == "unverified_table" for item in retrieved
        ),
        "required_fact_plan": plan,
        "available_required_facts": sorted(_facts(plan, "available")),
        "answered_required_facts": sorted(_facts(plan, "answer_present")),
        # Ground the recall denominator in facts parsed from the complete
        # checked-in source PDFs, not in metrics guessed from the query alone.
        "source_required_fact_plan": source_targets,
        "source_available_required_facts": sorted(source_required_keys),
        "source_fact_targets": source_targets,
        "source_facts_retrieved": sorted(retrieved_target_keys),
        "source_facts_projected": sorted(projected_target_keys),
        "final_answer": finalized.answer,
        "unsupported_claim_count": finalized.grounded.unsupported_count,
    }


def run(source: Path, output: Path) -> dict[str, Any]:
    if os.environ.get("ALLOW_REAL_PROVIDER", "false").casefold() not in {"false", "0", "no", "off"}:
        raise RuntimeError("REAL_PROVIDER_MUST_BE_DISABLED")
    output = output.resolve()
    if output.exists():
        raise FileExistsError("REFUSING_TO_OVERWRITE_EXISTING_AUDIT_ARTIFACT")
    for path in (*DOCUMENTS, source / "dataset.json"):
        if not path.is_file():
            raise FileNotFoundError(path.name)

    model = load_embedding_model()
    corpus, vectors, source_hashes = _build_corpus(model)
    source_evidence = [
        Evidence(
            content=row.content,
            source=str(row.metadata.get("source", "")),
            company=str(row.metadata.get("company", "")),
            confidence=1.0,
            metadata={**row.metadata, "chunk_id": row.chunk_id},
        )
        for row in corpus
    ]
    source_ledger = FactLedger.from_evidence(source_evidence)
    store = _InMemoryEmbeddingStore(corpus, vectors)
    retriever = HybridRetriever(model)
    questions = _load_dataset(source / "dataset.json")
    rows = [
        _project_question(row, retriever, store, source_evidence, source_ledger)
        for row in questions
    ]

    pairs: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        language, _, suffix = str(row["id"]).partition("-")
        pairs.setdefault(suffix, {})[language] = row
    parity = []
    for suffix, pair in sorted(pairs.items()):
        if set(pair) != {"EN", "ZH"}:
            continue
        en = set(pair["EN"]["source_facts_retrieved"])
        zh = set(pair["ZH"]["source_facts_retrieved"])
        en_targets = set(pair["EN"]["source_available_required_facts"])
        zh_targets = set(pair["ZH"]["source_available_required_facts"])
        en_context_plan = set(
            tuple(value) for value in pair["EN"]["available_required_facts"]
        )
        zh_context_plan = set(
            tuple(value) for value in pair["ZH"]["available_required_facts"]
        )
        parity.append({
            "pair": suffix,
            "english_only_source_targets": sorted(en_targets - zh_targets),
            "chinese_only_source_targets": sorted(zh_targets - en_targets),
            "english_only_source_facts_retrieved": sorted(en - zh),
            "chinese_only_source_facts_retrieved": sorted(zh - en),
            "english_only_context_plan_facts": sorted(en_context_plan - zh_context_plan),
            "chinese_only_context_plan_facts": sorted(zh_context_plan - en_context_plan),
        })

    coverage_rows = [
        item for item in rows if item["source_available_required_facts"]
    ]
    total_required = sum(len(item["source_available_required_facts"]) for item in coverage_rows)
    available_required = sum(len(item["source_facts_retrieved"]) for item in coverage_rows)
    answered_required = sum(len(item["source_facts_projected"]) for item in coverage_rows)
    summary = {
        "scope": "CURRENT_SOURCE_PRODUCTION_PROBE_AND_EXACT_VALUE_PROJECTION_AUDIT_ONLY",
        "retrieval_mode": "Production top-k plus shared bounded retrieval probes",
        "recall_denominator": (
            "Required facts with an authoritative extracted value in the complete checked-in PDF corpus; "
            "retrieval and answer projection require exact normalized value and compatible currency"
        ),
        "value_match_policy": "Exact normalized value, period, company, metric, and compatible currency",
        "provider_calls": 0,
        "evaluator_calls": 0,
        "api_cost_usd": 0,
        "dataset": str((source / "dataset.json").relative_to(ROOT)),
        "model": EMBEDDING_MODEL,
        "model_revision": EMBEDDING_MODEL_REVISION,
        "parser_version": PARSER_VERSION,
        "documents": source_hashes,
        "documents_parsed": 3,
        "questions": len(rows),
        "required_fact_questions": len(coverage_rows),
        "required_facts": total_required,
        "source_available_required_facts": total_required,
        "source_available_required_facts_retrieved": available_required,
        "required_fact_recall": available_required / total_required if total_required else None,
        "source_available_required_facts_projected": answered_required,
        "required_fact_projection_coverage": answered_required / total_required if total_required else None,
        "unsupported_numeric_or_fact_claims_in_projection": sum(
            item["unsupported_claim_count"] for item in rows
        ),
        "bilingual_pairs": len(parity),
        "pairs_with_source_required_fact_retrieval_difference": sum(
            bool(
                item["english_only_source_facts_retrieved"]
                or item["chinese_only_source_facts_retrieved"]
            )
            for item in parity
        ),
        "pairs_with_source_target_difference": sum(
            bool(
                item["english_only_source_targets"]
                or item["chinese_only_source_targets"]
            )
            for item in parity
        ),
        "pairs_with_context_plan_difference": sum(
            bool(
                item["english_only_context_plan_facts"]
                or item["chinese_only_context_plan_facts"]
            )
            for item in parity
        ),
        "pair_fact_recall_differences": parity,
        "rows": rows,
    }
    output.mkdir(parents=True)
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    compact = []
    for row in rows:
        saved = dict(row)
        saved.pop("final_answer", None)
        compact.append(saved)
    (output / "questions.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in compact),
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    summary = run(args.source.resolve(), args.output.resolve())
    printable = {
        key: value
        for key, value in summary.items()
        if key not in {"rows", "pair_fact_recall_differences", "documents"}
    }
    printable["documents"] = {name: "SHA256_RECORDED" for name in summary["documents"]}
    print(json.dumps(printable, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
