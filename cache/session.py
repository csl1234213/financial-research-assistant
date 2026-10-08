import json
import logging
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Dict, Optional

from cache.redis import get_redis_client, is_redis_available

logger = logging.getLogger(__name__)

SESSION_TTL = 86400
SESSION_PREFIX = "agent:session:"


@dataclass(frozen=True)
class ThreadCacheDeletion:
    successful: bool
    keys_deleted: int


class SessionCache:
    def __init__(self):
        self._redis = get_redis_client()

    def _key(
        self,
        thread_id: str,
        tenant_id: int = 0,
        request_key: str | None = None,
        *,
        user_id: int = 0,
    ) -> str:
        """Build a tenant- and user-scoped cache key.

        ``thread_id`` alone is user-controlled and commonly defaults to the
        same value. Including both principals prevents a cache hit from
        exposing one user's answer or conversation context to another user in
        the same workspace.
        """
        key = f"{SESSION_PREFIX}{tenant_id}:{user_id}:{thread_id}"
        if request_key is not None:
            digest = sha256(request_key.encode("utf-8")).hexdigest()[:16]
            key = f"{key}:{digest}"
        return key

    def _index_key(
        self,
        thread_id: str,
        tenant_id: int = 0,
        *,
        user_id: int = 0,
    ) -> str:
        """Build a fixed-shape key for the request variants of one thread."""

        digest = sha256(thread_id.encode("utf-8")).hexdigest()
        return f"{SESSION_PREFIX}index:{tenant_id}:{user_id}:{digest}"

    @staticmethod
    def _escape_match(value: str) -> str:
        """Escape user input before placing it in a Redis glob pattern."""

        escaped = value.replace("\\", "\\\\")
        for character in ("*", "?", "["):
            escaped = escaped.replace(character, f"\\{character}")
        return escaped

    def get_session(
        self,
        thread_id: str,
        tenant_id: int = 0,
        request_key: str | None = None,
        *,
        user_id: int = 0,
    ) -> Optional[Dict[str, Any]]:
        if not is_redis_available():
            return None
        try:
            data = self._redis.get(
                self._key(thread_id, tenant_id, request_key, user_id=user_id)
            )
            if data:
                return json.loads(data)
        except Exception as e:
            logger.warning(f"Redis get error: {e}")
        return None

    def save_session(
        self,
        thread_id: str,
        state: Dict[str, Any],
        tenant_id: int = 0,
        request_key: str | None = None,
        *,
        user_id: int = 0,
    ) -> bool:
        if not is_redis_available():
            return False
        try:
            key = self._key(thread_id, tenant_id, request_key, user_id=user_id)
            self._redis.setex(
                key,
                SESSION_TTL,
                json.dumps(state, ensure_ascii=False, default=str),
            )
            index_key = self._index_key(thread_id, tenant_id, user_id=user_id)
            self._redis.sadd(index_key, key)
            self._redis.expire(index_key, SESSION_TTL)
            return True
        except Exception as e:
            logger.warning(f"Redis save error: {e}")
            return False

    def delete_session(
        self,
        thread_id: str,
        tenant_id: int = 0,
        request_key: str | None = None,
        *,
        user_id: int = 0,
    ) -> bool:
        if not is_redis_available():
            return False
        try:
            key = self._key(thread_id, tenant_id, request_key, user_id=user_id)
            self._redis.delete(key)
            self._redis.srem(
                self._index_key(thread_id, tenant_id, user_id=user_id),
                key,
            )
            return True
        except Exception as e:
            logger.warning(f"Redis delete error: {e}")
            return False

    def delete_thread(
        self,
        thread_id: str,
        tenant_id: int = 0,
        *,
        user_id: int = 0,
    ) -> ThreadCacheDeletion:
        """Delete every cached request variant for one exact principal/thread.

        New entries are discovered through a hashed index. A safely escaped
        ``SCAN`` also removes pre-index cache entries created by older
        deployments without ever treating a client thread ID as a glob.
        """

        if not is_redis_available():
            return ThreadCacheDeletion(successful=True, keys_deleted=0)

        base_key = self._key(thread_id, tenant_id, user_id=user_id)
        index_key = self._index_key(thread_id, tenant_id, user_id=user_id)
        keys: set[str] = {base_key}
        try:
            for indexed_key in self._redis.smembers(index_key):
                if isinstance(indexed_key, bytes):
                    indexed_key = indexed_key.decode("utf-8")
                if indexed_key == base_key or indexed_key.startswith(f"{base_key}:"):
                    keys.add(indexed_key)

            pattern = f"{self._escape_match(base_key)}:*"
            for matched_key in self._redis.scan_iter(match=pattern):
                if isinstance(matched_key, bytes):
                    matched_key = matched_key.decode("utf-8")
                if matched_key.startswith(f"{base_key}:"):
                    keys.add(matched_key)

            deleted = int(self._redis.delete(*sorted(keys))) if keys else 0
            self._redis.delete(index_key)
            return ThreadCacheDeletion(successful=True, keys_deleted=deleted)
        except Exception as e:
            logger.warning("Redis thread cache deletion error: %s", e)
            return ThreadCacheDeletion(successful=False, keys_deleted=0)

    def exists(
        self,
        thread_id: str,
        tenant_id: int = 0,
        request_key: str | None = None,
        *,
        user_id: int = 0,
    ) -> bool:
        if not is_redis_available():
            return False
        try:
            return bool(
                self._redis.exists(
                    self._key(thread_id, tenant_id, request_key, user_id=user_id)
                )
            )
        except Exception:
            return False


session_cache = SessionCache()
