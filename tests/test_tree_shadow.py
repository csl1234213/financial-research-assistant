import json
from dataclasses import replace
from pathlib import Path

import pytest

from agent.tools.retrieval_contract import RetrievalRequest as ScopedRequest
from document_compatibility.engine import inspect_pdf
from retrieval.adaptive_contract import RetrievalMode, RetrievalRequest, RetrievalResult, RetrievalStatus
from retrieval.tree_shadow import TreeDecision, TreeReasoningRetriever, TreeRepository, run_shadow, tree_quality


@pytest.fixture(scope="module")
def tree():
    fixture = Path(__file__).parent / "fixtures" / "moutai-standard-statements-2025.pdf"
    report = inspect_pdf(fixture)[1]
    repository = TreeRepository()
    result = repository.build(report, tenant_id=7, content_sha256="fixture-version")
    assert repository.build(report, tenant_id=7, content_sha256="fixture-version") is result
    assert repository.build_count == 1
    return result


def request(tenant=7, documents=()):
    return RetrievalRequest(ScopedRequest(query="现金流量", tenant_id=tenant, document_ids=documents))


def test_real_fixture_tree_source_and_shadow_primary(tree):
    node = next(n for n in tree.nodes if n.level == 1 and n.source_block_ids)
    retriever = TreeReasoningRetriever(tree, lambda req, nodes: TreeDecision((node.node_id,), "test selection"))
    result = retriever.retrieve(request())
    assert result.evidence
    sources = {b.block_id: b.text for b in tree.report.blocks}
    assert all(e.text == sources[e.evidence_id] for e in result.evidence)
    assert tree.quality == "LOW" and tree.source_type == "FALLBACK_PAGE_TREE"
    primary = RetrievalResult(RetrievalStatus.NOT_FOUND, RetrievalMode.HYBRID)
    actual, shadow = run_shadow(primary, request(), retriever)
    assert actual is primary and shadow.evidence


@pytest.mark.parametrize("tenant,documents", [(8, ()), (7, ("foreign",))])
def test_tree_isolation(tree, tenant, documents):
    retriever = TreeReasoningRetriever(tree, lambda req, nodes: TreeDecision((), "empty"))
    with pytest.raises(ValueError, match="mismatch"):
        retriever.retrieve(request(tenant, documents))


def test_hallucination_rejected_and_failure_does_not_change_primary(tree):
    retriever = TreeReasoningRetriever(tree, lambda req, nodes: TreeDecision(("invented",), "bad"))
    with pytest.raises(ValueError, match="hallucinated"):
        retriever.retrieve(request())
    primary = RetrievalResult(RetrievalStatus.FOUND, RetrievalMode.FACT)
    actual, shadow = run_shadow(primary, request(), retriever)
    assert actual is primary and shadow.status == RetrievalStatus.ERROR
    assert run_shadow(primary, replace(request(), query_class="EXACT_FACT"), retriever) == (primary, None)


def test_summary_never_becomes_final_evidence(tree):
    node = next(n for n in tree.nodes if n.level == 1 and n.source_block_ids)
    edited = replace(tree, nodes=tuple(replace(n, summary="invented profit 999 billion") for n in tree.nodes))
    result = TreeReasoningRetriever(edited, lambda req, nodes: TreeDecision((node.node_id,), "test")).retrieve(
        request()
    )
    assert all("invented profit" not in ev.text for ev in result.evidence)


def test_real_section_projection_has_complete_source_coverage(tree):
    section_tree = TreeRepository().build(tree.report, tenant_id=7, content_sha256="fixture-version", use_sections=True)
    quality = tree_quality(section_tree)
    assert quality.page_coverage == 1 and quality.source_block_coverage == 1
    assert not quality.orphan_pages and not quality.invalid_ranges and not quality.errors
    assert quality.tree_quality in {"LOW", "MEDIUM"}
    assert section_tree.policy_version == "section-tree-v1"


@pytest.mark.parametrize("defect", ["range", "source", "cycle", "duplicate", "document"])
def test_entire_tree_is_validated_even_for_unselected_node(tree, defect):
    node = tree.nodes[1]
    if defect == "range":
        changed = replace(node, end_page=9999)
    elif defect == "source":
        changed = replace(node, source_block_ids=("missing",))
    elif defect == "cycle":
        changed = replace(node, parent_id=node.node_id)
    elif defect == "document":
        changed = replace(node, document_id="foreign")
    else:
        changed = node
    nodes = (*tree.nodes, changed) if defect == "duplicate" else (tree.nodes[0], changed, *tree.nodes[2:])
    bad = replace(tree, nodes=nodes)
    assert tree_quality(bad).tree_quality == "INVALID"
    with pytest.raises(ValueError, match="invalid tree"):
        TreeReasoningRetriever(bad, lambda req, nodes: TreeDecision((), "empty")).retrieve(request())


def test_decision_usage_is_recorded_not_assumed_zero(tree):
    result = TreeReasoningRetriever(
        tree,
        lambda req, nodes: TreeDecision(
            (), "mock usage", llm_calls=2, input_tokens=120, output_tokens=15, estimated_cost=0.01
        ),
    ).retrieve(request())
    assert result.cost_metadata == {"llm_calls": 2, "input_tokens": 120, "output_tokens": 15, "estimated_cost": 0.01}


def test_unstructured_decision_rejected(tree):
    with pytest.raises(ValueError, match="structured"):
        TreeReasoningRetriever(tree, lambda req, nodes: "go to risks").retrieve(request())


@pytest.mark.parametrize("ids,reason,calls", [("node", "reason", 0), (("node",), "", 0), ((), "ok", -1)])
def test_invalid_decision_schema(ids, reason, calls):
    with pytest.raises(ValueError):
        TreeDecision(ids, reason, llm_calls=calls)


def test_json_tree_cache_survives_repository_restart_and_source_version_changes(tree, tmp_path):
    repository = TreeRepository(tmp_path)
    first = repository.build(tree.report, tenant_id=7, content_sha256="v1")
    fresh = TreeRepository(tmp_path)
    again = fresh.build(tree.report, tenant_id=7, content_sha256="v1")
    assert again.nodes == first.nodes and fresh.build_count == 0
    fresh.build(tree.report, tenant_id=7, content_sha256="v2")
    fresh.build(tree.report, tenant_id=8, content_sha256="v1")
    fresh.build(tree.report, tenant_id=7, content_sha256="v1", use_sections=True)
    assert fresh.build_count == 3 and len(list(tmp_path.glob("*.json"))) == 4


def test_cached_hallucinated_node_rejected(tree, tmp_path):
    TreeRepository(tmp_path).build(tree.report, tenant_id=7, content_sha256="v1")
    artifact = next(tmp_path.glob("*.json"))
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["nodes"][1]["source_block_ids"] = ["hallucinated"]
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid cached"):
        TreeRepository(tmp_path).build(tree.report, tenant_id=7, content_sha256="v1")


def test_recursive_decision_reads_only_selected_children_and_aggregates_usage(tree):
    calls = []

    def decide(req, nodes):
        calls.append(nodes)
        if len(calls) == 1:
            return TreeDecision((tree.nodes[0].node_id,), "root", True, llm_calls=1, input_tokens=10)
        child = next(n for n in nodes if n.source_block_ids)
        return TreeDecision((child.node_id,), "child", llm_calls=1, input_tokens=5)

    result = TreeReasoningRetriever(tree, decide).retrieve(request())
    assert result.cost_metadata["llm_calls"] == 2
    assert result.cost_metadata["input_tokens"] == 15
    assert all(n.parent_id == tree.nodes[0].node_id for n in calls[1])
    assert len(result.trace["traversal_rounds"]) == 2


def test_recursive_decision_cannot_escape_branch(tree):
    calls = []

    def decide(req, nodes):
        calls.append(nodes)
        return TreeDecision((tree.nodes[0].node_id,), "root", len(calls) == 1)

    with pytest.raises(ValueError, match="escaped"):
        TreeReasoningRetriever(tree, decide).retrieve(request())
