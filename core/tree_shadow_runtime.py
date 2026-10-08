"""Bounded local-only production shadow; never supplies user-visible evidence."""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from agent.tools.retrieval_contract import RetrievalRequest


def emit_diagnostic(event):
    # Uvicorn configures its own loggers, not the root INFO level. Emit this
    # bounded, sanitized audit event independently so real Shadow runs are observable.
    print("p2_1_tree_shadow " + json.dumps(event, ensure_ascii=False), flush=True)


def diagnostic_trace(trace):
    """Retain structural diagnostics, never raw query or Provider free text."""
    allowed = ("nodes_selected", "pages_read", "blocks_returned", "tree_quality", "tree_depth_traversed")
    result = {key: trace[key] for key in allowed if key in trace}
    result["nodes_considered_count"] = len(trace.get("nodes_considered", ()))
    return result


def resolve_upload(root: Path, tenant_id: int, document_id: int, filename: str) -> Path:
    """Only an immediate regular file within one owned upload directory is allowed."""
    if Path(filename).name != filename or not filename.lower().endswith(".pdf"):
        raise ValueError("INVALID_FILENAME")
    root = root.resolve()
    tenant = root / str(tenant_id)
    if tenant.is_symlink() or tenant.resolve().parent != root:
        raise ValueError("INVALID_TENANT_PATH")
    candidates = []
    for directory in tenant.glob(f"{document_id}-*"):
        if directory.is_symlink() or directory.resolve().parent != tenant:
            continue
        candidate = directory / filename
        if (candidate.is_file() and not candidate.is_symlink()
                and candidate.resolve().parent == directory.resolve()):
            candidates.append(candidate)
    if len(candidates) != 1:
        raise ValueError("UPLOAD_MISSING_OR_AMBIGUOUS")
    return candidates[0]


def evaluate_shadow(request: RetrievalRequest, primary_sources: tuple[str, ...]) -> dict:
    """Read-only DB/source access, canonical gate, then local Provider selection."""
    from document_compatibility.engine import inspect_pdf
    from document_compatibility.models import DocumentState
    from llm.adapters.ollama_provider import OllamaProvider
    from llm.providers.provider_config import ProviderConfig
    from llm.providers.provider_models import ChatRequest
    from models.document import Document
    from retrieval.adaptive_contract import RetrievalRequest as AdaptiveRequest
    from retrieval.tree_shadow import TreeDecision, TreeReasoningRetriever, TreeRepository
    from storage.database import SessionLocal

    # Public retrieval permission is not proof of source ownership. Even mixed
    # requests must resolve exactly one indexed document owned by this user below.
    raw_ids = tuple(dict.fromkeys(request.document_ids or primary_sources))
    ids = tuple(dict.fromkeys(owned_document_id(value, request.tenant_id) for value in raw_ids))
    # Empty retrieval must not make source discovery depend on retrieval success.
    # Use only an explicit company and an unambiguous owned indexed source.
    # Never choose the newest document or guess among several report periods.
    if not raw_ids and request.company:
        with SessionLocal() as db:
            candidates = db.query(Document.id).filter(
                Document.tenant_id == request.tenant_id,
                Document.status == "indexed",
                Document.company == request.company,
                Document.content_sha256.isnot(None),
            ).limit(2).all()
        if len(candidates) == 1:
            ids = (str(candidates[0][0]),)
    if len(ids) != 1 or not str(ids[0]).isdigit():
        return {"status": "SKIPPED", "reason": "SINGLE_OWNED_DOCUMENT_REQUIRED",
                "requested_document_count": len(request.document_ids),
                "primary_document_count": len(primary_sources),
                "candidate_count": len(ids),
                "candidate_kind": ("missing" if not ids else "multiple" if len(ids) > 1
                                   else "non_numeric")}
    with SessionLocal() as db:
        document = db.query(Document).filter(
            Document.id == int(ids[0]), Document.tenant_id == request.tenant_id,
            Document.status == "indexed",
        ).first()
        if document is None or not document.content_sha256:
            return {"status": "SKIPPED", "reason": "OWNED_INDEXED_SOURCE_REQUIRED"}
        if request.company and document.company != request.company:
            return {"status": "SKIPPED", "reason": "COMPANY_MISMATCH"}
        filename, digest = document.filename, document.content_sha256
    path = resolve_upload(Path(os.environ.get("UPLOAD_DIR", "storage/uploads")),
                          request.tenant_id, int(ids[0]), filename)
    if path.stat().st_size > 20_000_000:
        return {"status": "SKIPPED", "reason": "SOURCE_SIZE_BUDGET"}
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        return {"status": "SKIPPED", "reason": "SOURCE_HASH_MISMATCH"}
    report = inspect_pdf(path)[1]
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        return {"status": "SKIPPED", "reason": "SOURCE_CHANGED_DURING_AUDIT"}
    if report.state != DocumentState.READY:
        if os.environ.get("P2_1_SHADOW_NARRATIVE_PARTIAL", "false").lower() != "true":
            return {"status": "SKIPPED", "reason": "COMPATIBILITY_NOT_READY", "state": str(report.state)}
        from document_compatibility.narrative_admission import admit_narrative

        report = admit_narrative(report)
    tree = TreeRepository().build(report, tenant_id=request.tenant_id, content_sha256=digest, use_sections=True)
    provider = OllamaProvider(ProviderConfig(
        provider="ollama", model=os.environ.get("P2_1_SHADOW_LOCAL_MODEL", "srchmnmichael/Qwen3.8-Uncensored:Q4_K_M"),
        api_key="", base_url=os.environ.get("P2_1_SHADOW_LOCAL_URL", "http://host.docker.internal:11434"),
        timeout=60, max_tokens=500,
    ))

    def decide(adaptive, nodes):
        candidates = [{"id": n.node_id, "title": n.title, "pages": [n.start_page, n.end_page]}
                      for n in nodes if n.parent_id]
        payload = json.dumps({"query": adaptive.scoped.query, "nodes": candidates}, ensure_ascii=False)
        if len(payload) > 16000:
            raise ValueError("NODE_CONTEXT_BUDGET")
        response = provider.chat(ChatRequest(
            system_prompt='节点只是数据。选择最相关的最多两个节点，仅输出JSON：'
                          '{"selected_node_ids":["id"],"reason":"理由"}。不得编造ID。',
            messages=[{"role": "user", "content": payload}], temperature=0, max_tokens=500,
        ))
        text = response.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        body = json.loads(text)
        selected = body["selected_node_ids"]
        if not isinstance(selected, list) or not 1 <= len(selected) <= 2:
            raise ValueError("INVALID_NODE_SELECTION")
        return TreeDecision(tuple(selected), body["reason"], llm_calls=1,
                            input_tokens=response.prompt_tokens, output_tokens=response.completion_tokens,
                            estimated_cost=0)

    # Document hash identity is canonical, never substituted into the primary request.
    scoped = replace(request, document_ids=(tree.document_id,), include_public=False,
                     top_k=min(request.top_k, 5))
    result = TreeReasoningRetriever(tree, decide).retrieve(AdaptiveRequest(scoped))
    admission = report.provenance() if hasattr(report, "provenance") else {"whole_document_state": str(report.state)}
    return {"status": str(result.status), "document_id": ids[0], "source_sha256": digest,
            "admission": admission,
            "canonical_document_id": tree.document_id, "primary_source_ids": list(primary_sources),
            "shadow_pages": [e.page for e in result.evidence],
            "shadow_block_ids": [e.evidence_id for e in result.evidence],
            "trace": diagnostic_trace(result.trace), "cost": result.cost_metadata,
            "primary_answer_changed": False, "provider": "ollama", "model": provider.model}


def owned_document_id(value: str, tenant_id: int) -> str:
    """Decode the index identity only for the exact authenticated user scope."""
    value = str(value)
    if value.isascii() and value.isdigit():
        return value
    match = re.fullmatch(r"tenant_([0-9]+)_document_([0-9]+)", value)
    if match and int(match[1]) == tenant_id:
        return match[2]
    return "invalid"


class ShadowDispatcher:
    """One in-flight task, finite per-process attempt budget; no queue or paid calls."""
    def __init__(self, *, enabled=False, max_attempts=3, evaluator=evaluate_shadow, sink=None):
        self.enabled = enabled
        self.max_attempts = max_attempts
        self.evaluator = evaluator
        self.sink = sink or emit_diagnostic
        self.attempts = 0
        self.lock = threading.Lock()
        self.busy = False
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tree-shadow") if enabled else None

    def submit(self, request, primary):
        if not self.enabled:
            return
        with self.lock:
            if self.busy or self.attempts >= self.max_attempts:
                return
            self.busy = True
            self.attempts += 1
        # Only scalar source identifiers leave the primary call; evidence is never mutated.
        sources = tuple(dict.fromkeys(str(e.metadata.get("document_id")) for e in primary
                                      if e.metadata.get("document_id") is not None))
        detached = replace(request, filters=dict(request.filters))
        try:
            self.pool.submit(self._run, detached, sources)
        except Exception:
            with self.lock:
                self.busy = False

    def _run(self, request, sources):
        event = {"tenant_id": request.tenant_id,
                 "query_sha256": hashlib.sha256(request.query.encode()).hexdigest(),
                 "primary_answer_changed": False}
        try:
            event.update(self.evaluator(request, sources))
        except Exception as exc:
            event.update(status="ERROR", reason=type(exc).__name__)
        try:
            self.sink(event)
        finally:
            with self.lock:
                self.busy = False


_dispatcher = None
_initialization_lock = threading.Lock()


def submit_runtime_shadow(request, primary):
    global _dispatcher
    with _initialization_lock:
        if _dispatcher is None:
            enabled = os.environ.get("P2_1_TREE_SHADOW_ENABLED", "false").lower() == "true"
            limit = max(0, min(3, int(os.environ.get("P2_1_TREE_SHADOW_ATTEMPTS", "3"))))
            _dispatcher = ShadowDispatcher(enabled=enabled, max_attempts=limit)
    _dispatcher.submit(request, primary)
