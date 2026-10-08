from datetime import datetime

from pydantic import BaseModel, Field, SecretStr


class LLMProviderUpdate(BaseModel):
    # Length validation happens after SecretStr parsing in the service so
    # FastAPI's validation payload can never echo credential input.
    api_key: SecretStr | None = None
    model: str | None = Field(default=None, min_length=1, max_length=255)
    base_url: str | None = Field(default=None, max_length=512)


class LLMDefaultProviderUpdate(BaseModel):
    provider: str = Field(min_length=1, max_length=50)


class LLMProviderSettings(BaseModel):
    provider: str
    display_name: str
    models: list[str]
    configured: bool
    is_default: bool
    key_hint: str | None
    model: str
    base_url: str | None = None
    updated_at: datetime | None


class LLMSettingsResponse(BaseModel):
    providers: list[LLMProviderSettings]
    default_provider: str | None
