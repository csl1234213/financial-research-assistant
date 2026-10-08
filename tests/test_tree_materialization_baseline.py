"""Frozen correct-node diagnostic over retained, content-addressed source artifacts.

This is a baseline receipt, not selector quality or closure acceptance.
"""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from agent.tools.retrieval_contract import RetrievalRequest as ScopedRequest
from document_compatibility.serialization import compatibility_report_from_dict
from document_compatibility.tree_models import DocumentTree, TreeNode
from retrieval.adaptive_contract import RetrievalRequest

SOURCE = "474905deeaf0f875fc0a1b097a626c0c7852c427faadc5d7fc7816cbf45ea288"
TREE = "c581f625d6d49252283fa4adedaee74f476098bfcb404b08aef4a7da4b57b036"
QUALITY = "f6735ac9ab7b3944dea564a43683c9adde9391317b8006df02f53aee5f6ece02"
EXPECTED = "46a648eb37d219014c5e73261d8f2888"
SEALED_BASELINE = "ac968d5b29f7b2c95ff343d2f90fe3dbca9e0264"


@pytest.fixture
def baseline_engine():
    source = subprocess.run(
        ["git", "show", f"{SEALED_BASELINE}:retrieval/tree_shadow.py"],
        cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True, text=True,
    ).stdout
    namespace = {"__name__": __name__}
    exec(compile(source, "sealed-tree-shadow-baseline", "exec"), namespace)
    return namespace["TreeReasoningRetriever"], namespace["TreeDecision"]


@pytest.fixture(scope="module")
def retained_tree():
    location = os.getenv("RC1_TREE_RETAINED_ARTIFACT_DIR")
    if not location:
        pytest.skip("Explicit retained artifact required; synthetic data is not a substitute")
    directory = Path(location)
    assert directory.name == SOURCE

    def read(digest):
        content = (directory / digest).read_bytes()
        assert hashlib.sha256(content).hexdigest() == digest
        return json.loads(content)

    payload, quality = read(TREE), read(QUALITY)
    report = compatibility_report_from_dict(quality["compatibility"])
    nodes = tuple(TreeNode(**{
        **node,
        "source_block_ids": tuple(node["source_block_ids"]),
        "child_ids": tuple(node["child_ids"]),
        "provenance": tuple(node["provenance"]),
    }) for node in payload["nodes"])
    return DocumentTree(1, report.document_id, SOURCE, nodes, report)


def test_correct_node_source_order_truncation_baseline(retained_tree, baseline_engine, record_property):
    TreeReasoningRetriever, TreeDecision = baseline_engine
    node = next(n for n in retained_tree.nodes if n.node_id.endswith(":page:8"))
    assert len(node.source_block_ids) == 22
    assert node.source_block_ids.index(EXPECTED) == 13
    request = RetrievalRequest(ScopedRequest(
        query="说明贵州茅台的主要业务", tenant_id=1,
        document_ids=(retained_tree.document_id,), top_k=5,
    ))
    result = TreeReasoningRetriever(retained_tree, lambda *_: TreeDecision(
        (node.node_id,), "Correct node injected; no provider selection",
    )).retrieve(request)
    present = any(EXPECTED in item.source_block_ids for item in result.evidence)
    record_property("EXPECTED_BLOCK_PRESENT", present)
    record_property("RETURNED_BLOCK_COUNT", len(result.evidence))
    record_property("PROVIDER_CALLS", result.cost_metadata["llm_calls"])
    assert not present
    assert len(result.evidence) == 5
    assert result.coverage.complete is None


def test_cross_node_source_order_starvation_baseline(retained_tree, baseline_engine, record_property):
    TreeReasoningRetriever, TreeDecision = baseline_engine
    nodes = tuple(next(n for n in retained_tree.nodes if n.node_id.endswith(f":page:{p}"))
                  for p in (1, 8))
    request = RetrievalRequest(ScopedRequest(
        query="说明贵州茅台的主要业务", tenant_id=1, top_k=5,
    ))
    result = TreeReasoningRetriever(retained_tree, lambda *_: TreeDecision(
        tuple(n.node_id for n in nodes), "Two selected nodes; no provider",
    )).retrieve(request)
    record_property("EVIDENCE_PAGES", [item.page for item in result.evidence])
    assert [item.page for item in result.evidence] == [1] * 5
