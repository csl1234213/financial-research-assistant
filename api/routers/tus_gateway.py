"""Opt-in authenticated proxy for standard tus requests, not a custom protocol."""

import base64
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from auth.dependencies import get_current_user
from core.upload_session_contracts import UploadState
from models.user import User


def build_tus_gateway_router(policy, upstream, *, max_bytes=50 * 1024 * 1024):
    """upstream is a configured, bounded-timeout client, never a user URL.

    Its tusd must enable the authenticated pre-create hook and forward
    Authorization. This router must be the only browser-reachable entry point.
    """
    router = APIRouter(prefix="/upload-transport", tags=["Isolated Tus Gateway"])

    async def persist_progress(result, upload_id, user):
        try:
            await run_in_threadpool(policy.resource_progress, upload_id, user.tenant_id, user.id,
                offset=result.headers.get("upload-offset"), length=result.headers.get("upload-length"))
        except ValueError as exc:
            raise HTTPException(502, "TUS_PROGRESS_RECEIPT_INVALID") from exc

    @router.api_route("/{upload_id}", methods=["POST", "HEAD", "PATCH", "OPTIONS"])
    async def transport(upload_id: str, request: Request, user: User = Depends(get_current_user)):
        try:
            session = await run_in_threadpool(policy.authorize, upload_id, user.tenant_id, user.id)
        except PermissionError as exc:
            raise HTTPException(404, "UPLOAD_NOT_FOUND") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        method = request.method
        if method in {"POST", "PATCH"} and session.state in {UploadState.VERIFIED, UploadState.FINALIZED}:
            raise HTTPException(409, "TUS_CONTENT_LOCKED")
        headers = {key: value for key, value in request.headers.items() if key.lower() in {
            "authorization", "tus-resumable", "upload-offset", "upload-length", "content-type",
        }}
        if method == "POST" and session.state == UploadState.UPLOADING:
            if request.headers.get("upload-length") != str(session.expected_size):
                raise HTTPException(409, "TUS_LENGTH_MISMATCH")
            # A lost creation response must not cause a second POST upstream.
            # Verify persisted transport identity/size before replaying Location.
            try:
                result = await run_in_threadpool(upstream.request, "HEAD", f"/files/{upload_id}", headers=headers)
            except httpx.TransportError as exc:
                raise HTTPException(502, "TUS_UPSTREAM_UNAVAILABLE") from exc
            if (result.status_code not in {200, 204}
                    or result.headers.get("upload-length") != str(session.expected_size)):
                raise HTTPException(409, "TUS_RESOURCE_RECOVERY_REQUIRED")
            await persist_progress(result, upload_id, user)
            return Response(status_code=201, headers={
                "Location": request.url.path, "Tus-Resumable": "1.0.0", "Cache-Control": "no-store",
            })
        if method == "POST":
            try:
                length = int(request.headers.get("upload-length", ""))
                await run_in_threadpool(policy.pre_create, upload_id, user.tenant_id, user.id, size=length)
            except ValueError as exc:
                raise HTTPException(409, "TUS_LENGTH_MISMATCH") from exc
            encoded = base64.b64encode(upload_id.encode("ascii")).decode("ascii")
            headers["Upload-Metadata"] = f"upload_id {encoded}"
        data = bytearray()
        try:
            async for chunk in request.stream():
                data.extend(chunk)
                if len(data) > min(max_bytes, session.expected_size):
                    raise HTTPException(413, "FILE_TOO_LARGE")
        except ClientDisconnect:
            # No incomplete request reaches tusd. Its committed offset remains
            # authoritative; a subsequent HEAD can safely resume from there.
            return Response(status_code=499, headers={"Cache-Control": "no-store"})
        if method != "PATCH" and data:
            raise HTTPException(400, "TUS_BODY_NOT_ALLOWED")
        path = "/files/" if method in {"POST", "OPTIONS"} else f"/files/{upload_id}"
        try:
            result = await run_in_threadpool(upstream.request, method, path, headers=headers, content=bytes(data))
        except httpx.TimeoutException as exc:
            raise HTTPException(504, "TUS_UPSTREAM_TIMEOUT") from exc
        except httpx.TransportError as exc:
            raise HTTPException(502, "TUS_UPSTREAM_UNAVAILABLE") from exc
        response_headers = {key: value for key, value in result.headers.items() if key.lower() in {
            "tus-resumable", "tus-version", "tus-extension", "tus-max-size", "upload-offset", "upload-length",
        }}
        if method == "POST" and result.status_code == 201:
            location = result.headers.get("location", "")
            if urlsplit(location).path != f"/files/{upload_id}":
                raise HTTPException(502, "TUS_IDENTITY_NOT_BOUND")
            await run_in_threadpool(policy.resource_created, upload_id, user.tenant_id, user.id)
            # Relative public path keeps tus on the browser's authenticated
            # origin even when a reverse proxy rewrites Host upstream.
            # Never trust client Forwarded headers to construct a remote URL.
            response_headers["Location"] = request.url.path
        response_headers["Cache-Control"] = "no-store"
        if method in {"HEAD", "PATCH"} and result.status_code in {200, 204}:
            await persist_progress(result, upload_id, user)
        return Response(content=result.content, status_code=result.status_code, headers=response_headers)

    return router
