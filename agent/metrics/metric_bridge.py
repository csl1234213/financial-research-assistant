# ============================================================
# MetricBridge — RuntimeState → MetricContext
# ============================================================
# The MetricBridge is the connector between the Agent Runtime
# and the Metrics Layer. It converts a RuntimeState into a
# concrete MetricContext that the MetricEngine can consume.
#
# The Bridge does NOT make business decisions.
# It does NOT know about:
#   - Which metric to use (MetricEngine handles that)
#   - Metric implementations (MetricFactory handles that)
#   - Export / Storage (later Sprint)
#   - Prometheus / OpenTelemetry (later Sprint)
#
# It ONLY converts:
#   RuntimeState → MetricContext
#
# The Bridge also prepares base labels for convenient metric
# recording (e.g., workflow name, tool name, provider name).
#
# Mirrors:
#   MetricBridge ↔ ToolBridge   (WorkflowStep → ToolContext)
#   MetricBridge ↔ MemoryBridge (RuntimeState → MemoryContext)
# ============================================================

from typing import Any, Dict, Optional

from agent.runtime_state import RuntimeState

from .metric_context import MetricContext


class MetricBridge:
    # ============================================================
    # Context construction
    # ============================================================

    @staticmethod
    def to_metric_context(
        state: RuntimeState,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MetricContext:
        return MetricContext(
            runtime_state=state,
            workflow=state.workflow,
            execution=list(state.execution),
            tool=MetricBridge._extract_tool(state),
            provider=MetricBridge._extract_provider(state),
            memory=MetricBridge._extract_memory(state),
            metadata=metadata or {},
        )

    # ============================================================
    # Label extraction
    # ============================================================

    @staticmethod
    def extract_labels(state: RuntimeState) -> Dict[str, str]:
        labels: Dict[str, str] = {}

        workflow_label = MetricBridge._extract_workflow_label(state)
        if workflow_label:
            labels["workflow"] = workflow_label

        tool_label = MetricBridge._extract_tool_label(state)
        if tool_label:
            labels["tool"] = tool_label

        provider_label = MetricBridge._extract_provider_label(state)
        if provider_label:
            labels["provider"] = provider_label

        return labels

    # ============================================================
    # Internal extractors
    # ============================================================

    @staticmethod
    def _extract_tool(state: RuntimeState) -> Optional[Any]:
        if state.tool_results:
            return state.tool_results[-1]
        return None

    @staticmethod
    def _extract_provider(state: RuntimeState) -> Optional[Dict[str, Any]]:
        if state.routing:
            last_route = state.routing[-1]
            if isinstance(last_route, dict) and "provider" in last_route:
                return last_route
        return None

    @staticmethod
    def _extract_memory(state: RuntimeState) -> Optional[Any]:
        return None

    @staticmethod
    def _extract_workflow_label(state: RuntimeState) -> Optional[str]:
        if state.workflow is not None:
            wf = state.workflow
            if hasattr(wf, "workflow") and hasattr(wf.workflow, "value"):
                return wf.workflow.value
            if hasattr(wf, "workflow"):
                return str(wf.workflow)
        return None

    @staticmethod
    def _extract_tool_label(state: RuntimeState) -> Optional[str]:
        if state.tool_results:
            last = state.tool_results[-1]
            if hasattr(last, "tool_name"):
                return last.tool_name
            if hasattr(last, "name"):
                return last.name
        return None

    @staticmethod
    def _extract_provider_label(state: RuntimeState) -> Optional[str]:
        provider = MetricBridge._extract_provider(state)
        if provider and isinstance(provider, dict):
            return provider.get("provider")
        return None
