from agent.agent_runtime import AgentRuntime
from agent.execution import strategies as _execution_strategies  # noqa: F401
from agent.execution.execution_dispatcher import ExecutionDispatcher
from agent.execution.execution_engine import ExecutionEngine as StrategyEngine
from agent.execution.financial_metrics_handler import (
    FinancialMetricsStepHandler,
    authorize_financial_metrics_tool,
)
from agent.execution_engine import ExecutionEngine
from agent.execution_plan import StepStatus, StepType
from agent.query_planner import QueryPlanner
from agent.reasoning_engine import ReasoningEngine
from agent.tools import ToolEngine, ToolRegistry
from agent.workflow.workflow_engine import WorkflowEngine
from agent.workflow.workflow_executor import WorkflowExecutor
from agent.workflow.workflows import (  # noqa: F401
    ComparisonWorkflow,
    DirectChatWorkflow,
    RAGWorkflow,
    ResearchWorkflow,
    ToolPipelineWorkflow,
)


class _IntentAnalyzer:
    def analyze(self, question):
        return {
            "intent": "GLOBAL_RESEARCH",
            "companies": [],
            "document_ids": None,
        }


class _Retriever:
    def retrieve_evidence(self, context, store):
        raise AssertionError("financial tool path must not retrieve")


class _CountingToolEngine(ToolEngine):
    def __init__(self):
        super().__init__(
            authorization_hook=authorize_financial_metrics_tool,
        )
        self.execution_count = 0

    def execute(self, context, tool):
        self.execution_count += 1
        return super().execute(context, tool)


def test_runtime_selects_governed_financial_tool_without_retrieval():
    tool_engine = _CountingToolEngine()
    step_engine = ExecutionEngine()
    step_engine.register_handler(
        StepType.TOOL_CALL,
        FinancialMetricsStepHandler(tool_engine),
    )
    runtime = AgentRuntime(
        planner=QueryPlanner(),
        executor=step_engine,
        reasoner=ReasoningEngine(),
        retriever=_Retriever(),
        intent_analyzer=_IntentAnalyzer(),
        strategy_engine=StrategyEngine(),
        dispatcher=ExecutionDispatcher(),
        workflow_engine=WorkflowEngine(),
        workflow_executor=WorkflowExecutor(),
    )

    # A prior plugin reload or registry-isolation test must not break the
    # production composition root.
    ToolRegistry.clear()
    result = runtime.run(
        "Calculate revenue growth from 100 to 125",
        tenant_id=42,
        thread_id="financial-tool-test",
    )

    assert tool_engine.execution_count == 1
    assert result.execution is not None
    assert result.execution["strategy"] == "tool_calling"
    assert result.execution["use_tools"] is True
    assert result.execution["use_retrieval"] is False
    assert result.execution["tool_calls"] == [
        {
            "step_id": 1,
            "tool_name": "financial_metrics",
            "operation": "growth_rate",
            "status": "success",
            "latency_ms": result.execution["tool_calls"][0]["latency_ms"],
            "policy": "agent_financial_metrics_v1",
            "output": {
                "operation": "growth_rate",
                "value": 25.0,
                "unit": "percent",
                "precision": 4,
                "inputs": {
                    "current": 125.0,
                    "previous": 100.0,
                },
            },
        }
    ]
    assert result.workflow is not None
    assert result.workflow["type"] == "tool_pipeline"
    assert result.context.startswith(
        "Deterministic financial calculation:",
    )
    assert "growth_rate: 25.0 percent" in result.context
    assert result.citations == []
    assert result.evidence == []
    assert result.plan is not None
    assert result.plan.tasks[0].status is StepStatus.COMPLETED
