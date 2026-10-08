import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from unittest.mock import MagicMock

import pytest

from tasks.broker import TaskBroker, get_broker
from tasks.retry import get_retry_count, should_retry


@pytest.fixture(autouse=True)
def _reset_broker():
    broker = get_broker()
    broker._redis = None
    broker._enabled = True
    broker._stream_initialized = False
    yield
    broker._redis = None
    broker._enabled = True
    broker._stream_initialized = False


class TestTaskBroker:
    def test_publish_task(self):
        mock_redis = MagicMock()
        mock_redis.xgroup_create.return_value = True
        broker = TaskBroker()
        broker._redis = mock_redis
        broker._enabled = True

        result = broker.publish_task(
            task_id="abc123",
            tenant_id=1,
            task_type="process_document",
        )

        assert result is True
        mock_redis.xadd.assert_called_once()
        call_args = mock_redis.xadd.call_args[0]
        assert call_args[0] == "financial:tasks:stream"
        message = call_args[1]
        assert message["task_id"] == "abc123"
        assert message["tenant_id"] == "1"
        assert message["task_type"] == "process_document"

    def test_consume_task(self):
        mock_redis = MagicMock()
        mock_redis.xgroup_create.return_value = True
        mock_redis.xreadgroup.return_value = [[
            "financial:tasks:stream",
            [["msg-001", {
                "task_id": "abc123",
                "tenant_id": "1",
                "task_type": "process_document",
            }]]
        ]]

        broker = TaskBroker()
        broker._redis = mock_redis
        broker._enabled = True
        broker.set_consumer_name("test-worker")

        result = broker.consume_task(timeout=1.0)

        assert result is not None
        assert result["task_id"] == "abc123"
        assert result["tenant_id"] == "1"
        assert result["task_type"] == "process_document"
        assert result["_message_id"] == "msg-001"

    def test_consume_task_empty_queue(self):
        mock_redis = MagicMock()
        mock_redis.xgroup_create.return_value = True
        mock_redis.xreadgroup.return_value = None

        broker = TaskBroker()
        broker._redis = mock_redis
        broker._enabled = True

        result = broker.consume_task(timeout=1.0)
        assert result is None

    def test_ack_task(self):
        mock_redis = MagicMock()
        broker = TaskBroker()
        broker._redis = mock_redis
        broker._enabled = True

        result = broker.ack_task("abc123", message_id="msg-001")
        assert result is True
        mock_redis.xack.assert_called_once_with(
            "financial:tasks:stream", "workers", "msg-001"
        )

    def test_ack_task_no_message_id(self):
        broker = TaskBroker()
        result = broker.ack_task("abc123")
        assert result is True

    def test_retry_task(self):
        mock_redis = MagicMock()
        mock_redis.xgroup_create.return_value = True
        broker = TaskBroker()
        broker._redis = mock_redis
        broker._enabled = True

        result = broker.retry_task(
            task_id="abc123",
            tenant_id=1,
            task_type="process_document",
        )

        assert result is True
        mock_redis.xadd.assert_called_once()

    def test_broker_disabled_when_no_redis(self):
        broker = TaskBroker()
        broker._enabled = False
        broker._redis = None
        assert not broker.enabled

    def test_publish_task_when_disabled(self):
        broker = TaskBroker()
        broker._enabled = False
        broker._redis = None
        result = broker.publish_task("abc123", 1, "process_document")
        assert result is False

    def test_consume_task_when_disabled(self):
        broker = TaskBroker()
        broker._enabled = False
        broker._redis = None
        result = broker.consume_task(timeout=1.0)
        assert result is None

    def test_set_consumer_name(self):
        broker = TaskBroker()
        broker.set_consumer_name("worker-007")
        assert broker._consumer_name == "worker-007"

    def test_claim_pending_tasks(self):
        mock_redis = MagicMock()
        mock_redis.xgroup_create.return_value = True
        mock_redis.xpending_range.return_value = [
            {"message_id": "msg-001", "time_since_delivered": 120000},
            {"message_id": "msg-002", "time_since_delivered": 30000},
        ]
        mock_redis.xclaim.return_value = [
            ["msg-001", {"task_id": "abc123", "tenant_id": "1", "task_type": "process_document"}],
        ]

        broker = TaskBroker()
        broker._redis = mock_redis
        broker._enabled = True
        broker.set_consumer_name("recovery-worker")

        results = broker.claim_pending_tasks(min_idle_ms=60000)

        assert len(results) == 1
        assert results[0]["task_id"] == "abc123"
        assert results[0]["_message_id"] == "msg-001"


class TestRetry:
    def test_should_retry_within_limit(self):
        assert should_retry(0, max_retry=3) is True
        assert should_retry(1, max_retry=3) is True
        assert should_retry(2, max_retry=3) is True

    def test_should_retry_exceeds_limit(self):
        assert should_retry(3, max_retry=3) is False
        assert should_retry(4, max_retry=3) is False

    def test_should_retry_default_max(self):
        assert should_retry(0) is True
        assert should_retry(2) is True

    def test_get_retry_count_from_task(self):
        task = MagicMock()
        task.retry_count = 2
        assert get_retry_count(task) == 2

    def test_get_retry_count_default(self):
        task = MagicMock(spec=[])
        assert get_retry_count(task) == 0


class TestBrokerIntegration:
    def test_broker_connection_failure_falls_back(self):
        broker = TaskBroker()
        broker._enabled = False
        broker._redis = None
        assert broker.enabled is False
        assert broker._redis is None

    def test_publish_message_format(self):
        mock_redis = MagicMock()
        mock_redis.xgroup_create.return_value = True
        broker = TaskBroker()
        broker._redis = mock_redis
        broker._enabled = True

        broker.publish_task(
            task_id="task-001",
            tenant_id=42,
            task_type="process_document",
        )

        call_args = mock_redis.xadd.call_args[0]
        message = call_args[1]
        assert "task_id" in message
        assert "tenant_id" in message
        assert "task_type" in message
        assert message["tenant_id"] == "42"
