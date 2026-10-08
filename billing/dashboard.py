import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from billing.models import BillingRecord
from models.usage import UsageRecord

logger = logging.getLogger(__name__)


def get_usage_summary(
    db: Session,
    tenant_id: int,
    period: Optional[str] = None,
) -> Dict[str, Any]:
    if period is None:
        now = datetime.now(timezone.utc)
        period = now.strftime("%Y-%m")

    period_start = datetime.strptime(period, "%Y-%m").replace(tzinfo=timezone.utc)
    if period_start.month == 12:
        period_end = period_start.replace(year=period_start.year + 1, month=1)
    else:
        period_end = period_start.replace(month=period_start.month + 1)

    usage_query = db.query(UsageRecord).filter(
        UsageRecord.tenant_id == tenant_id,
        UsageRecord.created_at >= period_start,
        UsageRecord.created_at < period_end,
    )

    total_requests = usage_query.count()

    usage_records = usage_query.all()
    total_tokens = 0
    top_tools: Counter = Counter()

    for record in usage_records:
        total_tokens += record.quantity
        meta = record.meta
        tools_used = meta.get("tools_used", [])
        for tool in tools_used:
            top_tools[tool] += 1

    billing_query = db.query(
        func.coalesce(func.sum(BillingRecord.amount), 0.0).label("total_cost")
    ).filter(
        BillingRecord.tenant_id == tenant_id,
        BillingRecord.created_at >= period_start,
        BillingRecord.created_at < period_end,
    )
    total_cost = round(billing_query.scalar() or 0.0, 6)

    return {
        "period": period,
        "total_requests": total_requests,
        "total_tokens": total_tokens,
        "total_cost": total_cost,
        "top_tools": [
            {"tool": tool, "count": count}
            for tool, count in top_tools.most_common(5)
        ],
    }


def get_tenant_plan_info(db: Session, tenant_id: int) -> Dict[str, Any]:
    from billing.plans import get_plan_limits, get_plan_price
    from billing.service import _get_tenant_plan_slug

    plan_slug = _get_tenant_plan_slug(db, tenant_id)
    limits = get_plan_limits(plan_slug)
    price = get_plan_price(plan_slug)

    return {
        "plan": plan_slug,
        "price": price,
        "limits": {
            "agent_chats_per_month": limits.agent_chats_per_month,
            "max_tokens_per_request": limits.max_tokens_per_request,
            "max_documents": limits.max_documents,
            "max_chats_per_day": limits.max_chats_per_day,
            "max_embeddings": limits.max_embeddings,
            "priority_support": limits.priority_support,
            "custom_tools": limits.custom_tools,
        },
    }
