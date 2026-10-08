from contextlib import nullcontext
from types import SimpleNamespace

from services.agent_runtime import runtime


def test_generation_duration_is_saved_in_assistant_message_metadata(monkeypatch):
    recorded_messages = []
    times = iter((100.0, 118.2))
    monkeypatch.setattr(runtime, "time", SimpleNamespace(time=lambda: next(times)))
    monkeypatch.setattr(runtime, "_load_history", lambda *args, **kwargs: [])
    monkeypatch.setattr(runtime, "_load_runtime_llm_settings", lambda *args: None)
    monkeypatch.setattr(runtime, "_try_cache", lambda *args: None)
    monkeypatch.setattr(runtime, "_save_to_cache", lambda *args: None)
    monkeypatch.setattr(runtime, "is_agent_available", lambda: True)
    monkeypatch.setattr(
        runtime, "get_agent_graph",
        lambda: {"run_agent": lambda *args, **kwargs: {"answer": "An explanation."}},
    )
    monkeypatch.setattr(runtime, "agent_checkpointer", lambda *args: nullcontext(None))
    monkeypatch.setattr(runtime, "node_span", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(
        runtime, "start_trace",
        lambda **kwargs: SimpleNamespace(request_id="duration-trace"),
    )
    for name in ("finish_trace", "log_agent_request", "log_agent_response"):
        monkeypatch.setattr(runtime, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(
        runtime, "_record_message",
        lambda *args, **kwargs: recorded_messages.append((args, kwargs)),
    )

    result = runtime.run_agent(
        "What is AI?", thread_id="duration-thread", tenant_id=7, user_id=11,
    )

    assert result["duration"] == 18.2
    assert [entry[1]["role"] for entry in recorded_messages] == ["user", "assistant"]
    assistant = recorded_messages[1]
    assert assistant[0] == (7, 11, "duration-thread")
    assert assistant[1]["metadata"]["duration_ms"] == 18200
    assert assistant[1]["metadata"]["trace_id"] == "duration-trace"
