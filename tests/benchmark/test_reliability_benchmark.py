# ============================================================
# test_reliability_benchmark.py
# Reliability Framework Benchmark & Regression
# ============================================================
# 验证：
#   1. Retry Accuracy          — 成功重试、退避次数、最大重试次数
#   2. Timeout Accuracy        — 正常完成、超时、超时后恢复
#   3. Circuit Breaker         — CLOSED → OPEN → HALF_OPEN → CLOSED
#   4. Health Check            — Healthy、Unhealthy、缓存间隔
#   5. Rate Limiter            — 正常、限流、窗口恢复、连续调用
#   6. Fallback                — 主成功、备用成功、全部失败、无备用
#   7. Pipeline                — 六机制协同运行
#   8. Performance             — 延迟与吞吐
#   9. Stability               — 多次重复运行结果一致
#  10. Failure Benchmark       — 生产环境故障场景
# ============================================================

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


import agent.reliability.mechanisms  # noqa: F401
from agent.reliability import (
    CircuitBreakerPolicy,
    FallbackPolicy,
    HealthCheckPolicy,
    PipelineResult,
    RateLimiterPolicy,
    ReliabilityContext,
    ReliabilityEngine,
    ReliabilityType,
    RetryPolicy,
    TimeoutPolicy,
)
from agent.reliability.mechanisms.circuit_breaker_reliability import CircuitBreakerReliability
from agent.reliability.mechanisms.fallback_reliability import FallbackReliability
from agent.reliability.mechanisms.health_check_reliability import HealthCheckReliability
from agent.reliability.mechanisms.rate_limiter_reliability import RateLimiterReliability
from agent.reliability.mechanisms.retry_reliability import RetryReliability
from agent.reliability.mechanisms.timeout_reliability import TimeoutReliability

# ============================================================
# 1. Retry Accuracy
# ============================================================

class TestRetryAccuracy:

    def test_retry_success_after_failures(self):
        retry = RetryReliability()
        call_count = {"count": 0}

        def flaky():
            call_count["count"] += 1
            if call_count["count"] < 3:
                raise ValueError("transient")
            return "ok"

        ctx = ReliabilityContext(metadata={"_callable": flaky})
        policy = RetryPolicy(max_retries=5, backoff_ms=1)

        result = retry.apply(ctx, policy)
        assert result.success is True
        assert call_count["count"] == 3
        assert result.retry_count == 2

    def test_retry_exhausted(self):
        retry = RetryReliability()
        call_count = {"count": 0}

        def always_fail():
            call_count["count"] += 1
            raise ValueError("always fail")

        ctx = ReliabilityContext(metadata={"_callable": always_fail})
        policy = RetryPolicy(max_retries=3, backoff_ms=1)

        result = retry.apply(ctx, policy)
        assert result.success is False
        assert call_count["count"] == 4
        assert result.retry_count == 3

    def test_backoff_count_accurate(self):
        retry = RetryReliability()
        call_count = {"count": 0}

        def flaky():
            call_count["count"] += 1
            if call_count["count"] < 2:
                raise ValueError("transient")
            return "ok"

        ctx = ReliabilityContext(metadata={"_callable": flaky})
        policy = RetryPolicy(max_retries=5, backoff_ms=1)

        result = retry.apply(ctx, policy)
        assert result.success is True
        assert result.retry_count == 1

    def test_max_retries_respected(self):
        retry = RetryReliability()
        call_count = {"count": 0}

        def always_fail():
            call_count["count"] += 1
            raise ValueError("fail")

        ctx = ReliabilityContext(metadata={"_callable": always_fail})
        policy = RetryPolicy(max_retries=2, backoff_ms=1)

        result = retry.apply(ctx, policy)
        assert result.success is False
        assert call_count["count"] == 3

    def test_retry_metadata_contains_attempts(self):
        retry = RetryReliability()
        call_count = {"count": 0}

        def flaky():
            call_count["count"] += 1
            if call_count["count"] < 2:
                raise ValueError("transient")
            return "ok"

        ctx = ReliabilityContext(metadata={"_callable": flaky})
        policy = RetryPolicy(max_retries=5, backoff_ms=1)

        result = retry.apply(ctx, policy)
        assert result.metadata.get("attempts") == 2


# ============================================================
# 2. Timeout Accuracy
# ============================================================

class TestTimeoutAccuracy:

    def test_timeout_completes_normally(self):
        t = TimeoutReliability()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        policy = TimeoutPolicy(timeout_ms=5000)

        result = t.apply(ctx, policy)
        assert result.success is True
        assert result.timeout_occurred is False

    def test_timeout_exceeded(self):
        t = TimeoutReliability()

        def slow():
            time.sleep(0.15)
            return "ok"

        ctx = ReliabilityContext(metadata={"_callable": slow})
        policy = TimeoutPolicy(timeout_ms=50)

        result = t.apply(ctx, policy)
        assert result.success is False
        assert result.timeout_occurred is True

    def test_timeout_after_exceeded_returns_false(self):
        t = TimeoutReliability()

        def slow():
            time.sleep(0.1)
            return "ok"

        ctx = ReliabilityContext(metadata={"_callable": slow})
        policy = TimeoutPolicy(timeout_ms=10)

        result = t.apply(ctx, policy)
        assert result.success is False

    def test_timeout_reset_clears_count(self):
        t = TimeoutReliability()
        t.reset()

        def slow():
            time.sleep(0.15)
            return "ok"

        ctx = ReliabilityContext(metadata={"_callable": slow})
        policy = TimeoutPolicy(timeout_ms=50)

        t.apply(ctx, policy)
        assert t.timeout_count == 1

        t.reset()
        assert t.timeout_count == 0


# ============================================================
# 3. Circuit Breaker Accuracy
# ============================================================

class TestCircuitBreakerAccuracy:

    def test_closed_to_open_transition(self):
        cb = CircuitBreakerReliability()
        fail_ctx = ReliabilityContext(metadata={"_callable": lambda: 1 / 0})
        policy = CircuitBreakerPolicy(failure_threshold=3, recovery_timeout_ms=100)

        for _ in range(3):
            result = cb.apply(fail_ctx, policy)
            assert result.success is False

        result = cb.apply(fail_ctx, policy)
        assert result.success is False
        assert result.metadata.get("state") == "open"

    def test_open_to_half_open_transition(self):
        cb = CircuitBreakerReliability()
        fail_ctx = ReliabilityContext(metadata={"_callable": lambda: 1 / 0})
        policy = CircuitBreakerPolicy(failure_threshold=2, recovery_timeout_ms=50)

        for _ in range(2):
            cb.apply(fail_ctx, policy)

        assert cb.apply(fail_ctx, policy).metadata.get("state") == "open"

        time.sleep(0.1)

        ok_ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        result = cb.apply(ok_ctx, policy)
        assert result.success is True

    def test_half_open_to_closed_transition(self):
        cb = CircuitBreakerReliability()
        fail_ctx = ReliabilityContext(metadata={"_callable": lambda: 1 / 0})
        policy = CircuitBreakerPolicy(failure_threshold=2, recovery_timeout_ms=50)

        for _ in range(2):
            cb.apply(fail_ctx, policy)

        time.sleep(0.1)

        ok_ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        for _ in range(3):
            result = cb.apply(ok_ctx, policy)
            assert result.success is True

        assert cb.apply(ok_ctx, policy).metadata.get("state") == "closed"

    def test_half_open_failure_reopens(self):
        cb = CircuitBreakerReliability()
        fail_ctx = ReliabilityContext(metadata={"_callable": lambda: 1 / 0})
        policy = CircuitBreakerPolicy(failure_threshold=2, recovery_timeout_ms=50)

        for _ in range(2):
            cb.apply(fail_ctx, policy)

        time.sleep(0.1)

        cb.apply(fail_ctx, policy)
        assert cb.apply(fail_ctx, policy).metadata.get("state") == "open"

    def test_full_state_transition_cycle(self):
        cb = CircuitBreakerReliability()
        fail_ctx = ReliabilityContext(metadata={"_callable": lambda: 1 / 0})
        ok_ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        policy = CircuitBreakerPolicy(failure_threshold=2, recovery_timeout_ms=50)

        for _ in range(2):
            cb.apply(fail_ctx, policy)
        assert cb.apply(fail_ctx, policy).metadata.get("state") == "open"

        time.sleep(0.1)

        for _ in range(3):
            cb.apply(ok_ctx, policy)
        assert cb.apply(ok_ctx, policy).metadata.get("state") == "closed"


# ============================================================
# 4. Health Check Accuracy
# ============================================================

class TestHealthCheckAccuracy:

    def test_healthy_passes(self):
        hc = HealthCheckReliability()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        policy = HealthCheckPolicy(enabled=True, interval_ms=30000)

        result = hc.apply(ctx, policy)
        assert result.success is True
        assert result.metadata["health_status"] == "healthy"

    def test_unhealthy_causes_failure(self):
        hc = HealthCheckReliability()
        hc.set_unhealthy()

        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        policy = HealthCheckPolicy(enabled=True, interval_ms=30000)

        result = hc.apply(ctx, policy)
        assert result.success is False
        assert result.metadata["health_status"] == "unhealthy"

    def test_health_check_interval_caching(self):
        hc = HealthCheckReliability()
        hc.set_unhealthy()

        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        policy = HealthCheckPolicy(enabled=True, interval_ms=30000)

        result1 = hc.apply(ctx, policy)
        assert result1.success is False
        assert "cached unhealthy status" in result1.metadata.get("reason", "")

        hc.set_healthy()
        result2 = hc.apply(ctx, policy)
        assert result2.success is True
        assert "cached healthy status" in result2.metadata.get("reason", "")


# ============================================================
# 5. Rate Limiter Accuracy
# ============================================================

class TestRateLimiterAccuracy:

    def test_rate_limiter_normal(self):
        rl = RateLimiterReliability()
        ctx = ReliabilityContext()
        policy = RateLimiterPolicy(max_requests=10, window_ms=60000)

        for _ in range(10):
            result = rl.apply(ctx, policy)
            assert result.success is True

    def test_rate_limiter_blocked(self):
        rl = RateLimiterReliability()
        ctx = ReliabilityContext()
        policy = RateLimiterPolicy(max_requests=2, window_ms=60000)

        rl.apply(ctx, policy)
        rl.apply(ctx, policy)
        result = rl.apply(ctx, policy)

        assert result.success is False
        assert result.metadata["rate_limit_blocked"] is True

    def test_rate_limiter_window_recovery(self):
        rl = RateLimiterReliability()
        ctx = ReliabilityContext()
        policy = RateLimiterPolicy(max_requests=2, window_ms=50)

        rl.apply(ctx, policy)
        rl.apply(ctx, policy)
        assert rl.apply(ctx, policy).success is False

        time.sleep(0.1)

        result = rl.apply(ctx, policy)
        assert result.success is True

    def test_rate_limiter_consecutive_calls(self):
        rl = RateLimiterReliability()
        ctx = ReliabilityContext()
        policy = RateLimiterPolicy(max_requests=5, window_ms=60000)

        for i in range(5):
            result = rl.apply(ctx, policy)
            assert result.success is True
            assert result.metadata["rate_limit_remaining"] == 4 - i


# ============================================================
# 6. Fallback Accuracy
# ============================================================

class TestFallbackAccuracy:

    def test_fallback_primary_success(self):
        fb = FallbackReliability()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        policy = FallbackPolicy(
            enabled=True,
            fallback_function=lambda: "fallback",
        )

        result = fb.apply(ctx, policy)
        assert result.success is True
        assert result.metadata["fallback_used"] is False

    def test_fallback_fallback_success(self):
        fb = FallbackReliability()

        def fail_primary():
            raise ValueError("primary down")

        ctx = ReliabilityContext(metadata={"_callable": fail_primary})
        policy = FallbackPolicy(
            enabled=True,
            fallback_function=lambda: "fallback_ok",
        )

        result = fb.apply(ctx, policy)
        assert result.success is True
        assert result.metadata["fallback_used"] is True
        assert result.metadata["fallback_success"] is True

    def test_fallback_both_fail(self):
        fb = FallbackReliability()

        def fail_primary():
            raise ValueError("primary down")

        def fail_fallback():
            raise RuntimeError("fallback also down")

        ctx = ReliabilityContext(metadata={"_callable": fail_primary})
        policy = FallbackPolicy(
            enabled=True,
            fallback_function=fail_fallback,
        )

        result = fb.apply(ctx, policy)
        assert result.success is False
        assert result.metadata["fallback_used"] is True
        assert result.metadata["fallback_success"] is False

    def test_fallback_no_fallback_configured(self):
        fb = FallbackReliability()

        def fail_primary():
            raise ValueError("primary down")

        ctx = ReliabilityContext(metadata={"_callable": fail_primary})
        policy = FallbackPolicy(enabled=True)

        result = fb.apply(ctx, policy)
        assert result.success is False
        assert "primary_error" in result.metadata


# ============================================================
# 7. Pipeline Accuracy
# ============================================================

class TestPipelineAccuracy:

    def test_full_pipeline_success(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        result = engine.execute_pipeline(ctx)

        assert isinstance(result, PipelineResult)
        assert result.success is True
        assert result.pipeline_order == [
            "health_check", "rate_limiter", "timeout",
            "retry", "circuit_breaker", "fallback",
        ]

    def test_pipeline_order_consistent(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})

        results = []
        for _ in range(3):
            results.append(engine.execute_pipeline(ctx))

        for r in results:
            assert r.success is True
            assert r.pipeline_order == [
                "health_check", "rate_limiter", "timeout",
                "retry", "circuit_breaker", "fallback",
            ]

    def test_pipeline_with_retry_recovery(self):
        engine = ReliabilityEngine()
        call_count = {"count": 0}

        def flaky():
            call_count["count"] += 1
            if call_count["count"] < 2:
                raise ValueError("transient")
            return "ok"

        ctx = ReliabilityContext(metadata={"_callable": flaky})
        result = engine.execute_pipeline(ctx)

        assert result.success is True
        assert call_count["count"] == 2

    def test_custom_pipeline_works(self):
        engine = ReliabilityEngine()
        engine.set_pipeline([
            ("timeout", TimeoutPolicy(timeout_ms=5000)),
            ("retry", RetryPolicy(max_retries=3, backoff_ms=1)),
        ])

        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        result = engine.execute_pipeline(ctx)

        assert result.success is True
        assert result.pipeline_order == ["timeout", "retry"]

    def test_pipeline_empty_without_callable(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext()
        result = engine.execute_pipeline(ctx)

        assert result.success is True
        assert "no callable in context" in result.metadata["reason"]


# ============================================================
# 8. Performance Benchmark
# ============================================================

class TestPerformanceBenchmark:

    def test_health_check_overhead(self):
        hc = HealthCheckReliability()
        ctx = ReliabilityContext(metadata={"_callable": lambda: None})
        policy = HealthCheckPolicy(enabled=True, interval_ms=30000)

        start = time.perf_counter()
        for _ in range(1000):
            hc.apply(ctx, policy)
        elapsed = (time.perf_counter() - start) * 1000

        avg = elapsed / 1000
        assert avg < 0.5, f"HealthCheck avg {avg:.3f}ms exceeds 0.5ms"

    def test_rate_limiter_overhead(self):
        rl = RateLimiterReliability()
        ctx = ReliabilityContext()
        policy = RateLimiterPolicy(max_requests=100000, window_ms=60000)

        start = time.perf_counter()
        for _ in range(1000):
            rl.apply(ctx, policy)
        elapsed = (time.perf_counter() - start) * 1000

        avg = elapsed / 1000
        assert avg < 0.5, f"RateLimiter avg {avg:.3f}ms exceeds 0.5ms"

    def test_timeout_wrapper_overhead(self):
        t = TimeoutReliability()
        ctx = ReliabilityContext(metadata={"_callable": lambda: None})
        policy = TimeoutPolicy(timeout_ms=5000)

        start = time.perf_counter()
        for _ in range(1000):
            t.apply(ctx, policy)
        elapsed = (time.perf_counter() - start) * 1000

        avg = elapsed / 1000
        assert avg < 1.0, f"Timeout avg {avg:.3f}ms exceeds 1.0ms"

    def test_retry_wrapper_overhead(self):
        retry = RetryReliability()
        ctx = ReliabilityContext(metadata={"_callable": lambda: None})
        policy = RetryPolicy(max_retries=3, backoff_ms=1)

        start = time.perf_counter()
        for _ in range(1000):
            retry.apply(ctx, policy)
        elapsed = (time.perf_counter() - start) * 1000

        avg = elapsed / 1000
        assert avg < 0.5, f"Retry avg {avg:.3f}ms exceeds 0.5ms"

    def test_circuit_breaker_overhead(self):
        cb = CircuitBreakerReliability()
        ctx = ReliabilityContext(metadata={"_callable": lambda: None})
        policy = CircuitBreakerPolicy(failure_threshold=3, recovery_timeout_ms=1000)

        start = time.perf_counter()
        for _ in range(1000):
            cb.apply(ctx, policy)
        elapsed = (time.perf_counter() - start) * 1000

        avg = elapsed / 1000
        assert avg < 0.5, f"CircuitBreaker avg {avg:.3f}ms exceeds 0.5ms"

    def test_full_pipeline_overhead(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext(metadata={"_callable": lambda: None})

        start = time.perf_counter()
        for _ in range(100):
            engine.execute_pipeline(ctx)
        elapsed = (time.perf_counter() - start) * 1000

        avg = elapsed / 100
        assert avg < 5, f"Full pipeline avg {avg:.3f}ms exceeds 5ms"


# ============================================================
# 9. Stability Benchmark
# ============================================================

class TestStability:

    def test_pipeline_100_runs_order_consistent(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})

        expected_order = [
            "health_check", "rate_limiter", "timeout",
            "retry", "circuit_breaker", "fallback",
        ]

        for _ in range(100):
            result = engine.execute_pipeline(ctx)
            assert result.success is True
            assert result.pipeline_order == expected_order

    def test_pipeline_100_runs_result_consistent(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})

        for _ in range(100):
            result = engine.execute_pipeline(ctx)
            assert result.success is True
            assert result.metadata["mechanism_count"] == 6

    def test_engine_apply_100_runs_consistent(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext()

        for _ in range(100):
            result = engine.apply(ctx, ReliabilityType.RETRY)
            assert result.success is True

    def test_mechanism_instance_stability(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext()

        for rtype in ReliabilityType:
            result = engine.apply(ctx, rtype)
            assert result.success is True


# ============================================================
# 10. Failure Benchmark
# ============================================================

class TestFailureBenchmark:

    def test_health_check_failure_blocks_provider(self):
        engine = ReliabilityEngine()
        engine.set_pipeline([
            ("health_check", HealthCheckPolicy(enabled=True, interval_ms=30000)),
            ("retry", RetryPolicy(max_retries=3, backoff_ms=1)),
        ])

        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        result = engine.execute_pipeline(ctx)
        assert result.success is True

        hc = engine._mechanism_instances["health_check"]
        hc.set_unhealthy()

        call_count = {"count": 0}

        def tracked():
            call_count["count"] += 1
            return "ok"

        ctx2 = ReliabilityContext(metadata={"_callable": tracked})
        result2 = engine.execute_pipeline(ctx2)
        assert result2.success is False
        assert call_count["count"] == 0

        hc.set_healthy()

    def test_rate_limit_exceeded_rejects(self):
        rl = RateLimiterReliability()
        ctx = ReliabilityContext()
        policy = RateLimiterPolicy(max_requests=1, window_ms=60000)

        rl.apply(ctx, policy)
        result = rl.apply(ctx, policy)

        assert result.success is False
        assert result.metadata["rate_limit_blocked"] is True

    def test_timeout_triggers_retry(self):
        engine = ReliabilityEngine()
        call_count = {"count": 0}

        def fail_then_succeed():
            call_count["count"] += 1
            if call_count["count"] == 1:
                raise RuntimeError("transient error")
            return "ok"

        pipeline = [
            ("retry", RetryPolicy(max_retries=3, backoff_ms=1)),
            ("timeout", TimeoutPolicy(timeout_ms=5000)),
        ]

        ctx = ReliabilityContext(metadata={"_callable": fail_then_succeed})
        result = engine.execute_pipeline(ctx, pipeline=pipeline)

        assert result.success is True
        assert call_count["count"] == 2

    def test_retry_exhaustion_records_in_circuit_breaker(self):
        engine = ReliabilityEngine()
        call_count = {"count": 0}

        def always_fail():
            call_count["count"] += 1
            raise ValueError("fail")

        ctx = ReliabilityContext(metadata={"_callable": always_fail})
        pipeline = [
            ("retry", RetryPolicy(max_retries=2, backoff_ms=1)),
            ("circuit_breaker", CircuitBreakerPolicy(failure_threshold=2, recovery_timeout_ms=5000)),
        ]

        for _ in range(3):
            engine.execute_pipeline(ctx, pipeline=pipeline)

        cb = engine._mechanism_instances.get("circuit_breaker")
        assert cb is not None
        assert cb._failure_count >= 2

    def test_circuit_breaker_open_rejects_immediately(self):
        cb = CircuitBreakerReliability()
        fail_ctx = ReliabilityContext(metadata={"_callable": lambda: 1 / 0})
        policy = CircuitBreakerPolicy(failure_threshold=2, recovery_timeout_ms=5000)

        for _ in range(2):
            cb.apply(fail_ctx, policy)

        result = cb.apply(fail_ctx, policy)
        assert result.success is False
        assert result.metadata.get("state") == "open"

    def test_fallback_success_returns_fallback_result(self):
        fb = FallbackReliability()

        def fail_primary():
            raise ValueError("primary down")

        ctx = ReliabilityContext(metadata={"_callable": fail_primary})
        policy = FallbackPolicy(
            enabled=True,
            fallback_function=lambda: "fallback_result",
        )

        result = fb.apply(ctx, policy)
        assert result.success is True
        assert result.metadata["fallback_used"] is True
        assert result.metadata["fallback_success"] is True

    def test_fallback_failure_pipeline_fails(self):
        engine = ReliabilityEngine()

        def fail_primary():
            raise ValueError("primary down")

        def fail_fallback():
            raise RuntimeError("fallback also down")

        ctx = ReliabilityContext(metadata={"_callable": fail_primary})
        pipeline = [
            ("fallback", FallbackPolicy(
                enabled=True,
                fallback_function=fail_fallback,
            )),
        ]

        result = engine.execute_pipeline(ctx, pipeline=pipeline)
        assert result.success is False


# ============================================================
# 11. Regression — 确保所有机制独立可用
# ============================================================

class TestRegressionAllMechanisms:

    def test_all_mechanisms_registered(self):
        from agent.reliability import ReliabilityRegistry

        expected = {
            "health_check", "rate_limiter", "timeout",
            "retry", "circuit_breaker", "fallback",
        }
        actual = set(ReliabilityRegistry.list_mechanisms())
        assert expected.issubset(actual)

    def test_all_mechanisms_apply_success(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext()

        for rtype in ReliabilityType:
            result = engine.apply(ctx, rtype)
            assert result.success is True

    def test_all_mechanisms_apply_with_callable(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})

        for rtype in ReliabilityType:
            result = engine.apply(ctx, rtype)
            assert result.success is True

    def test_get_pipeline_returns_all_mechanisms(self):
        engine = ReliabilityEngine()
        pipeline = engine.get_pipeline()
        assert len(pipeline) == 6

        names = [name for name, _ in pipeline]
        assert names == [
            "health_check", "rate_limiter", "timeout",
            "retry", "circuit_breaker", "fallback",
        ]
