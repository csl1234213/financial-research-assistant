from unittest.mock import MagicMock, patch

from cache.session import SessionCache


@patch("cache.session.is_redis_available", return_value=True)
def test_save_registers_request_variant_in_hashed_thread_index(mock_available):
    redis = MagicMock()
    cache = SessionCache()
    cache._redis = redis

    assert cache.save_session(
        "portfolio",
        {"answer": "ok"},
        tenant_id=7,
        request_key="question-and-history",
        user_id=9,
    )

    cache_key = cache._key(
        "portfolio",
        7,
        "question-and-history",
        user_id=9,
    )
    index_key = cache._index_key("portfolio", 7, user_id=9)
    redis.sadd.assert_called_once_with(index_key, cache_key)
    redis.expire.assert_called_once_with(index_key, 86400)


@patch("cache.session.is_redis_available", return_value=True)
def test_delete_thread_removes_all_exact_variants_without_glob_injection(
    mock_available,
):
    redis = MagicMock()
    redis.delete.side_effect = [3, 1]
    cache = SessionCache()
    cache._redis = redis
    base_key = "agent:session:7:9:portfolio*"
    indexed_variant = f"{base_key}:aaaaaaaaaaaaaaaa"
    scanned_variant = f"{base_key}:bbbbbbbbbbbbbbbb"
    other_thread = "agent:session:7:9:portfolio-leak:cccccccccccccccc"
    redis.smembers.return_value = {
        indexed_variant.encode(),
        other_thread.encode(),
    }
    redis.scan_iter.return_value = [
        scanned_variant.encode(),
        other_thread.encode(),
    ]

    deletion = cache.delete_thread("portfolio*", tenant_id=7, user_id=9)

    assert deletion.successful is True
    assert deletion.keys_deleted == 3
    redis.scan_iter.assert_called_once_with(
        match=r"agent:session:7:9:portfolio\*:*"
    )
    redis.delete.assert_any_call(
        base_key,
        indexed_variant,
        scanned_variant,
    )
    assert all(
        other_thread not in call.args
        for call in redis.delete.call_args_list
    )


@patch("cache.session.is_redis_available", return_value=False)
def test_delete_thread_is_safe_when_redis_is_unavailable(mock_available):
    redis = MagicMock()
    cache = SessionCache()
    cache._redis = redis

    deletion = cache.delete_thread("thread", tenant_id=7, user_id=9)

    assert deletion.successful is True
    assert deletion.keys_deleted == 0
    redis.delete.assert_not_called()


@patch("cache.session.is_redis_available", return_value=True)
def test_delete_thread_reports_redis_failure(mock_available):
    redis = MagicMock()
    redis.smembers.side_effect = RuntimeError("redis unavailable")
    cache = SessionCache()
    cache._redis = redis

    deletion = cache.delete_thread("thread", tenant_id=7, user_id=9)

    assert deletion.successful is False
    assert deletion.keys_deleted == 0
