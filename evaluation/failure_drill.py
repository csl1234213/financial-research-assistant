"""Isolated fault injection. No real provider requests or production mutations.

Uses real OpenAI SDK/DeepSeek adapter with an HTTP mock transport, and real
retriever/cache/broker classes with dependency failures injected at their seams.
This is not a complete HTTP/RAG/state-pollution acceptance test.
"""

import argparse
import json
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from openai import OpenAI

from llm.adapters.deepseek_provider import DeepSeekProvider
from llm.providers.provider_config import ProviderConfig
from llm.providers.provider_models import ChatRequest


def provider_case(status):
    attempts = []
    sleeps = []

    def transport(request):
        attempts.append(len(attempts) + 1)
        if status == "timeout":
            raise httpx.ReadTimeout("Injected timeout", request=request)
        return httpx.Response(
            status,
            headers={"Retry-After": "0.01"},
            json={"error": {"message": "Injected dependency failure", "type": "injected"}},
        )

    provider = DeepSeekProvider(
        ProviderConfig(provider="deepseek", model="deepseek-v4-flash", api_key="injection-only")
    )
    def client_factory(**kwargs):
        return OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(transport)))

    with (
        patch("llm.adapters.deepseek_provider.OpenAI", side_effect=client_factory),
        patch("time.sleep", side_effect=lambda seconds: sleeps.append(seconds)),
    ):
        try:
            provider.chat(ChatRequest(messages=[{"role": "user", "content": "Fault injection"}]))
        except Exception as exc:
            result = {
                "injected": status,
                "http_attempts": len(attempts),
                "retry_count": len(attempts) - 1,
                "backoff_seconds": sleeps,
                "final_error_class": type(exc).__name__,
                "retry_after_respected": all(s >= 0.01 for s in sleeps) if status == 429 else None,
                "bounded": len(attempts) <= 3,
                "scope": "Real SDK and adapter, not full application state",
            }
        else:
            raise AssertionError("Fault was incorrectly represented as success")
    provider._client.close()
    return result


def chroma_case():
    from retrieval.hybrid_retriever import HybridRetriever
    from retrieval.retrieval_context import RetrievalContext

    retriever = HybridRetriever()
    store = Mock()
    store.similarity_search.side_effect = ConnectionError("Injected Chroma unavailable")
    with patch.object(retriever, "_get_query_embedding", return_value=[0.0]):
        try:
            retriever.retrieve(RetrievalContext(question="Tesla revenue", company="Tesla", tenant_id=999), store)
        except ConnectionError:
            return {
                "injected": "chroma_unavailable",
                "outcome": "Exception propagated; no invented evidence",
                "returned_evidence": False,
                "scope": "Retriever seam; HTTP error UX/state not verified",
            }
    raise AssertionError("Unavailable Chroma did not fail closed")


def redis_case():
    from cache.session import SessionCache
    from tasks.broker import TaskBroker

    fake = Mock()
    fake.get.side_effect = ConnectionError("Injected Redis unavailable")
    fake.setex.side_effect = ConnectionError("Injected Redis unavailable")
    with (
        patch("cache.session.get_redis_client", return_value=fake),
        patch("cache.session.is_redis_available", return_value=True),
    ):
        cache = SessionCache()
        missing = cache.get_session("fault-drill", tenant_id=999)
        cache.save_session("fault-drill", {"answer": "test"}, tenant_id=999)
        fake.get.side_effect = None
        fake.get.return_value = json.dumps({"answer": "restored cache"})
        recovered = cache.get_session("fault-drill", tenant_id=999)
    with patch("redis.Redis") as factory:
        factory.return_value.ping.side_effect = ConnectionError("Injected Redis unavailable")
        broker = TaskBroker()
        broker._enabled = True
        fallback = not broker.enabled
    return {
        "injected": "redis_unavailable",
        "cache_miss_safe": missing is None,
        "cache_recovered": recovered == {"answer": "restored cache"},
        "broker_db_polling_fallback": fallback,
        "scope": "Cache/broker classes; actual worker DB polling and full conversation persistence not verified",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = {
        "injections": [provider_case(s) for s in [429, 503, "timeout"]],
        "chroma": chroma_case(),
        "redis": redis_case(),
        "real_provider_calls": 0,
        "production_dependencies_stopped": False,
        "conversation_state_check": "NOT_VERIFIED",
    }
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
