import os

ALLOW_GLOBAL_SEARCH = os.environ.get("ALLOW_GLOBAL_SEARCH", "false").lower() in ("true", "1", "yes")

DEFAULT_MIGRATION_TENANT = os.environ.get("DEFAULT_MIGRATION_TENANT", "default")

AUDIT_LOG_ENABLED = os.environ.get("AUDIT_LOG_ENABLED", "true").lower() in ("true", "1", "yes")

__all__ = [
    "ALLOW_GLOBAL_SEARCH",
    "DEFAULT_MIGRATION_TENANT",
    "AUDIT_LOG_ENABLED",
]
