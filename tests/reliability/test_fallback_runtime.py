# ============================================================
# test_fallback_runtime.py
# Fallback Runtime Integration Test Matrix
# ============================================================
# 验证：
#   1. 主 Provider 成功，不触发 Fallback
#   2. 主 Provider 失败，Fallback 成功
#   3. 主 Provider 失败，Fallback 也失败
#   4. 未配置 Fallback 时透传异常
#   5. 无 callable 模式（skeleton backward compat）
#   6. Engine Pipeline 集成
#   7. Fallback 属性
# ============================================================

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


# Ensure mechanisms are auto-registered
import agent.reliability.mechanisms  # noqa: F401
from agent.reliability import (
    FallbackPolicy,
    PipelineResult,
    ReliabilityContext,
    ReliabilityEngine,
    ReliabilityType,
)
from agent.reliability.mechanisms.fallback_reliability import FallbackReliability
from agent.runtime_state import RuntimeState

# ============================================================
# 1. 主 Provider 成功，不触发 Fallback
# ============================================================

class TestFallbackPrimarySuccess:

    def test_primary_success_no_fallback(self):
        fb = FallbackReliability()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        policy = FallbackPolicy(
            enabled=True,
            fallback_function=lambda: "fallback",
        )

        result = fb.apply(ctx, policy)
        assert result.success is True
        assert result.metadata["fallback_used"] is False

    def test_primary_success_no_fallback_configured(self):
        fb = FallbackReliability()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        policy = FallbackPolicy(enabled=True)

        result = fb.apply(ctx, policy)
        assert result.success is True
        assert result.metadata["fallback_used"] is False


# ============================================================
# 2. 主 Provider 失败，Fallback 成功
# ============================================================

class TestFallbackSuccess:

    def test_primary_fails_fallback_succeeds(self):
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
        assert fb.fallback_successes == 1

    def test_fallback_counter_increments(self):
        fb = FallbackReliability()

        def fail_primary():
            raise ValueError("primary down")

        ctx = ReliabilityContext(metadata={"_callable": fail_primary})
        policy = FallbackPolicy(
            enabled=True,
            fallback_function=lambda: "ok",
        )

        fb.apply(ctx, policy)
        assert fb.total_fallbacks == 1
        assert fb.fallback_successes == 1
        assert fb.fallback_failures == 0


# ============================================================
# 3. 主 Provider 失败，Fallback 也失败
# ============================================================

class TestFallbackBothFail:

    def test_both_fail(self):
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
        assert "primary_error" in result.metadata
        assert "fallback_error" in result.metadata
        assert fb.fallback_failures == 1


# ============================================================
# 4. 未配置 Fallback 时透传异常
# ============================================================

class TestFallbackNoConfig:

    def test_no_fallback_configured_propagates_error(self):
        fb = FallbackReliability()

        def fail_primary():
            raise ValueError("primary down")

        ctx = ReliabilityContext(metadata={"_callable": fail_primary})
        policy = FallbackPolicy(enabled=True)

        result = fb.apply(ctx, policy)
        assert result.success is False
        assert result.metadata["fallback_used"] is False
        assert "primary_error" in result.metadata

    def test_disabled_skips_fallback(self):
        fb = FallbackReliability()

        def fail_primary():
            raise ValueError("primary down")

        ctx = ReliabilityContext(metadata={"_callable": fail_primary})
        policy = FallbackPolicy(enabled=False)

        result = fb.apply(ctx, policy)
        assert result.success is True
        assert result.metadata["fallback_used"] is False


# ============================================================
# 5. 无 callable — skeleton 兼容
# ============================================================

class TestFallbackNoCallable:

    def test_fallback_without_callable(self):
        fb = FallbackReliability()
        ctx = ReliabilityContext()
        result = fb.apply(ctx, FallbackPolicy())

        assert result.success is True
        assert result.metadata["fallback_used"] is False

    def test_fallback_supports_always_true(self):
        fb = FallbackReliability()
        assert fb.supports(ReliabilityContext()) is True

    def test_fallback_mechanism_name(self):
        fb = FallbackReliability()
        assert fb.mechanism_name == "fallback"

    def test_fallback_mechanism_type(self):
        fb = FallbackReliability()
        assert fb.mechanism_type == ReliabilityType.FALLBACK


# ============================================================
# 6. Engine Pipeline 集成
# ============================================================

class TestFallbackPipeline:

    def test_engine_pipeline_includes_fallback(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        result = engine.execute_pipeline(ctx)

        assert isinstance(result, PipelineResult)
        assert "fallback" in result.pipeline_order

    def test_engine_pipeline_fallback_last(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        result = engine.execute_pipeline(ctx)

        assert result.pipeline_order[-1] == "fallback"

    def test_engine_pipeline_fallback_catches_failure(self):
        engine = ReliabilityEngine()

        def fail_primary():
            raise ValueError("primary down")

        ctx = ReliabilityContext(metadata={"_callable": fail_primary})
        pipeline = [
            ("fallback", FallbackPolicy(
                enabled=True,
                fallback_function=lambda: "fallback_ok",
            )),
        ]

        result = engine.execute_pipeline(ctx, pipeline=pipeline)
        assert result.success is True

    def test_engine_pipeline_fallback_only_no_fallback(self):
        engine = ReliabilityEngine()

        def fail_primary():
            raise ValueError("primary down")

        ctx = ReliabilityContext(metadata={"_callable": fail_primary})
        pipeline = [
            ("fallback", FallbackPolicy(enabled=True)),
        ]

        result = engine.execute_pipeline(ctx, pipeline=pipeline)
        assert result.success is False


# ============================================================
# 7. Fallback 属性
# ============================================================

class TestFallbackProperties:

    def test_reset_clears_all_state(self):
        fb = FallbackReliability()

        def fail_primary():
            raise ValueError("primary down")

        ctx = ReliabilityContext(metadata={"_callable": fail_primary})
        policy = FallbackPolicy(
            enabled=True,
            fallback_function=lambda: "ok",
        )

        fb.apply(ctx, policy)
        assert fb.total_fallbacks == 1

        fb.reset()
        assert fb.total_fallbacks == 0
        assert fb.fallback_successes == 0
        assert fb.fallback_failures == 0


# ============================================================
# 8. RuntimeState.fallback_used
# ============================================================

class TestRuntimeStateFallback:

    def test_fallback_used_default_false(self):
        state = RuntimeState()
        assert state.fallback_used is False

    def test_fallback_used_settable(self):
        state = RuntimeState()
        state.fallback_used = True
        assert state.fallback_used is True


# ============================================================
# 9. Engine single apply fallback
# ============================================================

class TestEngineSingleFallback:

    def test_engine_apply_fallback_primary_success(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        result = engine.apply(
            ctx,
            ReliabilityType.FALLBACK,
            FallbackPolicy(enabled=True),
        )

        assert result.success is True
        assert result.policy == ReliabilityType.FALLBACK
        assert result.metadata["fallback_used"] is False

    def test_engine_apply_fallback_with_fallback_function(self):
        engine = ReliabilityEngine()

        def fail_primary():
            raise ValueError("primary down")

        ctx = ReliabilityContext(metadata={"_callable": fail_primary})
        policy = FallbackPolicy(
            enabled=True,
            fallback_function=lambda: "saved",
        )

        result = engine.apply(ctx, ReliabilityType.FALLBACK, policy)
        assert result.success is True
        assert result.metadata["fallback_used"] is True


# ============================================================
# 10. set_pipeline() 可配置 Pipeline
# ============================================================

class TestConfigurablePipeline:

    def test_set_pipeline_works(self):
        engine = ReliabilityEngine()
        engine.set_pipeline([
            ("timeout", None),
            ("retry", None),
        ])

        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        result = engine.execute_pipeline(ctx)

        assert result.success is True
        assert result.pipeline_order == ["timeout", "retry"]
        assert len(result.pipeline_order) == 2

    def test_get_pipeline_returns_default(self):
        engine = ReliabilityEngine()
        pipeline = engine.get_pipeline()
        assert len(pipeline) == 6

    def test_get_pipeline_returns_custom(self):
        engine = ReliabilityEngine()
        engine.set_pipeline([
            ("retry", None),
        ])
        pipeline = engine.get_pipeline()
        assert len(pipeline) == 1

    def test_set_pipeline_resets_to_default(self):
        engine = ReliabilityEngine()
        engine.set_pipeline([
            ("retry", None),
        ])
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        result = engine.execute_pipeline(ctx)

        assert result.pipeline_order == ["retry"]

        result2 = engine.execute_pipeline(ctx, pipeline=None)
        assert result2.pipeline_order == ["retry"]


# ============================================================
# 11. 回归
# ============================================================

class TestFallbackRegression:

    def test_registry_has_fallback(self):
        from agent.reliability import ReliabilityRegistry

        assert "fallback" in ReliabilityRegistry.list_mechanisms()

    def test_old_mechanisms_still_work(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext()
        for rtype in ReliabilityType:
            result = engine.apply(ctx, rtype)
            assert result.success is True
