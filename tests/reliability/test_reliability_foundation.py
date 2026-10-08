# ============================================================
# test_reliability_foundation.py
# Reliability Foundation Test Matrix
# ============================================================
# 验证：
#   1. ReliabilityType 枚举完整性
#   2. ReliabilityStatus 枚举完整性（仅 ACTIVE/DISABLED）
#   3. CircuitState 枚举完整性（OPEN/HALF_OPEN/CLOSED）
#   4. ReliabilityScope 枚举完整性
#   5. ReliabilityContext 创建与插槽检查
#   6. 各 ReliabilityPolicy 数据模型
#   7. RetryCondition 预留接口
#   8. HealthCheckPolicy async 支持
#   9. ReliabilityResult 默认值
#   10. BaseReliability 接口完整性
#   11. slots=True 生效检查（内存布局）
#   12. Runtime 无耦合验证
#   13. 导入导出完整性
#
# ============================================================
# test_reliability_registry_factory.py
# Reliability Registry & Factory Test Matrix
# ============================================================
# 验证：
#   1. ReliabilityError / ReliabilityNotFound / ReliabilityRegistrationError
#   2. ReliabilityRegistry.register() / get() / get_default_policy()
#   3. ReliabilityRegistry.has_mechanism() / list_mechanisms() / clear()
#   4. ReliabilityFactory.create(str) / create(ReliabilityType)
#   5. ReliabilityFactory.create_default() / set_default() / get_default()
#   6. 6 个 Skeleton Mechanism 结构完整性
#   7. 自动注册：mechanisms/__init__.py 导入后全量注册
#   8. Runtime 无耦合
# ============================================================

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


from agent.reliability import (
    BaseReliability,
    CircuitBreakerPolicy,
    CircuitState,
    FallbackPolicy,
    HealthCheckPolicy,
    RateLimiterPolicy,
    ReliabilityContext,
    ReliabilityPolicy,
    ReliabilityResult,
    ReliabilityScope,
    ReliabilityStatus,
    ReliabilityType,
    RetryCondition,
    RetryPolicy,
    TimeoutPolicy,
)

# ============================================================
# 1. Enum Tests — 枚举完整性检查
# ============================================================

class TestReliabilityTypeEnum:

    def test_enum_members_count(self):
        members = list(ReliabilityType)
        assert len(members) == 6

    def test_enum_values_are_correct(self):
        assert ReliabilityType.RETRY.value == "retry"
        assert ReliabilityType.TIMEOUT.value == "timeout"
        assert ReliabilityType.CIRCUIT_BREAKER.value == "circuit_breaker"
        assert ReliabilityType.FALLBACK.value == "fallback"
        assert ReliabilityType.HEALTH_CHECK.value == "health_check"
        assert ReliabilityType.RATE_LIMITER.value == "rate_limiter"

    def test_enum_comparison(self):
        retry_type = ReliabilityType.RETRY
        assert retry_type == ReliabilityType.RETRY
        assert retry_type != ReliabilityType.TIMEOUT


class TestReliabilityStatusEnum:

    def test_enum_members_count(self):
        members = list(ReliabilityStatus)
        assert len(members) == 2

    def test_enum_values_are_correct(self):
        assert ReliabilityStatus.ACTIVE.value == "active"
        assert ReliabilityStatus.DISABLED.value == "disabled"

    def test_status_semantic_clean(self):
        assert ReliabilityStatus.ACTIVE != ReliabilityStatus.DISABLED
        assert not hasattr(ReliabilityStatus, "OPEN")
        assert not hasattr(ReliabilityStatus, "HALF_OPEN")
        assert not hasattr(ReliabilityStatus, "CLOSED")


class TestCircuitStateEnum:

    def test_enum_members_count(self):
        members = list(CircuitState)
        assert len(members) == 3

    def test_enum_values_are_correct(self):
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"
        assert CircuitState.CLOSED.value == "closed"

    def test_circuit_state_independent_from_status(self):
        assert CircuitState.OPEN != ReliabilityStatus.ACTIVE
        assert CircuitState.CLOSED != ReliabilityStatus.DISABLED


class TestReliabilityScopeEnum:

    def test_enum_members_count(self):
        members = list(ReliabilityScope)
        assert len(members) == 6

    def test_enum_values_are_correct(self):
        assert ReliabilityScope.RUNTIME.value == "runtime"
        assert ReliabilityScope.WORKFLOW.value == "workflow"
        assert ReliabilityScope.EXECUTION.value == "execution"
        assert ReliabilityScope.TOOL.value == "tool"
        assert ReliabilityScope.PROVIDER.value == "provider"
        assert ReliabilityScope.MEMORY.value == "memory"

    def test_scope_consistent_with_metrics(self):
        from agent.metrics.metric_enums import MetricScope
        metric_scopes = {m.value for m in MetricScope}
        reliability_scopes = {s.value for s in ReliabilityScope}
        assert metric_scopes == reliability_scopes


# ============================================================
# 2. Context Test — 上下文数据模型检查
# ============================================================

class TestReliabilityContext:

    def test_context_creation_defaults(self):
        context = ReliabilityContext()
        assert context.runtime_state is None
        assert context.workflow is None
        assert context.execution == []
        assert context.tool is None
        assert context.provider is None
        assert context.memory is None
        assert context.metadata == {}

    def test_context_with_metadata(self):
        context = ReliabilityContext(metadata={"correlation_id": "123"})
        assert context.metadata["correlation_id"] == "123"

    def test_context_has_slots(self):
        context = ReliabilityContext()
        assert hasattr(context, "__slots__")
        assert "runtime_state" in context.__slots__


# ============================================================
# 3. Policy Tests — 策略数据模型检查
# ============================================================

class TestBaseReliabilityPolicy:

    def test_policy_creation(self):
        policy = ReliabilityPolicy(
            policy_type=ReliabilityType.RETRY,
            enabled=True,
            metadata={"key": "value"},
        )
        assert policy.policy_type == ReliabilityType.RETRY
        assert policy.enabled is True
        assert policy.metadata["key"] == "value"

    def test_policy_default_metadata(self):
        policy = ReliabilityPolicy(policy_type=ReliabilityType.RETRY)
        assert policy.metadata == {}


# ============================================================
# 3a. RetryCondition — 预留接口测试
# ============================================================

class TestRetryCondition:

    def test_condition_creation_basic(self):
        condition = RetryCondition(
            condition_type="http_status",
            condition_value="429",
        )
        assert condition.condition_type == "http_status"
        assert condition.condition_value == "429"
        assert condition.metadata == {}

    def test_condition_creation_with_metadata(self):
        condition = RetryCondition(
            condition_type="http_status",
            condition_value="500",
            metadata={"retry_after": "5s"},
        )
        assert condition.metadata["retry_after"] == "5s"

    def test_condition_has_slots(self):
        condition = RetryCondition(
            condition_type="exception",
            condition_value="TimeoutError",
        )
        assert hasattr(condition, "__slots__")

    def test_condition_typical_scenarios(self):
        conditions = [
            RetryCondition("http_status", "429"),
            RetryCondition("http_status", "500"),
            RetryCondition("exception", "TimeoutError"),
            RetryCondition("provider_status", "busy"),
            RetryCondition("provider_status", "rate_limited"),
        ]
        assert len(conditions) == 5
        types = {c.condition_type for c in conditions}
        assert types == {"http_status", "exception", "provider_status"}


class TestRetryPolicy:

    def test_retry_default_values(self):
        policy = RetryPolicy()
        assert policy.policy_type == ReliabilityType.RETRY
        assert policy.max_retries == 3
        assert policy.backoff_ms == 1000
        assert policy.retry_exceptions == [Exception]
        assert policy.retry_conditions == []
        assert policy.enabled is True

    def test_retry_custom_values(self):
        policy = RetryPolicy(
            max_retries=5,
            backoff_ms=500,
            retry_exceptions=[ConnectionError, TimeoutError],
            enabled=True,
        )
        assert policy.max_retries == 5
        assert policy.backoff_ms == 500
        assert len(policy.retry_exceptions) == 2
        assert ConnectionError in policy.retry_exceptions

    def test_retry_with_conditions(self):
        condition = RetryCondition("http_status", "429")
        policy = RetryPolicy(
            retry_conditions=[condition],
        )
        assert len(policy.retry_conditions) == 1
        assert policy.retry_conditions[0].condition_value == "429"

    def test_retry_with_multiple_conditions(self):
        conditions = [
            RetryCondition("http_status", "429"),
            RetryCondition("http_status", "500"),
            RetryCondition("provider_status", "rate_limited"),
        ]
        policy = RetryPolicy(retry_conditions=conditions)
        assert len(policy.retry_conditions) == 3

    def test_retry_disabled(self):
        policy = RetryPolicy(enabled=False)
        assert policy.enabled is False

    def test_retry_has_slots(self):
        policy = RetryPolicy()
        assert hasattr(policy, "__slots__")


class TestTimeoutPolicy:

    def test_timeout_default_values(self):
        policy = TimeoutPolicy()
        assert policy.policy_type == ReliabilityType.TIMEOUT
        assert policy.timeout_ms == 30000
        assert policy.timeout_behavior == "raise"
        assert policy.enabled is True

    def test_timeout_custom_values(self):
        policy = TimeoutPolicy(
            timeout_ms=10000,
            timeout_behavior="fallback",
        )
        assert policy.timeout_ms == 10000
        assert policy.timeout_behavior == "fallback"


class TestCircuitBreakerPolicy:

    def test_circuit_breaker_default_values(self):
        policy = CircuitBreakerPolicy()
        assert policy.policy_type == ReliabilityType.CIRCUIT_BREAKER
        assert policy.failure_threshold == 5
        assert policy.recovery_timeout_ms == 30000
        assert policy.half_open_max_calls == 1
        assert policy.initial_state == CircuitState.CLOSED
        assert policy.enabled is True

    def test_circuit_breaker_custom_values(self):
        policy = CircuitBreakerPolicy(
            failure_threshold=10,
            recovery_timeout_ms=60000,
            half_open_max_calls=3,
            initial_state=CircuitState.OPEN,
        )
        assert policy.failure_threshold == 10
        assert policy.recovery_timeout_ms == 60000
        assert policy.half_open_max_calls == 3
        assert policy.initial_state == CircuitState.OPEN

    def test_circuit_breaker_initial_state_is_circuit_state(self):
        policy = CircuitBreakerPolicy()
        assert isinstance(policy.initial_state, CircuitState)


class TestFallbackPolicy:

    def test_fallback_default_values(self):
        policy = FallbackPolicy()
        assert policy.policy_type == ReliabilityType.FALLBACK
        assert policy.fallback_value is None
        assert policy.fallback_function is None
        assert policy.enabled is True

    def test_fallback_with_value(self):
        policy = FallbackPolicy(fallback_value="fallback_response")
        assert policy.fallback_value == "fallback_response"

    def test_fallback_with_function(self):
        def fallback_func():
            return "fallback"

        policy = FallbackPolicy(fallback_function=fallback_func)
        assert policy.fallback_function is fallback_func


class TestHealthCheckPolicy:

    def test_health_check_default_values(self):
        policy = HealthCheckPolicy()
        assert policy.policy_type == ReliabilityType.HEALTH_CHECK
        assert policy.interval_ms == 30000
        assert policy.check_function is None
        assert policy.enabled is True

    def test_health_check_custom_interval(self):
        policy = HealthCheckPolicy(interval_ms=10000)
        assert policy.interval_ms == 10000

    def test_health_check_sync_function(self):
        def sync_check() -> bool:
            return True

        policy = HealthCheckPolicy(check_function=sync_check)
        assert policy.check_function is sync_check
        assert policy.check_function() is True

    def test_health_check_async_function(self):
        async def async_check() -> bool:
            return True

        policy = HealthCheckPolicy(check_function=async_check)
        assert policy.check_function is async_check


class TestRateLimiterPolicy:

    def test_rate_limiter_default_values(self):
        policy = RateLimiterPolicy()
        assert policy.policy_type == ReliabilityType.RATE_LIMITER
        assert policy.max_requests == 100
        assert policy.window_ms == 60000
        assert policy.enabled is True

    def test_rate_limiter_custom_values(self):
        policy = RateLimiterPolicy(
            max_requests=1000,
            window_ms=3600000,
        )
        assert policy.max_requests == 1000
        assert policy.window_ms == 3600000


# ============================================================
# 4. Result Test — 结果数据模型检查
# ============================================================

class TestReliabilityResult:

    def test_result_default_values(self):
        result = ReliabilityResult()
        assert result.success is True
        assert result.policy is None
        assert result.retry_count == 0
        assert result.latency_ms == 0.0
        assert result.error is None
        assert result.metadata == {}

    def test_result_with_custom_values(self):
        result = ReliabilityResult(
            success=False,
            policy=ReliabilityType.RETRY,
            retry_count=3,
            latency_ms=1250.5,
            error="Maximum retries exceeded",
            metadata={"attempt": 3},
        )
        assert result.success is False
        assert result.policy == ReliabilityType.RETRY
        assert result.retry_count == 3
        assert result.latency_ms == 1250.5
        assert result.error == "Maximum retries exceeded"
        assert result.metadata["attempt"] == 3

    def test_result_with_success_after_retry(self):
        result = ReliabilityResult(
            success=True,
            policy=ReliabilityType.RETRY,
            retry_count=2,
            latency_ms=500.0,
        )
        assert result.success is True
        assert result.retry_count == 2


# ============================================================
# 5. BaseReliability — 抽象接口检查
# ============================================================

class TestBaseReliabilityInterface:

    def test_can_subclass(self):
        class MockReliability(BaseReliability):
            @property
            def mechanism_name(self) -> str:
                return "mock"

            @property
            def mechanism_type(self) -> ReliabilityType:
                return ReliabilityType.RETRY

            def supports(self, context: ReliabilityContext) -> bool:
                return True

            def apply(
                self,
                context: ReliabilityContext,
                policy: ReliabilityPolicy,
            ) -> ReliabilityResult:
                return ReliabilityResult(success=True)

            def reset(self) -> None:
                pass

        instance = MockReliability()
        assert instance.mechanism_name == "mock"
        assert instance.mechanism_type == ReliabilityType.RETRY
        assert instance.supports(ReliabilityContext()) is True
        result = instance.apply(ReliabilityContext(), RetryPolicy())
        assert isinstance(result, ReliabilityResult)
        instance.reset()


# ============================================================
# 6. slots=True Memory Layout Check — 插槽生效检查
# ============================================================

class TestSlotsEnabled:

    def test_all_dataclasses_have_slots(self):
        from dataclasses import is_dataclass

        models = [
            (ReliabilityContext(), "ReliabilityContext"),
            (ReliabilityPolicy(policy_type=ReliabilityType.RETRY), "ReliabilityPolicy"),
            (RetryCondition(condition_type="test", condition_value="v"), "RetryCondition"),
            (RetryPolicy(), "RetryPolicy"),
            (TimeoutPolicy(), "TimeoutPolicy"),
            (CircuitBreakerPolicy(), "CircuitBreakerPolicy"),
            (FallbackPolicy(), "FallbackPolicy"),
            (HealthCheckPolicy(), "HealthCheckPolicy"),
            (RateLimiterPolicy(), "RateLimiterPolicy"),
        ]

        for model, name in models:
            assert is_dataclass(model), f"{name} should be a dataclass"
            assert hasattr(model, "__slots__"), f"{name} should have __slots__"


# ============================================================
# 7. No Runtime Coupling Check — 无耦合验证
# ============================================================

class TestNoRuntimeCoupling:

    def test_runtime_types_are_forward_references(self):
        import inspect
        import sys

        module = sys.modules["agent.reliability.reliability_context"]
        source = inspect.getsource(module)
        assert "TYPE_CHECKING" in source
        assert "RuntimeState" in source

    def test_can_instantiate_without_runtime(self):
        context = ReliabilityContext()
        assert context is not None

        policies = [
            RetryPolicy(),
            TimeoutPolicy(),
            CircuitBreakerPolicy(),
            FallbackPolicy(),
            HealthCheckPolicy(),
            RateLimiterPolicy(),
        ]
        for policy in policies:
            assert policy is not None

        condition = RetryCondition(condition_type="test", condition_value="test")
        assert condition is not None

        result = ReliabilityResult()
        assert result is not None

    def test_no_circular_import(self):
        from agent.reliability import (
            base_reliability,
            reliability_context,
            reliability_enums,
            reliability_models,
            reliability_result,
        )

        assert all(module is not None for module in [
            reliability_enums,
            reliability_models,
            reliability_context,
            reliability_result,
            base_reliability,
        ])


# ============================================================
# 8. Import Export Check — 导出完整性检查
# ============================================================

class TestPublicExport:

    def test_all_expected_types_exported(self):
        expected_exports = [
            "BaseReliability",
            "CircuitBreakerPolicy",
            "CircuitState",
            "FallbackPolicy",
            "HealthCheckPolicy",
            "PipelineResult",
            "RateLimiterPolicy",
            "ReliabilityBridge",
            "ReliabilityContext",
            "ReliabilityEngine",
            "ReliabilityError",
            "ReliabilityFactory",
            "ReliabilityNotFound",
            "ReliabilityNotSupported",
            "ReliabilityPolicy",
            "ReliabilityRegistrationError",
            "ReliabilityRegistry",
            "ReliabilityResult",
            "ReliabilityScope",
            "ReliabilityStatus",
            "ReliabilityType",
            "RetryCondition",
            "RetryPolicy",
            "TimeoutPolicy",
        ]

        import agent.reliability
        for name in expected_exports:
            assert hasattr(agent.reliability, name), f"{name} should be exported"

    def test_import_count(self):
        from agent.reliability import __all__
        assert len(__all__) == 24
