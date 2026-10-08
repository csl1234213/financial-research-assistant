# ============================================================
# ReliabilityBridge — RuntimeState → ReliabilityContext
# ============================================================
# The ReliabilityBridge is the connector between the Agent
# Runtime and the Reliability Layer. It converts a RuntimeState
# into a concrete ReliabilityContext that the ReliabilityEngine
# can consume.
#
# The Bridge does NOT make business decisions.
# It does NOT know about:
#   - Which mechanism to use (ReliabilityEngine handles that)
#   - Mechanism implementations (ReliabilityFactory handles that)
#   - Retry / Timeout / CircuitBreaker internals
#   - Provider / Runtime internals
#
# It ONLY converts:
#   RuntimeState → ReliabilityContext
#
# Mirrors:
#   ReliabilityBridge ↔ MetricBridge   (RuntimeState → MetricContext)
#   ReliabilityBridge ↔ MemoryBridge   (RuntimeState → MemoryContext)
#   ReliabilityBridge ↔ ToolBridge     (WorkflowStep → ToolContext)
# ============================================================

from typing import Any, Dict, Optional

from agent.runtime_state import RuntimeState

from .reliability_context import ReliabilityContext


class ReliabilityBridge:
    @staticmethod
    def to_reliability_context(
        state: RuntimeState,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ReliabilityContext:
        return ReliabilityContext(
            runtime_state=state,
            workflow=state.workflow,
            execution=list(state.execution),
            tool=ReliabilityBridge._extract_tool(state),
            provider=ReliabilityBridge._extract_provider(state),
            memory=None,
            metadata=metadata or {},
        )

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
