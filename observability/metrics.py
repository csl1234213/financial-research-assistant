import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from billing.models import BillingRecord
from observability.models import AgentTrace

logger = logging.getLogger(__name__)

SUCCESSFUL_STATUSES = ("success", "cache_hit", "fallback")
TERMINAL_STATUSES = (*SUCCESSFUL_STATUSES, "failed")


def get_agent_metrics(
    db: Session,
    tenant_id: int,
    since: Optional[datetime] = None,
) -> Dict[str, Any]:
    base_query = db.query(AgentTrace).filter(
        AgentTrace.tenant_id == tenant_id
    )
    if since:
        base_query = base_query.filter(AgentTrace.started_at >= since)

    total_requests = base_query.count()

    success_query = base_query.filter(AgentTrace.status.in_(SUCCESSFUL_STATUSES))
    total_success = success_query.count()

    total_failed = base_query.filter(AgentTrace.status == "failed").count()
    total_cache_hits = base_query.filter(AgentTrace.status == "cache_hit").count()
    total_fallbacks = base_query.filter(AgentTrace.status == "fallback").count()
    total_terminal = base_query.filter(AgentTrace.status.in_(TERMINAL_STATUSES)).count()
    total_in_progress = total_requests - total_terminal

    success_rate = round((total_success / total_terminal * 100), 2) if total_terminal > 0 else 0.0

    avg_latency = (
        db.query(func.avg(AgentTrace.duration_ms))
        .filter(AgentTrace.tenant_id == tenant_id)
    )
    if since:
        avg_latency = avg_latency.filter(AgentTrace.started_at >= since)
    avg_latency = avg_latency.scalar() or 0.0

    billing_query = db.query(
        func.coalesce(func.sum(BillingRecord.amount), 0.0)
    ).filter(BillingRecord.tenant_id == tenant_id)
    if since:
        billing_query = billing_query.filter(BillingRecord.created_at >= since)
    total_cost = round(billing_query.scalar() or 0.0, 6)

    return {
        "total_requests": total_requests,
        "total_success": total_success,
        "total_failed": total_failed,
        "total_cache_hits": total_cache_hits,
        "total_fallbacks": total_fallbacks,
        "total_in_progress": total_in_progress,
        "success_rate": success_rate,
        "avg_latency_ms": round(avg_latency, 2),
        "total_cost": total_cost,
    }


def get_daily_metrics(
    db: Session,
    tenant_id: int,
    days: int = 7,
) -> Dict[str, Any]:
    from datetime import timedelta

    since = datetime.now(timezone.utc) - timedelta(days=days)
    traces = (
        db.query(AgentTrace)
        .filter(
            AgentTrace.tenant_id == tenant_id,
            AgentTrace.started_at >= since,
        )
        .all()
    )

    daily_data: Dict[str, Dict[str, Any]] = {}
    for trace in traces:
        if trace.started_at is None:
            continue
        day = trace.started_at.strftime("%Y-%m-%d")
        if day not in daily_data:
            daily_data[day] = {
                "requests": 0,
                "success": 0,
                "failed": 0,
                "cache_hits": 0,
                "fallbacks": 0,
                "in_progress": 0,
                "total_latency": 0.0,
                "count_latency": 0,
            }
        daily_data[day]["requests"] += 1
        if trace.status == "success":
            daily_data[day]["success"] += 1
        elif trace.status == "failed":
            daily_data[day]["failed"] += 1
        elif trace.status == "cache_hit":
            daily_data[day]["cache_hits"] += 1
        elif trace.status == "fallback":
            daily_data[day]["fallbacks"] += 1
        else:
            daily_data[day]["in_progress"] += 1
        if trace.duration_ms is not None:
            daily_data[day]["total_latency"] += trace.duration_ms
            daily_data[day]["count_latency"] += 1

    daily = []
    for day in sorted(daily_data.keys()):
        d = daily_data[day]
        avg_lat = (
            round(d["total_latency"] / d["count_latency"], 2)
            if d["count_latency"] > 0
            else 0.0
        )
        daily.append(
            {
                "date": day,
                "requests": d["requests"],
                "success": d["success"],
                "failed": d["failed"],
                "cache_hits": d["cache_hits"],
                "fallbacks": d["fallbacks"],
                "in_progress": d["in_progress"],
                "avg_latency_ms": avg_lat,
            }
        )

    return {"daily": daily}
