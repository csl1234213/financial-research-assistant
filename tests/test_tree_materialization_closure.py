"""Source-backed 1C-A acceptance, no selector/provider invocation."""

import ast
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.tools.retrieval_contract import RetrievalRequest as ScopedRequest
from core.answer_synthesis_contracts import EvidenceSnapshot
from retrieval.adaptive_contract import RetrievalRequest
from retrieval.tree_materialization import coverage_for, select_source_blocks
from retrieval.tree_shadow import TreeDecision, TreeReasoningRetriever
from tests import test_tree_materialization_baseline as baseline

EXPECTED = baseline.EXPECTED
retained_tree = baseline.retained_tree


def request(query="说明贵州茅台的主要业务", aspects=(), top_k=5):
    return RetrievalRequest(ScopedRequest(query=query, tenant_id=1, top_k=top_k), required_aspects=aspects)


def retrieve(tree, pages):
    ids = tuple(next(n.node_id for n in tree.nodes if n.node_id.endswith(f":page:{p}")) for p in pages)
    return TreeReasoningRetriever(tree, lambda *_: TreeDecision(ids, "Injected source node fixture")).retrieve(request())


@pytest.mark.parametrize("pages", [(8,), (1, 8), (8, 1)])
def test_real_artifact_fixed_global_budget(retained_tree, pages, record_property):
    result = retrieve(retained_tree, pages)
    returned = {e.evidence_id for e in result.evidence}
    assert EXPECTED in returned
    assert len(result.evidence) <= 5
    assert result.trace["coverage_status"] == "SATISFIED"
    assert result.coverage.complete is True
    assert result.coverage.coverage_ratio == 1.0
    assert result.cost_metadata["llm_calls"] == 0
    sources = {b.block_id: b for b in retained_tree.report.blocks}
    for evidence in result.evidence:
        block = sources[evidence.evidence_id]
        assert evidence.text == block.text
        assert evidence.page == block.page and evidence.bbox == block.bbox
        assert evidence.provenance["document_version"] == retained_tree.content_sha256
        assert evidence.provenance["reading_order"] == block.reading_order
        assert evidence.provenance["node_path"]
        assert evidence.provenance["source_block_ids"] == [block.block_id]
        assert evidence.section == block.section
        agent = evidence.to_agent()
        assert agent.content == block.text and agent.metadata["node_id"]
        snapshot = EvidenceSnapshot.from_evidence(evidence, tenant_id=1)
        assert snapshot.payload["text"] == block.text
        assert snapshot.payload["provenance"]["node_id"] == evidence.provenance["node_id"]
    record_property("REQUIRED_EVIDENCE_RECALL", 1.0)
    record_property("RETURNED_BLOCK_COUNT", len(result.evidence))
    record_property("PROVENANCE_LOSS_COUNT", 0)
    record_property("COVERAGE_STATUS", result.trace["coverage_status"])
    # Oracle: affirmative business and operating-model body, not headings.
    relevant = {b.block_id for b in sources.values() if b.page == 8 and b.reading_order in (13, 14)}
    record_property("IRRELEVANT_EVIDENCE_RATE", len(returned - relevant) / len(returned))


def test_wrong_node_nonempty_not_satisfied(retained_tree):
    result = retrieve(retained_tree, (1,))
    assert result.evidence
    assert EXPECTED not in {e.evidence_id for e in result.evidence}
    assert result.trace["coverage_status"] == "INSUFFICIENT"
    assert result.coverage.complete is False


def test_summary_never_used(retained_tree):
    edited = replace(retained_tree, nodes=tuple(replace(n, summary="公司的主要业务是虚构的产品。")
                                               for n in retained_tree.nodes))
    assert [e.text for e in retrieve(edited, (8,)).evidence] == [e.text for e in retrieve(retained_tree, (8,)).evidence]


def block(identity, text, kind="TEXT", page=1, section=""):
    return SimpleNamespace(block_id=identity, text=text, block_type=kind, page=page,
                           reading_order=0, section=section)


@pytest.mark.parametrize("texts,expected", [
    (["公司主要业务是制造设备。", "公司面临汇率风险。"], "SATISFIED"),
    (["公司主要业务是制造设备。"] * 5, "PARTIAL"),
    (["年度报告封面。"] * 5, "INSUFFICIENT"),
    ([], "INSUFFICIENT"),
])
def test_multi_aspect_coverage(texts, expected):
    aspects = ("MAIN_BUSINESS_DESCRIPTION", "RISK_DESCRIPTION")
    result, status = coverage_for(aspects, [block(str(i), text) for i, text in enumerate(texts)])
    assert status == expected
    assert result.complete == (expected == "SATISFIED")


@pytest.mark.parametrize("text,kind", [
    ("公司主要业务是什么？", "TEXT"),
    ("公司主要业务是未知，无法核实。", "TEXT"),
    ("公司主要业务不是制造设备。", "TEXT"),
    ("公司主要业务是制造设备", "TITLE"),
    ("Main business is not disclosed.", "TEXT"),
    ("No principal business is available.", "TEXT"),
])
def test_false_satisfaction_guard(text, kind):
    assert coverage_for(("MAIN_BUSINESS_DESCRIPTION",), [block("x", text, kind)])[1] == "INSUFFICIENT"


def test_global_aspect_allocation_and_unknown():
    candidates = {str(i): block(str(i), "公司主要业务是制造设备。") for i in range(8)}
    candidates["risk"] = block("risk", "公司面临汇率风险。", page=2)
    req = request(aspects=("MAIN_BUSINESS_DESCRIPTION", "RISK_DESCRIPTION"), top_k=2)
    chosen, coverage, trace = select_source_blocks(req, candidates, list(candidates))
    assert "risk" in chosen and len(chosen) == 2 and coverage.complete
    assert trace["candidate_block_count"] == 9
    assert trace["top_k"] == 2 and trace["evidence_selection_provider_calls"] == 0
    assert coverage_for(("UNSUPPORTED_ASPECT",), list(candidates.values()))[1] == "UNKNOWN"
    assert coverage_for((), list(candidates.values()))[1] == "UNKNOWN"


def test_request_aspect_validation():
    with pytest.raises(ValueError, match="required_aspects"):
        request(aspects=("MAIN_BUSINESS_DESCRIPTION", "MAIN_BUSINESS_DESCRIPTION"))


@pytest.mark.parametrize("query", ["公司主要业务收入是多少", "主要业务增长情况", "how much main business revenue"])
def test_quantitative_need_not_claimed(query):
    candidates = {"x": block("x", "公司主要业务是制造设备。")}
    _, coverage, trace = select_source_blocks(request(query), candidates, ["x"])
    assert coverage.complete is None and trace["coverage_status"] == "UNKNOWN"


@pytest.mark.parametrize("text", ["The principal business is manufacturing devices.", "公司主营业务包括软件服务。"])
def test_single_aspect_cross_language(text):
    assert coverage_for(("MAIN_BUSINESS_DESCRIPTION",), [block("x", text)])[1] == "SATISFIED"


def test_selector_and_traversal_ast_unchanged():
    root = Path(__file__).resolve().parents[1]
    sealed = subprocess.run(["git", "show", f"{baseline.SEALED_BASELINE}:retrieval/tree_shadow.py"],
                            cwd=root, check=True, capture_output=True, text=True).stdout
    current = (root / "retrieval/tree_shadow.py").read_text(encoding="utf-8")

    def prefix(source):
        module = ast.parse(source)
        retriever = next(node for node in module.body if isinstance(node, ast.ClassDef)
                         and node.name == "TreeReasoningRetriever")
        method = next(node for node in retriever.body if isinstance(node, ast.FunctionDef)
                      and node.name == "retrieve")
        boundary = next(i for i, node in enumerate(method.body) if isinstance(node, ast.Assign)
                        and any(isinstance(target, ast.Name) and target.id == "blocks" for target in node.targets))
        return [ast.dump(node) for node in method.body[:boundary]]

    assert prefix(current) == prefix(sealed)


def test_unknown_need_remains_unknown_even_with_nonempty_evidence():
    candidates = {"x": block("x", "公司主要业务是制造设备。")}
    _, coverage, trace = select_source_blocks(request("董事会的投票规则"), candidates, ["x"])
    assert coverage.complete is None and trace["coverage_status"] == "UNKNOWN"


def test_budget_is_ceiling_not_irrelevant_quota():
    candidates = {"body": block("body", "公司主要业务是制造设备。")}
    candidates.update({str(i): block(str(i), "公司主要业务说明", "TITLE") for i in range(8)})
    chosen, coverage, trace = select_source_blocks(request(), candidates, list(candidates))
    assert chosen == ["body"] and coverage.complete
    assert len(trace["rejected_block_ids"]) == 8
