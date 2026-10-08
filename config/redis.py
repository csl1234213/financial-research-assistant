import os
from urllib.parse import urlparse

REDIS_URL = os.environ.get(
    "REDIS_URL",
    "redis://localhost:6379/0"
)

parsed = urlparse(REDIS_URL)

REDIS_HOST = parsed.hostname or os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = parsed.port or int(os.environ.get("REDIS_PORT", "6379"))
REDIS_DB = int(
    parsed.path.lstrip("/")
    or os.environ.get("REDIS_DB", "0")
)

REDIS_PASSWORD = parsed.password or os.environ.get(
    "REDIS_PASSWORD",
    None
)

TASK_QUEUE_NAME = "financial:tasks:queue"

REDIS_ENABLED = os.environ.get(
    "REDIS_ENABLED",
    "true"
).lower() in ("true", "1", "yes")

MAX_RETRY = int(
    os.environ.get("TASK_MAX_RETRY", "3")
)

__all__ = [
    "REDIS_URL",
    "REDIS_HOST",
    "REDIS_PORT",
    "REDIS_DB",
    "REDIS_PASSWORD",
    "REDIS_ENABLED",
    "TASK_QUEUE_NAME",
    "MAX_RETRY",
]
