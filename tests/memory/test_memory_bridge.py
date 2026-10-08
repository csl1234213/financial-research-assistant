import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from unittest.mock import MagicMock

import pytest

from agent.memory.memory_bridge import MemoryBridge
from agent.memory.memory_context import MemoryContext
from agent.memory.memory_engine import MemoryEngine
from agent.memory.memory_enums import MemoryType
from agent.memory.memory_result import MemoryResult
from agent.planning import (
    ComplexityLevel,
    ComplexityModel,
    ComplexityResult,
    TaskModel,
    TaskResult,
    TaskType,
)
from agent.runtime_state import RuntimeState
from agent.workflow.workflow_enums import WorkflowStatus, WorkflowType
from agent.workflow.workflow_result import WorkflowResult


class TestMemoryBridge:
    """Test MemoryBridge: RuntimeState + TaskResult -> MemoryContext"""

    def test_to_memory_context_with_full_state(self):
        task_result = TaskResult(
            task=TaskModel(
                task_type=TaskType.DOCUMENT_QA,
                complexity=ComplexityLevel.MEDIUM,
            ),
            reason="Test reason",
            extracted_entities=["Apple"],
            estimated_tokens=500,
        )
        runtime_state = RuntimeState()
        runtime_state.workflow = WorkflowResult(
            workflow=WorkflowType.RAG,
            status=WorkflowStatus.DONE,
            reason="Test workflow",
        )

        ctx = MemoryBridge.to_memory_context(
            task_result=task_result,
            runtime_state=runtime_state,
        )

        assert isinstance(ctx, MemoryContext)
        assert ctx.task == task_result
        assert ctx.runtime_state == runtime_state
        assert ctx.workflow == runtime_state.workflow
        assert ctx.execution == []

    def test_to_memory_context_with_empty_state(self):
        ctx = MemoryBridge.to_memory_context()

        assert isinstance(ctx, MemoryContext)
        assert ctx.task is None
        assert isinstance(ctx.runtime_state, RuntimeState)
        assert ctx.workflow is None
        assert ctx.execution == []

    def test_to_memory_context_with_execution_list(self):
        runtime_state = RuntimeState()
        exec_result = MagicMock()
        exec_result.strategy = MagicMock()
        exec_result.strategy.value = "direct_llm"
        runtime_state.execution = [exec_result, exec_result]

        ctx = MemoryBridge.to_memory_context(runtime_state=runtime_state)

        assert len(ctx.execution) == 2

    def test_to_memory_context_preserves_routing(self):
        runtime_state = RuntimeState()
        runtime_state.routing = [{"provider": "deepseek", "model": "v3"}]

        ctx = MemoryBridge.to_memory_context(runtime_state=runtime_state)

        assert ctx.runtime_state.routing == [{"provider": "deepseek", "model": "v3"}]

    def test_to_memory_context_preserves_outputs(self):
        runtime_state = RuntimeState()
        runtime_state.outputs = ["output1", "output2"]

        ctx = MemoryBridge.to_memory_context(runtime_state=runtime_state)

        assert ctx.runtime_state.outputs == ["output1", "output2"]


class TestMemoryEngine:
    """Test MemoryEngine orchestration"""

    @pytest.fixture
    def engine(self):
        return MemoryEngine()

    @pytest.fixture
    def memory_context(self):
        task_result = TaskResult(
            task=TaskModel(
                task_type=TaskType.DOCUMENT_QA,
                complexity=ComplexityLevel.MEDIUM,
            ),
            reason="Test",
            extracted_entities=["Apple"],
            estimated_tokens=500,
        )
        return MemoryContext(
            task=task_result,
            runtime_state=RuntimeState(),
        )

    def test_engine_default_memory_type(self, engine):
        engine.set_default_memory_type(MemoryType.SESSION)
        assert engine._default_memory_type == MemoryType.SESSION

    def test_engine_default_memory_type_from_string(self, engine):
        engine.set_default_memory_type("session")
        assert engine._default_memory_type == MemoryType.SESSION

    def test_engine_store_returns_memory_result(self, engine, memory_context):
        engine.set_default_memory_type(MemoryType.SESSION)
        result = engine.store(memory_context)
        assert isinstance(result, MemoryResult)
        assert result.confidence == 1.0
        assert result.records == []

    def test_engine_retrieve_returns_memory_result(self, engine, memory_context):
        engine.set_default_memory_type(MemoryType.SESSION)
        result = engine.retrieve(memory_context)
        assert isinstance(result, MemoryResult)
        assert result.retrieved_count == 0
        assert result.records == []

    def test_engine_store_with_explicit_type(self, engine, memory_context):
        result = engine.store(memory_context, memory_type=MemoryType.WORKFLOW)
        assert isinstance(result, MemoryResult)
        assert "WorkflowMemory" in result.reason

    def test_engine_retrieve_with_explicit_type(self, engine, memory_context):
        result = engine.retrieve(memory_context, memory_type=MemoryType.WORKFLOW)
        assert isinstance(result, MemoryResult)


class TestMemoryRuntimeIntegration:
    """Test AgentRuntime + MemoryEngine integration"""

    def test_agent_runtime_accepts_memory_engine(self):
        from agent.agent_runtime import AgentRuntime

        planner = MagicMock()
        executor = MagicMock()
        reasoner = MagicMock()
        retriever = MagicMock()
        intent_analyzer = MagicMock()

        runtime = AgentRuntime(
            planner=planner,
            executor=executor,
            reasoner=reasoner,
            retriever=retriever,
            intent_analyzer=intent_analyzer,
            memory_engine=MemoryEngine(),
        )

        assert runtime.memory_engine is not None
        assert isinstance(runtime.memory_engine, MemoryEngine)

    def test_agent_runtime_without_memory_engine(self):
        from agent.agent_runtime import AgentRuntime

        planner = MagicMock()
        executor = MagicMock()
        reasoner = MagicMock()
        retriever = MagicMock()
        intent_analyzer = MagicMock()

        runtime = AgentRuntime(
            planner=planner,
            executor=executor,
            reasoner=reasoner,
            retriever=retriever,
            intent_analyzer=intent_analyzer,
        )

        assert runtime.memory_engine is None

    def test_agent_runtime_run_with_memory_engine(self):
        from agent.agent_runtime import AgentRuntime
        from agent.execution_plan import ExecutionPlan, PlanStep, StepType
        from agent.planning import (
            ComplexityLevel,
            TaskModel,
            TaskResult,
            TaskType,
        )
        from agent.reasoning_models import Evidence, ReasoningResult
        from agent.runtime_result import RuntimeResult

        class FakeRetriever:
            def retrieve_evidence(self, context, store):
                return [Evidence(
                    content="Revenue grew 10%.",
                    source="apple.pdf",
                    company=context.company or "Unknown",
                    confidence=0.95,
                    metadata={"chunk_id": "apple_0"},
                )]

        class FakeIntentAnalyzer:
            def analyze(self, query):
                return {"intent": "SINGLE_COMPANY", "companies": ["Apple"]}

        class FakePlanner:
            def plan(self, context):
                task = TaskModel(task_type=TaskType.DOCUMENT_QA, complexity=ComplexityLevel.MEDIUM)
                task_result = TaskResult(task=task, reason="Test", extracted_entities=["Apple"], estimated_tokens=500)
                complexity_result = ComplexityResult(
                    complexity=ComplexityModel(level=ComplexityLevel.MEDIUM, score=0.45, estimated_tokens=500, estimated_latency_ms=1500, estimated_cost=0.008),
                    reason="Test",
                    factors={},
                )
                plan = ExecutionPlan(
                    intent="single_company", original_query=context.question, task_type=TaskType.DOCUMENT_QA,
                    complexity=ComplexityLevel.MEDIUM, complexity_score=0.45, estimated_tokens=500,
                    estimated_latency_ms=1500, estimated_cost=0.008,
                    planner_reason="Test", complexity_reason="Test",
                    tasks=[PlanStep(step_id=1, step_type=StepType.RETRIEVE, description="Test", company="Apple", query=context.question)],
                )
                return plan, task_result, complexity_result

        class FakeReasoner:
            def analyze(self, results):
                return ReasoningResult(facts=["Test"], risks=[], opportunities=[], conclusion="Test")

        class FakeExecutor:
            def execute(self, plan, shared):
                shared["_all_evidence"] = []
                return plan

        memory_engine = MemoryEngine()
        memory_engine.set_default_memory_type(MemoryType.SESSION)

        runtime = AgentRuntime(
            planner=FakePlanner(),
            executor=FakeExecutor(),
            reasoner=FakeReasoner(),
            retriever=FakeRetriever(),
            intent_analyzer=FakeIntentAnalyzer(),
            memory_engine=memory_engine,
        )

        result = runtime.run("What is Apple revenue?")

        assert isinstance(result, RuntimeResult)
        assert result.memory is not None
        assert "retrieve" in result.memory
        assert "store" in result.memory
        assert result.memory["retrieve"] is not None
        assert result.memory["store"] is not None
        assert result.memory["retrieve"]["retrieved_count"] == 0
        assert result.memory["store"]["stored_count"] == 0

    def test_memory_context_fields_are_optional(self):
        ctx = MemoryContext()
        assert ctx.task is None
        assert isinstance(ctx.runtime_state, RuntimeState)
        assert ctx.workflow is None
        assert ctx.execution == []
