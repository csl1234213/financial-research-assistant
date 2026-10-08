import logging
import os
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from core.usage_events import UsageEvent
from models.document import Document
from models.plan import Plan
from models.subscription import TenantSubscription
from models.usage import UsageRecord

logger = logging.getLogger(__name__)

DEFAULT_PLAN_SLUG = "free"
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def chat_plan_limits_enabled() -> bool:
    """Read the chat quota switch with a safe, fail-closed default."""
    raw = os.environ.get("CHAT_PLAN_LIMITS_ENABLED")
    if raw is None or raw.strip().lower() in _TRUE_VALUES:
        return True
    if raw.strip().lower() in _FALSE_VALUES:
        return False
    logger.warning("Invalid CHAT_PLAN_LIMITS_ENABLED value; keeping chat limits enabled")
    return True


def _evaluation_bypass_enabled() -> bool:
    return os.environ.get("EVALUATION_BYPASS_PLAN_LIMITS", "false").strip().lower() in _TRUE_VALUES


def _evaluation_tenant_ids() -> set[int]:
    values: set[int] = set()
    for raw in os.environ.get("EVALUATION_BYPASS_TENANT_IDS", "").split(","):
        candidate = raw.strip()
        if not candidate:
            continue
        try:
            values.add(int(candidate))
        except ValueError:
            logger.warning("Ignoring invalid evaluation tenant id")
    return values


def should_bypass_plan_limit(tenant_id: int, *, context: str = "evaluation") -> bool:
    """Allow only explicitly configured evaluation tenants to bypass chat limits."""
    return (
        context == "evaluation"
        and _evaluation_bypass_enabled()
        and tenant_id in _evaluation_tenant_ids()
    )


def _get_default_plan(db: Session) -> Optional[Plan]:
    return db.query(Plan).filter(Plan.slug == DEFAULT_PLAN_SLUG).first()


def _get_tenant_plan(db: Session, tenant_id: int) -> Plan:
    sub = (
        db.query(TenantSubscription)
        .filter(
            TenantSubscription.tenant_id == tenant_id,
            TenantSubscription.status == "active",
        )
        .first()
    )
    if sub and sub.plan:
        return sub.plan
    default = _get_default_plan(db)
    if default:
        return default
    return Plan(
        name="Fallback",
        slug="fallback",
        max_documents=10,
        max_chats_per_day=50,
        max_embeddings=1000,
    )


def get_tenant_subscription(db: Session, tenant_id: int) -> Optional[dict]:
    sub = (
        db.query(TenantSubscription)
        .filter(
            TenantSubscription.tenant_id == tenant_id,
            TenantSubscription.status == "active",
        )
        .first()
    )
    if sub is None:
        return None
    return {
        "id": sub.id,
        "tenant_id": sub.tenant_id,
        "plan": {
            "id": sub.plan.id,
            "name": sub.plan.name,
            "slug": sub.plan.slug,
            "max_documents": sub.plan.max_documents,
            "max_chats_per_day": sub.plan.max_chats_per_day,
            "max_embeddings": sub.plan.max_embeddings,
        },
        "status": sub.status,
        "start_date": sub.start_date.isoformat() if sub.start_date else None,
        "end_date": sub.end_date.isoformat() if sub.end_date else None,
    }


def can_upload(db: Session, tenant_id: int) -> bool:
    if should_bypass_plan_limit(tenant_id):
        return True
    return check_plan_limit(db, tenant_id, UsageEvent.DOCUMENT_UPLOAD, "documents")


def get_document_quota(db: Session, tenant_id: int) -> dict[str, int | bool]:
    """Current holdings consume capacity; historical usage remains audit-only."""
    limit = _get_tenant_plan(db, tenant_id).max_documents
    used = db.query(Document).filter(Document.tenant_id == tenant_id).count()
    return {
        "used": used,
        "limit": limit,
        "remaining": max(0, limit - used),
        "bypassed": should_bypass_plan_limit(tenant_id),
    }


def can_chat(db: Session, tenant_id: int) -> bool:
    if not chat_plan_limits_enabled():
        return True
    if should_bypass_plan_limit(tenant_id):
        return True
    return check_plan_limit(db, tenant_id, UsageEvent.CHAT_REQUEST, "chats")


def check_plan_limit(
    db: Session,
    tenant_id: int,
    event_type: str,
    limit_type: str,
) -> bool:
    plan = _get_tenant_plan(db, tenant_id)

    if limit_type == "documents":
        quota = get_document_quota(db, tenant_id)
        return quota["used"] < quota["limit"]

    if limit_type == "chats":
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        limit = plan.max_chats_per_day
        count = (
            db.query(UsageRecord)
            .filter(
                UsageRecord.tenant_id == tenant_id,
                UsageRecord.event_type == event_type,
                UsageRecord.created_at >= today_start,
            )
            .count()
        )
        return count < limit

    if limit_type == "embeddings":
        limit = plan.max_embeddings
        count = (
            db.query(UsageRecord)
            .filter(
                UsageRecord.tenant_id == tenant_id,
                UsageRecord.event_type == event_type,
            )
            .count()
        )
        return count < limit

    return True


def initialize_default_plans(db: Session) -> None:
    existing = db.query(Plan).filter(Plan.slug == DEFAULT_PLAN_SLUG).first()
    if existing is None:
        free_plan = Plan(
            name="Free",
            slug="free",
            max_documents=10,
            max_chats_per_day=50,
            max_embeddings=1000,
            price=0.0,
        )
        db.add(free_plan)

    existing_pro = db.query(Plan).filter(Plan.slug == "pro").first()
    if existing_pro is None:
        pro_plan = Plan(
            name="Pro",
            slug="pro",
            max_documents=100,
            max_chats_per_day=500,
            max_embeddings=10000,
            price=29.99,
        )
        db.add(pro_plan)

    existing_ent = db.query(Plan).filter(Plan.slug == "enterprise").first()
    if existing_ent is None:
        ent_plan = Plan(
            name="Enterprise",
            slug="enterprise",
            max_documents=1000,
            max_chats_per_day=5000,
            max_embeddings=100000,
            price=99.99,
        )
        db.add(ent_plan)

    db.commit()
    logger.info("Default plans initialized")
