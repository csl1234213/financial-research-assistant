"""
Storage paths — re-exports from config package.
"""

import os

from config import CACHE_DIR, CHROMA_PATH, PDF_DIR, UPLOAD_DIR

__all__ = ["CHROMA_PATH", "UPLOAD_DIR", "PDF_DIR", "CACHE_DIR", "storage_config"]


class StorageConfig:
    def __init__(self):
        self.database_url = os.environ.get(
            "DATABASE_URL", "sqlite:///./financial_rag.db"
        )
        self.redis_url = os.environ.get(
            "REDIS_URL", "redis://localhost:6379/0"
        )
        self.agent_memory_dir = os.environ.get(
            "AGENT_MEMORY_DIR", "storage/memory"
        )
        self.use_postgres = self.database_url.startswith("postgresql")
        self.use_redis = "redis" in self.redis_url.lower()

    @staticmethod
    def _environment() -> str:
        """Read the canonical environment name with the legacy alias fallback."""

        return os.environ.get("APP_ENV", os.environ.get("ENV", "development")).strip().lower()

    @property
    def is_dev(self) -> bool:
        return self._environment() == "development"

    @property
    def is_test(self) -> bool:
        return self._environment() == "test"

    @property
    def is_production(self) -> bool:
        return self._environment() in {"production", "prod"}


storage_config = StorageConfig()
