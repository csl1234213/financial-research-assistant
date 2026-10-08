import time

import pytest

from agent.execution.execution_result import ExecutionResult as StrategyResult
from agent.execution.strategy_enums import ExecutionStrategyType
from agent.memory.memory_bridge import MemoryBridge
from agent.memory.memory_engine import MemoryEngine
from agent.memory.memory_enums import MemoryType
from agent.planning import (
    ComplexityLevel,
    TaskModel,
    TaskResult,
    TaskType,
)
from agent.runtime_state import RuntimeState
from agent.workflow.workflow_enums import WorkflowStatus, WorkflowType
from agent.workflow.workflow_result import WorkflowResult


class TestMemoryBenchmark:

    @pytest.fixture
    def engine(self):
        engine = MemoryEngine()
        engine.set_default_memory_type(MemoryType.SESSION)
        return engine

    @pytest.fixture
    def memory_context(self):
        task_result = TaskResult(
            task=TaskModel(
                task_type=TaskType.DOCUMENT_QA,
                complexity=ComplexityLevel.MEDIUM,
            ),
            reason="Benchmark test",
            extracted_entities=["Apple"],
            estimated_tokens=500,
        )
        runtime_state = RuntimeState()
        runtime_state.workflow = WorkflowResult(
            workflow=WorkflowType.RAG,
            status=WorkflowStatus.DONE,
            reason="Benchmark workflow",
        )
        runtime_state.execution = [
            StrategyResult(
                strategy=ExecutionStrategyType.RAG,
                reason="Benchmark execution",
                estimated_steps=2,
                parallelism=1,
                use_retrieval=True,
                confidence=0.95,
            )
        ]
        return MemoryBridge.to_memory_context(
            task_result=task_result,
            runtime_state=runtime_state,
        )

    @pytest.mark.perf
    def test_memory_store_latency(self, engine, memory_context):
        iterations = 50
        latencies = []

        for _ in range(iterations):
            start = time.perf_counter()
            engine.store(memory_context)
            elapsed_ms = (time.perf_counter() - start) * 1000
            latencies.append(elapsed_ms)

        avg_latency = sum(latencies) / len(latencies)
        max_latency = max(latencies)
        min_latency = min(latencies)

        assert avg_latency < 50, (
            f"Memory Store average latency {avg_latency:.2f}ms exceeds 50ms threshold"
        )
        assert max_latency < 100, (
            f"Memory Store max latency {max_latency:.2f}ms exceeds 100ms threshold"
        )

    @pytest.mark.perf
    def test_memory_retrieve_latency(self, engine, memory_context):
        iterations = 50
        latencies = []

        for _ in range(iterations):
            start = time.perf_counter()
            engine.retrieve(memory_context)
            elapsed_ms = (time.perf_counter() - start) * 1000
            latencies.append(elapsed_ms)

        avg_latency = sum(latencies) / len(latencies)
        max_latency = max(latencies)
        min_latency = min(latencies)

        assert avg_latency < 50, (
            f"Memory Retrieve average latency {avg_latency:.2f}ms exceeds 50ms threshold"
        )
        assert max_latency < 100, (
            f"Memory Retrieve max latency {max_latency:.2f}ms exceeds 100ms threshold"
        )

    @pytest.mark.perf
    def test_memory_bridge_latency(self, memory_context):
        task_result = TaskResult(
            task=TaskModel(
                task_type=TaskType.DOCUMENT_QA,
                complexity=ComplexityLevel.MEDIUM,
            ),
            reason="Test",
            extracted_entities=["Apple"],
            estimated_tokens=500,
        )
        runtime_state = RuntimeState()
        runtime_state.workflow = WorkflowResult(
            workflow=WorkflowType.RAG,
            status=WorkflowStatus.DONE,
        )

        iterations = 100
        latencies = []

        for _ in range(iterations):
            start = time.perf_counter()
            MemoryBridge.to_memory_context(
                task_result=task_result,
                runtime_state=runtime_state,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
            latencies.append(elapsed_ms)

        avg_latency = sum(latencies) / len(latencies)
        max_latency = max(latencies)

        assert avg_latency < 10, (
            f"MemoryBridge average latency {avg_latency:.2f}ms exceeds 10ms threshold"
        )
        assert max_latency < 20, (
            f"MemoryBridge max latency {max_latency:.2f}ms exceeds 20ms threshold"
        )

    def test_memory_store_stability(self, engine, memory_context):
        results = []
        for _ in range(20):
            result = engine.store(memory_context)
            results.append(result)

        confidences = [r.confidence for r in results]
        assert all(c == confidences[0] for c in confidences), (
            "Memory Store returned inconsistent confidence values"
        )

    def test_memory_retrieve_stability(self, engine, memory_context):
        results = []
        for _ in range(20):
            result = engine.retrieve(memory_context)
            results.append(result)

        counts = [r.retrieved_count for r in results]
        assert all(c == counts[0] for c in counts), (
            "Memory Retrieve returned inconsistent retrieved_count values"
        )
