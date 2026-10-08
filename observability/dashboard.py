import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from observability.metrics import get_agent_metrics, get_daily_metrics

logger = logging.getLogger(__name__)


def get_dashboard_metrics(
    db: Session,
    tenant_id: int,
    days: int = 7,
) -> Dict[str, Any]:
    metrics = get_agent_metrics(db, tenant_id)
    daily = get_daily_metrics(db, tenant_id, days=days)

    return {
        "overview": {
            "total_requests": metrics["total_requests"],
            "total_success": metrics["total_success"],
            "total_failed": metrics["total_failed"],
            "success_rate": metrics["success_rate"],
            "avg_latency_ms": metrics["avg_latency_ms"],
            "total_cost": metrics["total_cost"],
        },
        "daily": daily["daily"],
    }


def get_monitoring_overview(
    db: Session,
    tenant_id: int,
    period: Optional[str] = None,
) -> Dict[str, Any]:
    since = None
    if period:
        try:
            since = datetime.strptime(period, "%Y-%m").replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    metrics = get_agent_metrics(db, tenant_id, since=since)
    daily = get_daily_metrics(db, tenant_id, days=30)

    return {
        "total_requests": metrics["total_requests"],
        "total_success": metrics["total_success"],
        "total_failed": metrics["total_failed"],
        "success_rate": metrics["success_rate"],
        "avg_latency_ms": metrics["avg_latency_ms"],
        "total_cost": metrics["total_cost"],
        "daily": daily["daily"],
    }
