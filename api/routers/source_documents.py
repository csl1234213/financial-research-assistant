"""Authenticated source view for finalized formal uploads."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from auth.dependencies import get_current_user
from models.user import User


def build_source_document_router(service_resolver):
    router = APIRouter(tags=["Source Documents"])

    @router.get("/documents/{document_id}/source")
    def source(document_id: int, version: str = Query(pattern=r"^[0-9a-f]{64}$"),
               page: int = Query(default=1, ge=1), user: User = Depends(get_current_user)):
        try:
            pdf = service_resolver().read(document_id, tenant_id=user.tenant_id,
                                         user_id=user.id, version=version, page=page)
        except PermissionError as exc:
            raise HTTPException(404, "SOURCE_NOT_FOUND") from exc
        except ValueError as exc:
            code = str(exc)
            raise HTTPException(422 if code == "INVALID_SOURCE_PAGE" else 409, code) from exc
        return Response(pdf.content, media_type="application/pdf", headers={
            "Content-Disposition": 'inline; filename="document.pdf"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Source-SHA256": pdf.sha256,
            "X-PDF-Page-Count": str(pdf.page_count),
        })

    return router
