# ============================================================
# ReliabilityEngine — Reliability Layer Orchestrator
# ============================================================
# The ReliabilityEngine is the single entry point for the
# Reliability Layer. It receives a ReliabilityContext, creates
# the appropriate mechanism instance via Factory, and delegates
# apply to that instance.
#
# The Engine does NOT make business decisions.
# It does NOT know about:
#   - Which mechanism to use (determined by caller)
#   - Retry / Timeout / CircuitBreaker / Fallback internals
#   - Provider / Runtime / Workflow
#   - Actual retry algorithms or timeout enforcement
#
# It ONLY orchestrates:
#   Context → Factory → Registry → Mechanism.supports()
#   → Mechanism.apply() → Result
#
# Key features:
#   - Default mechanism: Retry (most fundamental)
#   - Hook system: before_apply / after_apply
#   - supports() guard with ReliabilityNotSupported
#   - String + Enum dispatch
#
# Mirrors:
#   agent.tools.ToolEngine          → ReliabilityEngine
#   agent.metrics.MetricEngine      → ReliabilityEngine
#   agent.tracing.TraceEngine       → ReliabilityEngine
# ============================================================

import logging
import time
from typing import Callable, Dict, List, Optional, Tuple, Union

from .base_reliability import BaseReliability
from .reliability_context import ReliabilityContext
from .reliability_enums import ReliabilityType
from .reliability_exceptions import ReliabilityNotSupported
from .reliability_factory import ReliabilityFactory
from .reliability_models import (
    CircuitBreakerPolicy,
    FallbackPolicy,
    HealthCheckPolicy,
    RateLimiterPolicy,
    ReliabilityPolicy,
    RetryPolicy,
    TimeoutPolicy,
)
from .reliability_result import PipelineResult, ReliabilityResult

logger = logging.getLogger(__name__)


class ReliabilityEngine:
    def __init__(self) -> None:
        self._default_reliability_type: Union[str, ReliabilityType] = ReliabilityType.RETRY
        self._before_apply_hooks: List[Callable[[ReliabilityContext], None]] = []
        self._after_apply_hooks: List[Callable[[ReliabilityResult], None]] = []
        self._mechanism_instances: Dict[str, BaseReliability] = {}
        self._pipeline: Optional[List[Tuple[str, ReliabilityPolicy]]] = None

    # ============================================================
    # Configuration
    # ============================================================

    def set_default_reliability_type(
        self,
        reliability_type: Union[str, ReliabilityType],
    ) -> None:
        if isinstance(reliability_type, str):
            reliability_type = ReliabilityType(reliability_type)
        self._default_reliability_type = reliability_type

    # ============================================================
    # Hooks
    # ============================================================

    def add_before_apply_hook(
        self,
        hook: Callable[[ReliabilityContext], None],
    ) -> None:
        self._before_apply_hooks.append(hook)

    def add_after_apply_hook(
        self,
        hook: Callable[[ReliabilityResult], None],
    ) -> None:
        self._after_apply_hooks.append(hook)

    def _run_before_apply_hooks(self, context: ReliabilityContext) -> None:
        for hook in self._before_apply_hooks:
            try:
                hook(context)
            except Exception:
                pass

    def _run_after_apply_hooks(self, result: ReliabilityResult) -> None:
        for hook in self._after_apply_hooks:
            try:
                hook(result)
            except Exception:
                pass

    # ============================================================
    # Apply
    # ============================================================

    def apply(
        self,
        context: ReliabilityContext,
        reliability_type: Union[str, ReliabilityType, None] = None,
        policy: Optional[ReliabilityPolicy] = None,
    ) -> ReliabilityResult:
        if reliability_type is None:
            reliability_type = self._default_reliability_type

        mechanism = self._create_mechanism(reliability_type)

        if not mechanism.supports(context):
            raise ReliabilityNotSupported(
                f"Reliability mechanism '{reliability_type}' does not support the given context."
            )

        self._run_before_apply_hooks(context)

        result = mechanism.apply(
            context,
            policy
            or ReliabilityPolicy(
                policy_type=ReliabilityType(reliability_type.value)
                if isinstance(reliability_type, ReliabilityType)
                else ReliabilityType(reliability_type),
            ),
        )

        self._run_after_apply_hooks(result)

        logger.info(
            "ReliabilityEngine: %s → success=%s, retry_count=%d, latency=%.2fms",
            reliability_type,
            result.success,
            result.retry_count,
            result.latency_ms,
        )
        return result

    # ============================================================
    # Pipeline — Chain of Responsibility
    # ============================================================
    # Executes a chain of reliability mechanisms in order:
    #   HealthCheck → RateLimiter → Timeout → Retry → CircuitBreaker → Fallback
    #
    # Each mechanism wraps the callable from outer to inner:
    #   - HealthCheck: prevents calls when service is known unhealthy
    #   - RateLimiter: rejects when rate limit exceeded
    #   - Timeout: protects the entire chain from hanging
    #   - Retry: retries on failure
    #   - CircuitBreaker: stops calls when provider is unhealthy
    #   - Fallback: catches primary failure, tries secondary provider
    #
    # Future mechanisms (Bulkhead, AdaptiveRetry, HedgedRequest)
    # are added to the pipeline without modifying Runtime or Provider.
    # ============================================================

    DEFAULT_PIPELINE: List[Tuple[str, ReliabilityPolicy]] = [
        ("health_check", HealthCheckPolicy(enabled=True, interval_ms=30000)),
        ("rate_limiter", RateLimiterPolicy(max_requests=100, window_ms=60000)),
        ("timeout", TimeoutPolicy(timeout_ms=5000)),
        ("retry", RetryPolicy(max_retries=3, backoff_ms=100)),
        ("circuit_breaker", CircuitBreakerPolicy(failure_threshold=3, recovery_timeout_ms=1000)),
        ("fallback", FallbackPolicy(enabled=True)),
    ]

    def set_pipeline(
        self,
        pipeline: List[Tuple[str, ReliabilityPolicy]],
    ) -> None:
        self._pipeline = pipeline

    def get_pipeline(self) -> List[Tuple[str, ReliabilityPolicy]]:
        if self._pipeline is not None:
            return self._pipeline
        return self.DEFAULT_PIPELINE

    def execute_pipeline(
        self,
        context: ReliabilityContext,
        pipeline: Optional[List[Tuple[str, ReliabilityPolicy]]] = None,
    ) -> PipelineResult:
        if pipeline is not None:
            _pipeline = pipeline
        elif self._pipeline is not None:
            _pipeline = self._pipeline
        else:
            _pipeline = self.DEFAULT_PIPELINE

        callable_fn = context.metadata.get("_callable")

        if callable_fn is None:
            return PipelineResult(
                success=True,
                pipeline_order=[name for name, _ in _pipeline],
                metadata={"reason": "no callable in context"},
            )

        total_start = time.time()
        pipeline_results: Dict[str, ReliabilityResult] = {}
        pipeline_order: List[str] = []

        wrapped = callable_fn
        for mechanism_name, policy in reversed(_pipeline):
            pipeline_order.insert(0, mechanism_name)
            wrapped = self._make_mechanism_wrapper(mechanism_name, wrapped, context, policy, pipeline_results)

        try:
            wrapped()
            total_elapsed = (time.time() - total_start) * 1000
            final_success = True
        except Exception:
            total_elapsed = (time.time() - total_start) * 1000
            final_success = False

        logger.info(
            "ReliabilityEngine Pipeline: %s → total_latency=%.2fms",
            " → ".join(pipeline_order),
            total_elapsed,
        )
        return PipelineResult(
            success=final_success,
            results=pipeline_results,
            total_latency_ms=total_elapsed,
            pipeline_order=pipeline_order,
            metadata={"mechanism_count": len(_pipeline)},
        )

    def _make_mechanism_wrapper(
        self,
        mechanism_name: str,
        inner_callable: Callable,
        context: ReliabilityContext,
        policy: ReliabilityPolicy,
        pipeline_results: Dict[str, ReliabilityResult],
    ) -> Callable:
        mechanism = self._create_mechanism(mechanism_name)

        def wrapper():
            _wrapper_ctx = ReliabilityContext(
                metadata={**context.metadata, "_callable": inner_callable},
            )
            result = mechanism.apply(_wrapper_ctx, policy)
            pipeline_results[mechanism_name] = result
            if not result.success:
                raise RuntimeError(f"Reliability mechanism '{mechanism_name}' failed: {result.error}")
            if mechanism_name in ("health_check", "rate_limiter"):
                return inner_callable()
            return result

        return wrapper

    # ============================================================
    # Internal helpers
    # ============================================================

    def _create_mechanism(
        self,
        reliability_type: Union[str, ReliabilityType],
    ) -> BaseReliability:
        if isinstance(reliability_type, ReliabilityType):
            reliability_type = reliability_type.value
        if reliability_type not in self._mechanism_instances:
            self._mechanism_instances[reliability_type] = ReliabilityFactory.create(reliability_type)
        return self._mechanism_instances[reliability_type]
