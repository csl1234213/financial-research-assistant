# ============================================================
# test_health_check_runtime.py
# Health Check Runtime Integration Test Matrix
# ============================================================
# 验证：
#   1. 默认为 Healthy
#   2. Healthy 状态允许调用
#   3. Unhealthy 状态拒绝调用
#   4. check_function 自定义检查
#   5. 跳过 Provider（unhealthy 时）
#   6. set_healthy / set_unhealthy
#   7. 无 callable 模式（skeleton backward compat）
#   8. Engine Pipeline 集成
#   9. 属性检查
# ============================================================

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

# Ensure mechanisms are auto-registered
import agent.reliability.mechanisms  # noqa: F401
from agent.reliability import (
    HealthCheckPolicy,
    PipelineResult,
    ReliabilityContext,
    ReliabilityEngine,
    ReliabilityType,
)
from agent.reliability.mechanisms.health_check_reliability import HealthCheckReliability
from agent.runtime_state import RuntimeState

# ============================================================
# 1. 默认为 Healthy
# ============================================================

class TestHealthCheckInitial:

    def test_initial_state_is_healthy(self):
        hc = HealthCheckReliability()
        assert hc.is_healthy is True

    def test_initial_check_count_zero(self):
        hc = HealthCheckReliability()
        assert hc.check_count == 0

    def test_initial_failed_check_count_zero(self):
        hc = HealthCheckReliability()
        assert hc.failed_check_count == 0


# ============================================================
# 2. Healthy 状态允许调用
# ============================================================

class TestHealthCheckHealthy:

    def test_healthy_without_callable(self):
        hc = HealthCheckReliability()
        ctx = ReliabilityContext()
        policy = HealthCheckPolicy(enabled=True, interval_ms=0)

        result = hc.apply(ctx, policy)
        assert result.success is True
        assert result.metadata["health_status"] == "healthy"

    def test_healthy_with_callable(self):
        hc = HealthCheckReliability()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        policy = HealthCheckPolicy(enabled=True, interval_ms=0)

        result = hc.apply(ctx, policy)
        assert result.success is True
        assert result.metadata["health_status"] == "healthy"

    def test_healthy_disabled_policy(self):
        hc = HealthCheckReliability()
        ctx = ReliabilityContext()
        policy = HealthCheckPolicy(enabled=False)

        result = hc.apply(ctx, policy)
        assert result.success is True
        assert result.metadata["health_status"] == "healthy"


# ============================================================
# 3. Unhealthy 状态拒绝调用
# ============================================================

class TestHealthCheckUnhealthy:

    def test_set_unhealthy_rejects(self):
        hc = HealthCheckReliability()
        hc.set_unhealthy()
        ctx = ReliabilityContext()
        policy = HealthCheckPolicy(enabled=True, interval_ms=0)

        result = hc.apply(ctx, policy)
        assert result.success is False
        assert result.metadata["health_status"] == "unhealthy"

    def test_unhealthy_cached_within_interval(self):
        hc = HealthCheckReliability()
        hc.set_unhealthy()
        ctx = ReliabilityContext()
        policy = HealthCheckPolicy(enabled=True, interval_ms=60000)

        result = hc.apply(ctx, policy)
        assert result.success is False
        assert "cached unhealthy status" in result.metadata["reason"]

    def test_set_healthy_restores(self):
        hc = HealthCheckReliability()
        hc.set_unhealthy()
        assert hc.is_healthy is False

        hc.set_healthy()
        assert hc.is_healthy is True


# ============================================================
# 4. check_function 自定义检查
# ============================================================

class TestHealthCheckCustomFunction:

    def test_check_function_returns_true(self):
        hc = HealthCheckReliability()
        hc.set_check_function(lambda: True)
        ctx = ReliabilityContext()
        policy = HealthCheckPolicy(enabled=True, interval_ms=0)

        result = hc.apply(ctx, policy)
        assert result.success is True
        assert result.metadata["health_status"] == "healthy"

    def test_check_function_returns_false(self):
        hc = HealthCheckReliability()
        hc.set_check_function(lambda: False)
        ctx = ReliabilityContext()
        policy = HealthCheckPolicy(enabled=True, interval_ms=0)

        result = hc.apply(ctx, policy)
        assert result.success is False
        assert result.metadata["health_status"] == "unhealthy"

    def test_check_function_raises_exception(self):
        hc = HealthCheckReliability()

        def bad_check():
            raise RuntimeError("network error")

        hc.set_check_function(bad_check)
        ctx = ReliabilityContext()
        policy = HealthCheckPolicy(enabled=True, interval_ms=0)

        result = hc.apply(ctx, policy)
        assert result.success is False
        assert result.metadata["health_status"] == "unhealthy"

    def test_policy_check_function_overrides_default(self):
        hc = HealthCheckReliability()
        hc.set_check_function(lambda: False)
        ctx = ReliabilityContext()
        policy = HealthCheckPolicy(
            enabled=True, interval_ms=0, check_function=lambda: True
        )

        result = hc.apply(ctx, policy)
        assert result.success is True
        assert result.metadata["health_status"] == "healthy"


# ============================================================
# 5. 无 callable — skeleton 兼容
# ============================================================

class TestHealthCheckNoCallable:

    def test_health_check_without_callable(self):
        hc = HealthCheckReliability()
        ctx = ReliabilityContext()
        result = hc.apply(ctx, HealthCheckPolicy())

        assert result.success is True

    def test_health_check_supports_always_true(self):
        hc = HealthCheckReliability()
        assert hc.supports(ReliabilityContext()) is True

    def test_health_check_mechanism_name(self):
        hc = HealthCheckReliability()
        assert hc.mechanism_name == "health_check"

    def test_health_check_mechanism_type(self):
        hc = HealthCheckReliability()
        assert hc.mechanism_type == ReliabilityType.HEALTH_CHECK


# ============================================================
# 6. Engine Pipeline 集成
# ============================================================

class TestHealthCheckPipeline:

    def test_engine_pipeline_includes_health_check(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        result = engine.execute_pipeline(ctx)

        assert isinstance(result, PipelineResult)
        assert "health_check" in result.pipeline_order

    def test_engine_pipeline_health_check_first(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        result = engine.execute_pipeline(ctx)

        assert result.pipeline_order[0] == "health_check"

    def test_engine_pipeline_with_custom_health_check(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        pipeline = [
            ("health_check", HealthCheckPolicy(enabled=True, interval_ms=0)),
        ]
        result = engine.execute_pipeline(ctx, pipeline=pipeline)

        assert result.success is True
        assert result.pipeline_order == ["health_check"]

    def test_engine_pipeline_unhealthy_blocks(self):
        engine = ReliabilityEngine()
        hc = engine._create_mechanism("health_check")
        hc.set_unhealthy()

        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        pipeline = [
            ("health_check", HealthCheckPolicy(enabled=True, interval_ms=0)),
        ]

        result = engine.execute_pipeline(ctx, pipeline=pipeline)
        assert result.success is False


# ============================================================
# 7. 属性
# ============================================================

class TestHealthCheckProperties:

    def test_reset_clears_all_state(self):
        hc = HealthCheckReliability()
        hc.set_unhealthy()
        hc.set_check_function(lambda: True)

        ctx = ReliabilityContext()
        hc.apply(ctx, HealthCheckPolicy(enabled=True, interval_ms=0))
        hc.apply(ctx, HealthCheckPolicy(enabled=True, interval_ms=0))

        assert hc.check_count > 0

        hc.reset()
        assert hc.is_healthy is True
        assert hc.check_count == 0
        assert hc.failed_check_count == 0

    def test_interval_caching(self):
        hc = HealthCheckReliability()
        hc.set_healthy()
        ctx = ReliabilityContext()
        policy = HealthCheckPolicy(enabled=True, interval_ms=60000)

        hc.apply(ctx, policy)
        result = hc.apply(ctx, policy)

        assert result.success is True
        assert "cached" in result.metadata["reason"]


# ============================================================
# 8. RuntimeState.health_status
# ============================================================

class TestRuntimeStateHealth:

    def test_health_status_default_none(self):
        state = RuntimeState()
        assert state.health_status is None

    def test_health_status_settable(self):
        state = RuntimeState()
        state.health_status = "healthy"
        assert state.health_status == "healthy"

    def test_health_status_unhealthy(self):
        state = RuntimeState()
        state.health_status = "unhealthy"
        assert state.health_status == "unhealthy"


# ============================================================
# 9. Engine single apply health check
# ============================================================

class TestEngineSingleHealthCheck:

    def test_engine_apply_health_check_normal(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext()
        result = engine.apply(
            ctx,
            ReliabilityType.HEALTH_CHECK,
            HealthCheckPolicy(enabled=True, interval_ms=0),
        )

        assert result.success is True
        assert result.policy == ReliabilityType.HEALTH_CHECK
        assert result.metadata["health_status"] == "healthy"

    def test_engine_apply_health_check_unhealthy(self):
        engine = ReliabilityEngine()
        hc = engine._create_mechanism("health_check")
        hc.set_unhealthy()

        ctx = ReliabilityContext()
        result = engine.apply(
            ctx,
            ReliabilityType.HEALTH_CHECK,
            HealthCheckPolicy(enabled=True, interval_ms=0),
        )

        assert result.success is False
        assert result.metadata["health_status"] == "unhealthy"


# ============================================================
# 10. 回归
# ============================================================

class TestHealthCheckRegression:

    def test_registry_has_health_check(self):
        from agent.reliability import ReliabilityRegistry

        assert "health_check" in ReliabilityRegistry.list_mechanisms()

    def test_old_mechanisms_still_work(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext()
        for rtype in ReliabilityType:
            result = engine.apply(ctx, rtype)
            assert result.success is True
