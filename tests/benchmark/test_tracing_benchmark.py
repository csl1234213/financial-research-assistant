# ============================================================
# test_tracing_benchmark.py
# Tracing Framework Benchmark & Regression
# ============================================================
# 验证：
#   1. Span Parent ID Accuracy (Nested spans)
#   2. Event Metadata Accuracy
#   3. Exception Handling (FAILED status)
#   4. Context Manager Span Auto-closing
#   5. Performance Benchmark (against latency targets)
# ============================================================

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from agent.tracing import (
    TraceContext,
    TraceEngine,
    TraceLevel,
    TraceResult,
    TracerType,
    TraceStatus,
    TraceType,
)

# ============================================================
# 1. Span Accuracy: Nested Parent IDs
# ============================================================

class TestSpanAccuracy:

    def test_nested_three_level_parent_id(self):
        """Runtime → Planning → Analyzer"""
        engine = TraceEngine()
        ctx = TraceContext()

        engine.start_trace(ctx, TracerType.MEMORY)

        span_runtime = engine.start_span("Runtime", TraceType.RUNTIME)
        assert span_runtime.parent_id is None

        span_planning = engine.start_span("Planning", TraceType.PLANNING)
        assert span_planning.parent_id == span_runtime.id

        span_analyzer = engine.start_span("Analyzer", TraceType.PLANNING)
        assert span_analyzer.parent_id == span_planning.id

        result = engine.finish_trace()
        assert len(result.spans) == 3

        # Verify the order and parent relationships
        spans = result.spans
        spans_by_id = {s.id: s for s in spans}

        assert spans[0].id == span_runtime.id
        assert spans[0].parent_id is None

        assert spans[1].id == span_planning.id
        assert spans[1].parent_id == span_runtime.id

        assert spans[2].id == span_analyzer.id
        assert spans[2].parent_id == span_planning.id

    def test_nested_multi_level_pop_verify(self):
        """Test that popping the stack restores correct parent"""
        engine = TraceEngine()
        ctx = TraceContext()

        engine.start_trace(ctx, TracerType.MEMORY)

        s1 = engine.start_span("Level1", TraceType.RUNTIME)
        s2 = engine.start_span("Level2", TraceType.RUNTIME)
        s3 = engine.start_span("Level3", TraceType.RUNTIME)

        assert engine.current_span is s3
        engine.end_span()
        assert engine.current_span is s2
        engine.end_span()
        assert engine.current_span is s1
        engine.end_span()
        assert engine.current_span is None

        result = engine.finish_trace()
        assert len(result.spans) == 3

    def test_span_depth_correct(self):
        engine = TraceEngine()
        ctx = TraceContext()
        engine.start_trace(ctx, TracerType.MEMORY)

        assert engine.span_depth == 0
        engine.start_span("A", TraceType.RUNTIME)
        assert engine.span_depth == 1
        engine.start_span("B", TraceType.RUNTIME)
        assert engine.span_depth == 2
        engine.start_span("C", TraceType.RUNTIME)
        assert engine.span_depth == 3
        engine.end_span()
        assert engine.span_depth == 2

        result = engine.finish_trace()
        assert len(result.spans) == 3


# ============================================================
# 2. Event Accuracy
# ============================================================

class TestEventAccuracy:

    def test_record_event_metadata_saved(self):
        engine = TraceEngine()
        ctx = TraceContext()
        engine.start_trace(ctx, TracerType.MEMORY)

        event = engine.record_event(
            "test message",
            TraceLevel.INFO,
            {"key": "value", "count": 42}
        )

        result = engine.finish_trace()
        assert len(result.events) == 1
        saved = result.events[0]
        assert saved.message == "test message"
        assert saved.level == TraceLevel.INFO
        assert saved.metadata["key"] == "value"
        assert saved.metadata["count"] == 42

    def test_multiple_events_all_saved(self):
        engine = TraceEngine()
        ctx = TraceContext()
        engine.start_trace(ctx, TracerType.MEMORY)

        events = []
        for i in range(10):
            event = engine.record_event(f"event_{i}", TraceLevel.DEBUG, {"i": i})
            events.append(event)

        result = engine.finish_trace()
        assert len(result.events) == 10
        for i, saved in enumerate(result.events):
            assert saved.message == f"event_{i}"
            assert saved.metadata["i"] == i


# ============================================================
# 3. Exception Handling
# ============================================================

class TestExceptionHandling:

    def test_exception_leaves_failed_status(self):
        engine = TraceEngine()
        ctx = TraceContext()
        engine.start_trace(ctx, TracerType.MEMORY)

        span = engine.start_span("Failing", TraceType.RUNTIME)
        try:
            raise ValueError("simulated failure")
        except ValueError:
            engine.end_span(TraceStatus.FAILED)

        result = engine.finish_trace()
        assert result.spans[0].status == TraceStatus.FAILED
        assert not result.success

    def test_exception_propagation_span_status(self):
        engine = TraceEngine()
        ctx = TraceContext()
        engine.start_trace(ctx, TracerType.MEMORY)

        span = engine.start_span("TopLevel", TraceType.RUNTIME)
        try:
            inner = engine.start_span("InnerFailing", TraceType.RUNTIME)
            raise RuntimeError("inner failure")
        except RuntimeError:
            engine.end_span(TraceStatus.FAILED)

        engine.end_span(TraceStatus.SUCCESS)
        result = engine.finish_trace()

        assert result.spans[0].status == TraceStatus.SUCCESS
        assert result.spans[1].status == TraceStatus.FAILED
        assert not result.success


# ============================================================
# 4. Context Manager
# ============================================================

class TestContextManager:

    def test_context_manager_auto_close_success(self):
        engine = TraceEngine()
        ctx = TraceContext()
        engine.start_trace(ctx, TracerType.MEMORY)

        with engine.span("AutoClosed", TraceType.RUNTIME) as span:
            assert span is not None
            assert engine.span_depth == 1

        assert engine.span_depth == 0
        result = engine.finish_trace()
        assert result.spans[0].status == TraceStatus.SUCCESS

    def test_context_manager_mark_failed_on_exception(self):
        engine = TraceEngine()
        ctx = TraceContext()
        engine.start_trace(ctx, TracerType.MEMORY)

        caught = False
        try:
            with engine.span("ExceptionSpan", TraceType.RUNTIME):
                raise ValueError("oops")
        except ValueError:
            caught = True

        assert caught
        result = engine.finish_trace()
        assert result.spans[0].status == TraceStatus.FAILED

    def test_context_manager_nested(self):
        engine = TraceEngine()
        ctx = TraceContext()
        engine.start_trace(ctx, TracerType.MEMORY)

        with engine.span("Level1", TraceType.RUNTIME):
            assert engine.span_depth == 1
            with engine.span("Level2", TraceType.RUNTIME):
                assert engine.span_depth == 2
                with engine.span("Level3", TraceType.RUNTIME):
                    assert engine.span_depth == 3
                assert engine.span_depth == 2
            assert engine.span_depth == 1
        assert engine.span_depth == 0

        result = engine.finish_trace()
        assert len(result.spans) == 3
        assert all(s.status == TraceStatus.SUCCESS for s in result.spans)


# ============================================================
# 5. Performance Benchmark
# ============================================================

class TestPerformance:

    @pytest.mark.perf
    def test_start_span_latency(self):
        engine = TraceEngine()
        ctx = TraceContext()
        engine.start_trace(ctx, TracerType.MEMORY)

        n = 100
        start = time.perf_counter()
        for _ in range(n):
            engine.start_span("perf", TraceType.RUNTIME)
        elapsed = time.perf_counter() - start
        ms_per = (elapsed * 1000) / n
        assert ms_per < 1.0

    @pytest.mark.perf
    def test_record_event_latency(self):
        engine = TraceEngine()
        ctx = TraceContext()
        engine.start_trace(ctx, TracerType.MEMORY)

        n = 100
        start = time.perf_counter()
        for _ in range(n):
            engine.record_event("perf", TraceLevel.INFO, {"key": "val"})
        elapsed = time.perf_counter() - start
        ms_per = (elapsed * 1000) / n
        assert ms_per < 0.5

    @pytest.mark.perf
    def test_end_span_latency(self):
        engine = TraceEngine()
        ctx = TraceContext()
        engine.start_trace(ctx, TracerType.MEMORY)

        n = 100
        for _ in range(n):
            engine.start_span("perf", TraceType.RUNTIME)
        start = time.perf_counter()
        for _ in range(n):
            engine.end_span()
        elapsed = time.perf_counter() - start
        ms_per = (elapsed * 1000) / n
        assert ms_per < 1.0

    @pytest.mark.perf
    def test_flush_latency(self):
        engine = TraceEngine()
        ctx = TraceContext()
        engine.start_trace(ctx, TracerType.MEMORY)

        n = 100
        for i in range(n):
            engine.start_span(f"span_{i}", TraceType.RUNTIME)
            engine.record_event(f"event_{i}", TraceLevel.INFO)
            engine.end_span()

        start = time.perf_counter()
        result = engine.finish_trace()
        elapsed = time.perf_counter() - start
        ms = elapsed * 1000
        assert ms < 5.0

    @pytest.mark.perf
    def test_nested_100_spans_latency(self):
        engine = TraceEngine()
        ctx = TraceContext()
        engine.start_trace(ctx, TracerType.MEMORY)

        start = time.perf_counter()
        depth = 100
        for i in range(depth):
            engine.start_span(f"level_{i}", TraceType.RUNTIME)
        for _ in range(depth):
            engine.end_span()
        elapsed = time.perf_counter() - start
        ms = elapsed * 1000
        assert ms < 20.0

    @pytest.mark.perf
    def test_full_pipeline_latency(self):
        n = 50
        start = time.perf_counter()
        for _ in range(n):
            engine = TraceEngine()
            ctx = TraceContext()
            engine.start_trace(ctx, TracerType.MEMORY)
            with engine.span("Runtime", TraceType.RUNTIME):
                engine.record_event("started", TraceLevel.INFO)
                with engine.span("Planning", TraceType.PLANNING):
                    engine.record_event("analyzing", TraceLevel.INFO)
                with engine.span("Workflow", TraceType.WORKFLOW):
                    engine.record_event("building", TraceLevel.INFO)
                    with engine.span("Tool", TraceType.TOOL):
                        engine.record_event("tool_exec", TraceLevel.INFO)
            result = engine.finish_trace()
        elapsed = time.perf_counter() - start
        ms_per_iter = (elapsed * 1000) / n
        assert ms_per_iter < 10.0


# ============================================================
# 6. Integration with Factory and Registry
# ============================================================

class TestIntegration:

    def test_engine_factory_registry_full_chain(self):
        """Verify full call chain: Engine → Factory → Registry → Tracer"""
        engine = TraceEngine()
        ctx = TraceContext()

        engine.set_default_tracer_type(TracerType.MEMORY)
        engine.start_trace(ctx)
        assert engine.tracer_name == "memory"

        with engine.span("Test", TraceType.RUNTIME):
            engine.record_event("test")
        result = engine.finish_trace()

        assert result.success
        assert len(result.spans) == 1
        assert len(result.events) == 1

    def test_hook_execution_order(self):
        engine = TraceEngine()
        ctx = TraceContext()

        order = []
        def before(ctx):
            order.append("before")
        def after(result):
            order.append("after")
            result.metadata["hook_called"] = True

        engine.add_before_trace_hook(before)
        engine.add_after_trace_hook(after)

        result = engine.trace(ctx)
        assert order == ["before", "after"]

    def test_all_builtin_tracers_work_with_engine(self):
        ctx = TraceContext()

        for tracer_type in [TracerType.CONSOLE, TracerType.MEMORY, TracerType.FILE]:
            engine = TraceEngine()
            engine.start_trace(ctx, tracer_type)
            with engine.span("test", TraceType.RUNTIME):
                engine.record_event("test")
            result = engine.finish_trace()
            assert isinstance(result, TraceResult)
            assert len(result.spans) == 1
