"""Source-backed isolated query-time tree shadow execution."""
from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Callable

from document_compatibility.narrative_admission import NarrativeAdmission
from document_compatibility.tree_artifact_builder import TreeArtifactBuilder as TreeRepository  # noqa: F401
from document_compatibility.tree_build_integrity import tree_quality

# Compatibility exports delegate to the sole authoritative build implementation.
from document_compatibility.tree_models import DocumentTree, TreeNode, TreeQualityReport  # noqa: F401
from retrieval.adaptive_contract import Evidence, RetrievalMode, RetrievalRequest, RetrievalResult, RetrievalStatus
from retrieval.tree_materialization import select_source_blocks


@dataclass(frozen=True)
class TreeDecision:
    selected_node_ids: tuple[str, ...]
    reason: str
    need_deeper_search: bool = False
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float | None = None

    def __post_init__(self):
        if not isinstance(self.selected_node_ids, tuple) or not all(
            isinstance(node_id, str) and node_id for node_id in self.selected_node_ids
        ):
            raise ValueError("decision requires explicit node identities")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("decision reason required")
        if not isinstance(self.need_deeper_search, bool):
            raise ValueError("need_deeper_search must be boolean")
        for value in (self.llm_calls, self.input_tokens, self.output_tokens):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("invalid decision usage")


class TreeReasoningRetriever:
    def __init__(
        self,
        tree: DocumentTree,
        decision: Callable[[RetrievalRequest, tuple[TreeNode, ...]], TreeDecision],
        *,
        max_rounds: int = 4,
    ):
        if not isinstance(max_rounds, int) or isinstance(max_rounds, bool) or not 1 <= max_rounds <= 8:
            raise ValueError("tree traversal rounds must be bounded")
        self.tree, self.decision = tree, decision
        self.max_rounds = max_rounds

    def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        start = perf_counter()
        tree, scoped = self.tree, request.scoped
        if tree_quality(tree).tree_quality == "INVALID":
            raise ValueError("invalid tree projection")
        if scoped.tenant_id != tree.tenant_id:
            raise ValueError("tree tenant mismatch")
        if scoped.document_ids and tree.document_id not in scoped.document_ids:
            raise ValueError("tree document mismatch")
        decision = self.decision(request, tree.nodes)
        if not isinstance(decision, TreeDecision):
            raise ValueError("tree decision must be structured")
        nodes = {n.node_id: n for n in tree.nodes}
        rounds = [decision]
        considered = list(nodes)
        while decision.need_deeper_search:
            if any(node_id not in nodes for node_id in decision.selected_node_ids):
                raise ValueError("hallucinated tree node")
            children = tuple(nodes[c] for node_id in decision.selected_node_ids for c in nodes[node_id].child_ids)
            if not children:
                break
            if len(rounds) >= self.max_rounds:
                raise ValueError("tree traversal budget exceeded")
            decision = self.decision(request, children)
            if not isinstance(decision, TreeDecision):
                raise ValueError("tree decision must be structured")
            allowed = {child.node_id for child in children}
            if any(node_id not in allowed for node_id in decision.selected_node_ids):
                raise ValueError("tree traversal escaped selected branch")
            considered.extend(child.node_id for child in children)
            rounds.append(decision)
        blocks = {b.block_id: b for b in tree.report.blocks}
        selected = []
        block_nodes = {}
        for node_id in decision.selected_node_ids:
            if node_id not in nodes:
                raise ValueError("hallucinated tree node")
            node = nodes[node_id]
            if node.document_id != tree.document_id or node.start_page < 1 or node.end_page < node.start_page:
                raise ValueError("invalid node source boundary")
            for block_id in node.source_block_ids:
                block = blocks.get(block_id)
                if block is None or not node.start_page <= block.page <= node.end_page:
                    raise ValueError("tree source block missing or out of range")
                if block_id not in selected and block.text.strip():
                    selected.append(block_id)
                block_nodes.setdefault(block_id, []).append(node_id)
        materialized, coverage, selection_trace = select_source_blocks(request, blocks, selected)
        evidence = []
        for block_id in materialized:
            block = blocks[block_id]
            node_ids = sorted(set(block_nodes[block_id]))
            path = []
            current = nodes[node_ids[0]]
            while current is not None:
                if current.node_id in path:
                    raise ValueError("tree ancestry cycle")
                path.append(current.node_id)
                current = nodes.get(current.parent_id)
            path.reverse()
            metadata = {
                "tenant_id": tree.tenant_id,
                "document_id": tree.document_id,
                "chunk_id": block_id,
                "page": block.page,
                "bbox": block.bbox,
                "source_block_ids": [block_id],
                "content_sha256": tree.content_sha256,
                "parser_version": block.parser_version,
                "source_ids": list(block.source_ids),
                "recovery_provenance": [vars(p) for p in block.provenance],
                "tree_schema_version": tree.schema_version,
                "tree_builder_version": tree.builder_version,
                "tree_policy_version": tree.policy_version,
                "document_version": tree.content_sha256,
                "section": block.section,
                "node_id": node_ids[0],
                "node_ids": node_ids,
                "node_path": path,
                "section_path": [nodes[i].title for i in path],
                "reading_order": block.reading_order,
                "source_locator": {"page": block.page, "bbox": block.bbox, "block_id": block_id},
            }
            if isinstance(tree.report, NarrativeAdmission):
                metadata.update(tree.report.provenance())
            evidence.append(
                Evidence(
                    block_id,
                    "TREE_PAGE",
                    tree.document_id,
                    block.text,
                    RetrievalMode.TREE,
                    block.source,
                    tree.document_id,
                    page=block.page,
                    bbox=block.bbox,
                    source_locator=metadata["source_locator"],
                    source_block_ids=(block_id,),
                    provenance=metadata,
                    section=block.section,
                    citation={"document_id": tree.document_id, "page": block.page},
                )
            )
        return RetrievalResult(
            RetrievalStatus.PARTIAL
            if len(selected) > scoped.top_k
            else (RetrievalStatus.FOUND if evidence else RetrievalStatus.NOT_FOUND),
            RetrievalMode.TREE,
            tuple(evidence),
            coverage=coverage,
            latency_ms=(perf_counter() - start) * 1000,
            cost_metadata={
                "llm_calls": sum(r.llm_calls for r in rounds),
                "estimated_cost": sum(r.estimated_cost for r in rounds)
                if all(r.estimated_cost is not None for r in rounds)
                else None,
                "input_tokens": sum(r.input_tokens for r in rounds),
                "output_tokens": sum(r.output_tokens for r in rounds),
            },
            trace={
                **selection_trace,
                "candidate_node_ids": list(decision.selected_node_ids),
                "query": scoped.query,
                "nodes_considered": list(dict.fromkeys(considered)),
                "traversal_rounds": [
                    {
                        "selected_node_ids": list(r.selected_node_ids),
                        "reason": r.reason,
                        "need_deeper_search": r.need_deeper_search,
                    }
                    for r in rounds
                ],
                "nodes_selected": list(decision.selected_node_ids),
                "reason": decision.reason,
                "pages_read": sorted({e.page for e in evidence}),
                "blocks_returned": len(evidence),
                "tree_quality": tree.quality,
                "need_deeper_search": decision.need_deeper_search,
                "root_nodes_inspected": [n.node_id for n in tree.nodes if n.parent_id is None],
                "tree_depth_traversed": max((nodes[i].level for i in decision.selected_node_ids), default=0),
            },
        )


def run_shadow(primary: RetrievalResult, request: RetrievalRequest, shadow: TreeReasoningRetriever):
    """Return original primary by identity, even when shadow fails."""
    if request.query_class == "EXACT_FACT":
        return primary, None
    try:
        result = shadow.retrieve(request)
    except Exception as exc:
        result = RetrievalResult(RetrievalStatus.ERROR, RetrievalMode.TREE, fallback_reason=type(exc).__name__)
    return primary, result
