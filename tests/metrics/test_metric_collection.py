# ============================================================
# test_metric_collection.py
# Auto Metrics Collection Test Matrix
# ============================================================
# 验证：
#   1. MetricEvent 创建
#   2. MetricCollector 创建
#   3. Event → Record 转换
#   4. Label 保留
#   5. emit_counter / emit_timer / emit_histogram
#   6. Workflow Metrics
#   7. Execution Metrics
#   8. Tool Metrics
#   9. Provider Metrics
#   10. Memory Metrics
#   11. 多模块聚合
# ============================================================

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


from agent.metrics import (
    MetricCollector,
    MetricEngine,
    MetricEvent,
    MetricResult,
    MetricScope,
    MetricType,
)


class TestMetricEvent:

    def test_event_creation_basic(self):
        event = MetricEvent(
            name="test_metric",
            scope=MetricScope.RUNTIME,
            metric_type=MetricType.COUNTER,
            value=1.0,
        )
        assert event.name == "test_metric"
        assert event.scope == MetricScope.RUNTIME
        assert event.metric_type == MetricType.COUNTER
        assert event.value == 1.0
        assert event.labels == {}

    def test_event_creation_with_labels(self):
        event = MetricEvent(
            name="tool_latency",
            scope=MetricScope.TOOL,
            metric_type=MetricType.TIMER,
            value=120.0,
            labels={"tool": "retrieval", "provider": "gemini"},
        )
        assert event.labels["tool"] == "retrieval"
        assert event.labels["provider"] == "gemini"

    def test_event_default_labels(self):
        event = MetricEvent(
            name="test",
            scope=MetricScope.RUNTIME,
            metric_type=MetricType.COUNTER,
            value=1.0,
        )
        assert event.labels == {}


class TestMetricCollector:

    def test_collector_creation(self):
        collector = MetricCollector(MetricEngine())
        assert collector.event_count == 0
        assert isinstance(collector.engine, MetricEngine)

    def test_emit_single_event(self):
        collector = MetricCollector(MetricEngine())
        event = MetricEvent(
            name="test_counter",
            scope=MetricScope.RUNTIME,
            metric_type=MetricType.COUNTER,
            value=1.0,
        )
        collector.emit(event)
        assert collector.event_count == 1

    def test_emit_batch_events(self):
        collector = MetricCollector(MetricEngine())
        events = [
            MetricEvent(name="e1", scope=MetricScope.RUNTIME, metric_type=MetricType.COUNTER, value=1.0),
            MetricEvent(name="e2", scope=MetricScope.RUNTIME, metric_type=MetricType.TIMER, value=100.0),
            MetricEvent(name="e3", scope=MetricScope.RUNTIME, metric_type=MetricType.HISTOGRAM, value=500.0),
        ]
        collector.emit_batch(events)
        assert collector.event_count == 3

    def test_emit_counter_convenience(self):
        collector = MetricCollector(MetricEngine())
        collector.emit_counter(
            name="test_count",
            scope=MetricScope.TOOL,
            value=1.0,
            labels={"tool": "python"},
        )
        assert collector.event_count == 1
        result = collector.collect()
        assert result.count == 1
        assert result.records[0].metric_type == MetricType.COUNTER
        assert result.records[0].labels["tool"] == "python"

    def test_emit_timer_convenience(self):
        collector = MetricCollector(MetricEngine())
        collector.emit_timer(
            name="test_latency",
            scope=MetricScope.PROVIDER,
            value=320.0,
            labels={"provider": "gemini"},
        )
        result = collector.collect()
        assert result.records[0].metric_type == MetricType.TIMER
        assert result.records[0].value == 320.0
        assert result.records[0].labels["provider"] == "gemini"

    def test_emit_histogram_convenience(self):
        collector = MetricCollector(MetricEngine())
        collector.emit_histogram(
            name="token_usage",
            scope=MetricScope.PROVIDER,
            value=1024.0,
        )
        result = collector.collect()
        assert result.records[0].metric_type == MetricType.HISTOGRAM
        assert result.records[0].value == 1024.0

    def test_collect_returns_metric_result(self):
        collector = MetricCollector(MetricEngine())
        collector.emit_counter("a", MetricScope.RUNTIME)
        result = collector.collect()
        assert isinstance(result, MetricResult)
        assert result.success is True
        assert result.count == 1


# ============================================================
# Workflow Metrics
# ============================================================

class TestWorkflowMetrics:

    def test_workflow_started_counter(self):
        collector = MetricCollector(MetricEngine())
        collector.emit_counter(
            name="workflow_started_total",
            scope=MetricScope.WORKFLOW,
            value=1.0,
            labels={"workflow": "rag"},
        )
        collector.emit_counter(
            name="workflow_started_total",
            scope=MetricScope.WORKFLOW,
            value=1.0,
            labels={"workflow": "multi_step"},
        )
        result = collector.collect()
        assert result.count == 2
        wf_names = {r.labels["workflow"] for r in result.records}
        assert wf_names == {"rag", "multi_step"}

    def test_workflow_completed_counter(self):
        collector = MetricCollector(MetricEngine())
        collector.emit_counter(
            name="workflow_completed_total",
            scope=MetricScope.WORKFLOW,
            value=1.0,
            labels={"workflow": "rag", "status": "success"},
        )
        collector.emit_counter(
            name="workflow_completed_total",
            scope=MetricScope.WORKFLOW,
            value=1.0,
            labels={"workflow": "rag", "status": "success"},
        )
        result = collector.collect()
        assert result.count == 2

    def test_workflow_duration_timer(self):
        collector = MetricCollector(MetricEngine())
        collector.emit_timer(
            name="workflow_duration",
            scope=MetricScope.WORKFLOW,
            value=450.0,
            labels={"workflow": "rag"},
        )
        collector.emit_timer(
            name="workflow_duration",
            scope=MetricScope.WORKFLOW,
            value=230.0,
            labels={"workflow": "multi_step"},
        )
        result = collector.collect()
        assert result.count == 2
        durations = {r.labels["workflow"]: r.value for r in result.records}
        assert durations["rag"] == 450.0
        assert durations["multi_step"] == 230.0


# ============================================================
# Execution Metrics
# ============================================================

class TestExecutionMetrics:

    def test_execution_total_counter(self):
        collector = MetricCollector(MetricEngine())
        n = 10
        for _ in range(n):
            collector.emit_counter(
                name="execution_total",
                scope=MetricScope.EXECUTION,
                value=1.0,
                labels={"strategy": "direct_llm"},
            )
        result = collector.collect()
        assert result.count == n

    def test_execution_duration_timer(self):
        collector = MetricCollector(MetricEngine())
        collector.emit_timer(
            name="execution_duration",
            scope=MetricScope.EXECUTION,
            value=150.0,
            labels={"strategy": "rag"},
        )
        collector.emit_timer(
            name="execution_duration",
            scope=MetricScope.EXECUTION,
            value=300.0,
            labels={"strategy": "multi_step"},
        )
        result = collector.collect()
        assert result.count == 2

    def test_execution_failed_counter(self):
        collector = MetricCollector(MetricEngine())
        collector.emit_counter(
            name="execution_failed_total",
            scope=MetricScope.EXECUTION,
            value=1.0,
            labels={"strategy": "rag", "error": "timeout"},
        )
        collector.emit_counter(
            name="execution_failed_total",
            scope=MetricScope.EXECUTION,
            value=1.0,
            labels={"strategy": "rag", "error": "rate_limit"},
        )
        result = collector.collect()
        assert result.count == 2


# ============================================================
# Tool Metrics
# ============================================================

class TestToolMetrics:

    def test_tool_calls_total_counter(self):
        collector = MetricCollector(MetricEngine())
        collector.emit_counter(
            name="tool_calls_total",
            scope=MetricScope.TOOL,
            value=1.0,
            labels={"tool": "retrieval"},
        )
        collector.emit_counter(
            name="tool_calls_total",
            scope=MetricScope.TOOL,
            value=1.0,
            labels={"tool": "retrieval"},
        )
        collector.emit_counter(
            name="tool_calls_total",
            scope=MetricScope.TOOL,
            value=1.0,
            labels={"tool": "python"},
        )
        result = collector.collect()
        assert result.count == 3

        retrieval_count = sum(1 for r in result.records if r.labels["tool"] == "retrieval")
        python_count = sum(1 for r in result.records if r.labels["tool"] == "python")
        assert retrieval_count == 2
        assert python_count == 1

    def test_tool_latency_timer(self):
        collector = MetricCollector(MetricEngine())
        collector.emit_timer(
            name="tool_latency",
            scope=MetricScope.TOOL,
            value=85.0,
            labels={"tool": "retrieval"},
        )
        collector.emit_timer(
            name="tool_latency",
            scope=MetricScope.TOOL,
            value=120.0,
            labels={"tool": "python"},
        )
        collector.emit_timer(
            name="tool_latency",
            scope=MetricScope.TOOL,
            value=95.0,
            labels={"tool": "retrieval"},
        )
        result = collector.collect()
        retrieval_latencies = [r.value for r in result.records if r.labels["tool"] == "retrieval"]
        assert retrieval_latencies == [85.0, 95.0]

    def test_tool_failed_counter(self):
        collector = MetricCollector(MetricEngine())
        collector.emit_counter(
            name="tool_failed_total",
            scope=MetricScope.TOOL,
            value=1.0,
            labels={"tool": "retrieval", "error": "connection_error"},
        )
        collector.emit_counter(
            name="tool_failed_total",
            scope=MetricScope.TOOL,
            value=1.0,
            labels={"tool": "python", "error": "syntax_error"},
        )
        result = collector.collect()
        assert result.count == 2


# ============================================================
# Provider Metrics
# ============================================================

class TestProviderMetrics:

    def test_provider_requests_total_counter(self):
        collector = MetricCollector(MetricEngine())
        collector.emit_counter(
            name="provider_requests_total",
            scope=MetricScope.PROVIDER,
            value=1.0,
            labels={"provider": "gemini", "model": "gemini-2.5-flash"},
        )
        collector.emit_counter(
            name="provider_requests_total",
            scope=MetricScope.PROVIDER,
            value=1.0,
            labels={"provider": "deepseek", "model": "deepseek-v3"},
        )
        collector.emit_counter(
            name="provider_requests_total",
            scope=MetricScope.PROVIDER,
            value=1.0,
            labels={"provider": "gemini", "model": "gemini-2.5-flash"},
        )
        result = collector.collect()
        assert result.count == 3

        gemini_count = sum(1 for r in result.records if r.labels["provider"] == "gemini")
        deepseek_count = sum(1 for r in result.records if r.labels["provider"] == "deepseek")
        assert gemini_count == 2
        assert deepseek_count == 1

    def test_provider_latency_timer(self):
        collector = MetricCollector(MetricEngine())
        collector.emit_timer(
            name="provider_latency",
            scope=MetricScope.PROVIDER,
            value=320.0,
            labels={"provider": "gemini", "model": "gemini-2.5-flash"},
        )
        collector.emit_timer(
            name="provider_latency",
            scope=MetricScope.PROVIDER,
            value=180.0,
            labels={"provider": "deepseek", "model": "deepseek-v3"},
        )
        collector.emit_timer(
            name="provider_latency",
            scope=MetricScope.PROVIDER,
            value=350.0,
            labels={"provider": "gemini", "model": "gemini-2.5-flash"},
        )
        result = collector.collect()
        gemini_latencies = [r.value for r in result.records if r.labels["provider"] == "gemini"]
        assert gemini_latencies == [320.0, 350.0]

    def test_token_usage_histogram(self):
        collector = MetricCollector(MetricEngine())
        collector.emit_histogram(
            name="token_usage",
            scope=MetricScope.PROVIDER,
            value=1024.0,
            labels={"provider": "gemini"},
        )
        collector.emit_histogram(
            name="token_usage",
            scope=MetricScope.PROVIDER,
            value=2048.0,
            labels={"provider": "deepseek"},
        )
        collector.emit_histogram(
            name="token_usage",
            scope=MetricScope.PROVIDER,
            value=512.0,
            labels={"provider": "gemini"},
        )
        result = collector.collect()
        assert result.count == 3

    def test_provider_errors_total(self):
        collector = MetricCollector(MetricEngine())
        collector.emit_counter(
            name="provider_errors_total",
            scope=MetricScope.PROVIDER,
            value=1.0,
            labels={"provider": "gemini", "error": "rate_limit"},
        )
        collector.emit_counter(
            name="provider_errors_total",
            scope=MetricScope.PROVIDER,
            value=1.0,
            labels={"provider": "gemini", "error": "timeout"},
        )
        result = collector.collect()
        assert result.count == 2


# ============================================================
# Memory Metrics
# ============================================================

class TestMemoryMetrics:

    def test_memory_retrieve_total(self):
        collector = MetricCollector(MetricEngine())
        n = 5
        for _ in range(n):
            collector.emit_counter(
                name="memory_retrieve_total",
                scope=MetricScope.MEMORY,
                value=1.0,
            )
        result = collector.collect()
        assert result.count == n

    def test_memory_hit_total(self):
        collector = MetricCollector(MetricEngine())
        collector.emit_counter(
            name="memory_hit_total",
            scope=MetricScope.MEMORY,
            value=1.0,
        )
        collector.emit_counter(
            name="memory_hit_total",
            scope=MetricScope.MEMORY,
            value=1.0,
        )
        collector.emit_counter(
            name="memory_hit_total",
            scope=MetricScope.MEMORY,
            value=1.0,
        )
        result = collector.collect()
        assert result.count == 3

    def test_memory_store_total(self):
        collector = MetricCollector(MetricEngine())
        collector.emit_counter(
            name="memory_store_total",
            scope=MetricScope.MEMORY,
            value=1.0,
        )
        collector.emit_counter(
            name="memory_store_total",
            scope=MetricScope.MEMORY,
            value=1.0,
        )
        result = collector.collect()
        assert result.count == 2

    def test_memory_hit_rate_calculation(self):
        collector = MetricCollector(MetricEngine())
        retrieve_count = 10
        hit_count = 7

        for _ in range(retrieve_count):
            collector.emit_counter("memory_retrieve_total", MetricScope.MEMORY)
        for _ in range(hit_count):
            collector.emit_counter("memory_hit_total", MetricScope.MEMORY)

        result = collector.collect()

        total_retrieve = sum(1 for r in result.records if r.name == "memory_retrieve_total")
        total_hit = sum(1 for r in result.records if r.name == "memory_hit_total")
        assert total_retrieve == retrieve_count
        assert total_hit == hit_count

        hit_rate = total_hit / total_retrieve
        assert hit_rate == 0.7


# ============================================================
# Multi-module Aggregation
# ============================================================

class TestMultiModuleAggregation:

    def test_all_five_modules_aggregate(self):
        collector = MetricCollector(MetricEngine())

        collector.emit_counter("workflow_started_total", MetricScope.WORKFLOW,
                               labels={"workflow": "rag"})
        collector.emit_counter("execution_total", MetricScope.EXECUTION,
                               labels={"strategy": "rag"})
        collector.emit_counter("tool_calls_total", MetricScope.TOOL,
                               labels={"tool": "retrieval"})
        collector.emit_counter("provider_requests_total", MetricScope.PROVIDER,
                               labels={"provider": "gemini"})
        collector.emit_counter("memory_retrieve_total", MetricScope.MEMORY)

        result = collector.collect()
        assert result.count == 5
        assert result.success is True

        scopes = {r.scope for r in result.records}
        assert scopes == {
            MetricScope.WORKFLOW,
            MetricScope.EXECUTION,
            MetricScope.TOOL,
            MetricScope.PROVIDER,
            MetricScope.MEMORY,
        }

    def test_all_metric_types_aggregate(self):
        collector = MetricCollector(MetricEngine())

        collector.emit_counter("c1", MetricScope.RUNTIME)
        collector.emit_timer("t1", MetricScope.RUNTIME, 100.0)
        collector.emit_histogram("h1", MetricScope.RUNTIME, 500.0)

        result = collector.collect()
        types = {r.metric_type for r in result.records}
        assert types == {MetricType.COUNTER, MetricType.TIMER, MetricType.HISTOGRAM}

    def test_labels_preserved_across_modules(self):
        collector = MetricCollector(MetricEngine())

        collector.emit_timer("tool_latency", MetricScope.TOOL, 85.0,
                             labels={"tool": "retrieval"})
        collector.emit_timer("provider_latency", MetricScope.PROVIDER, 320.0,
                             labels={"provider": "gemini", "model": "gemini-2.5-flash"})
        collector.emit_counter("execution_total", MetricScope.EXECUTION,
                               labels={"strategy": "rag"})

        result = collector.collect()

        tool_record = [r for r in result.records if r.name == "tool_latency"][0]
        assert tool_record.labels["tool"] == "retrieval"

        provider_record = [r for r in result.records if r.name == "provider_latency"][0]
        assert provider_record.labels["provider"] == "gemini"
        assert provider_record.labels["model"] == "gemini-2.5-flash"

        exec_record = [r for r in result.records if r.name == "execution_total"][0]
        assert exec_record.labels["strategy"] == "rag"
