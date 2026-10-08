from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.tenant_context import get_current_tenant
from models.tenant import Tenant
from services.plan_service import get_tenant_subscription
from storage.database import get_db

router = APIRouter(tags=["Subscription"])


@router.get("/subscription/me")
def get_my_subscription(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    sub = get_tenant_subscription(db=db, tenant_id=tenant.id)
    if sub is None:
        return {
            "tenant_id": tenant.id,
            "subscription": None,
            "message": "No active subscription",
        }
    return {
        "tenant_id": tenant.id,
        "subscription": sub,
    }
