import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from models.usage import UsageRecord
from storage.database import SessionLocal

logger = logging.getLogger(__name__)


def record_usage(
    tenant_id: int,
    event_type: str,
    resource_type: str = "generic",
    quantity: int = 1,
    user_id: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
    db: Optional[Session] = None,
) -> Optional[UsageRecord]:
    if tenant_id is None:
        raise ValueError("tenant_id is required to record usage")

    should_close = db is None
    if db is None:
        db = SessionLocal()

    try:
        record = UsageRecord(
            tenant_id=tenant_id,
            user_id=user_id,
            event_type=event_type,
            resource_type=resource_type,
            quantity=quantity,
        )
        if metadata:
            record.meta = metadata
        db.add(record)
        db.commit()
        db.refresh(record)
        return record
    except Exception as e:
        logger.error(f"Failed to record usage: {e}")
        if db:
            db.rollback()
        return None
    finally:
        if should_close and db:
            db.close()


def record_batch_usage(
    events: List[Dict[str, Any]],
    db: Optional[Session] = None,
) -> int:
    if not events:
        return 0

    should_close = db is None
    if db is None:
        db = SessionLocal()

    count = 0
    try:
        for event in events:
            tenant_id = event.get("tenant_id")
            if tenant_id is None:
                logger.warning("Skipping batch event without tenant_id")
                continue
            record = UsageRecord(
                tenant_id=tenant_id,
                user_id=event.get("user_id"),
                event_type=event.get("event_type", "unknown"),
                resource_type=event.get("resource_type", "generic"),
                quantity=event.get("quantity", 1),
            )
            meta = event.get("metadata")
            if meta:
                record.meta = meta
            db.add(record)
            count += 1
        db.commit()
        return count
    except Exception as e:
        logger.error(f"Failed to record batch usage: {e}")
        if db:
            db.rollback()
        return count
    finally:
        if should_close and db:
            db.close()


def get_usage_summary(
    tenant_id: int,
    db: Session,
    since: Optional[str] = None,
) -> Dict[str, Any]:
    from sqlalchemy import func

    query = db.query(
        UsageRecord.event_type,
        func.count(UsageRecord.id).label("count"),
        func.sum(UsageRecord.quantity).label("total_quantity"),
    ).filter(UsageRecord.tenant_id == tenant_id)

    if since:
        query = query.filter(UsageRecord.created_at >= since)

    query = query.group_by(UsageRecord.event_type)

    rows = query.all()
    events = [
        {
            "event_type": row.event_type,
            "count": row.count,
            "total_quantity": row.total_quantity or 0,
        }
        for row in rows
    ]

    return {
        "tenant_id": tenant_id,
        "events": events,
    }
