"""Redis transport adapter: durable obligation stays in the canonical Task."""

import re

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError


class IngestionStreamPublisher:
    def __init__(self, redis_client, *, namespace):
        if not re.fullmatch(r"p23:[a-f0-9]{32}", namespace):
            raise ValueError("ISOLATED_STREAM_IDENTITY_REQUIRED")
        self.redis = redis_client
        self.stream = namespace + ":ingestion"

    def __call__(self, task_id, tenant_id, task_type):
        try:
            self.redis.xadd(
                self.stream,
                {
                    "task_id": task_id,
                    "tenant_id": str(tenant_id),
                    "task_type": task_type,
                },
            )
        except RedisTimeoutError as error:
            raise TimeoutError("INGESTION_TRANSPORT_TIMEOUT") from error
        except RedisConnectionError as error:
            raise ConnectionError("INGESTION_TRANSPORT_UNAVAILABLE") from error
        return True
