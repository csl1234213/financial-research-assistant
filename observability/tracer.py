import logging
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from sqlalchemy.orm import Session

from observability.models import AgentSpan, AgentTrace
from storage.database import SessionLocal

logger = logging.getLogger(__name__)


def start_trace(
    thread_id: str = "default",
    tenant_id: Optional[int] = None,
    user_id: Optional[int] = None,
) -> AgentTrace:
    """Create a trace for a tenant-scoped request.

    Anonymous requests (including the legacy public ``tenant_id=0`` sentinel)
    intentionally have no persistence scope. They retain their request id and
    timing for the caller/log stream, but ``finish_trace`` will not attempt an
    invalid foreign-key write. Persisting anonymous traces requires an explicit
    schema and access-control design.
    """

    request_id = str(uuid.uuid4())[:12]
    tenant_scope = tenant_id if tenant_id is not None and tenant_id > 0 else None
    trace = AgentTrace(
        request_id=request_id,
        tenant_id=tenant_scope,
        user_id=user_id,
        thread_id=thread_id,
        status="started",
        started_at=datetime.now(timezone.utc),
    )
    return trace


def finish_trace(
    trace: AgentTrace,
    status: str = "success",
    metadata: Optional[Dict[str, Any]] = None,
    db: Optional[Session] = None,
):
    trace.status = status
    trace.finished_at = datetime.now(timezone.utc)
    if trace.started_at:
        trace.duration_ms = (
            trace.finished_at - trace.started_at
        ).total_seconds() * 1000
    if metadata is not None:
        trace.meta = _merge_metadata(trace.meta, metadata)

    if trace.tenant_id is None:
        trace.meta = _merge_metadata(
            trace.meta,
            {"persistence": "skipped_no_tenant_scope"},
        )
        logger.info(
            "Skipping persistence for anonymous trace request_id=%s",
            trace.request_id,
        )
        return trace

    should_close = db is None
    if db is None:
        db = SessionLocal()
    try:
        db.add(trace)
        db.commit()
        db.refresh(trace)
        return trace
    except Exception:
        logger.exception("Failed to save trace request_id=%s", trace.request_id)
        if db:
            db.rollback()
        trace.meta = _merge_metadata(trace.meta, {"persistence": "failed"})
        return trace
    finally:
        if should_close and db:
            db.close()


def add_span(
    trace: AgentTrace,
    node_name: str,
    status: str = "started",
    duration_ms: Optional[float] = None,
    metadata: Optional[Mapping[str, Any]] = None,
    db: Optional[Session] = None,
) -> AgentSpan:
    """Attach a span to ``trace`` and optionally enlist it in a caller transaction.

    Assigning the relationship (rather than only ``trace_id``) lets SQLAlchemy
    cascade spans created before the trace has an id.  ``finish_trace`` can then
    persist the complete request graph in one transaction.
    """

    span = AgentSpan(
        trace=trace,
        node_name=node_name,
        status=status,
        duration_ms=duration_ms,
        started_at=datetime.now(timezone.utc),
    )
    if status in ("success", "failed"):
        span.finished_at = datetime.now(timezone.utc)
    if metadata is not None:
        span.meta = metadata
    if db is not None:
        db.add(trace)
        db.add(span)
    return span


@contextmanager
def node_span(
    trace: AgentTrace,
    node_name: str,
    metadata: Optional[Mapping[str, Any]] = None,
    db: Optional[Session] = None,
):
    t0 = time.time()
    span = add_span(trace, node_name, status="started", metadata=metadata, db=db)
    try:
        yield span
        span.status = "success"
    except Exception as e:
        span.status = "failed"
        if span.meta:
            span.meta = {**span.meta, "error": str(e)}
        else:
            span.meta = {"error": str(e)}
        raise
    finally:
        span.duration_ms = round((time.time() - t0) * 1000, 2)
        span.finished_at = datetime.now(timezone.utc)
        if db is not None:
            db.add(span)


def _merge_metadata(
    existing: Mapping[str, Any],
    incoming: Mapping[str, Any],
) -> Dict[str, Any]:
    """Preserve earlier trace fields while allowing terminal fields to update."""

    return {**dict(existing), **dict(incoming)}


def get_trace_by_request_id(db: Session, request_id: str) -> Optional[AgentTrace]:
    return db.query(AgentTrace).filter(AgentTrace.request_id == request_id).first()


def get_trace_by_id(db: Session, trace_id: int) -> Optional[AgentTrace]:
    return db.query(AgentTrace).filter(AgentTrace.id == trace_id).first()


def get_trace_detail(db: Session, trace_id: int) -> Optional[Dict[str, Any]]:
    trace = get_trace_by_id(db, trace_id)
    if trace is None:
        return None

    spans = (
        db.query(AgentSpan)
        .filter(AgentSpan.trace_id == trace.id)
        .order_by(AgentSpan.started_at)
        .all()
    )

    return {
        "id": trace.id,
        "request_id": trace.request_id,
        "tenant_id": trace.tenant_id,
        "user_id": trace.user_id,
        "thread_id": trace.thread_id,
        "status": trace.status,
        "started_at": trace.started_at.isoformat() if trace.started_at else None,
        "finished_at": trace.finished_at.isoformat() if trace.finished_at else None,
        "duration_ms": trace.duration_ms,
        "metadata": trace.meta,
        "spans": [
            {
                "id": s.id,
                "node_name": s.node_name,
                "status": s.status,
                "duration_ms": s.duration_ms,
                "metadata": s.meta,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "finished_at": s.finished_at.isoformat() if s.finished_at else None,
            }
            for s in spans
        ],
    }


def get_traces(
    db: Session,
    tenant_id: int,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    traces = (
        db.query(AgentTrace)
        .filter(AgentTrace.tenant_id == tenant_id)
        .order_by(AgentTrace.started_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [
        {
            "id": t.id,
            "request_id": t.request_id,
            "thread_id": t.thread_id,
            "status": t.status,
            "duration_ms": t.duration_ms,
            "started_at": t.started_at.isoformat() if t.started_at else None,
            "spans_count": len(t.spans) if t.spans else 0,
        }
        for t in traces
    ]
