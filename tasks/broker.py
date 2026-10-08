import logging
from typing import Any, Dict, List, Optional

from config.redis import (
    REDIS_DB,
    REDIS_ENABLED,
    REDIS_HOST,
    REDIS_PASSWORD,
    REDIS_PORT,
    TASK_QUEUE_NAME,
)

logger = logging.getLogger(__name__)

STREAM_NAME = "financial:tasks:stream"
CONSUMER_GROUP = "workers"
LEGACY_QUEUE_NAME = TASK_QUEUE_NAME


class TaskBroker:
    def __init__(self):
        self._redis = None
        self._enabled = REDIS_ENABLED
        self._consumer_name = None
        self._stream_initialized = False

    @property
    def redis(self):
        if self._redis is None and self._enabled:
            try:
                import redis

                self._redis = redis.Redis(
                    host=REDIS_HOST,
                    port=REDIS_PORT,
                    db=REDIS_DB,
                    password=REDIS_PASSWORD,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
                self._redis.ping()
                logger.info("Redis broker connected")
            except Exception as e:
                logger.warning(f"Redis unavailable, falling back to DB polling: {e}")
                self._enabled = False
                self._redis = None
        return self._redis

    @property
    def enabled(self) -> bool:
        if self._redis is None:
            self.redis
        return self._enabled and self._redis is not None

    def set_consumer_name(self, name: str):
        self._consumer_name = name

    def _ensure_consumer_group(self):
        if not self.enabled or self._stream_initialized:
            return
        try:
            self._redis.xgroup_create(
                STREAM_NAME, CONSUMER_GROUP, id="0", mkstream=True
            )
            logger.info(f"Created consumer group '{CONSUMER_GROUP}' on stream '{STREAM_NAME}'")
        except Exception:
            pass
        self._stream_initialized = True

    def publish_task(self, task_id: str, tenant_id: int, task_type: str) -> bool:
        if not self.enabled:
            return False

        try:
            self._ensure_consumer_group()
            message = {
                "task_id": task_id,
                "tenant_id": str(tenant_id),
                "task_type": task_type,
            }
            self._redis.xadd(STREAM_NAME, message, maxlen=10000)
            logger.info(f"Published task {task_id} to Redis stream")
            return True
        except Exception as e:
            logger.error(f"Failed to publish task {task_id}: {e}")
            return False

    def consume_task(self, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None

        try:
            self._ensure_consumer_group()
            consumer = self._consumer_name or "default-consumer"
            result = self._redis.xreadgroup(
                CONSUMER_GROUP,
                consumer,
                {STREAM_NAME: ">"},
                count=1,
                block=max(1, int(timeout * 1000)),
            )
            if not result:
                return None

            stream_name, messages = result[0]
            if not messages:
                return None

            message_id, data = messages[0]
            data["_message_id"] = message_id
            return data
        except Exception as e:
            logger.error(f"Failed to consume task: {e}")
            return None

    def ack_task(self, task_id: str, message_id: str = None) -> bool:
        if not self.enabled or not message_id:
            return True
        try:
            self._redis.xack(STREAM_NAME, CONSUMER_GROUP, message_id)
            return True
        except Exception as e:
            logger.error(f"Failed to ack task {task_id}: {e}")
            return False

    def retry_task(self, task_id: str, tenant_id: int, task_type: str) -> bool:
        return self.publish_task(task_id, tenant_id, task_type)

    def claim_pending_tasks(self, min_idle_ms: int = 60000, count: int = 10) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []

        try:
            self._ensure_consumer_group()
            consumer = self._consumer_name or "default-consumer"
            pending = self._redis.xpending_range(
                STREAM_NAME, CONSUMER_GROUP, min="-", max="+", count=count
            )
            if not pending:
                return []

            messages_to_claim = []
            for entry in pending:
                if entry["time_since_delivered"] >= min_idle_ms:
                    messages_to_claim.append(entry["message_id"])

            if not messages_to_claim:
                return []

            claimed = self._redis.xclaim(
                STREAM_NAME,
                CONSUMER_GROUP,
                consumer,
                min_idle_time=min_idle_ms,
                message_ids=messages_to_claim,
            )
            results = []
            for message_id, data in claimed:
                data["_message_id"] = message_id
                results.append(data)
            return results
        except Exception as e:
            logger.error(f"Failed to claim pending tasks: {e}")
            return []


_broker: Optional[TaskBroker] = None


def get_broker() -> TaskBroker:
    global _broker
    if _broker is None:
        _broker = TaskBroker()
    return _broker
