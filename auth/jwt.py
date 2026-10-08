import hashlib
import os
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

DEVELOPMENT_SECRET_KEY = "dev-secret-key-change-in-development"
_INSECURE_PRODUCTION_SECRETS = {
    "",
    DEVELOPMENT_SECRET_KEY,
    "dev-secret-key-change-in-production",
    "change-me-to-a-random-secret-key",
    "change-me",
    "your-secret-key",
    "test-secret",
    "dev-secret",
    "secret",
    "password",
    "default",
    "changeme",
}
# Reject the retired signing value without publishing its literal.
_RETIRED_SIGNING_KEY_SHA256 = bytes.fromhex(
    "ae593b0aba02527b0e7920b7e11bd37d55b464eec8aa12841d9a0cd383ce45e8"
)
_MIN_PRODUCTION_SECRET_LENGTH = 32


def _is_production() -> bool:
    return os.getenv("APP_ENV", "development").strip().lower() in {"production", "prod"}


def _resolve_secret_key() -> str:
    """Require an explicit strong production signing key, without a fallback."""
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    if app_env in {"production", "prod"}:
        secret_key = os.getenv("AUTH_SECRET_KEY", "").strip()
        if (
            not secret_key
            or secret_key.lower() in _INSECURE_PRODUCTION_SECRETS
            or hashlib.sha256(secret_key.lower().encode()).digest() == _RETIRED_SIGNING_KEY_SHA256
            or len(secret_key) < _MIN_PRODUCTION_SECRET_LENGTH
        ):
            raise RuntimeError(
                "AUTH_SECRET_KEY must be set to a strong, non-placeholder value "
                "when APP_ENV=production."
            )
    else:
        secret_key = (os.getenv("AUTH_SECRET_KEY") or os.getenv("SECRET_KEY") or "").strip()
    return secret_key or DEVELOPMENT_SECRET_KEY


SECRET_KEY = _resolve_secret_key()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("AUTH_TOKEN_EXPIRE_MINUTES", "1440"))


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
