# ============================================================
# test_metric_bridge.py
# MetricBridge Unit Tests
# ============================================================
# 验证：
#   1. RuntimeState → MetricContext 基础转换
#   2. Workflow 映射
#   3. Tool 映射
#   4. Provider 映射
#   5. Memory 映射
#   6. Labels 提取
#   7. Metadata 支持
# ============================================================

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


from agent.metrics.metric_bridge import MetricBridge
from agent.metrics.metric_context import MetricContext
from agent.runtime_state import RuntimeState
from agent.workflow.workflow_enums import WorkflowStatus, WorkflowType
from agent.workflow.workflow_result import WorkflowResult


class TestMetricBridgeBasicConversion:

    def test_to_metric_context_returns_metric_context(self):
        state = RuntimeState()
        ctx = MetricBridge.to_metric_context(state)

        assert isinstance(ctx, MetricContext)

    def test_to_metric_context_with_empty_state(self):
        state = RuntimeState()
        ctx = MetricBridge.to_metric_context(state)

        assert ctx.runtime_state == state
        assert ctx.workflow is None
        assert ctx.execution == []
        assert ctx.tool is None
        assert ctx.provider is None
        assert ctx.memory is None
        assert ctx.metadata == {}

    def test_to_metric_context_with_metadata(self):
        state = RuntimeState()
        metadata = {"runtime_id": "abc123", "session_id": "sess456"}
        ctx = MetricBridge.to_metric_context(state, metadata=metadata)

        assert ctx.metadata["runtime_id"] == "abc123"
        assert ctx.metadata["session_id"] == "sess456"


class TestMetricBridgeWorkflowMapping:

    def test_workflow_mapped_correctly(self):
        state = RuntimeState()
        state.workflow = WorkflowResult(
            workflow=WorkflowType.RAG,
            status=WorkflowStatus.DONE,
            reason="Test workflow",
        )

        ctx = MetricBridge.to_metric_context(state)
        assert ctx.workflow == state.workflow
        assert ctx.workflow.workflow == WorkflowType.RAG

    def test_workflow_none_when_not_set(self):
        state = RuntimeState()
        ctx = MetricBridge.to_metric_context(state)
        assert ctx.workflow is None


class TestMetricBridgeToolMapping:

    def test_tool_mapped_to_latest_tool_result(self):
        state = RuntimeState()
        tool1 = MagicMock()
        tool1.tool_name = "retrieval"
        tool2 = MagicMock()
        tool2.tool_name = "python"
        state.tool_results = [tool1, tool2]

        ctx = MetricBridge.to_metric_context(state)
        assert ctx.tool == tool2

    def test_tool_none_when_no_tool_results(self):
        state = RuntimeState()
        ctx = MetricBridge.to_metric_context(state)
        assert ctx.tool is None


class TestMetricBridgeProviderMapping:

    def test_provider_extracted_from_routing(self):
        state = RuntimeState()
        state.routing = [{"provider": "gemini", "model": "gemini-2.5-flash"}]

        ctx = MetricBridge.to_metric_context(state)
        assert ctx.provider is not None
        assert ctx.provider["provider"] == "gemini"
        assert ctx.provider["model"] == "gemini-2.5-flash"

    def test_provider_none_when_no_routing(self):
        state = RuntimeState()
        ctx = MetricBridge.to_metric_context(state)
        assert ctx.provider is None

    def test_provider_last_routing_entry(self):
        state = RuntimeState()
        state.routing = [
            {"provider": "gemini"},
            {"provider": "deepseek"},
        ]

        ctx = MetricBridge.to_metric_context(state)
        assert ctx.provider["provider"] == "deepseek"


class TestMetricBridgeExecutionMapping:

    def test_execution_list_mapped(self):
        state = RuntimeState()
        exec_result = MagicMock()
        exec_result.strategy = MagicMock()
        exec_result.strategy.value = "direct_llm"
        state.execution = [exec_result, exec_result]

        ctx = MetricBridge.to_metric_context(state)
        assert len(ctx.execution) == 2


class TestMetricBridgeLabelExtraction:

    def test_extract_labels_returns_workflow_label(self):
        state = RuntimeState()
        state.workflow = WorkflowResult(
            workflow=WorkflowType.RAG,
            status=WorkflowStatus.DONE,
            reason="Test",
        )

        labels = MetricBridge.extract_labels(state)
        assert labels["workflow"] == "rag"

    def test_extract_labels_returns_tool_label(self):
        state = RuntimeState()
        tool = MagicMock()
        tool.tool_name = "retrieval"
        state.tool_results = [tool]

        labels = MetricBridge.extract_labels(state)
        assert labels["tool"] == "retrieval"

    def test_extract_labels_returns_provider_label(self):
        state = RuntimeState()
        state.routing = [{"provider": "gemini"}]

        labels = MetricBridge.extract_labels(state)
        assert labels["provider"] == "gemini"

    def test_extract_labels_all_three(self):
        state = RuntimeState()
        state.workflow = WorkflowResult(
            workflow=WorkflowType.RAG,
            status=WorkflowStatus.DONE,
            reason="Test",
        )
        tool = MagicMock()
        tool.tool_name = "retrieval"
        state.tool_results = [tool]
        state.routing = [{"provider": "gemini"}]

        labels = MetricBridge.extract_labels(state)
        assert labels == {
            "workflow": "rag",
            "tool": "retrieval",
            "provider": "gemini",
        }

    def test_extract_labels_empty_state(self):
        state = RuntimeState()
        labels = MetricBridge.extract_labels(state)
        assert labels == {}


class TestMetricBridgeMemoryMapping:

    def test_memory_is_none(self):
        state = RuntimeState()
        ctx = MetricBridge.to_metric_context(state)
        assert ctx.memory is None


class TestMetricBridgeRuntimeStatePreservation:

    def test_runtime_state_preserved_in_context(self):
        state = RuntimeState()
        state.routing = [{"provider": "gemini"}]
        state.tool_results = [MagicMock()]
        state.outputs = ["output1"]

        ctx = MetricBridge.to_metric_context(state)
        assert ctx.runtime_state is state
        assert ctx.runtime_state.routing == state.routing
        assert ctx.runtime_state.tool_results == state.tool_results
        assert ctx.runtime_state.outputs == state.outputs
