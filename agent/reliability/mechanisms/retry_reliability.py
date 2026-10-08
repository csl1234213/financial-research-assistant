# ============================================================
# RetryReliability — Retry mechanism
# ============================================================
# Implements retry logic with configurable max_retries and
# backoff. Supports both:
#   - Direct callable retry: context.metadata["_callable"]
#   - Skeleton mode: returns success immediately (backward compat)
#
# Usage:
#   retry = RetryReliability()
#   ctx = ReliabilityContext(metadata={"_callable": my_fn})
#   result = retry.apply(ctx, RetryPolicy(max_retries=3))
# ============================================================

import logging
import time
from typing import Optional

from agent.reliability.base_reliability import BaseReliability
from agent.reliability.reliability_context import ReliabilityContext
from agent.reliability.reliability_enums import ReliabilityType
from agent.reliability.reliability_models import ReliabilityPolicy, RetryPolicy
from agent.reliability.reliability_result import ReliabilityResult

logger = logging.getLogger(__name__)


class RetryReliability(BaseReliability):
    def __init__(self) -> None:
        self._last_attempts: int = 0
        self._last_error: Optional[str] = None

    @property
    def mechanism_name(self) -> str:
        return "retry"

    @property
    def mechanism_type(self) -> ReliabilityType:
        return ReliabilityType.RETRY

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
                policy=ReliabilityType.RETRY,
                retry_count=0,
            )

        max_retries = 3
        backoff_ms = 100
        if isinstance(policy, RetryPolicy):
            max_retries = policy.max_retries
            backoff_ms = policy.backoff_ms

        start = time.time()
        last_error: Optional[Exception] = None

        for attempt in range(max_retries + 1):
            try:
                _callable_result = callable_fn()
                elapsed_ms = (time.time() - start) * 1000
                self._last_attempts = attempt
                self._last_error = None

                logger.info(
                    "Retry: success on attempt %d/%d | latency=%.2fms",
                    attempt + 1,
                    max_retries + 1,
                    elapsed_ms,
                )
                return ReliabilityResult(
                    success=True,
                    policy=ReliabilityType.RETRY,
                    retry_count=attempt,
                    latency_ms=elapsed_ms,
                    metadata={
                        "attempts": attempt + 1,
                        "max_retries": max_retries,
                        "backoff_ms": backoff_ms,
                    },
                )
            except Exception as e:
                last_error = e
                self._last_error = str(e)

                if attempt < max_retries:
                    sleep_ms = backoff_ms * (2**attempt)
                    logger.warning(
                        "Retry: attempt %d/%d failed (%s), retrying in %dms",
                        attempt + 1,
                        max_retries + 1,
                        str(e),
                        sleep_ms,
                    )
                    time.sleep(sleep_ms / 1000.0)

        elapsed_ms = (time.time() - start) * 1000
        self._last_attempts = max_retries

        logger.error(
            "Retry: all %d attempts failed | latency=%.2fms | error=%s",
            max_retries + 1,
            elapsed_ms,
            str(last_error),
        )
        return ReliabilityResult(
            success=False,
            policy=ReliabilityType.RETRY,
            retry_count=max_retries,
            latency_ms=elapsed_ms,
            error=str(last_error) if last_error else "Unknown error",
            metadata={
                "attempts": max_retries + 1,
                "max_retries": max_retries,
                "backoff_ms": backoff_ms,
            },
        )

    def reset(self) -> None:
        self._last_attempts = 0
        self._last_error = None

    @property
    def last_attempts(self) -> int:
        return self._last_attempts

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error
