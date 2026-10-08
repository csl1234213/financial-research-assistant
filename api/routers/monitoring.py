from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from core.tenant_context import get_current_tenant
from models.tenant import Tenant
from observability.dashboard import get_monitoring_overview
from observability.metrics import get_agent_metrics
from observability.tracer import get_trace_detail, get_traces
from storage.database import get_db

router = APIRouter(tags=["Monitoring"])


@router.get("/monitoring/overview")
def monitoring_overview(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    period: str = Query(
        default=None,
        description="Period in YYYY-MM format",
    ),
):
    data = get_monitoring_overview(db=db, tenant_id=tenant.id, period=period)
    return data


@router.get("/monitoring/metrics")
def monitoring_metrics(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    period: str = Query(
        default=None,
        description="Period in YYYY-MM format",
    ),
):
    from datetime import datetime, timezone

    since = None
    if period:
        try:
            since = datetime.strptime(period, "%Y-%m").replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    metrics = get_agent_metrics(db=db, tenant_id=tenant.id, since=since)
    return metrics


@router.get("/monitoring/traces")
def monitoring_traces(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    traces = get_traces(db=db, tenant_id=tenant.id, limit=limit, offset=offset)
    return {"traces": traces, "total": len(traces), "limit": limit, "offset": offset}


@router.get("/monitoring/traces/{trace_id}")
def monitoring_trace_detail(
    trace_id: int,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    detail = get_trace_detail(db=db, trace_id=trace_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Trace not found")
    if detail["tenant_id"] != tenant.id:
        raise HTTPException(status_code=404, detail="Trace not found")
    return detail
