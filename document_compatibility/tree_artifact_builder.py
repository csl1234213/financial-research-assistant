"""Authoritative tree artifact builder shared by ingestion and legacy APIs."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

from document_compatibility.models import CompatibilityReport, DocumentState
from document_compatibility.narrative_admission import NarrativeAdmission
from document_compatibility.tree_build_integrity import tree_quality
from document_compatibility.tree_models import DocumentTree, TreeNode


class TreeArtifactBuilder:
    """In-memory test repository; cache identity includes source policy and tenant."""

    def __init__(self, artifact_directory: Path | None = None):
        self.cache: dict[tuple, DocumentTree] = {}
        self.build_count = 0
        self.artifact_directory = artifact_directory

    def build(
        self, report: CompatibilityReport | NarrativeAdmission,
        *, tenant_id: int, content_sha256: str, use_sections: bool = False
    ) -> DocumentTree:
        narrative = isinstance(report, NarrativeAdmission)
        if narrative:
            report.validate()
        if (
            (not narrative and report.state != DocumentState.READY)
            or not content_sha256
            or isinstance(tenant_id, bool)
            or not isinstance(tenant_id, int)
            or tenant_id < 0
        ):
            raise ValueError("tree requires a ready document and explicit source version")
        policy = "section-tree-v1" if use_sections else "page-tree-v1"
        source_digest = hashlib.sha256(
            json.dumps(
                [(b.block_id, b.page, b.text, b.section, b.source_ids) for b in report.blocks],
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()
        key = (tenant_id, report.document_id, content_sha256, report.parsed_with_policy_version, policy, source_digest)
        if key in self.cache:
            return self.cache[key]
        artifact = None
        if self.artifact_directory is not None:
            artifact = self.artifact_directory / (hashlib.sha256(repr(key).encode()).hexdigest() + ".json")
            if artifact.exists():
                payload = json.loads(artifact.read_text(encoding="utf-8"))
                if payload.get("key") != list(key) or payload.get("schema_version") != "1":
                    raise ValueError("tree artifact version mismatch")
                recovered_nodes = tuple(
                    TreeNode(
                        **{
                            **item,
                            "source_block_ids": tuple(item["source_block_ids"]),
                            "child_ids": tuple(item["child_ids"]),
                            "provenance": tuple(item.get("provenance", ())),
                        }
                    )
                    for item in payload["nodes"]
                )
                recovered = DocumentTree(
                    tenant_id,
                    report.document_id,
                    content_sha256,
                    recovered_nodes,
                    report,
                    policy_version=policy,
                    source_type=payload["source_type"],
                )
                quality = tree_quality(recovered)
                if quality.tree_quality == "INVALID":
                    raise ValueError("invalid cached tree artifact")
                recovered = replace(recovered, quality=quality.tree_quality)
                self.cache[key] = recovered
                return recovered
        pages = sorted({p.page for p in report.pages})
        if not pages or pages[0] < 1:
            raise ValueError("invalid page inventory")
        blocks = {b.block_id: b for b in report.blocks}
        if len(blocks) != len(report.blocks):
            raise ValueError("duplicate source block identity")
        if any(b.document_id != report.document_id or b.page not in pages for b in blocks.values()):
            raise ValueError("source block outside document/page inventory")
        children = tuple(f"{report.document_id}:page:{page}" for page in pages)
        root = TreeNode(
            f"{report.document_id}:root",
            report.document_id,
            None,
            "Document",
            0,
            pages[0],
            pages[-1],
            tuple(blocks),
            children,
        )
        nodes = [root]
        for page, node_id in zip(pages, children):
            ids = tuple(b.block_id for b in report.blocks if b.page == page)
            nodes.append(TreeNode(node_id, report.document_id, root.node_id, f"Page {page}", 1, page, page, ids))
        if use_sections and any(b.section.strip() for b in report.blocks):
            groups = []
            for block in report.blocks:
                title = block.section.strip() or f"Page {block.page}"
                if not groups or groups[-1][0] != title:
                    groups.append((title, []))
                groups[-1][1].append(block)
            section_nodes = []
            for index, (title, group) in enumerate(groups):
                section_nodes.append(
                    TreeNode(
                        f"{report.document_id}:section:{index}",
                        report.document_id,
                        root.node_id,
                        title,
                        1,
                        min(b.page for b in group),
                        max(b.page for b in group),
                        tuple(b.block_id for b in group),
                    )
                )
            missing = [n for n in nodes[1:] if not n.source_block_ids]
            nodes = [
                replace(root, child_ids=tuple(n.node_id for n in (*section_nodes, *missing))),
                *section_nodes,
                *missing,
            ]
        tree = DocumentTree(
            tenant_id,
            report.document_id,
            content_sha256,
            tuple(nodes),
            report,
            policy_version=policy,
            source_type="LAYOUT"
            if use_sections and len(nodes) > 1 and any(b.section.strip() for b in report.blocks)
            else "FALLBACK_PAGE_TREE",
        )
        quality = tree_quality(tree)
        if quality.tree_quality == "INVALID":
            raise ValueError(f"invalid tree: {quality.errors}")
        tree = replace(
            tree,
            quality=quality.tree_quality,
            nodes=tuple(
                replace(
                    n,
                    provenance=tuple(
                        sorted({source for block_id in n.source_block_ids for source in blocks[block_id].source_ids})
                    ),
                )
                for n in tree.nodes
            ),
        )
        if artifact is not None:
            from dataclasses import asdict

            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(
                json.dumps(
                    {
                        "key": list(key),
                        "schema_version": tree.schema_version,
                        "builder_version": tree.builder_version,
                        "summary_model": tree.summary_model,
                        "source_type": tree.source_type,
                        "nodes": [asdict(n) for n in tree.nodes],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        self.cache[key] = tree
        self.build_count += 1
        return tree
