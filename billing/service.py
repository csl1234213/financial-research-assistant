import logging
from datetime import datetime, timezone
from typing import Tuple

from sqlalchemy.orm import Session

from billing.plans import get_plan_limits, is_enterprise
from models.subscription import TenantSubscription
from models.usage import UsageRecord

logger = logging.getLogger(__name__)


def _get_tenant_plan_slug(db: Session, tenant_id: int) -> str:
    sub = (
        db.query(TenantSubscription)
        .filter(
            TenantSubscription.tenant_id == tenant_id,
            TenantSubscription.status == "active",
        )
        .first()
    )
    if sub and sub.plan:
        return sub.plan.slug
    return "free"


def check_quota(
    db: Session,
    tenant_id: int,
    resource: str,
) -> Tuple[bool, str]:
    if resource == "agent_chat":
        return _check_agent_chat_quota(db, tenant_id)
    if resource == "document":
        return _check_document_quota(db, tenant_id)
    if resource == "token":
        return _check_token_quota(db, tenant_id)
    return True, ""


def _check_agent_chat_quota(
    db: Session,
    tenant_id: int,
) -> Tuple[bool, str]:
    plan_slug = _get_tenant_plan_slug(db, tenant_id)
    limits = get_plan_limits(plan_slug)

    if is_enterprise(plan_slug):
        return True, ""

    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    count = (
        db.query(UsageRecord)
        .filter(
            UsageRecord.tenant_id == tenant_id,
            UsageRecord.event_type == "chat_request",
            UsageRecord.created_at >= month_start,
        )
        .count()
    )

    if count >= limits.agent_chats_per_month:
        return False, f"Monthly agent chat limit ({limits.agent_chats_per_month}) exceeded"
    return True, ""


def _check_document_quota(
    db: Session,
    tenant_id: int,
) -> Tuple[bool, str]:
    from services.plan_service import get_document_quota, should_bypass_plan_limit

    if should_bypass_plan_limit(tenant_id):
        return True, ""

    quota = get_document_quota(db, tenant_id)
    if quota["used"] >= quota["limit"]:
        return False, f"Document upload limit ({quota['limit']}) exceeded"
    return True, ""


def _check_token_quota(
    db: Session,
    tenant_id: int,
) -> Tuple[bool, str]:
    plan_slug = _get_tenant_plan_slug(db, tenant_id)

    if is_enterprise(plan_slug):
        return True, ""

    return True, ""
