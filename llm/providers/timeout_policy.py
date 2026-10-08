"""Shared deadline arithmetic; no model identity or implicit retry policy."""
import math
import queue
import threading
import time

from .provider_exceptions import ProviderTimeoutError


def effective_timeout(configured: float, deadline: float | None, *, now: float | None = None) -> float:
    if (isinstance(configured, bool) or not isinstance(configured, (int, float))
            or not math.isfinite(configured) or configured <= 0):
        raise ValueError("INVALID_PROVIDER_TIMEOUT")
    if deadline is None:
        return float(configured)
    if isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or not math.isfinite(deadline):
        raise ValueError("INVALID_PROVIDER_DEADLINE")
    remaining = deadline - (time.monotonic() if now is None else now)
    if remaining <= 0:
        raise ProviderTimeoutError("Provider exceeded its total deadline", timeout_source="TOTAL_REQUEST_DEADLINE")
    return min(float(configured), remaining)


def invoke_with_deadline(call, remaining: float):
    """Bound caller waiting; discard late results without claiming cancellation.

    A synchronous transport may continue running. Its own socket timeout still
    applies; this containment boundary does not guarantee remote inference stops.
    """
    result = queue.Queue(maxsize=1)

    def run():
        try:
            result.put((True, call()))
        except BaseException as error:
            result.put((False, error))

    worker = threading.Thread(target=run, name="llm-provider-call", daemon=True)
    worker.start()
    worker.join(timeout=max(0.001, remaining))
    if worker.is_alive():
        raise ProviderTimeoutError("Provider exceeded its total deadline",
            timeout_source="TOTAL_REQUEST_DEADLINE", cancellation_guaranteed=False)
    success, value = result.get_nowait()
    if success:
        return value
    raise value
