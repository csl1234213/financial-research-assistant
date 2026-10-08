from fastapi import APIRouter, Depends

from auth.dependencies import require_admin_user
from core.core_engine import refresh_knowledge_base
from models.user import User

router = APIRouter(tags=["System"])


@router.post("/refresh")
def refresh(_operator: User = Depends(require_admin_user)):
    refresh_knowledge_base()

    return {
        "status": "ok",
        "message": "knowledge base refreshed",
    }
