# ============================================================
# test_reliability_engine.py
# ReliabilityEngine Test Matrix
# ============================================================
# 验证：
#   1. ReliabilityEngine 创建
#   2. Engine 调用 Factory（间接验证）
#   3. Factory 调用 Registry（间接验证）
#   4. apply() 正常返回值
#   5. Enum + 字符串调用
#   6. Default Reliability（默认 Retry）
#   7. set_default_reliability_type()
#   8. before_apply Hook
#   9. after_apply Hook
#   10. Hook 执行顺序
#   11. ReliabilityNotSupported
#   12. Runtime 无耦合
# ============================================================

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pytest

# Ensure mechanisms are auto-registered
import agent.reliability.mechanisms  # noqa: F401
from agent.reliability import (
    BaseReliability,
    ReliabilityContext,
    ReliabilityEngine,
    ReliabilityNotSupported,
    ReliabilityPolicy,
    ReliabilityResult,
    ReliabilityType,
    RetryPolicy,
)

# ============================================================
# 1. Engine Creation
# ============================================================

class TestEngineCreation:

    def test_engine_instantiation(self):
        engine = ReliabilityEngine()
        assert engine is not None

    def test_engine_has_no_runtime_dependency(self):
        engine = ReliabilityEngine()
        assert engine._default_reliability_type == ReliabilityType.RETRY
        assert engine._before_apply_hooks == []
        assert engine._after_apply_hooks == []


# ============================================================
# 2. apply() — basic
# ============================================================

class TestEngineApply:

    def test_apply_returns_reliability_result(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext()
        result = engine.apply(ctx)
        assert isinstance(result, ReliabilityResult)

    def test_apply_default_is_retry(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext()
        result = engine.apply(ctx)
        assert result.policy == ReliabilityType.RETRY

    def test_apply_with_string(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext()
        result = engine.apply(ctx, "timeout")
        assert isinstance(result, ReliabilityResult)
        assert result.policy == ReliabilityType.TIMEOUT

    def test_apply_with_enum(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext()
        result = engine.apply(ctx, ReliabilityType.CIRCUIT_BREAKER)
        assert isinstance(result, ReliabilityResult)
        assert result.policy == ReliabilityType.CIRCUIT_BREAKER

    def test_apply_all_six_mechanisms(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext()
        expected = [
            "retry",
            "timeout",
            "circuit_breaker",
            "fallback",
            "health_check",
            "rate_limiter",
        ]
        for name in expected:
            result = engine.apply(ctx, name)
            assert result.success is True
            assert result.policy.value == name

    def test_apply_all_six_mechanisms_by_enum(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext()
        for rtype in ReliabilityType:
            result = engine.apply(ctx, rtype)
            assert result.success is True
            assert result.policy == rtype

    def test_apply_with_policy(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext()
        policy = RetryPolicy(max_retries=5, backoff_ms=500)
        result = engine.apply(ctx, ReliabilityType.RETRY, policy)
        assert isinstance(result, ReliabilityResult)
        assert result.policy == ReliabilityType.RETRY


# ============================================================
# 3. set_default_reliability_type()
# ============================================================

class TestEngineDefaultType:

    def test_default_is_retry(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext()
        result = engine.apply(ctx)
        assert result.policy == ReliabilityType.RETRY

    def test_set_default_by_enum(self):
        engine = ReliabilityEngine()
        engine.set_default_reliability_type(ReliabilityType.TIMEOUT)
        ctx = ReliabilityContext()
        result = engine.apply(ctx)
        assert result.policy == ReliabilityType.TIMEOUT

    def test_set_default_by_string(self):
        engine = ReliabilityEngine()
        engine.set_default_reliability_type("circuit_breaker")
        ctx = ReliabilityContext()
        result = engine.apply(ctx)
        assert result.policy == ReliabilityType.CIRCUIT_BREAKER

    def test_apply_overrides_default(self):
        engine = ReliabilityEngine()
        engine.set_default_reliability_type(ReliabilityType.TIMEOUT)
        ctx = ReliabilityContext()
        result = engine.apply(ctx, ReliabilityType.RETRY)
        assert result.policy == ReliabilityType.RETRY


# ============================================================
# 4. Hooks — before_apply / after_apply
# ============================================================

class TestEngineHooks:

    def test_before_apply_hook_called(self):
        engine = ReliabilityEngine()
        called = []

        def before_hook(ctx):
            called.append("before")

        engine.add_before_apply_hook(before_hook)
        engine.apply(ReliabilityContext())
        assert called == ["before"]

    def test_after_apply_hook_called(self):
        engine = ReliabilityEngine()
        called = []

        def after_hook(result):
            called.append("after")

        engine.add_after_apply_hook(after_hook)
        engine.apply(ReliabilityContext())
        assert called == ["after"]

    def test_both_hooks_called_in_order(self):
        engine = ReliabilityEngine()
        order = []

        def before_hook(ctx):
            order.append("before")

        def after_hook(result):
            order.append("after")

        engine.add_before_apply_hook(before_hook)
        engine.add_after_apply_hook(after_hook)
        engine.apply(ReliabilityContext())
        assert order == ["before", "after"]

    def test_multiple_before_hooks_called(self):
        engine = ReliabilityEngine()
        called = []

        def hook1(ctx):
            called.append("h1")

        def hook2(ctx):
            called.append("h2")

        engine.add_before_apply_hook(hook1)
        engine.add_before_apply_hook(hook2)
        engine.apply(ReliabilityContext())
        assert called == ["h1", "h2"]

    def test_multiple_after_hooks_called(self):
        engine = ReliabilityEngine()
        called = []

        def hook1(result):
            called.append("h1")

        def hook2(result):
            called.append("h2")

        engine.add_after_apply_hook(hook1)
        engine.add_after_apply_hook(hook2)
        engine.apply(ReliabilityContext())
        assert called == ["h1", "h2"]

    def test_hook_exception_dont_crash_engine(self):
        engine = ReliabilityEngine()

        def bad_hook(ctx):
            raise RuntimeError("hook crash")

        engine.add_before_apply_hook(bad_hook)
        result = engine.apply(ReliabilityContext())
        assert result.success is True

    def test_after_hook_exception_dont_crash_engine(self):
        engine = ReliabilityEngine()

        def bad_hook(result):
            raise RuntimeError("hook crash")

        engine.add_after_apply_hook(bad_hook)
        result = engine.apply(ReliabilityContext())
        assert result.success is True

    def test_hook_receives_context(self):
        engine = ReliabilityEngine()
        received = {}

        def hook(ctx):
            received["metadata"] = ctx.metadata

        ctx = ReliabilityContext(metadata={"key": "value"})
        engine.add_before_apply_hook(hook)
        engine.apply(ctx)
        assert received["metadata"] == {"key": "value"}

    def test_hook_receives_result(self):
        engine = ReliabilityEngine()
        received = {}

        def hook(result):
            received["success"] = result.success
            received["policy"] = result.policy

        engine.add_after_apply_hook(hook)
        engine.apply(ReliabilityContext())
        assert received["success"] is True
        assert received["policy"] == ReliabilityType.RETRY


# ============================================================
# 5. ReliabilityNotSupported
# ============================================================

class TestEngineNotSupported:

    def test_not_supported_is_exception(self):
        assert issubclass(ReliabilityNotSupported, Exception)

    def test_not_supported_with_message(self):
        err = ReliabilityNotSupported("Test message")
        assert str(err) == "Test message"

    def test_engine_raises_when_supports_false(self):
        from agent.reliability import ReliabilityRegistry

        class NonSupportingReliability(BaseReliability):
            @property
            def mechanism_name(self) -> str:
                return "no_support"
            @property
            def mechanism_type(self) -> ReliabilityType:
                return ReliabilityType.RETRY
            def supports(self, context: ReliabilityContext) -> bool:
                return False
            def apply(self, context: ReliabilityContext, policy: ReliabilityPolicy) -> ReliabilityResult:
                return ReliabilityResult()
            def reset(self) -> None:
                pass

        ReliabilityRegistry.register("no_support", NonSupportingReliability)

        engine = ReliabilityEngine()
        with pytest.raises(ReliabilityNotSupported, match="no_support"):
            engine.apply(ReliabilityContext(), "no_support")


# ============================================================
# 6. Integration — 端到端流程
# ============================================================

class TestEngineIntegration:

    def test_full_flow_with_all_mechanisms(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext(metadata={"phase": "test"})

        for rtype in ReliabilityType:
            result = engine.apply(ctx, rtype)
            assert isinstance(result, ReliabilityResult)
            assert result.success is True

    def test_engine_uses_factory_via_registry(self):
        from agent.reliability import ReliabilityRegistry

        engine = ReliabilityEngine()
        assert "retry" in ReliabilityRegistry.list_mechanisms()
        result = engine.apply(ReliabilityContext(), "retry")
        assert result is not None
        assert result.policy == ReliabilityType.RETRY

    def test_engine_does_not_modify_runtime(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext()
        result = engine.apply(ctx)
        assert result.success is True
        assert ctx.runtime_state is None


# ============================================================
# 7. No Runtime Coupling
# ============================================================

class TestEngineNoRuntimeCoupling:

    def test_engine_instantiation_no_runtime(self):
        engine = ReliabilityEngine()
        assert engine is not None

    def test_engine_apply_no_runtime(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext()
        result = engine.apply(ctx)
        assert isinstance(result, ReliabilityResult)

    def test_engine_source_no_runtime_import(self):
        import inspect
        import sys

        module = sys.modules["agent.reliability.reliability_engine"]
        source = inspect.getsource(module)
        assert "from agent.runtime_state" not in source
        assert "RuntimeState" not in source
