# ============================================================
# test_retry_runtime.py
# Retry Runtime Integration Test Matrix
# ============================================================
# 验证：
#   1. Provider Success — 一次成功，retry_count=0
#   2. Retry Success — 第二次成功，retry_count=1
#   3. Retry Failed — 全部失败，max_retries=3
#   4. Metrics — retry_total, retry_success 增加
#   5. ReliabilityBridge — RuntimeState → ReliabilityContext
#   6. RuntimeState.retry_count — 字段存在
#   7. RuntimeResult.reliability — 字段存在
#   8. 无 Retry 回归 — 旧流程 100% 兼容
#   9. Exponential backoff
#   10. RetryReliability — 直接调用 callable
#   11. Engine + Retry 集成
# ============================================================

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from unittest.mock import MagicMock, patch

import pytest

# Ensure mechanisms are auto-registered
import agent.reliability.mechanisms  # noqa: F401
from agent.reliability import (
    ReliabilityBridge,
    ReliabilityContext,
    ReliabilityEngine,
    ReliabilityType,
    RetryPolicy,
)
from agent.reliability.mechanisms.retry_reliability import RetryReliability
from agent.runtime_result import RuntimeResult
from agent.runtime_state import RuntimeState

# ============================================================
# 1. Provider Success — 一次成功
# ============================================================

class TestRetryProviderSuccess:

    def test_callable_succeeds_first_time(self):
        retry = RetryReliability()
        call_count = {"count": 0}

        def success_callable():
            call_count["count"] += 1
            return "success"

        ctx = ReliabilityContext(metadata={"_callable": success_callable})
        policy = RetryPolicy(max_retries=3, backoff_ms=10)

        result = retry.apply(ctx, policy)

        assert result.success is True
        assert result.retry_count == 0
        assert call_count["count"] == 1
        assert result.policy == ReliabilityType.RETRY

    def test_callable_succeeds_first_time_no_callable(self):
        retry = RetryReliability()
        ctx = ReliabilityContext()
        result = retry.apply(ctx, RetryPolicy())

        assert result.success is True
        assert result.retry_count == 0


# ============================================================
# 2. Retry Success — 第二次成功
# ============================================================

class TestRetrySuccess:

    def test_succeeds_on_second_attempt(self):
        retry = RetryReliability()
        call_count = {"count": 0}

        def flaky_callable():
            call_count["count"] += 1
            if call_count["count"] == 1:
                raise ValueError("first attempt failed")
            return "success"

        ctx = ReliabilityContext(metadata={"_callable": flaky_callable})
        policy = RetryPolicy(max_retries=3, backoff_ms=10)

        result = retry.apply(ctx, policy)

        assert result.success is True
        assert result.retry_count == 1
        assert call_count["count"] == 2

    def test_succeeds_on_last_attempt(self):
        retry = RetryReliability()
        call_count = {"count": 0}

        def stubborn_callable():
            call_count["count"] += 1
            if call_count["count"] <= 3:
                raise RuntimeError("fail")
            return "finally"

        ctx = ReliabilityContext(metadata={"_callable": stubborn_callable})
        policy = RetryPolicy(max_retries=3, backoff_ms=10)

        result = retry.apply(ctx, policy)

        assert result.success is True
        assert result.retry_count == 3
        assert call_count["count"] == 4


# ============================================================
# 3. Retry Failed — 全部失败
# ============================================================

class TestRetryFailed:

    def test_all_attempts_fail(self):
        retry = RetryReliability()
        call_count = {"count": 0}

        def always_fail():
            call_count["count"] += 1
            raise RuntimeError("always fails")

        ctx = ReliabilityContext(metadata={"_callable": always_fail})
        policy = RetryPolicy(max_retries=2, backoff_ms=10)

        result = retry.apply(ctx, policy)

        assert result.success is False
        assert result.retry_count == 2
        assert result.error == "always fails"
        assert call_count["count"] == 3

    def test_failed_result_has_error(self):
        retry = RetryReliability()

        def fail_fn():
            raise ValueError("specific error")

        ctx = ReliabilityContext(metadata={"_callable": fail_fn})
        policy = RetryPolicy(max_retries=1, backoff_ms=10)

        result = retry.apply(ctx, policy)

        assert result.success is False
        assert "specific error" in result.error
        assert result.retry_count == 1


# ============================================================
# 4. RetryReliability — 属性
# ============================================================

class TestRetryReliabilityProperties:

    def test_mechanism_name(self):
        retry = RetryReliability()
        assert retry.mechanism_name == "retry"

    def test_mechanism_type(self):
        retry = RetryReliability()
        assert retry.mechanism_type == ReliabilityType.RETRY

    def test_supports_always_true(self):
        retry = RetryReliability()
        assert retry.supports(ReliabilityContext()) is True

    def test_reset_clears_state(self):
        retry = RetryReliability()

        def fail_fn():
            raise RuntimeError("test error")

        ctx = ReliabilityContext(metadata={"_callable": fail_fn})
        retry.apply(ctx, RetryPolicy(max_retries=1, backoff_ms=10))

        assert retry.last_attempts == 1
        assert retry.last_error == "test error"

        retry.reset()
        assert retry.last_attempts == 0
        assert retry.last_error is None

    def test_last_attempts_after_success(self):
        retry = RetryReliability()
        call_count = {"count": 0}

        def flaky():
            call_count["count"] += 1
            if call_count["count"] == 1:
                raise ValueError("fail")
            return "ok"

        ctx = ReliabilityContext(metadata={"_callable": flaky})
        retry.apply(ctx, RetryPolicy(max_retries=3, backoff_ms=10))

        assert retry.last_attempts == 1
        assert retry.last_error is None


# ============================================================
# 5. Exponential Backoff
# ============================================================

class TestExponentialBackoff:

    def test_backoff_increases_exponentially(self):
        retry = RetryReliability()
        sleep_times = []

        def fail_then_succeed():
            if len(sleep_times) == 0:
                raise RuntimeError("fail")
            return "ok"

        with patch("time.sleep", side_effect=lambda s: sleep_times.append(s)):
            ctx = ReliabilityContext(metadata={"_callable": fail_then_succeed})
            policy = RetryPolicy(max_retries=3, backoff_ms=100)
            retry.apply(ctx, policy)

        assert len(sleep_times) == 1
        assert sleep_times[0] == pytest.approx(0.1, abs=0.01)

    def test_backoff_multiple_retries(self):
        retry = RetryReliability()
        sleep_times = []

        def always_fail():
            raise RuntimeError("fail")

        with patch("time.sleep", side_effect=lambda s: sleep_times.append(s)):
            ctx = ReliabilityContext(metadata={"_callable": always_fail})
            policy = RetryPolicy(max_retries=2, backoff_ms=100)
            retry.apply(ctx, policy)

        assert len(sleep_times) == 2
        assert sleep_times[0] == pytest.approx(0.1, abs=0.01)
        assert sleep_times[1] == pytest.approx(0.2, abs=0.01)


# ============================================================
# 6. ReliabilityBridge
# ============================================================

class TestReliabilityBridge:

    def test_bridge_creates_context(self):
        state = RuntimeState()
        ctx = ReliabilityBridge.to_reliability_context(state)
        assert isinstance(ctx, ReliabilityContext)

    def test_bridge_preserves_runtime_state(self):
        state = RuntimeState()
        ctx = ReliabilityBridge.to_reliability_context(state)
        assert ctx.runtime_state is state

    def test_bridge_with_metadata(self):
        state = RuntimeState()
        ctx = ReliabilityBridge.to_reliability_context(
            state,
            metadata={"phase": "test"},
        )
        assert ctx.metadata["phase"] == "test"

    def test_bridge_workflow_none_by_default(self):
        state = RuntimeState()
        ctx = ReliabilityBridge.to_reliability_context(state)
        assert ctx.workflow is None

    def test_bridge_execution_empty_by_default(self):
        state = RuntimeState()
        ctx = ReliabilityBridge.to_reliability_context(state)
        assert ctx.execution == []

    def test_bridge_tool_none_by_default(self):
        state = RuntimeState()
        ctx = ReliabilityBridge.to_reliability_context(state)
        assert ctx.tool is None

    def test_bridge_provider_none_by_default(self):
        state = RuntimeState()
        ctx = ReliabilityBridge.to_reliability_context(state)
        assert ctx.provider is None

    def test_bridge_with_routing(self):
        state = RuntimeState()
        state.routing = [{"provider": "gemini", "model": "gemini-pro"}]
        ctx = ReliabilityBridge.to_reliability_context(state)
        assert ctx.provider == {"provider": "gemini", "model": "gemini-pro"}

    def test_bridge_with_tool_results(self):
        state = RuntimeState()
        mock_tool = MagicMock()
        mock_tool.tool_name = "retrieval"
        state.tool_results = [mock_tool]
        ctx = ReliabilityBridge.to_reliability_context(state)
        assert ctx.tool is mock_tool


# ============================================================
# 7. RuntimeState.retry_count
# ============================================================

class TestRuntimeStateRetryCount:

    def test_retry_count_default_zero(self):
        state = RuntimeState()
        assert state.retry_count == 0

    def test_retry_count_settable(self):
        state = RuntimeState()
        state.retry_count = 2
        assert state.retry_count == 2


# ============================================================
# 8. RuntimeResult.reliability
# ============================================================

class TestRuntimeResultReliability:

    def test_reliability_field_default_none(self):
        result = RuntimeResult()
        assert result.reliability is None

    def test_reliability_field_settable(self):
        info = {
            "mechanism": "retry",
            "success": True,
            "retry_count": 1,
        }
        result = RuntimeResult(reliability=info)
        assert result.reliability == info
        assert result.reliability["retry_count"] == 1


# ============================================================
# 9. Engine + Retry Integration
# ============================================================

class TestEngineRetryIntegration:

    def test_engine_apply_with_callable(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        result = engine.apply(ctx, ReliabilityType.RETRY, RetryPolicy(max_retries=2, backoff_ms=10))

        assert result.success is True
        assert result.retry_count == 0
        assert result.policy == ReliabilityType.RETRY

    def test_engine_apply_retry_success_on_second_attempt(self):
        engine = ReliabilityEngine()
        call_count = {"count": 0}

        def flaky():
            call_count["count"] += 1
            if call_count["count"] == 1:
                raise ValueError("fail")
            return "ok"

        ctx = ReliabilityContext(metadata={"_callable": flaky})
        result = engine.apply(ctx, ReliabilityType.RETRY, RetryPolicy(max_retries=3, backoff_ms=10))

        assert result.success is True
        assert result.retry_count == 1
        assert call_count["count"] == 2

    def test_engine_apply_retry_failed(self):
        engine = ReliabilityEngine()

        def always_fail():
            raise RuntimeError("always fail")

        ctx = ReliabilityContext(metadata={"_callable": always_fail})
        result = engine.apply(ctx, ReliabilityType.RETRY, RetryPolicy(max_retries=1, backoff_ms=10))

        assert result.success is False
        assert result.error == "always fail"

    def test_engine_hooks_fire_during_retry(self):
        engine = ReliabilityEngine()
        hooks_called = []

        def before_hook(ctx):
            hooks_called.append("before")

        def after_hook(result):
            hooks_called.append("after")

        engine.add_before_apply_hook(before_hook)
        engine.add_after_apply_hook(after_hook)

        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        engine.apply(ctx, ReliabilityType.RETRY, RetryPolicy(max_retries=2, backoff_ms=10))

        assert hooks_called == ["before", "after"]


# ============================================================
# 10. 无 Retry 回归 — 旧流程 100% 兼容
# ============================================================

class TestNoRetryBackwardCompat:

    def test_retry_reliability_without_callable(self):
        retry = RetryReliability()
        ctx = ReliabilityContext()
        result = retry.apply(ctx, RetryPolicy())

        assert result.success is True
        assert result.retry_count == 0

    def test_engine_without_callable(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext()
        result = engine.apply(ctx, ReliabilityType.RETRY)

        assert result.success is True
        assert result.retry_count == 0
        assert result.policy == ReliabilityType.RETRY

    def test_all_mechanisms_still_work(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext()
        for rtype in ReliabilityType:
            result = engine.apply(ctx, rtype)
            assert result.success is True

    def test_retry_mechanism_is_idempotent_without_callable(self):
        retry = RetryReliability()
        ctx = ReliabilityContext()
        for _ in range(5):
            result = retry.apply(ctx, RetryPolicy())
            assert result.success is True
            assert result.retry_count == 0


# ============================================================
# 11. ReliabilityEngine 默认参数
# ============================================================

class TestEngineDefaultRetry:

    def test_engine_default_is_retry(self):
        engine = ReliabilityEngine()
        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        result = engine.apply(ctx)

        assert result.success is True
        assert result.policy == ReliabilityType.RETRY
        assert result.retry_count == 0

    def test_engine_with_default_policy(self):
        engine = ReliabilityEngine()
        engine.set_default_reliability_type(ReliabilityType.RETRY)

        ctx = ReliabilityContext(metadata={"_callable": lambda: "ok"})
        result = engine.apply(ctx)

        assert result.success is True
        assert result.policy == ReliabilityType.RETRY


# ============================================================
# 12. 端到端 — AgentRuntime 集成
# ============================================================

class TestAgentRuntimeRetryIntegration:

    def test_runtime_without_reliability_engine(self):
        from agent.agent_runtime import AgentRuntime
        from agent.execution_engine import ExecutionEngine
        from agent.query_planner import QueryPlanner
        from agent.reasoning_engine import ReasoningEngine

        retriever = MagicMock()
        planner = MagicMock(spec=QueryPlanner)
        executor = MagicMock(spec=ExecutionEngine)
        reasoner = MagicMock(spec=ReasoningEngine)
        intent_analyzer = MagicMock()

        runtime = AgentRuntime(
            planner=planner,
            executor=executor,
            reasoner=reasoner,
            retriever=retriever,
            intent_analyzer=intent_analyzer,
        )

        assert runtime.reliability_engine is None

    def test_runtime_with_reliability_engine(self):
        from agent.agent_runtime import AgentRuntime
        from agent.execution_engine import ExecutionEngine
        from agent.query_planner import QueryPlanner
        from agent.reasoning_engine import ReasoningEngine

        retriever = MagicMock()
        planner = MagicMock(spec=QueryPlanner)
        executor = MagicMock(spec=ExecutionEngine)
        reasoner = MagicMock(spec=ReasoningEngine)
        intent_analyzer = MagicMock()

        reliability_engine = ReliabilityEngine()

        runtime = AgentRuntime(
            planner=planner,
            executor=executor,
            reasoner=reasoner,
            retriever=retriever,
            intent_analyzer=intent_analyzer,
            reliability_engine=reliability_engine,
        )

        assert runtime.reliability_engine is reliability_engine
