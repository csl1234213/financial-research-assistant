# ============================================================
# test_rate_limiter_runtime.py
# Rate Limiter Runtime Integration Test Matrix
# ============================================================
# 验证：
#   1. 初始状态，无请求
#   2. 未超过限制，通过
#   3. 超过限制，拒绝
#   4. 时间窗口过期后恢复
#   5. 固定窗口算法
#   6. 无 callable 模式（skeleton backward compat）
#   7. Engine Pipeline 集成
#   8. 属性检查
# ============================================================

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


# Ensure mechanisms are auto-registered
import agent.reliability.mechanisms  # noqa: F401
from agent.reliability import (
    PipelineResult,
    RateLimiterPolicy,
    ReliabilityContext,
    ReliabilityEngine,
    ReliabilityType,
)
from agent.reliability.mechanisms.rate_limiter_reliability import RateLimiterReliability
from agent.runtime_state import RuntimeState

# ============================================================
# 1. 初始状态
# ============================================================

class TestRateLimiterInitial:

    def test_initial_state_zero_requests(self):
        rl = RateLimiterReliability()
        assert rl.total_requests == 0

    def test_initial_blocked_requests_zero(self):
        rl = RateLimiterReliability()
        assert rl.blocked_requests == 0

    def test_initial_remaining_zero(self):
        rl = RateLimiterReliability()
        assert rl.remaining == 0


# ============================================================
# 2. 未超过限制，通过
# ============================================================

class TestRateLimiterAllowed:

    def test_under_limit_allowed(self):
        rl = RateLimiterReliability()
        ctx = ReliabilityContext()
        policy = RateLimiterPolicy(max_requests=5, window_ms=60000)

        for i in range(5):
            result = rl.apply(ctx, policy)
            assert result.success is True
            assert result.metadata["rate_limit_blocked"] is False

        assert rl.total_requests == 5

    def test_remaining_correct(self):
        rl = RateLimiterReliability()
        ctx = ReliabilityContext()
        policy = RateLimiterPolicy(max_requests=5, window_ms=60000)

        rl.apply(ctx, policy)
        rl.apply(ctx, policy)
        result = rl.apply(ctx, policy)

        assert result.metadata["rate_limit_remaining"] == 2


# ============================================================
# 3. 超过限制，拒绝
# ============================================================

class TestRateLimiterBlocked:

    def test_over_limit_blocked(self):
        rl = RateLimiterReliability()
        ctx = ReliabilityContext()
        policy = RateLimiterPolicy(max_requests=3, window_ms=60000)

        rl.apply(ctx, policy)
        rl.apply(ctx, policy)
        rl.apply(ctx, policy)
        result = rl.apply(ctx, policy)

        assert result.success is False
        assert result.metadata["rate_limit_blocked"] is True
        assert rl.blocked_requests == 1

    def test_disabled_always_allowed(self):
        rl = RateLimiterReliability()
        ctx = ReliabilityContext()
        policy = RateLimiterPolicy(enabled=False, max_requests=0)

        result = rl.apply(ctx, policy)
        assert result.success is True
        assert result.metadata["rate_limit_remaining"] == 0
        assert "rate limiter disabled" in result.metadata["reason"]


# ============================================================
# 4. 时间窗口过期后恢复
# ============================================================

class TestRateLimiterWindowRecovery:

    def test_window_expiration_clears_old_timestamps(self):
        rl = RateLimiterReliability()
        ctx = ReliabilityContext()
        policy = RateLimiterPolicy(max_requests=3, window_ms=100)

        rl.apply(ctx, policy)
        rl.apply(ctx, policy)
        rl.apply(ctx, policy)

        assert rl.apply(ctx, policy).success is False

        time.sleep(0.15)

        result = rl.apply(ctx, policy)
        assert result.success is True
        assert result.metadata["rate_limit_remaining"] == 2


# ============================================================
# 5. 无 callable — skeleton 兼容
# ============================================================

class TestRateLimiterNoCallable:

    def test_rate_limiter_without_callable(self):
        rl = RateLimiterReliability()
        ctx = ReliabilityContext()
        result = rl.apply(ctx, RateLimiterPolicy())

        assert result.success is True
        assert "rate_limit_remaining" in result.metadata

    def test_rate_limiter_supports_always_true(self):
        rl = RateLimiterReliability()
        assert rl.supports(ReliabilityContext()) is True

    def test_rate_limiter_mechanism_name(self):
        rl = RateLimiterReliability()
        assert rl.mechanism_name == "rate_limiter"

    def test_rate_limiter_mechanism_type(self):
        rl = RateLimiterReliability()
        assert rl.mechanism_type == ReliabilityType.RATE_LIMITER


# ============================================================
# 6. Engine Pipeline 集成
# ============================================================

class TestRateLimiterPipeline:

    def test_engine_pipeline_includes_rate_limiter(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        result = engine.execute_pipeline(ctx)

        assert isinstance(result, PipelineResult)
        assert "rate_limiter" in result.pipeline_order

    def test_engine_pipeline_rate_limiter_second(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        result = engine.execute_pipeline(ctx)

        assert result.pipeline_order[1] == "rate_limiter"

    def test_engine_pipeline_over_limit_fails(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        pipeline = [
            ("rate_limiter", RateLimiterPolicy(max_requests=2, window_ms=60000)),
        ]

        engine.execute_pipeline(ctx, pipeline=pipeline)
        engine.execute_pipeline(ctx, pipeline=pipeline)
        result = engine.execute_pipeline(ctx, pipeline=pipeline)

        assert result.success is False


# ============================================================
# 7. 属性
# ============================================================

class TestRateLimiterProperties:

    def test_reset_clears_all_state(self):
        rl = RateLimiterReliability()
        policy = RateLimiterPolicy(max_requests=2, window_ms=60000)
        ctx = ReliabilityContext()

        rl.apply(ctx, policy)
        rl.apply(ctx, policy)
        rl.apply(ctx, policy)

        assert rl.blocked_requests == 1

        rl.reset()
        assert rl.total_requests == 0
        assert rl.blocked_requests == 0


# ============================================================
# 8. RuntimeState.rate_limit_remaining
# ============================================================

class TestRuntimeStateRateLimit:

    def test_rate_limit_remaining_default_zero(self):
        state = RuntimeState()
        assert state.rate_limit_remaining == 0

    def test_rate_limit_remaining_settable(self):
        state = RuntimeState()
        state.rate_limit_remaining = 50
        assert state.rate_limit_remaining == 50


# ============================================================
# 9. Engine single apply rate limiter
# ============================================================

class TestEngineSingleRateLimiter:

    def test_engine_apply_rate_limiter_normal(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext()
        result = engine.apply(
            ctx,
            ReliabilityType.RATE_LIMITER,
            RateLimiterPolicy(max_requests=100, window_ms=60000),
        )

        assert result.success is True
        assert result.policy == ReliabilityType.RATE_LIMITER
        assert result.metadata["rate_limit_remaining"] == 99

    def test_engine_apply_rate_limiter_over_limit(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext()
        policy = RateLimiterPolicy(max_requests=1, window_ms=60000)

        engine.apply(ctx, ReliabilityType.RATE_LIMITER, policy)
        result = engine.apply(ctx, ReliabilityType.RATE_LIMITER, policy)

        assert result.success is False
        assert "rate_limit_blocked" in result.metadata


# ============================================================
# 10. 回归
# ============================================================

class TestRateLimiterRegression:

    def test_registry_has_rate_limiter(self):
        from agent.reliability import ReliabilityRegistry

        assert "rate_limiter" in ReliabilityRegistry.list_mechanisms()

    def test_old_mechanisms_still_work(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext()
        for rtype in ReliabilityType:
            result = engine.apply(ctx, rtype)
            assert result.success is True
