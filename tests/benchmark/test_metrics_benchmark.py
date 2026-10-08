# ============================================================
# test_metrics_benchmark.py
# Metrics Framework Benchmark & Regression
# ============================================================
# 验证：
#   1. Counter Accuracy (increment × 100 → count=100)
#   2. Timer Accuracy (observe → collect)
#   3. Histogram Accuracy (distribution correctness)
#   4. Multi Metric Aggregation
#   5. Performance Benchmark (against latency targets)
# ============================================================

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from agent.metrics import (
    BaseMetric,
    MetricContext,
    MetricEngine,
    MetricFactory,
    MetricRecord,
    MetricScope,
    MetricType,
)

# ============================================================
# 1. Counter Accuracy
# ============================================================

class TestCounterAccuracy:

    def test_increment_100_yields_count_100(self):
        engine = MetricEngine()
        ctx = MetricContext()

        for i in range(100):
            engine.increment(ctx, "tool_calls", value=1.0,
                             scope=MetricScope.TOOL,
                             labels={"tool": "python"})

        result = engine.collect()
        assert result.count == 100
        assert result.success is True
        for record in result.records:
            assert record.metric_type == MetricType.COUNTER
            assert record.name == "tool_calls"
            assert record.labels["tool"] == "python"

    def test_increment_multiple_names(self):
        engine = MetricEngine()
        ctx = MetricContext()

        engine.increment(ctx, "tool_calls", scope=MetricScope.TOOL)
        engine.increment(ctx, "tool_calls", scope=MetricScope.TOOL)
        engine.increment(ctx, "provider_requests", scope=MetricScope.PROVIDER)
        engine.increment(ctx, "provider_requests", scope=MetricScope.PROVIDER)
        engine.increment(ctx, "provider_requests", scope=MetricScope.PROVIDER)

        result = engine.collect()
        assert result.count == 5

        tool_calls = [r for r in result.records if r.name == "tool_calls"]
        provider_reqs = [r for r in result.records if r.name == "provider_requests"]
        assert len(tool_calls) == 2
        assert len(provider_reqs) == 3

    def test_increment_custom_value(self):
        engine = MetricEngine()
        ctx = MetricContext()

        engine.increment(ctx, "batch_items", value=50.0)
        result = engine.collect()
        assert result.records[0].value == 50.0


# ============================================================
# 2. Timer Accuracy
# ============================================================

class TestTimerAccuracy:

    def test_observe_stores_correct_value(self):
        engine = MetricEngine()
        ctx = MetricContext()

        engine.observe(ctx, "provider_latency", 320.0,
                       scope=MetricScope.PROVIDER,
                       labels={"provider": "gemini"})
        engine.observe(ctx, "provider_latency", 180.0,
                       scope=MetricScope.PROVIDER,
                       labels={"provider": "deepseek"})

        result = engine.collect()
        assert result.count == 2
        assert result.records[0].metric_type == MetricType.TIMER
        assert result.records[0].value == 320.0
        assert result.records[0].labels["provider"] == "gemini"
        assert result.records[1].value == 180.0
        assert result.records[1].labels["provider"] == "deepseek"

    def test_observe_with_labels_preserved(self):
        engine = MetricEngine()
        ctx = MetricContext()

        engine.observe(ctx, "workflow_duration", 450.0,
                       labels={"workflow": "rag", "step": "retrieval"})

        result = engine.collect()
        assert result.records[0].labels["workflow"] == "rag"
        assert result.records[0].labels["step"] == "retrieval"


# ============================================================
# 3. Histogram Accuracy
# ============================================================

class TestHistogramAccuracy:

    def test_histogram_values_correct(self):
        engine = MetricEngine()
        ctx = MetricContext()

        values = [100.0, 200.0, 300.0]
        for v in values:
            engine.observe(ctx, "token_usage", v,
                           metric_type=MetricType.HISTOGRAM,
                           scope=MetricScope.PROVIDER)

        result = engine.collect()
        assert result.count == 3
        for i, record in enumerate(result.records):
            assert record.metric_type == MetricType.HISTOGRAM
            assert record.value == values[i]

    def test_histogram_large_distribution(self):
        engine = MetricEngine()
        ctx = MetricContext()

        n = 50
        for i in range(n):
            engine.observe(ctx, "response_size", float(i * 100),
                           metric_type=MetricType.HISTOGRAM)

        result = engine.collect()
        assert result.count == n
        assert result.records[0].value == 0.0
        assert result.records[-1].value == 4900.0


# ============================================================
# 4. Multi Metric Aggregation
# ============================================================

class TestMultiMetricAggregation:

    def test_counter_timer_histogram_together(self):
        engine = MetricEngine()
        ctx = MetricContext()

        engine.increment(ctx, "tool_calls", scope=MetricScope.TOOL,
                         labels={"tool": "retrieval"})
        engine.increment(ctx, "tool_calls", scope=MetricScope.TOOL,
                         labels={"tool": "python"})
        engine.observe(ctx, "provider_latency", 320.0,
                       scope=MetricScope.PROVIDER,
                       labels={"provider": "gemini"})
        engine.observe(ctx, "token_usage", 1024.0,
                       metric_type=MetricType.HISTOGRAM,
                       scope=MetricScope.PROVIDER)

        result = engine.collect()
        assert result.count == 4
        assert result.success is True

        types = {r.metric_type for r in result.records}
        assert types == {MetricType.COUNTER, MetricType.TIMER, MetricType.HISTOGRAM}

    def test_aggregation_respects_instance_count(self):
        engine = MetricEngine()
        ctx = MetricContext()

        assert engine.instance_count == 0
        engine.increment(ctx, "a", 1)
        assert engine.instance_count == 1
        engine.observe(ctx, "b", 100)
        assert engine.instance_count == 2
        engine.observe(ctx, "c", 200, metric_type=MetricType.HISTOGRAM)
        assert engine.instance_count == 3

        result = engine.collect()
        assert result.count == 3

    def test_all_three_metric_names_accessible(self):
        ctx = MetricContext()

        for name in ["counter", "timer", "histogram"]:
            metric = MetricFactory.create(name)
            assert isinstance(metric, BaseMetric)


# ============================================================
# 5. Performance Benchmark
# ============================================================

class TestPerformance:

    @pytest.mark.perf
    def test_increment_latency(self):
        engine = MetricEngine()
        ctx = MetricContext()

        n = 100
        start = time.perf_counter()
        for _ in range(n):
            engine.increment(ctx, "perf_counter")
        elapsed = time.perf_counter() - start
        ms_per = (elapsed * 1000) / n
        assert ms_per < 1.0

    @pytest.mark.perf
    def test_observe_latency(self):
        engine = MetricEngine()
        ctx = MetricContext()

        n = 100
        start = time.perf_counter()
        for _ in range(n):
            engine.observe(ctx, "perf_timer", 100.0)
        elapsed = time.perf_counter() - start
        ms_per = (elapsed * 1000) / n
        assert ms_per < 1.0

    @pytest.mark.perf
    def test_record_latency(self):
        engine = MetricEngine()
        ctx = MetricContext()

        n = 100
        start = time.perf_counter()
        for _ in range(n):
            engine.record(ctx, MetricRecord(
                name="perf_record",
                metric_type=MetricType.TIMER,
                value=100.0,
                scope=MetricScope.RUNTIME,
                timestamp=time.time(),
            ))
        elapsed = time.perf_counter() - start
        ms_per = (elapsed * 1000) / n
        assert ms_per < 1.0

    @pytest.mark.perf
    def test_collect_latency(self):
        engine = MetricEngine()
        ctx = MetricContext()

        n = 500
        for _ in range(n):
            engine.increment(ctx, "perf_collect")
        start = time.perf_counter()
        result = engine.collect()
        elapsed = time.perf_counter() - start
        ms = elapsed * 1000
        assert result.count == n
        assert ms < 5.0

    @pytest.mark.perf
    def test_10000_records_latency(self):
        engine = MetricEngine()
        ctx = MetricContext()

        n = 10000
        start = time.perf_counter()
        for _ in range(n):
            engine.increment(ctx, "perf_massive")
        elapsed = time.perf_counter() - start
        ms = elapsed * 1000
        assert ms < 100.0

    @pytest.mark.perf
    def test_multi_metric_full_pipeline(self):
        n = 100
        start = time.perf_counter()
        for _ in range(n):
            engine = MetricEngine()
            ctx = MetricContext()
            engine.increment(ctx, "tool_calls", scope=MetricScope.TOOL,
                             labels={"tool": "python"})
            engine.observe(ctx, "provider_latency", 320.0,
                           scope=MetricScope.PROVIDER,
                           labels={"provider": "gemini"})
            engine.observe(ctx, "token_usage", 1024.0,
                           metric_type=MetricType.HISTOGRAM)
            result = engine.collect()
        elapsed = time.perf_counter() - start
        ms_per_iter = (elapsed * 1000) / n
        assert ms_per_iter < 10.0


# ============================================================
# 6. Hook Integration
# ============================================================

class TestHookIntegration:

    def test_hooks_fire_on_record_and_collect(self):
        engine = MetricEngine()
        ctx = MetricContext()

        calls = []
        engine.add_before_record_hook(lambda c, r: calls.append("before_record"))
        engine.add_after_record_hook(lambda c, r: calls.append("after_record"))
        engine.add_before_collect_hook(lambda c: calls.append("before_collect"))
        engine.add_after_collect_hook(lambda r: calls.append("after_collect"))

        engine.increment(ctx, "test")
        result = engine.collect(ctx)

        assert calls == ["before_record", "after_record", "before_collect", "after_collect"]
