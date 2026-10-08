from dataclasses import replace
from pathlib import Path

import pytest

from agent.tools.retrieval_contract import RetrievalRequest as ScopedRequest
from document_compatibility.engine import inspect_pdf
from evaluation.adaptive_retrieval_benchmark import BenchmarkCase, FinancialRetrievalBenchmark, ReferenceSpan
from retrieval.adaptive_contract import Evidence, RetrievalMode, RetrievalRequest, RetrievalResult, RetrievalStatus
from retrieval.tree_shadow import TreeDecision, TreeReasoningRetriever, TreeRepository


class StaticRetriever:
    def __init__(self, *evidence):
        self.result = RetrievalResult(RetrievalStatus.FOUND, RetrievalMode.HYBRID, evidence)

    def retrieve(self, request):
        return self.result


def setup_case(reviewed=True):
    source = ReferenceSpan("doc", "block", 12, "审计意见：无保留意见。")
    case = BenchmarkCase(
        "phrase-001", RetrievalRequest(ScopedRequest("无保留意见", 7), query_class="EXACT_PHRASE"), (source,), reviewed
    )
    ev = Evidence(
        "block",
        "TREE_PAGE",
        "doc",
        source.text,
        RetrievalMode.TREE,
        "PDF",
        "report.pdf",
        page=12,
        source_block_ids=("block",),
    )
    return source, case, ev


def test_can_award_hybrid_without_claiming_answer_accuracy_or_promotion():
    source, case, ev = setup_case()
    result = FinancialRetrievalBenchmark((source,)).run_case(case, StaticRetriever(ev), StaticRetriever())
    assert result["winner"] == "HYBRID"
    assert result["hybrid"]["evidence_recall"] == 1
    assert result["hybrid"]["answer_accuracy"] == "NOT_EVALUATED"
    assert not result["production_promote"]


def test_summary_hallucination_and_wrong_page_do_not_count_as_recalled():
    source, case, ev = setup_case()
    for wrong in (replace(ev, text="净利润999亿元"), replace(ev, page=13)):
        result = FinancialRetrievalBenchmark((source,)).run_case(case, StaticRetriever(), StaticRetriever(wrong))
        assert result["tree"]["evidence_recall"] == 0
        assert result["tree"]["citation_mismatch_count"] == 1


def test_unreviewed_gold_cannot_produce_accuracy_or_winner():
    source, case, ev = setup_case(False)
    result = FinancialRetrievalBenchmark((source,)).run_case(case, StaticRetriever(ev), StaticRetriever(ev))
    assert result["winner"] == "NOT_EVALUATED"
    assert result["tree"]["evidence_precision"] is None


def test_exact_fact_comparison_preserves_fact_preference_only_with_valid_evidence():
    source, case, ev = setup_case()
    case = replace(case, request=replace(case.request, query_class="EXACT_FACT"))
    fact = StaticRetriever(ev)
    result = FinancialRetrievalBenchmark((source,)).run_case(case, StaticRetriever(ev), StaticRetriever(ev), fact)
    assert result["winner"] == "FACT" and result["fact"]["evidence_recall"] == 1
    bad = StaticRetriever(replace(ev, page=999))
    result = FinancialRetrievalBenchmark((source,)).run_case(case, StaticRetriever(ev), StaticRetriever(ev), bad)
    assert result["winner"] != "FACT"


def test_ground_truth_cannot_be_fabricated():
    source, case, ev = setup_case()
    with pytest.raises(ValueError, match="ground truth"):
        FinancialRetrievalBenchmark((source,)).run_case(
            replace(case, expected=(replace(source, text="fabricated"),)), StaticRetriever(ev), StaticRetriever(ev)
        )


def test_real_moutai_source_benchmark_wiring():
    fixture = Path(__file__).parent / "fixtures" / "moutai-standard-statements-2025.pdf"
    report = inspect_pdf(fixture)[1]
    tree = TreeRepository().build(report, tenant_id=7, content_sha256="fixture", use_sections=True)
    block = next(b for b in report.blocks if "货币资金" in b.text)
    node = next(n for n in tree.nodes if n.parent_id and block.block_id in n.source_block_ids)
    retriever = TreeReasoningRetriever(tree, lambda req, nodes: TreeDecision((node.node_id,), "wiring test"))
    sources = tuple(ReferenceSpan(b.document_id, b.block_id, b.page, b.text, b.section) for b in report.blocks)
    expected = next(s for s in sources if s.block_id == block.block_id)
    case = BenchmarkCase(
        "moutai-wiring",
        RetrievalRequest(ScopedRequest("货币资金", 7, top_k=20), query_class="EXACT_PHRASE"),
        (expected,),
        gold_reviewed=False,
    )
    result = FinancialRetrievalBenchmark(sources).run_case(case, StaticRetriever(), retriever)
    assert result["tree"]["found"]
    assert result["tree"]["citation_mismatch_count"] == 0
    assert result["winner"] == "NOT_EVALUATED"
