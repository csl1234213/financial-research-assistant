"""Explicit isolated Redis Streams adapter for durable ingestion tasks."""

import re

from redis.exceptions import ResponseError
from sqlalchemy import select

from models.task import Task


class IngestionStreamConsumer:
    def __init__(self, redis_client, session_factory, runner, *, namespace, consumer):
        if not re.fullmatch(r"p23:[a-f0-9]{32}", namespace) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", consumer):
            raise ValueError("ISOLATED_STREAM_IDENTITY_REQUIRED")
        self.redis = redis_client
        self.session_factory = session_factory
        self.runner = runner
        self.stream = f"{namespace}:ingestion"
        self.group = "ingestion-workers"
        self.consumer = consumer

    def initialize(self):
        try:
            self.redis.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except ResponseError as error:
            if not str(error).startswith("BUSYGROUP"):
                raise

    def handle(self, message_id, fields):
        task_id = fields.get("task_id")
        if not isinstance(task_id, str) or not re.fullmatch(r"[a-f0-9]{32}", task_id):
            return "rejected"
        with self.session_factory() as session:
            task = session.scalar(select(Task).where(Task.public_id == task_id))
            if (task is None or task.task_type != "process_document"
                    or fields.get("tenant_id") != str(task.tenant_id)
                    or fields.get("task_type") != task.task_type or not task.payload.get("upload_id")):
                return "rejected"
            tenant_id, user_id = task.tenant_id, task.user_id
        outcome = self.runner.run(task_id, tenant_id=tenant_id, user_id=user_id)
        if outcome in {"ready", "failed", "quarantined"}:
            # A crash before ACK leads to terminal replay, not repeated writes.
            self.redis.xack(self.stream, self.group, message_id)
        return outcome

    def consume_one(self):
        messages = self.redis.xreadgroup(self.group, self.consumer, {self.stream: ">"}, count=1, block=1000)
        if not messages:
            return "idle"
        message_id, fields = messages[0][1][0]
        return self.handle(message_id, fields)

    def reclaim_one(self, *, idle_ms=60000):
        if type(idle_ms) is not int or not 1000 <= idle_ms <= 3600000:
            raise ValueError("INVALID_RECLAIM_BUDGET")
        result = self.redis.xautoclaim(self.stream, self.group, self.consumer,
                                      min_idle_time=idle_ms, start_id="0-0", count=1)
        if not result[1]:
            return "idle"
        message_id, fields = result[1][0]
        return self.handle(message_id, fields)
