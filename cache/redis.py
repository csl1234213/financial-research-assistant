import logging
import os

logger = logging.getLogger(__name__)

_redis_client = None


def get_redis_client():
    global _redis_client
    if _redis_client is not None:
        return _redis_client

    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    try:
        import redis as _redis

        _redis_client = _redis.Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        _redis_client.ping()
        logger.info(f"Redis connected: {redis_url}")
    except Exception as e:
        logger.warning(f"Redis not available ({e}), using in-memory fallback")
        _redis_client = False

    return _redis_client


def is_redis_available() -> bool:
    client = get_redis_client()
    return client is not False
