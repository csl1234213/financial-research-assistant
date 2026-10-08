"""Request-local, secret-free accounting of actual provider usage.

No prompts, answers, credentials or headers are captured. Missing or failed
provider usage stays unknown rather than being represented as billed zero.
"""

from contextlib import contextmanager
from contextvars import ContextVar

from llm.providers.provider_models import ChatResponse

_calls: ContextVar[list[dict] | None] = ContextVar("llm_usage_calls", default=None)


@contextmanager
def collect_usage():
    calls: list[dict] = []
    token = _calls.set(calls)
    try:
        yield calls
    finally:
        _calls.reset(token)


def record_usage(response: ChatResponse) -> None:
    calls = _calls.get()
    if calls is None:
        return
    available = response.metadata.get("usage_available", response.total_tokens > 0)
    calls.append(
        {
            "provider": response.provider,
            "model": response.model,
            "served_model": response.metadata.get("served_model"),
            "input_tokens": response.prompt_tokens if available else None,
            "output_tokens": response.completion_tokens if available else None,
            "total_tokens": response.total_tokens if available else None,
            "cached_tokens": response.metadata.get("cached_tokens") if available else None,
            "finish_reason": response.metadata.get("finish_reason"),
            "usage_available": bool(available),
        }
    )


def record_failed_usage(provider: str, model: str) -> None:
    calls = _calls.get()
    if calls is not None:
        calls.append({"provider": provider, "model": model, "usage_available": False})


def summarize_usage(calls: list[dict]) -> dict:
    complete = all(call["usage_available"] for call in calls)
    return {
        "calls": list(calls),
        "complete": complete,
        "input_tokens": sum(call["input_tokens"] for call in calls) if complete else None,
        "output_tokens": sum(call["output_tokens"] for call in calls) if complete else None,
        "total_tokens": sum(call["total_tokens"] for call in calls) if complete else None,
        "cached_tokens": (
            sum(call["cached_tokens"] for call in calls)
            if complete and all(call.get("cached_tokens") is not None for call in calls)
            else None
        ),
    }
