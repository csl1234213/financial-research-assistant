from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from core.tenant_context import get_current_tenant
from models.tenant import Tenant
from services.usage_service import get_usage_summary
from storage.database import get_db

router = APIRouter(tags=["Usage"])


@router.get("/usage/me")
def get_my_usage(
    request: Request,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    summary = get_usage_summary(tenant_id=tenant.id, db=db)
    return summary
