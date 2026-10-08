from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user
from models.user import User
from storage.database import get_db
from tasks.repository import TaskRepository

router = APIRouter(tags=["Tasks"])


@router.get("/tasks/{task_id}")
def get_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    repo = TaskRepository(db)
    task = repo.get_task(task_id)

    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Access denied: task belongs to another tenant")

    return {
        "id": task.public_id,
        "type": task.task_type,
        "status": task.status,
        "tenant_id": task.tenant_id,
        "user_id": task.user_id,
        "progress": task.progress,
        "error": task.error_message,
        "result": task.result,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


@router.get("/tasks")
def list_tasks(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    repo = TaskRepository(db)
    result = repo.list_tasks(
        tenant_id=current_user.tenant_id,
        status=status,
        page=page,
        size=size,
    )

    return {
        "items": [
            {
                "id": t.public_id,
                "type": t.task_type,
                "status": t.status,
                "tenant_id": t.tenant_id,
                "user_id": t.user_id,
                "progress": t.progress,
                "error": t.error_message,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            }
            for t in result["items"]
        ],
        "total": result["total"],
        "page": result["page"],
        "size": result["size"],
    }
