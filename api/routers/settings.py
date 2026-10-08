from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from api.schemas.settings import (
    LLMDefaultProviderUpdate,
    LLMProviderSettings,
    LLMProviderUpdate,
    LLMSettingsResponse,
)
from auth.dependencies import get_current_user
from models.llm_provider_setting import LLMProviderSetting
from models.user import User
from services.llm_settings_service import (
    SUPPORTED_LLM_PROVIDERS,
    CredentialEncryptionError,
    delete_provider_setting,
    get_provider_setting,
    list_provider_settings,
    set_default_provider,
    upsert_provider_setting,
)
from storage.database import get_db

router = APIRouter(prefix="/settings", tags=["Settings"])


def _provider_definition(provider: str) -> dict[str, object]:
    definition = SUPPORTED_LLM_PROVIDERS.get(provider.strip().lower())
    if definition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unsupported LLM provider",
        )
    return definition


def _serialize_provider(
    provider: str,
    setting: LLMProviderSetting | None,
) -> LLMProviderSettings:
    definition = _provider_definition(provider)
    return LLMProviderSettings(
        provider=provider,
        display_name=str(definition["display_name"]),
        models=list(definition["models"]),
        configured=setting is not None,
        is_default=setting.is_default if setting is not None else False,
        key_hint=(
            f"••••{setting.key_hint}"
            if setting is not None and setting.key_hint
            else None
        ),
        model=setting.model if setting is not None else str(definition["default_model"]),
        base_url=(
            setting.base_url
            if setting is not None and setting.base_url
            else (str(definition["base_url"]) if definition.get("base_url") else None)
        ),
        updated_at=setting.updated_at if setting is not None else None,
    )


def _serialize_settings(
    db: Session,
    *,
    tenant_id: int,
    user_id: int,
) -> LLMSettingsResponse:
    settings = {
        setting.provider: setting
        for setting in list_provider_settings(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
        )
    }
    default_provider = next(
        (
            setting.provider
            for setting in settings.values()
            if setting.is_default
        ),
        None,
    )
    return LLMSettingsResponse(
        providers=[
            _serialize_provider(provider, settings.get(provider))
            for provider in SUPPORTED_LLM_PROVIDERS
        ],
        default_provider=default_provider,
    )


@router.get("/llm", response_model=LLMSettingsResponse)
def get_llm_settings(
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LLMSettingsResponse:
    response.headers["Cache-Control"] = "no-store"
    return _serialize_settings(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
    )


@router.put("/llm/default", response_model=LLMSettingsResponse)
def put_default_llm_provider(
    request: LLMDefaultProviderUpdate,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LLMSettingsResponse:
    response.headers["Cache-Control"] = "no-store"
    normalized_provider = request.provider.strip().lower()
    _provider_definition(normalized_provider)
    try:
        set_default_provider(
            db,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            provider=normalized_provider,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return _serialize_settings(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
    )


@router.put("/llm/{provider}", response_model=LLMProviderSettings)
def put_llm_setting(
    provider: str,
    request: LLMProviderUpdate,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LLMProviderSettings:
    response.headers["Cache-Control"] = "no-store"
    normalized_provider = provider.strip().lower()
    _provider_definition(normalized_provider)
    try:
        setting = upsert_provider_setting(
            db,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            provider=normalized_provider,
            api_key=(
                request.api_key.get_secret_value()
                if request.api_key is not None
                else None
            ),
            model=request.model,
            base_url=request.base_url,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except CredentialEncryptionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM credential storage is not configured",
        ) from exc
    return _serialize_provider(normalized_provider, setting)


@router.delete("/llm/{provider}", response_model=LLMProviderSettings)
def clear_llm_setting(
    provider: str,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LLMProviderSettings:
    response.headers["Cache-Control"] = "no-store"
    normalized_provider = provider.strip().lower()
    _provider_definition(normalized_provider)
    delete_provider_setting(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        provider=normalized_provider,
    )
    return _serialize_provider(
        normalized_provider,
        get_provider_setting(
            db,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            provider=normalized_provider,
        ),
    )
