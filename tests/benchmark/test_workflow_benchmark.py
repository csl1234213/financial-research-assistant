# ============================================================
# test_workflow_benchmark.py
# Workflow Selection Accuracy, Stability, and Latency
# ============================================================

import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

import pytest

from agent.execution.execution_context import ExecutionContext
from agent.execution.execution_engine import ExecutionEngine as StrategyExecutionEngine
from agent.planning import (
    ComplexityAnalyzer,
    PlanningContext,
    TaskAnalyzer,
)
from agent.workflow.workflow_context import WorkflowContext
from agent.workflow.workflow_engine import WorkflowEngine
from agent.workflow.workflow_enums import WorkflowType

# ============================================================
# Pipeline function (reusable)
# ============================================================

def _run_pipeline(question: str) -> Tuple[str, str, WorkflowType]:
    task_analyzer = TaskAnalyzer()
    complexity_analyzer = ComplexityAnalyzer()
    strategy_engine = StrategyExecutionEngine()
    workflow_engine = WorkflowEngine()

    planning_ctx = PlanningContext(question=question)
    task_result = task_analyzer.analyze(planning_ctx)
    complexity_result = complexity_analyzer.analyze(task_result)
    execution_context = ExecutionContext(
        task=task_result,
        complexity=complexity_result,
        routing=None,
    )
    strategy_result = strategy_engine.execute(execution_context)
    workflow_ctx = WorkflowContext(
        task=task_result,
        complexity=complexity_result,
        execution=strategy_result,
        routing=None,
    )
    workflow_result = workflow_engine.build(workflow_ctx)

    return (
        task_result.task.task_type.value,
        strategy_result.strategy.value,
        workflow_result.workflow,
    )


# ============================================================
# Benchmark case definitions
# ============================================================

@dataclass
class BenchmarkCase:
    question: str
    expected_workflow: WorkflowType
    expected_task_type: Optional[str] = None
    expected_strategy: Optional[str] = None
    min_step_count: int = 1
    max_step_count: int = 6


BENCHMARK_CASES: List[BenchmarkCase] = [
    # ============================================================
    # DIRECT_CHAT — simple conversational
    # ============================================================
    BenchmarkCase(
        question="Hello",
        expected_workflow=WorkflowType.DIRECT_CHAT,
        expected_task_type="chat",
        expected_strategy="direct_llm",
        min_step_count=1,
        max_step_count=1,
    ),
    BenchmarkCase(
        question="What is AI",
        expected_workflow=WorkflowType.DIRECT_CHAT,
        expected_task_type="chat",
        expected_strategy="direct_llm",
        min_step_count=1,
        max_step_count=1,
    ),
    BenchmarkCase(
        question="Summarize this report",
        expected_workflow=WorkflowType.DIRECT_CHAT,
        expected_task_type="chat",
        expected_strategy="direct_llm",
        min_step_count=1,
        max_step_count=1,
    ),
    BenchmarkCase(
        question="How are you doing today",
        expected_workflow=WorkflowType.DIRECT_CHAT,
        min_step_count=1,
        max_step_count=1,
    ),
    BenchmarkCase(
        question="Explain machine learning",
        expected_workflow=WorkflowType.DIRECT_CHAT,
        expected_task_type="chat",
        expected_strategy="direct_llm",
        min_step_count=1,
        max_step_count=1,
    ),

    # ============================================================
    # RAG — document QA, financial analysis
    # ============================================================
    BenchmarkCase(
        question="Analyze Apple 10-K",
        expected_workflow=WorkflowType.RAG,
        expected_task_type="document_qa",
        expected_strategy="rag",
        min_step_count=3,
        max_step_count=3,
    ),
    BenchmarkCase(
        question="What are the risk factors in the annual report",
        expected_workflow=WorkflowType.RAG,
        expected_task_type="document_qa",
        expected_strategy="rag",
        min_step_count=3,
        max_step_count=3,
    ),
    BenchmarkCase(
        question="What is the P/E ratio of Apple",
        expected_workflow=WorkflowType.RAG,
        expected_task_type="document_qa",
        expected_strategy="rag",
        min_step_count=3,
        max_step_count=3,
    ),
    BenchmarkCase(
        question="What is the revenue for Q1",
        expected_workflow=WorkflowType.RAG,
        expected_task_type="document_qa",
        expected_strategy="rag",
        min_step_count=3,
        max_step_count=3,
    ),
    BenchmarkCase(
        question="Research NVIDIA chips",
        expected_workflow=WorkflowType.MULTI_STEP,
        expected_task_type="research",
        expected_strategy="multi_step",
        min_step_count=5,
        max_step_count=5,
    ),
    BenchmarkCase(
        question="Financial deep research",
        expected_workflow=WorkflowType.MULTI_STEP,
        expected_task_type="research",
        expected_strategy="multi_step",
        min_step_count=5,
        max_step_count=5,
    ),
    BenchmarkCase(
        question="Analyze market trends",
        expected_workflow=WorkflowType.MULTI_STEP,
        expected_task_type="research",
        expected_strategy="multi_step",
        min_step_count=5,
        max_step_count=5,
    ),
    BenchmarkCase(
        question="Deep dive into NVIDIA strategy",
        expected_workflow=WorkflowType.MULTI_STEP,
        expected_task_type="research",
        expected_strategy="multi_step",
        min_step_count=5,
        max_step_count=5,
    ),

    # ============================================================
    # PARALLEL — comparison
    # ============================================================
    BenchmarkCase(
        question="Compare Apple Tesla",
        expected_workflow=WorkflowType.PARALLEL,
        expected_task_type="comparison",
        expected_strategy="parallel",
        min_step_count=4,
        max_step_count=4,
    ),
    BenchmarkCase(
        question="Compare Microsoft and Google financial performance",
        expected_workflow=WorkflowType.PARALLEL,
        expected_task_type="comparison",
        expected_strategy="parallel",
        min_step_count=4,
        max_step_count=4,
    ),
]


# ============================================================
# Accuracy Tests
# ============================================================

class TestWorkflowAccuracy:

    @pytest.mark.parametrize("case", BENCHMARK_CASES, ids=lambda c: c.question)
    def test_workflow_selection(self, case: BenchmarkCase):
        task_type, strategy, workflow = _run_pipeline(case.question)
        assert workflow == case.expected_workflow, (
            f"Q: '{case.question}' → expected {case.expected_workflow.value}, "
            f"got {workflow.value} (task={task_type}, strategy={strategy})"
        )

    @pytest.mark.parametrize("case", BENCHMARK_CASES, ids=lambda c: c.question)
    def test_task_type(self, case: BenchmarkCase):
        if case.expected_task_type is None:
            pytest.skip("No expected task type")
        task_type, _, _ = _run_pipeline(case.question)
        assert task_type == case.expected_task_type

    @pytest.mark.parametrize("case", BENCHMARK_CASES, ids=lambda c: c.question)
    def test_strategy(self, case: BenchmarkCase):
        if case.expected_strategy is None:
            pytest.skip("No expected strategy")
        _, strategy, _ = _run_pipeline(case.question)
        assert strategy == case.expected_strategy

    def test_accuracy_at_least_95_percent(self):
        correct = 0
        total = len(BENCHMARK_CASES)
        failures = []
        for case in BENCHMARK_CASES:
            _, _, workflow = _run_pipeline(case.question)
            if workflow == case.expected_workflow:
                correct += 1
            else:
                failures.append((case.question, case.expected_workflow.value, workflow.value))

        accuracy = correct / total * 100
        assert accuracy >= 95.0, (
            f"Accuracy: {accuracy:.1f}% ({correct}/{total}). "
            f"Failures: {failures}"
        )


# ============================================================
# Stability Tests
# ============================================================

STABILITY_RUNS = 5


class TestWorkflowStability:

    @pytest.mark.parametrize("case", BENCHMARK_CASES, ids=lambda c: c.question)
    def test_workflow_stable(self, case: BenchmarkCase):
        results = []
        for _ in range(STABILITY_RUNS):
            task_type, strategy, workflow = _run_pipeline(case.question)
            results.append((task_type, strategy, workflow))

        first = results[0]
        for i, r in enumerate(results[1:], start=2):
            assert r == first, (
                f"Run {i} differs from Run 1 for '{case.question}': "
                f"Run 1: {first}, Run {i}: {r}"
            )

    @pytest.mark.parametrize("case", BENCHMARK_CASES, ids=lambda c: c.question)
    def test_step_count_stable(self, case: BenchmarkCase):
        planning_ctx = PlanningContext(question=case.question)
        task_analyzer = TaskAnalyzer()
        complexity_analyzer = ComplexityAnalyzer()
        strategy_engine = StrategyExecutionEngine()
        workflow_engine = WorkflowEngine()

        step_counts = []
        for _ in range(STABILITY_RUNS):
            task_result = task_analyzer.analyze(planning_ctx)
            complexity_result = complexity_analyzer.analyze(task_result)
            exec_context = ExecutionContext(
                task=task_result,
                complexity=complexity_result,
                routing=None,
            )
            strategy_result = strategy_engine.execute(exec_context)
            workflow_ctx = WorkflowContext(
                task=task_result,
                complexity=complexity_result,
                execution=strategy_result,
                routing=None,
            )
            workflow_result = workflow_engine.build(workflow_ctx)
            step_counts.append(len(workflow_result.steps))

        assert len(set(step_counts)) == 1, (
            f"Step count varies across {STABILITY_RUNS} runs: {step_counts}"
        )
        assert case.min_step_count <= step_counts[0] <= case.max_step_count, (
            f"Step count {step_counts[0]} out of range "
            f"[{case.min_step_count}, {case.max_step_count}]"
        )


# ============================================================
# Execution Path Stability
# ============================================================

class TestExecutionPathStability:

    def test_workflow_engine_consistent_mapping(self):
        for case in BENCHMARK_CASES:
            planning_ctx = PlanningContext(question=case.question)
            task_analyzer = TaskAnalyzer()
            complexity_analyzer = ComplexityAnalyzer()
            strategy_engine = StrategyExecutionEngine()
            workflow_engine = WorkflowEngine()

            task_result = task_analyzer.analyze(planning_ctx)
            complexity_result = complexity_analyzer.analyze(task_result)
            exec_context = ExecutionContext(
                task=task_result,
                complexity=complexity_result,
                routing=None,
            )
            strategy_result = strategy_engine.execute(exec_context)

            workflow_ctx = WorkflowContext(
                task=task_result,
                complexity=complexity_result,
                execution=strategy_result,
                routing=None,
            )
            workflow_result = workflow_engine.build(workflow_ctx)

            for step in workflow_result.steps:
                assert step.step_id
                assert step.name
                if hasattr(step, 'depends_on') and step.depends_on:
                    for dep in step.depends_on:
                        dep_step_ids = [s.step_id for s in workflow_result.steps]
                        assert dep in dep_step_ids, (
                            f"Step '{step.step_id}' depends on '{dep}' "
                            f"which is not in [{dep_step_ids}]"
                        )

    def test_workflow_result_has_required_fields(self):
        for case in BENCHMARK_CASES:
            planning_ctx = PlanningContext(question=case.question)
            task_analyzer = TaskAnalyzer()
            complexity_analyzer = ComplexityAnalyzer()
            strategy_engine = StrategyExecutionEngine()
            workflow_engine = WorkflowEngine()

            task_result = task_analyzer.analyze(planning_ctx)
            complexity_result = complexity_analyzer.analyze(task_result)
            exec_context = ExecutionContext(
                task=task_result,
                complexity=complexity_result,
                routing=None,
            )
            strategy_result = strategy_engine.execute(exec_context)
            workflow_ctx = WorkflowContext(
                task=task_result,
                complexity=complexity_result,
                execution=strategy_result,
                routing=None,
            )
            workflow_result = workflow_engine.build(workflow_ctx)

            assert workflow_result.workflow is not None
            assert workflow_result.steps is not None
            assert len(workflow_result.steps) > 0
            assert workflow_result.estimated_time_ms > 0
            assert workflow_result.confidence is not None
            assert workflow_result.reason is not None


# ============================================================
# Latency Benchmark
# ============================================================

class TestLatencyBenchmark:

    WORKFLOW_ENGINE_MAX_MS = 5
    WORKFLOW_EXECUTOR_MAX_MS = 20
    FULL_PIPELINE_MAX_MS = 1500

    def _measure_latency(self, fn: Callable, iterations: int = 10) -> float:
        times = []
        for _ in range(iterations):
            start = time.perf_counter()
            fn()
            elapsed = time.perf_counter() - start
            times.append(elapsed * 1000)
        return sum(times) / len(times)

    def test_workflow_engine_latency(self):
        planning_ctx = PlanningContext(question="Analyze Apple 10-K")
        task_analyzer = TaskAnalyzer()
        complexity_analyzer = ComplexityAnalyzer()
        strategy_engine = StrategyExecutionEngine()
        workflow_engine = WorkflowEngine()

        def _run():
            task_result = task_analyzer.analyze(planning_ctx)
            complexity_result = complexity_analyzer.analyze(task_result)
            exec_context = ExecutionContext(
                task=task_result,
                complexity=complexity_result,
                routing=None,
            )
            strategy_result = strategy_engine.execute(exec_context)
            workflow_ctx = WorkflowContext(
                task=task_result,
                complexity=complexity_result,
                execution=strategy_result,
                routing=None,
            )
            workflow_engine.build(workflow_ctx)

        avg_ms = self._measure_latency(_run, iterations=20)
        assert avg_ms < self.WORKFLOW_ENGINE_MAX_MS, (
            f"WorkflowEngine avg latency {avg_ms:.2f}ms > {self.WORKFLOW_ENGINE_MAX_MS}ms"
        )

    def test_full_pipeline_latency(self):
        def _run():
            _run_pipeline("Analyze Apple 10-K")

        avg_ms = self._measure_latency(_run, iterations=20)
        assert avg_ms < self.FULL_PIPELINE_MAX_MS, (
            f"Full pipeline avg latency {avg_ms:.2f}ms > {self.FULL_PIPELINE_MAX_MS}ms"
        )

    def test_workflow_engine_instantiation_cold_start(self):
        start = time.perf_counter()
        _ = WorkflowEngine()
        elapsed = (time.perf_counter() - start) * 1000
        assert elapsed < 1, f"WorkflowEngine cold start {elapsed:.2f}ms > 1ms"

    def test_strategy_engine_latency(self):
        planning_ctx = PlanningContext(question="Analyze Apple 10-K")
        task_analyzer = TaskAnalyzer()
        complexity_analyzer = ComplexityAnalyzer()
        strategy_engine = StrategyExecutionEngine()

        def _run():
            task_result = task_analyzer.analyze(planning_ctx)
            complexity_result = complexity_analyzer.analyze(task_result)
            exec_context = ExecutionContext(
                task=task_result,
                complexity=complexity_result,
                routing=None,
            )
            strategy_engine.execute(exec_context)

        avg_ms = self._measure_latency(_run, iterations=20)
        assert avg_ms < 20, f"StrategyEngine avg latency {avg_ms:.2f}ms > 20ms"
