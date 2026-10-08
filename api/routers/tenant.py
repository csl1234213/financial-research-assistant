from fastapi import APIRouter, Depends

from api.schemas.tenant import TenantResponse
from core.tenant_context import get_current_tenant
from models.tenant import Tenant

router = APIRouter(tags=["Tenant"])


@router.get("/tenant/me", response_model=TenantResponse)
def get_my_tenant(current_tenant: Tenant = Depends(get_current_tenant)):
    return TenantResponse.model_validate(current_tenant)
