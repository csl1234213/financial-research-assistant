"""Behavioral coverage for the reusable agent tracing subsystem."""

import pytest

from agent.tracing import (
    MemoryTracer,
    TraceContext,
    TraceEngine,
    TraceFactory,
    TraceLevel,
    TraceRegistry,
    TracerNotFound,
    TracerRegistrationError,
    TracerType,
    TraceStatus,
    TraceType,
)


def test_memory_trace_captures_nested_spans_events_and_hooks():
    engine = TraceEngine()
    context = TraceContext(metadata={"tenant_id": "tenant-a"})
    hook_calls: list[str] = []

    engine.add_before_trace_hook(lambda received: hook_calls.append(received.metadata["tenant_id"]))
    engine.add_before_trace_hook(lambda _context: (_ for _ in ()).throw(RuntimeError("ignored")))
    engine.add_after_trace_hook(lambda result: hook_calls.append(str(result.success)))
    engine.add_after_trace_hook(lambda _result: (_ for _ in ()).throw(RuntimeError("ignored")))

    engine.set_default_tracer_type("memory")
    engine.start_trace(context)
    assert engine.tracer_name == "memory"

    with engine.span("runtime", TraceType.RUNTIME, {"request_id": "request-a"}) as parent:
        assert parent.parent_id is None
        assert parent.metadata == {"request_id": "request-a"}
        assert engine.current_span is parent

        child = engine.start_span("retrieval", TraceType.TOOL)
        assert child.parent_id == parent.id
        event = engine.record_event("retrieved", TraceLevel.DEBUG, {"documents": 2})
        assert event is not None
        assert event.metadata == {"documents": 2}
        assert engine.end_span() is child

    result = engine.finish_trace()

    assert hook_calls == ["tenant-a", "True"]
    assert engine.span_depth == 0
    assert [span.name for span in result.spans] == ["runtime", "retrieval"]
    assert all(span.status is TraceStatus.SUCCESS for span in result.spans)
    assert result.events == [event]
    assert result.success is True


def test_trace_engine_guards_and_failure_path():
    engine = TraceEngine()

    assert engine.finish_trace().success is True
    assert engine.end_span() is None
    assert engine.record_event("ignored") is None
    assert engine.current_span is None
    assert engine.tracer_name is None
    with pytest.raises(RuntimeError, match="not started"):
        engine.start_span("invalid", TraceType.RUNTIME)

    engine.start_trace(TraceContext(), TracerType.MEMORY)
    with pytest.raises(ValueError, match="boom"):
        with engine.span("failure", TraceType.EXECUTION):
            raise ValueError("boom")

    result = engine.finish_trace()
    assert result.spans[0].status is TraceStatus.FAILED
    assert result.success is False


def test_factory_registry_contracts(monkeypatch):
    monkeypatch.setattr(TraceFactory, "_default_tracer", None)

    assert {"console", "memory", "file"} <= set(TraceRegistry.list_tracers())
    assert TraceRegistry.has_tracer("memory")
    assert TraceRegistry.get("memory") is MemoryTracer
    assert TraceRegistry.get_metadata("memory").persistent is False

    with pytest.raises(TracerNotFound):
        TraceRegistry.get("missing")
    with pytest.raises(TracerNotFound):
        TraceRegistry.get_metadata("missing")
    with pytest.raises(TracerRegistrationError):
        TraceRegistry.register("invalid", object)
    with pytest.raises(TracerRegistrationError):
        TraceRegistry.register("memory", MemoryTracer)
    with pytest.raises(KeyError):
        TraceFactory.set_default("missing")
    with pytest.raises(RuntimeError, match="No default tracer"):
        TraceFactory.create_default()

    TraceFactory.set_default(TracerType.MEMORY)
    assert TraceFactory.get_default() == "memory"
    assert isinstance(TraceFactory.create_default(), MemoryTracer)
    assert isinstance(TraceFactory.create("memory"), MemoryTracer)


@pytest.mark.parametrize(
    ("tracer_type", "expected_name"),
    [
        (TracerType.CONSOLE, "console"),
        (TracerType.MEMORY, "memory"),
        (TracerType.FILE, "file"),
    ],
)
def test_all_builtin_tracers_share_the_engine_contract(tracer_type, expected_name):
    engine = TraceEngine().start_trace(TraceContext(), tracer_type)
    tracer = TraceFactory.create(tracer_type)

    assert engine.tracer_name == expected_name
    assert tracer.supports(TraceContext()) is True
    engine.start_span("operation", TraceType.WORKFLOW)
    engine.record_event("complete")

    result = engine.finish_trace()
    assert len(result.spans) == 1
    assert len(result.events) == 1
    assert result.success is True


def test_one_shot_trace_uses_selected_tracer():
    result = TraceEngine().trace(TraceContext(), TracerType.MEMORY)

    assert result.spans == []
    assert result.events == []
    assert result.success is True
