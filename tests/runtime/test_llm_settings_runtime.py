import json
import sys
from contextlib import nullcontext
from types import ModuleType, SimpleNamespace

from services.agent_runtime import graph, runtime
from services.llm_settings_service import RuntimeLLMSettings


def test_response_language_is_part_of_chat_cache_key():
    common = ("Moutai FY2025 revenue?", [], "贵州茅台")
    english = runtime._cache_key(*common, answer_language="en")
    chinese = runtime._cache_key(*common, answer_language="zh-CN")

    assert english != chinese


def _settings(revision: str, api_key: str) -> RuntimeLLMSettings:
    return RuntimeLLMSettings(
        provider_configs={
            "deepseek": {
                "api_key": api_key,
                "base_url": "https://api.deepseek.com",
            }
        },
        provider_models={"deepseek": "deepseek-v4-flash"},
        default_provider="deepseek",
        revision=revision,
    )


def test_runtime_passes_request_settings_to_graph_and_revises_cache_key(
    monkeypatch,
):
    settings_a = _settings("settings-revision-a", "sk-runtime-a")
    settings_b = _settings("settings-revision-b", "sk-runtime-b")
    loaded_settings = iter((settings_a, settings_b))
    graph_calls = []
    cache_keys = []

    def fake_graph_run(question, **kwargs):
        graph_calls.append((question, kwargs))
        return {
            "answer": "safe fake response",
            "thread_id": kwargs["thread_id"],
        }

    def fake_try_cache(
        tenant_id,
        user_id,
        thread_id,
        request_key,
    ):
        del tenant_id, user_id, thread_id
        cache_keys.append(request_key)
        return None

    monkeypatch.setattr(
        runtime,
        "_load_runtime_llm_settings",
        lambda tenant_id, user_id: next(loaded_settings),
    )
    monkeypatch.setattr(runtime, "_load_history", lambda *args, **kwargs: [])
    monkeypatch.setattr(runtime, "_try_cache", fake_try_cache)
    monkeypatch.setattr(runtime, "_record_message", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime, "_save_to_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime, "is_agent_available", lambda: True)
    monkeypatch.setattr(
        runtime,
        "get_agent_graph",
        lambda: {"run_agent": fake_graph_run},
    )
    monkeypatch.setattr(
        runtime,
        "agent_checkpointer",
        lambda *args, **kwargs: nullcontext(None),
    )
    monkeypatch.setattr(
        runtime,
        "node_span",
        lambda *args, **kwargs: nullcontext(),
    )
    monkeypatch.setattr(
        runtime,
        "start_trace",
        lambda **kwargs: SimpleNamespace(request_id="trace-settings"),
    )
    monkeypatch.setattr(runtime, "finish_trace", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        runtime,
        "log_agent_request",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        runtime,
        "log_agent_response",
        lambda *args, **kwargs: None,
    )

    first = runtime.run_agent(
        "What is AI?",
        tenant_id=7,
        user_id=11,
        thread_id="settings-runtime",
    )
    second = runtime.run_agent(
        "What is AI?",
        tenant_id=7,
        user_id=11,
        thread_id="settings-runtime",
    )

    assert first["answer"] == "safe fake response"
    assert second["answer"] == "safe fake response"
    assert graph_calls[0][1]["llm_settings"] is settings_a
    assert graph_calls[1][1]["llm_settings"] is settings_b
    assert cache_keys[0] != cache_keys[1]
    assert json.loads(cache_keys[0])["llm_settings_revision"] == (
        "settings-revision-a"
    )
    assert json.loads(cache_keys[1])["llm_settings_revision"] == (
        "settings-revision-b"
    )
    assert "sk-runtime-a" not in cache_keys[0]
    assert "sk-runtime-b" not in cache_keys[1]


def test_graph_places_request_settings_in_langgraph_context(monkeypatch):
    llm_settings = _settings("graph-revision", "sk-graph-context")
    invocation = {}

    class FakeCompiledGraph:
        def invoke(
            self,
            state,
            *,
            config,
            context,
            durability,
        ):
            invocation.update(
                {
                    "state": state,
                    "config": config,
                    "context": context,
                    "durability": durability,
                }
            )
            return {"answer": "fake graph answer"}

    monkeypatch.setattr(
        graph,
        "build_agent_graph",
        lambda: FakeCompiledGraph(),
    )

    response = graph.run_agent(
        "Analyze Tesla",
        tenant_id=23,
        user_id=42,
        llm_settings=llm_settings,
    )

    assert response["answer"] == "fake graph answer"
    assert invocation["state"]["tenant_id"] == 23
    assert invocation["state"]["user_id"] == 42
    assert invocation["context"]["llm_settings"] is llm_settings
    assert invocation["durability"] is None


def test_disabled_real_provider_returns_specific_secret_free_fallback():
    result = runtime._fallback_response(
        "用户问题不应被回显",
        "disabled-provider-test",
        "Real provider calls are disabled; set ALLOW_REAL_PROVIDER=true only for an explicit live run",
    )

    assert result["answer"].startswith("[Provider Disabled]")
    assert "No AI answer was generated" in result["answer"]
    assert "用户问题不应被回显" not in result["answer"]


def test_execute_node_forwards_context_settings_to_core_runtime(monkeypatch):
    llm_settings = _settings("execute-revision", "sk-execute-context")
    captured = {}

    def fake_run_rag(question, **kwargs):
        captured["question"] = question
        captured.update(kwargs)
        return SimpleNamespace(
            report="fake report",
            citations=[],
            context="",
            research_mode="default",
            intent={"intent": "SINGLE_COMPANY"},
            evidence=[],
            plan=SimpleNamespace(tasks=[], intent="SINGLE_COMPANY"),
            routing=None,
            planning=None,
            execution=None,
            workflow=None,
        )

    fake_core_engine = ModuleType("core.core_engine")
    fake_core_engine.run_rag = fake_run_rag
    monkeypatch.setitem(sys.modules, "core.core_engine", fake_core_engine)

    result = graph._execute_node(
        {
            "question": "Analyze Tesla",
            "company": "Tesla",
            "tenant_id": 31,
            "thread_id": "request-scope",
            "history": [],
        },
        SimpleNamespace(context={"llm_settings": llm_settings}),
    )

    assert result["report"] == "fake report"
    assert captured["tenant_id"] == 31
    assert captured["llm_settings"] is llm_settings
