from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy.orm import Session

from config.llm import (
    ANTHROPIC_BASE_URL,
    ANTHROPIC_MODEL,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    DOUBAO_BASE_URL,
    DOUBAO_MODEL,
    GEMINI_MODEL,
    LLM_PROVIDER,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
)
from llm.providers.provider_guard import normalize_local_ollama_url
from models.llm_provider_setting import LLMProviderSetting

logger = logging.getLogger(__name__)

SUPPORTED_LLM_PROVIDERS: dict[str, dict[str, object]] = {
    "ollama": {
        "display_name": "本地模型（Ollama）",
        "default_model": "",
        "base_url": "http://host.docker.internal:11434",
        "models": [],
        "local": True,
    },
    "deepseek": {
        "display_name": "DeepSeek",
        "default_model": DEEPSEEK_MODEL,
        "base_url": DEEPSEEK_BASE_URL,
        "models": [
            "deepseek-v4-flash",
            "deepseek-v4-pro",
        ],
    },
    "gemini": {
        "display_name": "Google Gemini",
        "default_model": GEMINI_MODEL,
        "base_url": None,
        "models": [
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
        ],
    },
    "openai": {
        "display_name": "OpenAI / ChatGPT",
        "default_model": OPENAI_MODEL,
        "base_url": OPENAI_BASE_URL,
        "models": [
            "gpt-5.5",
            "gpt-5.4",
            "gpt-5.4-mini",
            "gpt-5.4-nano",
        ],
    },
    "anthropic": {
        "display_name": "Anthropic Claude",
        "default_model": ANTHROPIC_MODEL,
        "base_url": ANTHROPIC_BASE_URL,
        "models": [
            "claude-fable-5",
            "claude-opus-4-8",
            "claude-sonnet-5",
            "claude-haiku-4-5-20251001",
        ],
    },
    "doubao": {
        "display_name": "豆包（火山方舟）",
        "default_model": DOUBAO_MODEL,
        "base_url": DOUBAO_BASE_URL,
        "models": [
            "doubao-seed-2-0-pro-260215",
            "doubao-seed-2-0-lite-260215",
            "doubao-seed-2-0-mini-260215",
        ],
    },
}


@dataclass(frozen=True)
class RuntimeLLMSettings:
    provider_configs: dict[str, dict[str, str]]
    provider_models: dict[str, str]
    default_provider: str | None
    revision: str


class CredentialEncryptionError(RuntimeError):
    """Raised when the dedicated credential-encryption key is unavailable."""


def _fernet() -> MultiFernet:
    """Build a rotating cipher from dedicated deployment secret material.

    The first comma-separated key encrypts new values; all configured keys can
    decrypt existing values. This permits safe key rotation without coupling
    provider credentials to the JWT signing lifecycle.
    """

    configured_keys = [
        key.strip()
        for key in os.getenv("LLM_CREDENTIAL_ENCRYPTION_KEYS", "").split(",")
        if key.strip()
    ]
    key_file = os.getenv("LLM_CREDENTIAL_KEY_FILE", "").strip()
    if not configured_keys and key_file:
        configured_keys = [_load_or_create_key_file(Path(key_file))]
    if not configured_keys:
        raise CredentialEncryptionError(
            "LLM credential encryption is not configured on the backend"
        )

    ciphers = []
    for secret in configured_keys:
        digest = hashlib.sha256(
            b"financial-rag:llm-provider-settings:v1:" + secret.encode("utf-8")
        ).digest()
        ciphers.append(Fernet(base64.urlsafe_b64encode(digest)))
    return MultiFernet(ciphers)


def _load_or_create_key_file(path: Path) -> str:
    """Load a deployment-owned key file, creating it atomically if absent."""

    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
        generated = secrets.token_urlsafe(48)
        try:
            descriptor = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            value = path.read_text(encoding="utf-8").strip()
        else:
            try:
                os.write(descriptor, generated.encode("utf-8"))
            finally:
                os.close(descriptor)
            value = generated
    except OSError as exc:
        raise CredentialEncryptionError(
            "LLM credential encryption key file is unavailable"
        ) from exc

    if len(value) < 32:
        raise CredentialEncryptionError(
            "LLM credential encryption key material is invalid"
        )
    return value


def _encrypt_api_key(api_key: str) -> str:
    return _fernet().encrypt(api_key.encode("utf-8")).decode("ascii")


def _decrypt_api_key(encrypted_api_key: str) -> str:
    try:
        return _fernet().decrypt(encrypted_api_key.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
        raise CredentialEncryptionError(
            "Stored LLM credential could not be decrypted"
        ) from exc


def _setting_query(
    db: Session,
    *,
    tenant_id: int,
    user_id: int,
):
    return db.query(LLMProviderSetting).filter(
        LLMProviderSetting.tenant_id == tenant_id,
        LLMProviderSetting.user_id == user_id,
    )


def get_provider_setting(
    db: Session,
    *,
    tenant_id: int,
    user_id: int,
    provider: str,
) -> LLMProviderSetting | None:
    return _setting_query(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
    ).filter(LLMProviderSetting.provider == provider).first()


def list_provider_settings(
    db: Session,
    *,
    tenant_id: int,
    user_id: int,
) -> list[LLMProviderSetting]:
    return _setting_query(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
    ).order_by(LLMProviderSetting.provider.asc()).all()


def upsert_provider_setting(
    db: Session,
    *,
    tenant_id: int,
    user_id: int,
    provider: str,
    api_key: str | None,
    model: str | None = None,
    base_url: str | None = None,
) -> LLMProviderSetting:
    definition = SUPPORTED_LLM_PROVIDERS[provider]
    is_local = bool(definition.get("local"))
    setting = get_provider_setting(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        provider=provider,
    )
    selected_base_url = (
        normalize_local_ollama_url(
            base_url or (setting.base_url if setting is not None else None)
        )
        if is_local
        else None
    )
    if not is_local and base_url is not None:
        raise ValueError("Custom endpoints are only supported for local Ollama")
    normalized_key = api_key.strip() if api_key is not None else None
    if normalized_key is not None and not normalized_key:
        raise ValueError("API key cannot be blank")
    if is_local and normalized_key is not None:
        raise ValueError("Local Ollama does not accept an API key")
    if normalized_key is not None and not 8 <= len(normalized_key) <= 4096:
        raise ValueError("API key must contain between 8 and 4096 characters")
    if setting is None and normalized_key is None and not is_local:
        raise ValueError("API key is required when configuring a provider")
    if setting is not None and normalized_key is None and model is None and base_url is None:
        raise ValueError("API key, model, or endpoint must be provided")
    selected_model = model or (
        setting.model if setting is not None else str(definition["default_model"])
    )
    if is_local:
        selected_model = selected_model.strip()
        if not selected_model:
            raise ValueError("Ollama model name is required")
        if len(selected_model) > 255:
            raise ValueError("Ollama model name is too long")
    elif selected_model not in definition["models"]:
        raise ValueError("Unsupported model for LLM provider")

    if setting is None:
        is_first_provider = (
            _setting_query(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
            ).count()
            == 0
        )
        setting = LLMProviderSetting(
            tenant_id=tenant_id,
            user_id=user_id,
            provider=provider,
            encrypted_api_key=(
                _encrypt_api_key(normalized_key)
                if normalized_key is not None
                else None
            ),
            key_hint=normalized_key[-4:] if normalized_key is not None else None,
            model=selected_model,
            base_url=selected_base_url,
            is_default=is_first_provider,
        )
        db.add(setting)
    else:
        if normalized_key is not None:
            setting.encrypted_api_key = _encrypt_api_key(normalized_key)
            setting.key_hint = normalized_key[-4:]
        setting.model = selected_model
        if is_local:
            setting.base_url = selected_base_url
        setting.revision = str(uuid4())
        setting.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(setting)
    return setting


def delete_provider_setting(
    db: Session,
    *,
    tenant_id: int,
    user_id: int,
    provider: str,
) -> bool:
    setting = get_provider_setting(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        provider=provider,
    )
    if setting is None:
        return False
    was_default = setting.is_default
    db.delete(setting)
    db.flush()
    if was_default:
        replacement = _preferred_setting(
            list_provider_settings(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
            )
        )
        if replacement is not None:
            replacement.is_default = True
            replacement.revision = str(uuid4())
            replacement.updated_at = datetime.now(timezone.utc)
    db.commit()
    return True


def _preferred_setting(
    settings: list[LLMProviderSetting],
) -> LLMProviderSetting | None:
    if not settings:
        return None
    return next(
        (setting for setting in settings if setting.provider == LLM_PROVIDER),
        settings[0],
    )


def set_default_provider(
    db: Session,
    *,
    tenant_id: int,
    user_id: int,
    provider: str,
) -> LLMProviderSetting:
    """Select a configured provider without accepting or exposing its key."""

    setting = get_provider_setting(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        provider=provider,
    )
    if setting is None:
        raise ValueError("LLM provider must be configured before it can be selected")

    _setting_query(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
    ).filter(LLMProviderSetting.is_default.is_(True)).update(
        {LLMProviderSetting.is_default: False},
        synchronize_session="fetch",
    )
    db.flush()
    setting.is_default = True
    setting.revision = str(uuid4())
    setting.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(setting)
    return setting


def get_runtime_llm_settings(
    db: Session,
    *,
    tenant_id: int,
    user_id: int,
) -> RuntimeLLMSettings:
    """Return request-scoped provider configuration without logging secrets."""

    provider_configs: dict[str, dict[str, str]] = {}
    provider_models: dict[str, str] = {}
    revision_records: list[dict[str, str | int | bool]] = []
    explicit_default: str | None = None

    for setting in list_provider_settings(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
    ):
        definition = SUPPORTED_LLM_PROVIDERS.get(setting.provider)
        if definition is None:
            continue
        api_key = ""
        if setting.encrypted_api_key:
            try:
                api_key = _decrypt_api_key(setting.encrypted_api_key)
            except CredentialEncryptionError:
                logger.error(
                    "Unable to load LLM credential for tenant=%s user=%s provider=%s",
                    tenant_id,
                    user_id,
                    setting.provider,
                )
                raise

        provider_config = {"api_key": api_key}
        base_url = definition.get("base_url")
        if setting.base_url:
            base_url = setting.base_url
        if base_url:
            provider_config["base_url"] = str(base_url)
        provider_configs[setting.provider] = provider_config
        provider_models[setting.provider] = setting.model
        if setting.is_default and explicit_default is None:
            explicit_default = setting.provider
        revision_records.append(
            {
                "id": setting.id,
                "provider": setting.provider,
                "model": setting.model,
                "base_url": setting.base_url or "",
                "revision": setting.revision,
                "is_default": setting.is_default,
                "updated_at": setting.updated_at.isoformat(),
            }
        )

    configured = list(provider_configs)
    default_provider = explicit_default or (
        LLM_PROVIDER
        if LLM_PROVIDER in provider_configs
        else (configured[0] if configured else None)
    )
    revision = hashlib.sha256(
        json.dumps(
            revision_records,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return RuntimeLLMSettings(
        provider_configs=provider_configs,
        provider_models=provider_models,
        default_provider=default_provider,
        revision=revision,
    )
