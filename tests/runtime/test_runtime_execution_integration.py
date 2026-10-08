# ============================================================
# Runtime Execution Integration Tests
# ============================================================

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from agent.agent_runtime import AgentRuntime
from agent.execution import ExecutionStrategyType
from agent.execution.execution_dispatcher import ExecutionDispatcher
from agent.execution.execution_engine import ExecutionEngine as StrategyExecutionEngine
from agent.execution.execution_handler import (
    ExecutionHandlerContext,
    ExecutionOutput,
)
from agent.execution.execution_handler_registry import ExecutionHandlerRegistry
from agent.execution.handlers import (  # noqa: F401 — auto-registration
    DirectLLMHandler,
    MultiStepHandler,
    ParallelHandler,
    RagHandler,
    ToolCallingHandler,
)
from agent.execution_engine import ExecutionEngine
from agent.planning import (
    ComplexityLevel,
    ComplexityResult,
    PlanningContext,
    TaskResult,
    TaskType,
)
from agent.planning.complexity_models import ComplexityModel
from agent.planning.task_models import TaskModel
from agent.query_planner import QueryPlanner
from agent.reasoning_engine import ReasoningEngine
from agent.runtime_result import RuntimeResult
from llm.providers.base_provider import BaseProvider
from llm.providers.provider_config import ProviderConfig
from llm.providers.provider_models import (
    ChatRequest,
    ChatResponse,
    ProviderCapability,
)
from llm.providers.provider_registry import ProviderRegistry
from llm.router import CapabilityRoutingPolicy, ModelRouter, RoutingContext, RoutingPolicy


class _MockProvider(BaseProvider):
    def __init__(self, config: ProviderConfig):
        self._config = config

    @property
    def provider_name(self) -> str:
        return self._config.provider

    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content="mock",
            provider=self._config.provider,
            model=self._config.model,
        )

    def health(self) -> bool:
        return True

    def list_models(self) -> list:
        return [self._config.model]

    def get_capability(self) -> ProviderCapability:
        return ProviderCapability(
            supports_stream=True,
            supports_tools=True,
            max_context_tokens=8192,
        )


class _MockRetriever:
    def retrieve_evidence(self, context, store):
        return []


class _MockIntentAnalyzer:
    def analyze(self, question):
        return {"companies": [], "intent": "qa"}


class _MockExecutor(ExecutionEngine):
    def execute(self, plan, shared):
        pass


class TestRuntimeExecutionIntegration:

    @pytest.fixture(autouse=True)
    def _setup(self):
        ProviderRegistry.clear()

        ProviderRegistry.register("openai", _MockProvider)
        ProviderRegistry.register("gemini", _MockProvider)

        self.strategy_engine = StrategyExecutionEngine()
        self.dispatcher = ExecutionDispatcher()
        self.router = ModelRouter(
            policy=RoutingPolicy(CapabilityRoutingPolicy())
        )
        self.runtime = AgentRuntime(
            planner=QueryPlanner(),
            executor=_MockExecutor(),
            reasoner=ReasoningEngine(),
            retriever=_MockRetriever(),
            intent_analyzer=_MockIntentAnalyzer(),
            router=self.router,
            strategy_engine=self.strategy_engine,
            dispatcher=self.dispatcher,
        )
        yield
        ProviderRegistry.clear()

    # =========================
    # ExecutionResult in Runtime
    # =========================

    def test_runtime_creates_execution_result(self):
        result = self.runtime.run("What is Apple's revenue?")
        assert result.execution is not None
        assert "strategy" in result.execution
        assert "reason" in result.execution
        assert "estimated_steps" in result.execution
        assert "parallelism" in result.execution
        assert "use_retrieval" in result.execution
        assert "use_tools" in result.execution
        assert "confidence" in result.execution

    def test_runtime_context_contains_execution_result(self):
        result = self.runtime.run("What is Apple's revenue?")
        assert isinstance(result.execution, dict)
        assert result.execution["strategy"] in [
            "rag", "direct_llm", "multi_step", "parallel", "tool_calling"
        ]

    def test_execution_result_for_document_qa(self):
        result = self.runtime.run("Analyze the Apple 10-K document")
        assert result.execution is not None
        assert result.execution["strategy"] == "rag"
        assert result.execution["use_retrieval"] is True

    def test_execution_result_for_chat(self):
        result = self.runtime.run("Hello, how are you?")
        assert result.execution is not None
        assert result.execution["strategy"] == "direct_llm"
        assert result.execution["estimated_steps"] == 1

    # =========================
    # RuntimeResult has execution
    # =========================

    def test_runtime_result_has_execution_field(self):
        result = self.runtime.run("What is net income?")
        assert hasattr(result, "execution")
        assert isinstance(result.execution, dict)

    def test_runtime_result_execution_not_none(self):
        result = self.runtime.run("Compare Apple and Tesla")
        assert result.execution is not None

    # =========================
    # Backward Compatibility
    # =========================

    def test_run_rag_unchanged(self):
        result = self.runtime.run("What is the revenue?")
        assert isinstance(result, RuntimeResult)
        assert result.planning is not None
        assert "task_type" in result.planning

    def test_runtime_without_strategy_engine(self):
        runtime_no_strategy = AgentRuntime(
            planner=QueryPlanner(),
            executor=_MockExecutor(),
            reasoner=ReasoningEngine(),
            retriever=_MockRetriever(),
            intent_analyzer=_MockIntentAnalyzer(),
            router=self.router,
        )
        result = runtime_no_strategy.run("Hello")
        assert result.execution is None

    def test_planning_still_works(self):
        result = self.runtime.run("What is the revenue?")
        assert result.planning is not None
        assert "task_type" in result.planning
        assert "complexity" in result.planning

    def test_routing_still_works(self):
        result = self.runtime.run("Hello")
        assert result.routing is not None

    # =========================
    # Regression
    # =========================

    def test_planner_imports_still_work(self):
        assert True

    def test_router_imports_still_work(self):
        assert True

    def test_execution_imports_still_work(self):
        assert True

    # =========================
    # Dispatcher Integration
    # =========================

    def test_dispatcher_is_passed_to_runtime(self):
        assert self.runtime.dispatcher is not None
        assert isinstance(self.runtime.dispatcher, ExecutionDispatcher)

    def test_runtime_uses_dispatcher_for_rag(self):
        result = self.runtime.run("Analyze the Apple 10-K document")
        assert result.execution is not None
        assert result.execution["strategy"] == "rag"

    def test_runtime_uses_dispatcher_for_direct_llm(self):
        result = self.runtime.run("Hello, how are you?")
        assert result.execution is not None
        assert result.execution["strategy"] == "direct_llm"

    def test_runtime_without_dispatcher_falls_back(self):
        runtime_no_dispatcher = AgentRuntime(
            planner=QueryPlanner(),
            executor=_MockExecutor(),
            reasoner=ReasoningEngine(),
            retriever=_MockRetriever(),
            intent_analyzer=_MockIntentAnalyzer(),
            router=self.router,
            strategy_engine=self.strategy_engine,
        )
        result = runtime_no_dispatcher.run("What is the revenue?")
        assert isinstance(result, RuntimeResult)

    def test_dispatcher_dispatch_rag(self):
        from agent.execution.execution_context import ExecutionContext

        task_result = TaskResult(
            task=TaskModel(task_type=TaskType.DOCUMENT_QA),
            reason="test",
        )
        complexity_result = ComplexityResult(
            complexity=ComplexityModel(level=ComplexityLevel.LOW),
            reason="test",
        )
        exec_ctx = ExecutionContext(
            task=task_result,
            complexity=complexity_result,
            routing=RoutingContext(task=TaskType.DOCUMENT_QA),
        )
        strategy_result = self.strategy_engine.execute(exec_ctx)
        assert strategy_result.strategy == ExecutionStrategyType.RAG

        handler_ctx = ExecutionHandlerContext(
            plan=self.runtime.planner.plan(
                PlanningContext(
                    question="Test",
                    companies=[],
                )
            )[0],
            executor=_MockExecutor(),
        )
        output = self.dispatcher.dispatch(strategy_result, handler_ctx)
        assert isinstance(output, ExecutionOutput)

    def test_dispatcher_dispatch_direct_llm(self):
        from agent.execution.execution_context import ExecutionContext

        task_result = TaskResult(
            task=TaskModel(task_type=TaskType.CHAT),
            reason="test",
        )
        complexity_result = ComplexityResult(
            complexity=ComplexityModel(level=ComplexityLevel.LOW),
            reason="test",
        )
        exec_ctx = ExecutionContext(
            task=task_result,
            complexity=complexity_result,
            routing=RoutingContext(task=TaskType.CHAT),
        )
        strategy_result = self.strategy_engine.execute(exec_ctx)
        assert strategy_result.strategy == ExecutionStrategyType.DIRECT_LLM

        handler_ctx = ExecutionHandlerContext(
            plan=self.runtime.planner.plan(
                PlanningContext(
                    question="Hello",
                    companies=[],
                )
            )[0],
            executor=_MockExecutor(),
        )
        output = self.dispatcher.dispatch(strategy_result, handler_ctx)
        assert isinstance(output, ExecutionOutput)

    def test_handler_registry_has_all_strategies(self):
        expected = {
            ExecutionStrategyType.RAG,
            ExecutionStrategyType.DIRECT_LLM,
            ExecutionStrategyType.PARALLEL,
            ExecutionStrategyType.MULTI_STEP,
            ExecutionStrategyType.TOOL_CALLING,
        }
        registered = set(ExecutionHandlerRegistry.list_handlers())
        for strategy_type in expected:
            assert strategy_type in registered, f"{strategy_type} not registered"

    def test_dispatcher_fallback(self):
        self.dispatcher.set_fallback(ExecutionStrategyType.RAG)
        assert self.dispatcher._fallback_strategy_type == ExecutionStrategyType.RAG

    def test_dispatcher_no_handler_no_fallback(self):
        from agent.execution.execution_context import ExecutionContext

        task_result = TaskResult(
            task=TaskModel(task_type=TaskType.COMPARISON),
            reason="test",
        )
        complexity_result = ComplexityResult(
            complexity=ComplexityModel(level=ComplexityLevel.HIGH),
            reason="test",
        )
        exec_ctx = ExecutionContext(
            task=task_result,
            complexity=complexity_result,
            routing=RoutingContext(task=TaskType.COMPARISON),
        )
        strategy_result = self.strategy_engine.execute(exec_ctx)

        handler_ctx = ExecutionHandlerContext(
            plan=self.runtime.planner.plan(
                PlanningContext(
                    question="Compare Apple and Tesla",
                    companies=[],
                )
            )[0],
            executor=_MockExecutor(),
        )
        output = self.dispatcher.dispatch(strategy_result, handler_ctx)
        assert isinstance(output, ExecutionOutput)
        assert output.context == ""
