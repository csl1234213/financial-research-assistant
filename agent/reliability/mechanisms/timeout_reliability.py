# ============================================================
# TimeoutReliability — Timeout enforcement mechanism
# ============================================================
# Wraps a callable with a timeout. If the callable does not
# complete within `timeout_ms`, it raises a TimeoutError.
#
# Usage:
#   timeout = TimeoutReliability()
#   ctx = ReliabilityContext(metadata={"_callable": my_fn})
#   result = timeout.apply(ctx, TimeoutPolicy(timeout_ms=5000))
#
# In the pipeline:
#   Timeout → Retry → CircuitBreaker → Provider
#   Timeout is the outermost wrapper — it protects the entire
#   chain from hanging indefinitely.
# ============================================================

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError

from agent.reliability.base_reliability import BaseReliability
from agent.reliability.reliability_context import ReliabilityContext
from agent.reliability.reliability_enums import ReliabilityType
from agent.reliability.reliability_models import ReliabilityPolicy, TimeoutPolicy
from agent.reliability.reliability_result import ReliabilityResult

logger = logging.getLogger(__name__)

_TIMEOUT_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="reliability_timeout")


class TimeoutReliability(BaseReliability):
    def __init__(self) -> None:
        self._timeout_count: int = 0
        self._total_timeout_ms: float = 0.0

    @property
    def mechanism_name(self) -> str:
        return "timeout"

    @property
    def mechanism_type(self) -> ReliabilityType:
        return ReliabilityType.TIMEOUT

    def supports(
        self,
        context: ReliabilityContext,
    ) -> bool:
        return True

    def apply(
        self,
        context: ReliabilityContext,
        policy: ReliabilityPolicy,
    ) -> ReliabilityResult:
        callable_fn = context.metadata.get("_callable")

        if callable_fn is None:
            return ReliabilityResult(
                success=True,
                policy=ReliabilityType.TIMEOUT,
                timeout_occurred=False,
            )

        timeout_ms = 30000
        if isinstance(policy, TimeoutPolicy):
            timeout_ms = policy.timeout_ms

        start = time.time()

        future = _TIMEOUT_EXECUTOR.submit(callable_fn)
        try:
            future.result(timeout=timeout_ms / 1000.0)
            elapsed_ms = (time.time() - start) * 1000

            logger.info(
                "Timeout: completed within %dms (limit=%dms)",
                int(elapsed_ms),
                timeout_ms,
            )
            return ReliabilityResult(
                success=True,
                policy=ReliabilityType.TIMEOUT,
                latency_ms=elapsed_ms,
                timeout_occurred=False,
                metadata={
                    "timeout_ms": timeout_ms,
                    "elapsed_ms": elapsed_ms,
                },
            )
        except FutureTimeoutError:
            elapsed_ms = (time.time() - start) * 1000
            self._timeout_count += 1
            self._total_timeout_ms += elapsed_ms

            logger.warning(
                "Timeout: exceeded %dms (elapsed=%.2fms)",
                timeout_ms,
                elapsed_ms,
            )
            return ReliabilityResult(
                success=False,
                policy=ReliabilityType.TIMEOUT,
                latency_ms=elapsed_ms,
                error=f"Timeout after {timeout_ms}ms",
                timeout_occurred=True,
                metadata={
                    "timeout_ms": timeout_ms,
                    "elapsed_ms": elapsed_ms,
                },
            )
        except Exception as e:
            elapsed_ms = (time.time() - start) * 1000
            return ReliabilityResult(
                success=False,
                policy=ReliabilityType.TIMEOUT,
                latency_ms=elapsed_ms,
                error=str(e),
                timeout_occurred=False,
                metadata={
                    "timeout_ms": timeout_ms,
                    "elapsed_ms": elapsed_ms,
                },
            )

    def reset(self) -> None:
        self._timeout_count = 0
        self._total_timeout_ms = 0.0

    @property
    def timeout_count(self) -> int:
        return self._timeout_count

    @property
    def total_timeout_ms(self) -> float:
        return self._total_timeout_ms
