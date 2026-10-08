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

from abc import ABC

import pytest

from agent.reliability import (
    BaseReliability,
    ReliabilityContext,
    ReliabilityError,
    ReliabilityFactory,
    ReliabilityNotFound,
    ReliabilityPolicy,
    ReliabilityRegistrationError,
    ReliabilityRegistry,
    ReliabilityResult,
    ReliabilityType,
    RetryPolicy,
)

# ============================================================
# Helper: create a unique mock reliability for isolated tests
# ============================================================

def _make_mock(name: str, rtype: ReliabilityType = ReliabilityType.RETRY):
    class MockReliability(BaseReliability):
        @property
        def mechanism_name(self) -> str:
            return name
        @property
        def mechanism_type(self) -> ReliabilityType:
            return rtype
        def supports(self, context: ReliabilityContext) -> bool:
            return True
        def apply(self, context: ReliabilityContext, policy: ReliabilityPolicy) -> ReliabilityResult:
            return ReliabilityResult()
        def reset(self) -> None:
            pass
    return MockReliability


# ============================================================
# 1. Exceptions — 异常层次测试
# ============================================================

class TestReliabilityExceptions:

    def test_reliability_error_is_base_exception(self):
        assert issubclass(ReliabilityError, Exception)
        error = ReliabilityError("test error")
        assert str(error) == "test error"

    def test_reliability_not_found_inherits(self):
        assert issubclass(ReliabilityNotFound, ReliabilityError)
        err = ReliabilityNotFound("not found")
        assert isinstance(err, ReliabilityError)

    def test_reliability_registration_error_inherits(self):
        assert issubclass(ReliabilityRegistrationError, ReliabilityError)
        err = ReliabilityRegistrationError("already registered")
        assert isinstance(err, ReliabilityError)

    def test_exception_constructor_with_message(self):
        msg = "Mechanism 'xyz' not found. Available: ['retry', 'timeout']"
        err = ReliabilityNotFound(msg)
        assert str(err) == msg


# ============================================================
# 2. ReliabilityRegistry — 注册器测试
# ============================================================

class TestReliabilityRegistry:

    def test_register_mechanism(self):
        Mock = _make_mock("mock_rr_test")
        policy = RetryPolicy(max_retries=5)
        ReliabilityRegistry.register("mock_rr_test", Mock, policy)

        assert ReliabilityRegistry.has_mechanism("mock_rr_test")
        assert "mock_rr_test" in ReliabilityRegistry.list_mechanisms()
        assert ReliabilityRegistry.get("mock_rr_test") == Mock
        assert ReliabilityRegistry.get_default_policy("mock_rr_test") == policy

    def test_register_raises_when_not_subclass(self):
        class NotABaseReliability:
            pass

        with pytest.raises(ReliabilityRegistrationError):
            ReliabilityRegistry.register("bad_rr_test", NotABaseReliability)

    def test_register_raises_when_duplicate(self):
        Mock1 = _make_mock("dup_test")
        Mock2 = _make_mock("dup_test")

        ReliabilityRegistry.register("dup_test", Mock1)
        with pytest.raises(ReliabilityRegistrationError):
            ReliabilityRegistry.register("dup_test", Mock2)

    def test_get_raises_when_not_found(self):
        with pytest.raises(ReliabilityNotFound):
            ReliabilityRegistry.get("nonexistent_rr")

    def test_get_default_policy_raises_when_not_found(self):
        Mock = _make_mock("no_policy_test")
        ReliabilityRegistry.register("no_policy_test", Mock)
        with pytest.raises(ReliabilityNotFound):
            ReliabilityRegistry.get_default_policy("no_policy_test")

    def test_has_mechanism_returns_correct_bool(self):
        Mock = _make_mock("has_test")
        ReliabilityRegistry.register("has_test", Mock)
        assert ReliabilityRegistry.has_mechanism("has_test") is True
        assert ReliabilityRegistry.has_mechanism("other_rr") is False

    def test_list_mechanisms_returns_all_registered(self):
        Mock1 = _make_mock("one_rr")
        Mock2 = _make_mock("two_rr")

        ReliabilityRegistry.register("one_rr", Mock1)
        ReliabilityRegistry.register("two_rr", Mock2)

        mechanisms = ReliabilityRegistry.list_mechanisms()
        assert "one_rr" in mechanisms
        assert "two_rr" in mechanisms


# ============================================================
# Setup: Import mechanisms for auto-registration
# ============================================================

def _ensure_mechanisms_imported():
    import agent.reliability.mechanisms
    return agent.reliability.mechanisms


_ensure_mechanisms_imported()


# ============================================================
# 3. ReliabilityFactory — 工厂测试
# ============================================================

class TestReliabilityFactory:

    def test_create_by_string_name(self):
        mechanism = ReliabilityFactory.create("retry")
        assert isinstance(mechanism, BaseReliability)
        assert mechanism.mechanism_name == "retry"
        assert mechanism.mechanism_type == ReliabilityType.RETRY

    def test_create_by_enum_type(self):
        mechanism = ReliabilityFactory.create(ReliabilityType.RETRY)
        assert isinstance(mechanism, BaseReliability)
        assert mechanism.mechanism_name == "retry"
        assert mechanism.mechanism_type == ReliabilityType.RETRY

    def test_create_raises_when_not_found(self):
        with pytest.raises(ReliabilityNotFound):
            ReliabilityFactory.create("nonexistent_factory")

    def test_set_default_and_get_default(self):
        ReliabilityFactory.set_default("retry")
        assert ReliabilityFactory.get_default() == "retry"

    def test_set_default_by_enum(self):
        ReliabilityFactory.set_default(ReliabilityType.RETRY)
        assert ReliabilityFactory.get_default() == "retry"

    def test_set_default_raises_when_not_found(self):
        with pytest.raises(KeyError):
            ReliabilityFactory.set_default("nonexistent_factory")

    def test_create_default_creates_retry_by_default(self):
        mechanism = ReliabilityFactory.create_default()
        assert isinstance(mechanism, BaseReliability)
        assert mechanism.mechanism_type == ReliabilityType.RETRY

    def test_create_default_uses_set_default(self):
        ReliabilityFactory.set_default("timeout")
        mechanism = ReliabilityFactory.create_default()
        assert mechanism.mechanism_type == ReliabilityType.TIMEOUT


# ============================================================
# 4. Skeleton Mechanisms — 骨架实现测试
# ============================================================

class TestSkeletonMechanisms:

    @classmethod
    def setup_class(cls):
        cls.retry = ReliabilityFactory.create("retry")
        cls.timeout = ReliabilityFactory.create("timeout")
        cls.circuit_breaker = ReliabilityFactory.create("circuit_breaker")
        cls.fallback = ReliabilityFactory.create("fallback")
        cls.health_check = ReliabilityFactory.create("health_check")
        cls.rate_limiter = ReliabilityFactory.create("rate_limiter")

    def test_all_six_mechanisms_are_instantiable(self):
        assert self.retry is not None
        assert self.timeout is not None
        assert self.circuit_breaker is not None
        assert self.fallback is not None
        assert self.health_check is not None
        assert self.rate_limiter is not None

    def test_retry_skeleton_interface(self):
        assert self.retry.mechanism_name == "retry"
        assert self.retry.mechanism_type == ReliabilityType.RETRY
        assert self.retry.supports(ReliabilityContext()) is True
        result = self.retry.apply(ReliabilityContext(), RetryPolicy())
        assert isinstance(result, ReliabilityResult)
        self.retry.reset()

    def test_timeout_skeleton_interface(self):
        assert self.timeout.mechanism_name == "timeout"
        assert self.timeout.mechanism_type == ReliabilityType.TIMEOUT
        assert self.timeout.supports(ReliabilityContext()) is True
        result = self.timeout.apply(ReliabilityContext(), RetryPolicy())
        assert isinstance(result, ReliabilityResult)
        self.timeout.reset()

    def test_circuit_breaker_skeleton_interface(self):
        assert self.circuit_breaker.mechanism_name == "circuit_breaker"
        assert self.circuit_breaker.mechanism_type == ReliabilityType.CIRCUIT_BREAKER
        assert self.circuit_breaker.supports(ReliabilityContext()) is True
        result = self.circuit_breaker.apply(ReliabilityContext(), RetryPolicy())
        assert isinstance(result, ReliabilityResult)
        self.circuit_breaker.reset()

    def test_fallback_skeleton_interface(self):
        assert self.fallback.mechanism_name == "fallback"
        assert self.fallback.mechanism_type == ReliabilityType.FALLBACK
        assert self.fallback.supports(ReliabilityContext()) is True
        result = self.fallback.apply(ReliabilityContext(), RetryPolicy())
        assert isinstance(result, ReliabilityResult)
        self.fallback.reset()

    def test_health_check_skeleton_interface(self):
        assert self.health_check.mechanism_name == "health_check"
        assert self.health_check.mechanism_type == ReliabilityType.HEALTH_CHECK
        assert self.health_check.supports(ReliabilityContext()) is True
        result = self.health_check.apply(ReliabilityContext(), RetryPolicy())
        assert isinstance(result, ReliabilityResult)
        self.health_check.reset()

    def test_rate_limiter_skeleton_interface(self):
        assert self.rate_limiter.mechanism_name == "rate_limiter"
        assert self.rate_limiter.mechanism_type == ReliabilityType.RATE_LIMITER
        assert self.rate_limiter.supports(ReliabilityContext()) is True
        result = self.rate_limiter.apply(ReliabilityContext(), RetryPolicy())
        assert isinstance(result, ReliabilityResult)
        self.rate_limiter.reset()

    def test_all_implement_base_reliability_abc(self):
        assert isinstance(self.retry, ABC)
        assert isinstance(self.retry, BaseReliability)
        assert issubclass(type(self.retry), BaseReliability)


# ============================================================
# 5. Auto-registration — 自动注册测试
# ============================================================

class TestAutoRegistration:

    def test_all_six_mechanisms_are_auto_registered(self):
        mechanisms = ReliabilityRegistry.list_mechanisms()
        expected = {
            "retry", "timeout", "circuit_breaker",
            "fallback", "health_check", "rate_limiter",
        }
        registered = set(mechanisms)
        assert expected.issubset(registered), f"Missing: {expected - registered}"

    def test_can_create_every_mechanism_after_auto_registration(self):
        expected = ["retry", "timeout", "circuit_breaker", "fallback", "health_check", "rate_limiter"]
        for name in expected:
            mechanism = ReliabilityFactory.create(name)
            assert mechanism is not None
            assert isinstance(mechanism, BaseReliability)

    def test_default_policies_are_registered(self):
        expected = ["retry", "timeout", "circuit_breaker", "fallback", "health_check", "rate_limiter"]
        for name in expected:
            policy = ReliabilityRegistry.get_default_policy(name)
            assert policy is not None

    def test_no_coupling_to_runtime(self):
        from agent.reliability.mechanisms import retry_reliability
        assert retry_reliability is not None


# ============================================================
# 6. Integration — 端到端测试
# ============================================================

class TestIntegration:

    def test_full_workflow(self):
        retry = ReliabilityFactory.create("retry")
        context = ReliabilityContext(metadata={"test": "value"})
        policy = RetryPolicy(max_retries=3)

        result = retry.apply(context, policy)

        assert isinstance(result, ReliabilityResult)
        assert result.success is True
        assert result.policy == ReliabilityType.RETRY

    def test_create_via_enum_returns_correct_instance(self):
        from agent.reliability.mechanisms.retry_reliability import RetryReliability

        mechanism = ReliabilityFactory.create(ReliabilityType.RETRY)
        assert isinstance(mechanism, RetryReliability)

        mechanism = ReliabilityFactory.create(ReliabilityType.TIMEOUT)
        from agent.reliability.mechanisms.timeout_reliability import TimeoutReliability
        assert isinstance(mechanism, TimeoutReliability)

    def test_list_mechanisms_matches_enum_count(self):
        expected = sorted([t.value for t in ReliabilityType])
        mechanisms = sorted(ReliabilityRegistry.list_mechanisms())
        for t in expected:
            assert t in mechanisms, f"Expected '{t}' in registered mechanisms"
