from llm.providers.provider_models import ChatResponse
from llm.usage import collect_usage, record_failed_usage, record_usage, summarize_usage


def test_actual_usage_is_accumulated_without_prompt_or_credentials():
    with collect_usage() as calls:
        record_usage(
            ChatResponse(
                "private response", "deepseek", "model", 120, 30, 150, {"usage_available": True, "cached_tokens": 20}
            )
        )
        record_usage(
            ChatResponse(
                "private response", "deepseek", "model", 10, 5, 15, {"usage_available": True, "cached_tokens": 0}
            )
        )
    result = summarize_usage(calls)
    assert result["input_tokens"] == 130
    assert result["output_tokens"] == 35
    assert result["cached_tokens"] == 20
    assert "private response" not in str(result)


def test_missing_usage_is_not_reported_as_billed_zero():
    with collect_usage() as calls:
        record_usage(ChatResponse("answer", "provider", "model"))
    assert summarize_usage(calls)["input_tokens"] is None
    assert not summarize_usage(calls)["complete"]


def test_failed_usage_keeps_total_unknown():
    with collect_usage() as calls:
        record_failed_usage("provider", "model")
    assert summarize_usage(calls)["total_tokens"] is None


def test_nested_contexts_do_not_mix_requests():
    with collect_usage() as first:
        with collect_usage() as second:
            record_failed_usage("second", "model")
        record_failed_usage("first", "model")
    assert [c["provider"] for c in first] == ["first"]
    assert [c["provider"] for c in second] == ["second"]
