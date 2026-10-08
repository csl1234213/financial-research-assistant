import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


class TestRedisSessionCache:
    @patch("cache.session.is_redis_available")
    def test_save_and_get_session(self, mock_available):
        mock_available.return_value = True
        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        from cache.session import SessionCache

        cache = SessionCache()
        cache._redis = mock_redis

        state = {"answer": "NVIDIA Q1: $60.9B", "thread_id": "test_thread", "quality_score": 85.0}

        cache.save_session("test_thread", state)

        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args[0]
        assert "agent:session:0:0:test_thread" == call_args[0]
        assert call_args[1] == 86400

        mock_redis.get.return_value = json.dumps(state)
        restored = cache.get_session("test_thread")
        assert restored is not None
        assert restored["answer"] == "NVIDIA Q1: $60.9B"
        assert restored["quality_score"] == 85.0

    @patch("cache.session.is_redis_available")
    def test_get_nonexistent_session(self, mock_available):
        mock_available.return_value = True
        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        from cache.session import SessionCache

        cache = SessionCache()
        cache._redis = mock_redis
        result = cache.get_session("nonexistent")
        assert result is None

    @patch("cache.session.is_redis_available")
    def test_delete_session(self, mock_available):
        mock_available.return_value = True
        mock_redis = MagicMock()

        from cache.session import SessionCache

        cache = SessionCache()
        cache._redis = mock_redis
        result = cache.delete_session("to_delete")
        assert result is True
        mock_redis.delete.assert_called_once_with("agent:session:0:0:to_delete")

    @patch("cache.session.is_redis_available")
    def test_exists_session(self, mock_available):
        mock_available.return_value = True
        mock_redis = MagicMock()
        mock_redis.exists.return_value = True

        from cache.session import SessionCache

        cache = SessionCache()
        cache._redis = mock_redis
        assert cache.exists("exists_thread") is True

    @patch("cache.session.is_redis_available")
    def test_exists_session_false(self, mock_available):
        mock_available.return_value = True
        mock_redis = MagicMock()
        mock_redis.exists.return_value = False

        from cache.session import SessionCache

        cache = SessionCache()
        cache._redis = mock_redis
        assert cache.exists("no_thread") is False

    @patch("cache.session.is_redis_available")
    def test_session_ttl_24h(self, mock_available):
        mock_available.return_value = True
        mock_redis = MagicMock()

        from cache.session import SESSION_TTL, SessionCache

        assert SESSION_TTL == 86400

        cache = SessionCache()
        cache._redis = mock_redis
        cache.save_session("ttl_test", {"key": "value"})

        mock_redis.setex.assert_called_once()
        assert mock_redis.setex.call_args[0][1] == 86400

    @patch("cache.session.is_redis_available")
    def test_redis_unavailable_fallback(self, mock_available):
        mock_available.return_value = True
        mock_redis = MagicMock()
        mock_redis.setex.side_effect = Exception("Connection refused")

        from cache.session import SessionCache

        cache = SessionCache()
        cache._redis = mock_redis
        result = cache.save_session("fallback", {"key": "val"})
        assert result is False

    @patch("cache.session.is_redis_available")
    def test_redis_not_available_returns_none(self, mock_available):
        mock_available.return_value = False

        from cache.session import SessionCache

        cache = SessionCache()
        assert cache.get_session("any") is None
        assert cache.save_session("any", {}) is False
        assert cache.delete_session("any") is False
        assert cache.exists("any") is False

    def test_tenant_and_request_scopes_produce_distinct_keys(self):
        from cache.session import SessionCache

        cache = SessionCache()

        tenant_a = cache._key("default", tenant_id=1, request_key="first question")
        tenant_b = cache._key("default", tenant_id=2, request_key="first question")
        new_question = cache._key("default", tenant_id=1, request_key="second question")

        assert tenant_a != tenant_b
        assert tenant_a != new_question
        assert "first question" not in tenant_a

    def test_users_in_same_tenant_produce_distinct_keys(self):
        from cache.session import SessionCache

        cache = SessionCache()

        user_a = cache._key(
            "default",
            tenant_id=1,
            request_key="same question",
            user_id=101,
        )
        user_b = cache._key(
            "default",
            tenant_id=1,
            request_key="same question",
            user_id=102,
        )

        assert user_a != user_b
