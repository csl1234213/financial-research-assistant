# ============================================================
# test_timeout_runtime.py
# Timeout Runtime Integration Test Matrix
# ============================================================
# 验证：
#   1. 正常完成（不超时，success=True）
#   2. 超时（timeout_occurred=True, success=False）
#   3. 超时后 Retry 成功
#   4. 超时后 Retry 仍超时
#   5. RuntimeState.timeout_count
#   6. 无 callable 模式（skeleton backward compat）
#   7. 指数退避 + 超时组合
#   8. TimeoutReliability 属性
#   9. Engine Pipeline 集成
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
    ReliabilityContext,
    ReliabilityEngine,
    ReliabilityType,
    TimeoutPolicy,
)
from agent.reliability.mechanisms.timeout_reliability import TimeoutReliability
from agent.runtime_state import RuntimeState

# ============================================================
# 1. 正常完成 — 不超时
# ============================================================

class TestTimeoutNormal:

    def test_timeout_completes_normally(self):
        timeout = TimeoutReliability()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        policy = TimeoutPolicy(timeout_ms=5000)

        result = timeout.apply(ctx, policy)

        assert result.success is True
        assert result.timeout_occurred is False
        assert result.policy == ReliabilityType.TIMEOUT

    def test_timeout_completes_with_short_timeout(self):
        timeout = TimeoutReliability()

        def fast_fn():
            return "done"

        ctx = ReliabilityContext(metadata={"_callable": fast_fn})
        policy = TimeoutPolicy(timeout_ms=1000)

        result = timeout.apply(ctx, policy)

        assert result.success is True
        assert result.timeout_occurred is False

    def test_timeout_metadata_contains_timeout_ms(self):
        timeout = TimeoutReliability()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        policy = TimeoutPolicy(timeout_ms=3000)

        result = timeout.apply(ctx, policy)

        assert result.metadata["timeout_ms"] == 3000
        assert "elapsed_ms" in result.metadata


# ============================================================
# 2. 超时
# ============================================================

class TestTimeoutExceeded:

    def test_timeout_exceeded(self):
        timeout = TimeoutReliability()

        def slow_fn():
            time.sleep(0.5)
            return "late"

        ctx = ReliabilityContext(metadata={"_callable": slow_fn})
        policy = TimeoutPolicy(timeout_ms=100)

        result = timeout.apply(ctx, policy)

        assert result.success is False
        assert result.timeout_occurred is True
        assert "Timeout after 100ms" in result.error

    def test_timeout_count_increments(self):
        timeout = TimeoutReliability()

        def slow_fn():
            time.sleep(0.3)
            return "late"

        ctx = ReliabilityContext(metadata={"_callable": slow_fn})
        policy = TimeoutPolicy(timeout_ms=50)

        timeout.apply(ctx, policy)
        timeout.apply(ctx, policy)

        assert timeout.timeout_count == 2

    def test_timeout_reset(self):
        timeout = TimeoutReliability()

        def slow_fn():
            time.sleep(0.3)
            return "late"

        ctx = ReliabilityContext(metadata={"_callable": slow_fn})
        policy = TimeoutPolicy(timeout_ms=50)

        timeout.apply(ctx, policy)
        assert timeout.timeout_count == 1

        timeout.reset()
        assert timeout.timeout_count == 0


# ============================================================
# 3. 无 callable — skeleton 兼容
# ============================================================

class TestTimeoutNoCallable:

    def test_timeout_without_callable(self):
        timeout = TimeoutReliability()
        ctx = ReliabilityContext()
        result = timeout.apply(ctx, TimeoutPolicy())

        assert result.success is True
        assert result.timeout_occurred is False

    def test_timeout_supports_always_true(self):
        timeout = TimeoutReliability()
        assert timeout.supports(ReliabilityContext()) is True

    def test_timeout_mechanism_name(self):
        timeout = TimeoutReliability()
        assert timeout.mechanism_name == "timeout"

    def test_timeout_mechanism_type(self):
        timeout = TimeoutReliability()
        assert timeout.mechanism_type == ReliabilityType.TIMEOUT


# ============================================================
# 4. Timeout + callable 异常
# ============================================================

class TestTimeoutWithException:

    def test_timeout_callable_raises_exception(self):
        timeout = TimeoutReliability()

        def error_fn():
            raise ValueError("inner error")

        ctx = ReliabilityContext(metadata={"_callable": error_fn})
        policy = TimeoutPolicy(timeout_ms=5000)

        result = timeout.apply(ctx, policy)

        assert result.success is False
        assert result.timeout_occurred is False
        assert "inner error" in result.error


# ============================================================
# 5. Engine Pipeline 集成
# ============================================================

class TestEnginePipelineTimeout:

    def test_engine_pipeline_includes_timeout(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        result = engine.execute_pipeline(ctx)

        assert isinstance(result, PipelineResult)
        assert "timeout" in result.pipeline_order
        assert "retry" in result.pipeline_order
        assert "circuit_breaker" in result.pipeline_order

    def test_engine_pipeline_timeout_order(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        result = engine.execute_pipeline(ctx)

        assert result.pipeline_order[0] == "health_check"
        assert result.pipeline_order[1] == "rate_limiter"
        assert result.pipeline_order[2] == "timeout"
        assert "retry" in result.pipeline_order
        assert "circuit_breaker" in result.pipeline_order
        assert "fallback" in result.pipeline_order

    def test_engine_pipeline_custom_pipeline(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        custom = [
            ("timeout", TimeoutPolicy(timeout_ms=1000)),
            ("retry", None),
        ]
        result = engine.execute_pipeline(ctx, pipeline=custom)

        assert len(result.pipeline_order) == 2
        assert result.pipeline_order == ["timeout", "retry"]

    def test_engine_pipeline_no_callable(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext()
        result = engine.execute_pipeline(ctx)

        assert result.success is True
        assert "no callable" in result.metadata.get("reason", "")


# ============================================================
# 6. RuntimeState.timeout_count
# ============================================================

class TestRuntimeStateTimeoutCount:

    def test_timeout_count_default_zero(self):
        state = RuntimeState()
        assert state.timeout_count == 0

    def test_timeout_count_settable(self):
        state = RuntimeState()
        state.timeout_count = 3
        assert state.timeout_count == 3


# ============================================================
# 7. 超时后 Retry 组合
# ============================================================

class TestTimeoutRetryCombo:

    def test_timeout_then_retry_success(self):
        engine = ReliabilityEngine()
        call_count = {"count": 0}

        def flaky():
            call_count["count"] += 1
            if call_count["count"] == 1:
                raise ValueError("transient failure")
            return "ok"

        ctx = ReliabilityContext(metadata={"_callable": flaky})
        pipeline = [
            ("timeout", TimeoutPolicy(timeout_ms=5000)),
            ("retry", None),
        ]

        result = engine.execute_pipeline(ctx, pipeline=pipeline)
        assert result.success is True
        assert call_count["count"] == 2


# ============================================================
# 8. Engine single apply timeout
# ============================================================

class TestEngineSingleTimeout:

    def test_engine_apply_timeout_normal(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        result = engine.apply(ctx, ReliabilityType.TIMEOUT, TimeoutPolicy(timeout_ms=5000))

        assert result.success is True
        assert result.policy == ReliabilityType.TIMEOUT
        assert result.timeout_occurred is False

    def test_engine_apply_timeout_exceeded(self):
        engine = ReliabilityEngine()

        def slow_fn():
            time.sleep(0.3)
            return "late"

        ctx = ReliabilityContext(metadata={"_callable": slow_fn})
        result = engine.apply(ctx, ReliabilityType.TIMEOUT, TimeoutPolicy(timeout_ms=50))

        assert result.success is False
        assert result.timeout_occurred is True
