"""Isolated real-embedding Hybrid/Tree wiring; no production store or provider calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np

from agent.tools.retrieval_contract import RetrievalRequest as ScopedRequest
from document_compatibility.engine import inspect_pdf
from evaluation.adaptive_retrieval_benchmark import BenchmarkCase, FinancialRetrievalBenchmark, ReferenceSpan
from retrieval.adaptive_adapters import HybridEvidenceAdapter
from retrieval.adaptive_contract import RetrievalRequest
from retrieval.hybrid_retriever import HybridRetriever
from retrieval.tree_shadow import TreeDecision, TreeReasoningRetriever, TreeRepository, tree_quality
from storage.vector_models import SearchResult


class LocalVectorCorpus:
    """Real cosine similarity over local embeddings, implementing the existing store surface."""

    def __init__(self, rows, embeddings):
        self.rows = rows
        self.embeddings = np.asarray(embeddings)

    def similarity_search(self, query_embedding, top_k=5, tenant_id=None):
        query = np.asarray(query_embedding)
        scores = self.embeddings @ query / (np.linalg.norm(self.embeddings, axis=1) * max(np.linalg.norm(query), 1e-12))
        indices = np.argsort(-scores)
        return [
            replace(self.rows[int(i)], score=float(scores[i]))
            for i in indices
            if self.rows[int(i)].metadata["tenant_id"] == tenant_id
        ][:top_k]

    def lexical_corpus(self, tenant_id=None):
        return [r for r in self.rows if r.metadata["tenant_id"] == tenant_id]


def run(fixture: Path, model, *, narrative: bool = False):
    from embedding import embed_query

    report = inspect_pdf(fixture)[1]
    tree = TreeRepository().build(
        report, tenant_id=7, content_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest(), use_sections=True
    )
    rows = [
        SearchResult(
            tree.document_id,
            b.block_id,
            0,
            b.text,
            {
                "tenant_id": 7,
                "company": "贵州茅台",
                "source": fixture.name,
                "page": b.page,
                "section": b.section,
                "source_block_ids": [b.block_id],
                "bbox": b.bbox,
                "score_semantics": "similarity",
                "source_authority": "tenant_upload",
            },
        )
        for b in report.blocks
        if b.text.strip()
    ]
    embeddings = model.encode(
        ["passage: " + r.content for r in rows], convert_to_numpy=True, batch_size=16, show_progress_bar=False
    )
    hybrid = HybridEvidenceAdapter(HybridRetriever(model), LocalVectorCorpus(rows, embeddings))

    def decide(request, nodes):
        # Deterministic orientation, not a learned or LLM reasoning quality claim.
        query = embed_query(model, request.scoped.query, convert_to_tensor=False)
        candidates = [n for n in nodes if n.parent_id]
        titles = model.encode(["passage: " + n.title for n in candidates], convert_to_numpy=True)
        scores = titles @ query / (np.linalg.norm(titles, axis=1) * max(np.linalg.norm(query), 1e-12))
        return TreeDecision(
            tuple(candidates[int(i)].node_id for i in np.argsort(-scores)[:2]),
            "Local embedding orientation over section titles; no gold consulted",
        )

    retriever = TreeReasoningRetriever(tree, decide)
    sources = tuple(ReferenceSpan(b.document_id, b.block_id, b.page, b.text, b.section) for b in report.blocks)
    benchmark = FinancialRetrievalBenchmark(sources)
    queries = [
        ("EXACT_FACT", "贵州茅台2025年总资产是多少？", "资产总计"),
        ("EXACT_PHRASE", "财报中哪里提到货币资金？", "货币资金"),
        ("LOCAL_SEMANTIC", "公司有没有讨论渠道改革？", "渠道"),
        ("SECTION_LOOKUP", "管理层如何评价行业环境？", "行业"),
        ("EXHAUSTIVE", "报告列出的主要风险有哪些？", "风险"),
        ("CAUSAL", "为什么净利润下降？", "净利润"),
        ("CROSS_SECTION", "利润下降与销售费用变化有什么关系？", "销售费用"),
        ("TREND", "过去三年经营现金流怎么变化？", "经营活动产生的现金流量净额"),
        ("AMBIGUOUS", "公司有多少钱？", ""),
        ("MULTI_DOCUMENT", "比较贵州茅台和五粮液盈利能力和风险。", ""),
    ]
    if narrative:
        queries = [
            ("EXACT_PHRASE", "哪里提到直销和批发代理渠道？", "直销和批发代理渠道"),
            ("EXACT_PHRASE", "哪里提到宏观经济风险？", "一是宏观经济风险"),
            ("SECTION_LOOKUP", "行业格局与趋势章节如何评价行业形势？", "从行业形势看"),
            ("SECTION_LOOKUP", "公司未来经营计划如何安排基建项目？", "七是扎实推进基建项目建设"),
            ("LOCAL_SEMANTIC", "公司是否计划扩大酿酒生产能力？", "产能扩建"),
            ("LOCAL_SEMANTIC", "公司通过什么渠道销售产品？", "直销和批发代理渠道"),
            ("EXHAUSTIVE", "列出风险类别并说明风险防控计划。", "风险"),
            ("EXHAUSTIVE", "报告列出的主要风险有哪些？", "一是宏观经济风险"),
            ("CAUSAL", "资源为什么向优势企业集中？", "优胜劣汰"),
            ("CAUSAL", "为什么公司认为未来消费水平将提升？", "居民收入增加"),
            ("CAUSAL", "管理层如何解释营业收入变动？", "主要是酱香系列酒产品结构调整影响"),
            ("SECTION_LOOKUP", "哪些章节讨论建设项目投资管理？", "强化投资精准性与项目全过程管理"),
            ("LOCAL_SEMANTIC", "公司讨论了哪些渠道和终端改革？", "渠道端、终端"),
        ]
    results = []
    for index, (query_class, query, keyword) in enumerate(queries):

        def compact(text):
            return re.sub(r"\s+", "", text)

        provisional = tuple(s for s in sources if keyword and compact(keyword) in compact(s.text))
        reviewed = narrative or index in {0, 1}
        if reviewed and not narrative:
            audited_id = "9356d5a65ff21a66d374272c0a4226b6" if index == 0 else "c3bb6340c0ee056629db33ca8b26008c"
            provisional = tuple(s for s in sources if s.block_id == audited_id)
            if len(provisional) != 1:
                raise ValueError("audited fixture span missing; review source version before scoring")
        if narrative:
            if index == 6:
                anchors = ("一是宏观经济风险", "八是加强风险防控体系建设")
                provisional = tuple(
                    min((s for s in sources if compact(anchor) in compact(s.text)), key=lambda s: len(s.text))
                    for anchor in anchors
                )
            else:
                provisional = (min(provisional, key=lambda s: len(s.text)),)
        case = BenchmarkCase(
            f"moutai-{index + 1:03}",
            RetrievalRequest(
                ScopedRequest(query, 7, top_k=5, company="贵州茅台", document_ids=(tree.document_id,)),
                query_class=query_class,
            ),
            provisional,
            gold_reviewed=reviewed,
        )
        result = benchmark.run_case(case, hybrid, retriever)
        result["gold_note"] = (
            "Reviewed native narrative source block; bounded excerpt corpus"
            if narrative
            else "Reviewed FY2025 consolidated source row; other period/parent rows excluded"
            if reviewed
            else "Keyword candidates only; semantic source review required"
        )
        result["candidate_source_count"] = len(provisional)
        result["case_readiness"] = (
            "AMBIGUOUS_QUERY"
            if query_class == "AMBIGUOUS"
            else "INCOMPLETE_CORPUS"
            if query_class in {"TREND", "MULTI_DOCUMENT"}
            else "REVIEWED"
            if reviewed
            else "SOURCE_REVIEW_REQUIRED"
            if provisional
            else "NO_KEYWORD_CANDIDATE"
        )
        results.append(result)
    counts = {name: sum(x["winner"] == name for x in results) for name in ("HYBRID", "TREE", "TIE", "NOT_EVALUATED")}
    return {
        "fixture": str(fixture),
        "fixture_sha256": tree.content_sha256,
        "tree_quality": asdict(tree_quality(tree)),
        "provider_calls": 0,
        "gold_reviewed_case_count": len(queries) if narrative else 2,
        "nonempty_source_pages": len({b.page for b in report.blocks if b.text.strip()}),
        "results": results,
        "summary": counts,
        "answer_accuracy": "NOT_EVALUATED",
        "primary_answer_changed_by_shadow_count": 0,
        "primary_answer_change_validation": "Not connected to production; validated separately by shadow tests",
        "tree_provider_calls": 0,
        "tree_benchmark_cost": 0,
        "generation_provider_cost": 0,
        "embedding_compute_cost": "NOT_ESTIMATED",
    }


if __name__ == "__main__":
    os.environ["ALLOW_REAL_PROVIDER"] = "false"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from embedding import load_embedding_model

    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=root / "tests/fixtures/moutai-standard-statements-2025.pdf")
    parser.add_argument("--narrative", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run(args.fixture, load_embedding_model(), narrative=args.narrative)
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
        print(json.dumps(result["summary"]))
    else:
        print(serialized)
