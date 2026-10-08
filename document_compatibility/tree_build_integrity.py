"""Build-time full-source structural integrity, never query coverage."""
from document_compatibility.tree_models import DocumentTree, TreeQualityReport


def tree_quality(tree: DocumentTree) -> TreeQualityReport:
    """Validate the entire projection, including nodes not chosen by a query."""
    nodes = {n.node_id: n for n in tree.nodes}
    pages = {p.page for p in tree.report.pages}
    blocks = {b.block_id: b for b in tree.report.blocks}
    errors, invalid, overlap = [], [], []
    if len(nodes) != len(tree.nodes):
        errors.append("DUPLICATE_NODE")
    roots = [n for n in tree.nodes if n.parent_id is None]
    if len(roots) != 1:
        errors.append("INVALID_ROOT_COUNT")
    elif roots[0].level != 0:
        errors.append("INVALID_ROOT_LEVEL")
    covered_pages, covered_blocks = set(), set()
    for node in tree.nodes:
        if node.document_id != tree.document_id:
            errors.append("CROSS_DOCUMENT_NODE")
        if node.start_page not in pages or node.end_page not in pages or node.start_page > node.end_page:
            invalid.append(node.node_id)
        parent = nodes.get(node.parent_id)
        if node.parent_id is not None:
            if parent is None or node.node_id not in parent.child_ids or node.level != parent.level + 1:
                errors.append("INVALID_PARENT")
            elif node.start_page < parent.start_page or node.end_page > parent.end_page:
                invalid.append(node.node_id)
        if len(set(node.child_ids)) != len(node.child_ids):
            errors.append("DUPLICATE_CHILD")
        for child_id in node.child_ids:
            if child_id not in nodes or nodes[child_id].parent_id != node.node_id:
                errors.append("INVALID_CHILD")
        visited, current = set(), node
        while current is not None:
            if current.node_id in visited:
                errors.append("CYCLE")
                break
            visited.add(current.node_id)
            current = nodes.get(current.parent_id)
        for block_id in node.source_block_ids:
            block = blocks.get(block_id)
            if block is None or block.document_id != tree.document_id:
                errors.append("MISSING_SOURCE_BLOCK")
            elif not node.start_page <= block.page <= node.end_page:
                errors.append("BLOCK_OUTSIDE_NODE_RANGE")
            else:
                covered_blocks.add(block_id)
        if node.parent_id is not None and node.node_id not in invalid:
            covered_pages.update(p for p in pages if node.start_page <= p <= node.end_page)
    # Ancestor nesting is legitimate; disjoint source blocks on the same page are also legitimate.
    for index, left in enumerate(tree.nodes):
        for right in tree.nodes[index + 1 :]:
            if left.parent_id is not None and left.parent_id == right.parent_id:
                if set(left.source_block_ids) & set(right.source_block_ids):
                    overlap.append((left.node_id, right.node_id))
    orphan = tuple(sorted(pages - covered_pages))
    section_pages = {
        p
        for n in tree.nodes
        if n.level == 1 and not n.title.startswith("Page ")
        for p in pages
        if n.start_page <= p <= n.end_page
    }
    quality = (
        "INVALID"
        if errors or invalid or overlap or orphan or covered_blocks != set(blocks)
        else ("MEDIUM" if tree.source_type == "LAYOUT" else "LOW")
    )
    return TreeQualityReport(
        len(nodes),
        max((n.level for n in tree.nodes), default=0),
        len(section_pages) / len(pages) if pages else 0,
        len(covered_pages) / len(pages) if pages else 0,
        orphan,
        len(covered_blocks) / len(blocks) if blocks else 0,
        sum(bool(n.summary) for n in tree.nodes) / len(nodes) if nodes else 0,
        tuple(invalid),
        tuple(overlap),
        tuple(sorted(set(errors))),
        quality,
    )



class TreeBuildIntegrityEvaluator:
    """Evaluate unchanged full-document build invariants."""

    def evaluate(self, artifact: DocumentTree) -> TreeQualityReport:
        return tree_quality(artifact)
