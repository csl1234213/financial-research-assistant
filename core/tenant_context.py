from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user
from auth.jwt import decode_token
from models.tenant import Tenant
from models.user import User
from storage.database import get_db


def get_current_tenant(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Tenant:
    tenant = db.query(Tenant).filter(Tenant.id == user.tenant_id).first()
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant not found",
        )
    request.state.tenant_id = tenant.id
    request.state.user_id = user.id
    return tenant


def get_current_tenant_optional(
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[Tenant]:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    try:
        token = auth_header[len("Bearer "):]
        payload = decode_token(token)
        if payload is None:
            return None
        user_id_str = payload.get("sub")
        if user_id_str is None:
            return None
        user_id = int(user_id_str)
        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            return None
        tenant = db.query(Tenant).filter(Tenant.id == user.tenant_id).first()
        if tenant:
            request.state.tenant_id = tenant.id
            request.state.user_id = user.id
        return tenant
    except (HTTPException, Exception):
        return None
