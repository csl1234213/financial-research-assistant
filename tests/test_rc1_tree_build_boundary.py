"""Real fixture golden equivalence and query-free runtime build gate."""
import hashlib
import inspect
import json
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from document_compatibility.engine import inspect_pdf
from document_compatibility.tree_artifact_builder import TreeArtifactBuilder
from document_compatibility.tree_build_integrity import TreeBuildIntegrityEvaluator
from tasks.ingestion_tree_stage import FinancialTreeStage
from tests.formal_ingestion_test_harness import SOURCE, current_time, formal, setup_real  # noqa: F401


@pytest.fixture(scope="module")
def report():
    return inspect_pdf(Path(__file__).parent / "fixtures/moutai-standard-statements-2025.pdf")[1]


@pytest.mark.parametrize("sections,count,digest", [
    (False, 72, "9e0554dbe21ef32cf5ccc086838db67a7511be9a879fc73d04b11d911c873dc7"),
    (True, 189, "5cd5485eaafa3cb9a6478dcd7815c4eea8301bb26f6610e39ec04f0ca0254e5c"),
])
def test_pre_refactor_real_fixture_equivalence(report, sections, count, digest):
    # Captured by executing the original pre-refactor implementation, not
    # calculated from the new builder or the legacy compatibility alias.
    tree = TreeArtifactBuilder().build(report, tenant_id=7, content_sha256="fixture-version", use_sections=sections)
    projection = json.dumps([asdict(node) for node in tree.nodes], sort_keys=True).encode()
    assert len(tree.nodes) == count
    assert hashlib.sha256(projection).hexdigest() == digest
    audit = TreeBuildIntegrityEvaluator().evaluate(tree)
    assert audit.source_block_coverage == audit.page_coverage == 1
    assert not audit.errors and not audit.invalid_ranges and not audit.orphan_pages
    for node in tree.nodes:
        assert node.provenance == tuple(sorted({source for block in report.blocks
            if block.block_id in node.source_block_ids for source in block.source_ids}))


def test_no_query_required():
    forbidden = {"query", "conversation", "answer_type", "retrieval_request"}
    assert not forbidden.intersection(inspect.signature(TreeArtifactBuilder.build).parameters)
    assert not forbidden.intersection(inspect.signature(TreeBuildIntegrityEvaluator.evaluate).parameters)


def test_fresh_import_without_retrieval_engine_or_answer():
    code = '''
import importlib.abc
import sys
class DenyQueryModules(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('retrieval.', 'core.answer_synthesis', 'api.routers.grounded_answers')):
            raise AssertionError('forbidden build dependency: ' + fullname)
sys.meta_path.insert(0, DenyQueryModules())
import tasks.ingestion_tree_stage
assert 'retrieval.tree_shadow' not in sys.modules
'''
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_missing_source_block_runtime_gate(report, monkeypatch):
    tree = TreeArtifactBuilder().build(report, tenant_id=7, content_sha256="fixture-version")
    missing = report.blocks[0].block_id
    broken = replace(tree, nodes=tuple(replace(node,
        source_block_ids=tuple(block for block in node.source_block_ids if block != missing)) for node in tree.nodes))
    audit = TreeBuildIntegrityEvaluator().evaluate(broken)
    assert audit.tree_quality == "INVALID" and audit.source_block_coverage < 1
    monkeypatch.setattr(TreeArtifactBuilder, "build", lambda *args, **kwargs: broken)
    monkeypatch.setattr("tasks.ingestion_tree_stage.compatibility_report_from_dict", lambda _: report)

    class Store:
        writes = 0

        def read(self, tenant, sha, digest):
            return json.dumps({"schema": "financial-ingestion-quality.v1", "quality_status": "PASS",
                "source_sha256": sha, "parse_artifact_sha256": "parse", "compatibility": {}}).encode()

        def put(self, *args):
            self.writes += 1
            raise AssertionError("incomplete build cannot persist success")

    store = Store()
    lease = SimpleNamespace(stage="BUILDING_TREE", tenant_id=7, source_sha256="fixture-version", document_id=42)
    with pytest.raises(ValueError, match="TREE_INVALID"):
        FinancialTreeStage(store).execute(lease, parse_artifact_sha256="parse", quality_artifact_sha256="quality")
    assert store.writes == 0


def test_incomplete_build_cannot_advance_document_to_ready(formal, tmp_path, monkeypatch):  # noqa: F811
    from tasks.ingestion_stage_executor import IngestionStageExecutor
    ledger, task = setup_real(formal, tmp_path)
    executor = IngestionStageExecutor(ledger, source_resolver=lambda _: SOURCE, clock=current_time)
    for _ in range(3):
        assert executor.run_one(task) == "completed"
    original = TreeArtifactBuilder.build
    injected_builds = []

    def incomplete(self, *args, **kwargs):
        tree = original(self, *args, **kwargs)
        injected_builds.append(tree)
        missing = tree.report.blocks[0].block_id
        return replace(tree, nodes=tuple(replace(node,
            source_block_ids=tuple(block for block in node.source_block_ids if block != missing))
            for node in tree.nodes))

    monkeypatch.setattr(TreeArtifactBuilder, "build", incomplete)
    assert executor.run_one(task) == "failed"
    assert len(injected_builds) == 1  # Failure must be our injection, not an upstream serializer error.
    status = ledger.status(task, 1, 2)
    assert status["status"] == "failed"
    assert "BUILDING_TREE" not in status["completed_stages"]
    with pytest.raises(ValueError):
        ledger.ready_index(task, 1, 2)
