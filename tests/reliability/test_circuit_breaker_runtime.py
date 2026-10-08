# ============================================================
# test_circuit_breaker_runtime.py
# Circuit Breaker Runtime Integration Test Matrix
# ============================================================
# 验证：
#   1. 初始 CLOSED 状态
#   2. 连续失败 → OPEN
#   3. OPEN 状态拒绝请求
#   4. OPEN → HALF_OPEN（恢复超时后）
#   5. HALF_OPEN 成功 → CLOSED
#   6. HALF_OPEN 失败 → OPEN
#   7. RuntimeState.circuit_state / failure_count
#   8. 无 callable 模式（skeleton backward compat）
#   9. Engine Pipeline 集成
#   10. 熔断器属性
# ============================================================

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pytest

# Ensure mechanisms are auto-registered
import agent.reliability.mechanisms  # noqa: F401
from agent.reliability import (
    CircuitBreakerPolicy,
    PipelineResult,
    ReliabilityContext,
    ReliabilityEngine,
    ReliabilityType,
)
from agent.reliability.mechanisms.circuit_breaker_reliability import CircuitBreakerReliability
from agent.reliability.reliability_enums import CircuitState
from agent.runtime_state import RuntimeState

# ============================================================
# 1. 初始 CLOSED 状态
# ============================================================

class TestCircuitBreakerInitial:

    def test_initial_state_closed(self):
        cb = CircuitBreakerReliability()
        assert cb.state == CircuitState.CLOSED

    def test_initial_failure_count_zero(self):
        cb = CircuitBreakerReliability()
        assert cb.failure_count == 0

    def test_callable_succeeds_in_closed_state(self):
        cb = CircuitBreakerReliability()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        policy = CircuitBreakerPolicy(failure_threshold=3)

        result = cb.apply(ctx, policy)

        assert result.success is True
        assert result.circuit_state == CircuitState.CLOSED.value
        assert cb.state == CircuitState.CLOSED
        assert cb.total_successes == 1

    def test_success_resets_failure_count(self):
        cb = CircuitBreakerReliability()
        policy = CircuitBreakerPolicy(failure_threshold=3)

        def fail_fn():
            raise ValueError("fail")

        ctx = ReliabilityContext(metadata={"_callable": fail_fn})
        cb.apply(ctx, policy)
        cb.apply(ctx, policy)

        assert cb.failure_count == 2

        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        cb.apply(ctx, policy)

        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED


# ============================================================
# 2. 连续失败 → OPEN
# ============================================================

class TestCircuitBreakerOpen:

    def test_consecutive_failures_opens_circuit(self):
        cb = CircuitBreakerReliability()
        policy = CircuitBreakerPolicy(failure_threshold=3)

        def fail_fn():
            raise ValueError("fail")

        ctx = ReliabilityContext(metadata={"_callable": fail_fn})

        cb.apply(ctx, policy)
        cb.apply(ctx, policy)
        assert cb.state == CircuitState.CLOSED

        cb.apply(ctx, policy)
        assert cb.state == CircuitState.OPEN
        assert cb.failure_count == 3

    def test_open_rejects_calls(self):
        cb = CircuitBreakerReliability()
        policy = CircuitBreakerPolicy(failure_threshold=2)

        def fail_fn():
            raise ValueError("fail")

        ctx = ReliabilityContext(metadata={"_callable": fail_fn})

        cb.apply(ctx, policy)
        cb.apply(ctx, policy)
        assert cb.state == CircuitState.OPEN

        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        result = cb.apply(ctx, policy)

        assert result.success is False
        assert "OPEN" in result.error
        assert cb.total_rejections == 1

    def test_open_does_not_increment_failure_count_further(self):
        cb = CircuitBreakerReliability()
        policy = CircuitBreakerPolicy(failure_threshold=2)

        def fail_fn():
            raise ValueError("fail")

        ctx = ReliabilityContext(metadata={"_callable": fail_fn})

        cb.apply(ctx, policy)
        cb.apply(ctx, policy)
        assert cb.failure_count == 2

        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        cb.apply(ctx, policy)
        assert cb.failure_count == 2


# ============================================================
# 3. OPEN → HALF_OPEN → CLOSED 恢复
# ============================================================

class TestCircuitBreakerRecovery:

    def test_open_to_half_open_after_timeout(self):
        cb = CircuitBreakerReliability()
        policy = CircuitBreakerPolicy(failure_threshold=2, recovery_timeout_ms=50)

        def fail_fn():
            raise ValueError("fail")

        ctx = ReliabilityContext(metadata={"_callable": fail_fn})

        cb.apply(ctx, policy)
        cb.apply(ctx, policy)
        assert cb.state == CircuitState.OPEN

        time.sleep(0.1)

        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        result = cb.apply(ctx, policy)

        assert result.success is True
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_half_open_failure_returns_to_open(self):
        cb = CircuitBreakerReliability()
        policy = CircuitBreakerPolicy(failure_threshold=2, recovery_timeout_ms=50)

        def fail_fn():
            raise ValueError("fail")

        ctx = ReliabilityContext(metadata={"_callable": fail_fn})

        cb.apply(ctx, policy)
        cb.apply(ctx, policy)
        assert cb.state == CircuitState.OPEN

        time.sleep(0.1)

        cb.apply(ctx, policy)
        assert cb.state == CircuitState.OPEN


# ============================================================
# 4. 无 callable — skeleton 兼容
# ============================================================

class TestCircuitBreakerNoCallable:

    def test_circuit_breaker_without_callable(self):
        cb = CircuitBreakerReliability()
        ctx = ReliabilityContext()
        result = cb.apply(ctx, CircuitBreakerPolicy())

        assert result.success is True
        assert result.circuit_state == CircuitState.CLOSED.value

    def test_circuit_breaker_supports_always_true(self):
        cb = CircuitBreakerReliability()
        assert cb.supports(ReliabilityContext()) is True

    def test_circuit_breaker_mechanism_name(self):
        cb = CircuitBreakerReliability()
        assert cb.mechanism_name == "circuit_breaker"

    def test_circuit_breaker_mechanism_type(self):
        cb = CircuitBreakerReliability()
        assert cb.mechanism_type == ReliabilityType.CIRCUIT_BREAKER


# ============================================================
# 5. CircuitBreaker 属性
# ============================================================

class TestCircuitBreakerProperties:

    def test_reset_clears_all_state(self):
        cb = CircuitBreakerReliability()
        policy = CircuitBreakerPolicy(failure_threshold=2)

        def fail_fn():
            raise ValueError("fail")

        ctx = ReliabilityContext(metadata={"_callable": fail_fn})
        cb.apply(ctx, policy)
        cb.apply(ctx, policy)

        assert cb.state == CircuitState.OPEN
        assert cb.failure_count == 2

        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
        assert cb.total_rejections == 0
        assert cb.total_successes == 0
        assert cb.total_failures == 0

    def test_total_failures_count(self):
        cb = CircuitBreakerReliability()
        policy = CircuitBreakerPolicy(failure_threshold=5)

        def fail_fn():
            raise ValueError("fail")

        ctx = ReliabilityContext(metadata={"_callable": fail_fn})
        cb.apply(ctx, policy)
        cb.apply(ctx, policy)

        assert cb.total_failures == 2

    def test_total_successes_count(self):
        cb = CircuitBreakerReliability()
        policy = CircuitBreakerPolicy(failure_threshold=5)

        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        cb.apply(ctx, policy)
        cb.apply(ctx, policy)

        assert cb.total_successes == 2


# ============================================================
# 6. Engine Pipeline 集成
# ============================================================

class TestCircuitBreakerPipeline:

    def test_engine_pipeline_includes_circuit_breaker(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        result = engine.execute_pipeline(ctx)

        assert isinstance(result, PipelineResult)
        assert "circuit_breaker" in result.pipeline_order

    def test_engine_pipeline_circuit_breaker_order(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        result = engine.execute_pipeline(ctx)

        assert "circuit_breaker" in result.pipeline_order
        cb_idx = result.pipeline_order.index("circuit_breaker")
        timeout_idx = result.pipeline_order.index("timeout")
        retry_idx = result.pipeline_order.index("retry")
        assert timeout_idx < cb_idx
        assert retry_idx < cb_idx

    def test_pipeline_success_with_all_mechanisms(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        result = engine.execute_pipeline(ctx)

        assert result.success is True
        assert len(result.pipeline_order) == 6

    def test_pipeline_circuit_breaker_with_custom_policy(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        pipeline = [
            ("circuit_breaker", CircuitBreakerPolicy(failure_threshold=10, recovery_timeout_ms=500)),
        ]
        result = engine.execute_pipeline(ctx, pipeline=pipeline)

        assert result.success is True
        assert result.pipeline_order == ["circuit_breaker"]

    def test_pipeline_circuit_breaker_stops_when_open(self):
        engine = ReliabilityEngine()
        policy = CircuitBreakerPolicy(failure_threshold=2, recovery_timeout_ms=10000)

        def fail_fn():
            raise ValueError("fail")

        ctx = ReliabilityContext(metadata={"_callable": fail_fn})
        pipeline = [("circuit_breaker", policy)]

        engine.execute_pipeline(ctx, pipeline=pipeline)
        engine.execute_pipeline(ctx, pipeline=pipeline)

        cb = None
        for name in ["circuit_breaker"]:
            mechanism = engine._create_mechanism(name)
            if hasattr(mechanism, "state"):
                cb = mechanism
                break

        if cb is None:
            pytest.skip("Cannot access circuit breaker state from engine")

        assert cb.state == CircuitState.OPEN


# ============================================================
# 7. RuntimeState.circuit_state / failure_count
# ============================================================

class TestRuntimeStateCircuit:

    def test_circuit_state_default_none(self):
        state = RuntimeState()
        assert state.circuit_state is None

    def test_circuit_state_settable(self):
        state = RuntimeState()
        state.circuit_state = "open"
        assert state.circuit_state == "open"

    def test_failure_count_default_zero(self):
        state = RuntimeState()
        assert state.failure_count == 0

    def test_failure_count_settable(self):
        state = RuntimeState()
        state.failure_count = 5
        assert state.failure_count == 5


# ============================================================
# 8. Engine single apply circuit breaker
# ============================================================

class TestEngineSingleCircuitBreaker:

    def test_engine_apply_circuit_breaker_normal(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        result = engine.apply(
            ctx,
            ReliabilityType.CIRCUIT_BREAKER,
            CircuitBreakerPolicy(failure_threshold=3),
        )

        assert result.success is True
        assert result.policy == ReliabilityType.CIRCUIT_BREAKER
        assert result.circuit_state == CircuitState.CLOSED.value

    def test_engine_apply_circuit_breaker_multiple_failures(self):
        engine = ReliabilityEngine()

        def fail_fn():
            raise ValueError("fail")

        ctx = ReliabilityContext(metadata={"_callable": fail_fn})
        policy = CircuitBreakerPolicy(failure_threshold=2)

        engine.apply(ctx, ReliabilityType.CIRCUIT_BREAKER, policy)
        result = engine.apply(ctx, ReliabilityType.CIRCUIT_BREAKER, policy)

        assert result.success is False
        assert result.circuit_state == CircuitState.OPEN.value


# ============================================================
# 9. 回归 — 无 Reliability 兼容
# ============================================================

class TestCircuitBreakerRegression:

    def test_no_circuit_breaker_still_works(self):
        from agent.reliability import ReliabilityRegistry

        assert "circuit_breaker" in ReliabilityRegistry.list_mechanisms()

    def test_old_mechanisms_still_work(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext()
        for rtype in ReliabilityType:
            result = engine.apply(ctx, rtype)
            assert result.success is True
