"""Opt-in tusd v2 hook router; transport gateway authorization is still required."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from auth.dependencies import get_current_user
from models.user import User


class TusHookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    Type: str
    Event: dict


def build_tus_hook_router(policy):
    router = APIRouter(prefix="/internal/tus", tags=["Isolated Tus Hooks"])

    @router.post("/hooks")
    def hook(body: TusHookRequest, user: User = Depends(get_current_user)):
        # tusd must forward Authorization from the original request. Uploaded
        # metadata never supplies tenant/user identity or a filesystem path.
        upload = body.Event.get("Upload")
        if not isinstance(upload, dict):
            raise HTTPException(400, "INVALID_TUS_EVENT")
        try:
            if body.Type == "pre-create":
                metadata = upload.get("MetaData")
                if not isinstance(metadata, dict):
                    raise ValueError("INVALID_TUS_METADATA")
                return policy.pre_create(metadata.get("upload_id"), user.tenant_id, user.id,
                    size=upload.get("Size"), deferred=upload.get("SizeIsDeferred", False),
                    partial=upload.get("IsPartial", False), final=upload.get("IsFinal", False))
            if body.Type == "pre-finish":
                return policy.pre_finish(upload.get("ID"), user.tenant_id, user.id,
                    size=upload.get("Size"), offset=upload.get("Offset"))
            if body.Type == "post-create":
                policy.resource_created(upload.get("ID"), user.tenant_id, user.id)
                return {}
            raise ValueError("UNSUPPORTED_TUS_HOOK")
        except (PermissionError, ValueError):
            # tusd v2 expects 2xx JSON rejection, not an HTTP 4xx/5xx which
            # represents a hook failure and can trigger retries.
            response = {"HTTPResponse": {
                "StatusCode": 403, "Body": "TUS_SESSION_REJECTED",
            }}
            # tusd ignores RejectUpload outside pre-create. Pre-finish can
            # change the response, not roll back persisted transport bytes;
            # business checksum/finalize must remain a separate hard gate.
            if body.Type == "pre-create":
                response["RejectUpload"] = True
            return response

    return router
