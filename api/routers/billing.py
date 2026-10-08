from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from billing.dashboard import get_tenant_plan_info, get_usage_summary
from billing.plans import get_plan_list
from core.tenant_context import get_current_tenant
from models.tenant import Tenant
from storage.database import get_db

router = APIRouter(tags=["Billing"])


@router.get("/billing/usage")
def get_billing_usage(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    period: str = Query(
        default=None,
        description="Period in YYYY-MM format, e.g. 2026-07",
    ),
):
    summary = get_usage_summary(db=db, tenant_id=tenant.id, period=period)
    return summary


@router.get("/billing/plan")
def get_billing_plan(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    plan_info = get_tenant_plan_info(db=db, tenant_id=tenant.id)
    return plan_info


@router.get("/billing/plans")
def list_available_plans():
    return {"plans": get_plan_list()}
