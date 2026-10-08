# ============================================================
# V5 Phase 3 Sprint 2 Step 3 — Execution Benchmark
# ============================================================
# 40 execution cases covering all 5 strategies.
# Measures: Dispatch Accuracy, Execution Latency,
# Strategy Distribution, Handler Coverage, Success Rate.
# ============================================================

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import pytest

from agent.agent_runtime import AgentRuntime
from agent.execution import (
    ExecutionContext,
    ExecutionDispatcher,
    ExecutionHandlerContext,
    ExecutionHandlerRegistry,
    ExecutionOutput,
    ExecutionStrategyType,
)
from agent.execution.execution_engine import ExecutionEngine as StrategyExecutionEngine
from agent.execution.handlers import (  # noqa: F401 — auto-registration
    DirectLLMHandler,
    MultiStepHandler,
    ParallelHandler,
    RagHandler,
    ToolCallingHandler,
)
from agent.execution_engine import ExecutionEngine
from agent.planning import (
    PlanningContext,
    TaskType,
)
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
from llm.router import (
    CapabilityRoutingPolicy,
    ModelRouter,
    RoutingPolicy,
)

# ============================================================
# Mock Dependencies
# ============================================================

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


# ============================================================
# Benchmark Case
# ============================================================

@dataclass
class BenchmarkCase:
    prompt: str
    expected_strategy: ExecutionStrategyType
    expected_task_type: TaskType
    category: str = ""


# ============================================================
# 40 Benchmark Cases
# ============================================================

BENCHMARK_CASES: List[BenchmarkCase] = [
    # ========================
    # DirectLLM (10 cases)
    # ========================
    BenchmarkCase("Hello", ExecutionStrategyType.DIRECT_LLM, TaskType.CHAT, "chat"),
    BenchmarkCase("How are you today?", ExecutionStrategyType.DIRECT_LLM, TaskType.CHAT, "chat"),
    BenchmarkCase("What is machine learning?", ExecutionStrategyType.DIRECT_LLM, TaskType.CHAT, "chat"),
    BenchmarkCase("Tell me a joke about programming", ExecutionStrategyType.DIRECT_LLM, TaskType.CHAT, "chat"),
    BenchmarkCase("Explain blockchain in simple terms", ExecutionStrategyType.DIRECT_LLM, TaskType.CHAT, "chat"),
    BenchmarkCase("What is the tallest mountain in the world?", ExecutionStrategyType.DIRECT_LLM, TaskType.CHAT, "chat"),
    BenchmarkCase("Who invented the internet?", ExecutionStrategyType.DIRECT_LLM, TaskType.CHAT, "chat"),
    BenchmarkCase("Give me a recipe for pasta", ExecutionStrategyType.DIRECT_LLM, TaskType.CHAT, "chat"),
    BenchmarkCase("What is the meaning of life?", ExecutionStrategyType.DIRECT_LLM, TaskType.CHAT, "chat"),
    BenchmarkCase("How do airplanes fly?", ExecutionStrategyType.DIRECT_LLM, TaskType.CHAT, "chat"),

    # ========================
    # RAG (10 cases)
    # ========================
    BenchmarkCase("What is Apple's revenue?", ExecutionStrategyType.RAG, TaskType.DOCUMENT_QA, "document_qa"),
    BenchmarkCase("Analyze the Apple 10-K document", ExecutionStrategyType.RAG, TaskType.DOCUMENT_QA, "document_qa"),
    BenchmarkCase("What is Apple's profit margin?", ExecutionStrategyType.RAG, TaskType.DOCUMENT_QA, "document_qa"),
    BenchmarkCase("Show me the balance sheet of Apple", ExecutionStrategyType.RAG, TaskType.DOCUMENT_QA, "document_qa"),
    BenchmarkCase("What is the EBITDA of Apple?", ExecutionStrategyType.RAG, TaskType.DOCUMENT_QA, "document_qa"),
    BenchmarkCase("Analyze the annual report of Apple", ExecutionStrategyType.RAG, TaskType.DOCUMENT_QA, "document_qa"),
    BenchmarkCase("What are the risk factors in the filing?", ExecutionStrategyType.RAG, TaskType.DOCUMENT_QA, "document_qa"),
    BenchmarkCase("Apple earnings per share this quarter", ExecutionStrategyType.RAG, TaskType.DOCUMENT_QA, "document_qa"),
    BenchmarkCase("What is Apple's cash flow?", ExecutionStrategyType.RAG, TaskType.DOCUMENT_QA, "document_qa"),
    BenchmarkCase("Apple dividend analysis", ExecutionStrategyType.RAG, TaskType.DOCUMENT_QA, "document_qa"),

    # ========================
    # Parallel (5 cases)
    # ========================
    BenchmarkCase("Compare Apple and Tesla", ExecutionStrategyType.PARALLEL, TaskType.COMPARISON, "comparison"),
    BenchmarkCase("Apple vs Tesla comparison", ExecutionStrategyType.PARALLEL, TaskType.COMPARISON, "comparison"),
    BenchmarkCase("Compare the revenue of Apple and Tesla", ExecutionStrategyType.PARALLEL, TaskType.COMPARISON, "comparison"),
    BenchmarkCase("Apple and Tesla financial comparison", ExecutionStrategyType.PARALLEL, TaskType.COMPARISON, "comparison"),
    BenchmarkCase("Compare Apple and NVIDIA", ExecutionStrategyType.PARALLEL, TaskType.COMPARISON, "comparison"),

    # ========================
    # MultiStep (5 cases)
    # ========================
    BenchmarkCase("Research AI market trends", ExecutionStrategyType.MULTI_STEP, TaskType.RESEARCH, "research"),
    BenchmarkCase("Deep research on AI market trends and future outlook", ExecutionStrategyType.MULTI_STEP, TaskType.RESEARCH, "research"),
    BenchmarkCase("Analyze the AI industry outlook and forecast", ExecutionStrategyType.MULTI_STEP, TaskType.RESEARCH, "research"),
    BenchmarkCase("Investigate the semiconductor market trends", ExecutionStrategyType.MULTI_STEP, TaskType.RESEARCH, "research"),
    BenchmarkCase("Assessment of the electric vehicle sector", ExecutionStrategyType.MULTI_STEP, TaskType.RESEARCH, "research"),

    # ========================
    # ToolCalling (5 cases)
    # ========================
    BenchmarkCase("OCR this invoice", ExecutionStrategyType.TOOL_CALLING, TaskType.OCR, "ocr"),
    BenchmarkCase("Scan this document with OCR", ExecutionStrategyType.TOOL_CALLING, TaskType.OCR, "ocr"),
    BenchmarkCase("Analyze this chart image", ExecutionStrategyType.TOOL_CALLING, TaskType.IMAGE_ANALYSIS, "image"),
    BenchmarkCase("What does this picture show?", ExecutionStrategyType.TOOL_CALLING, TaskType.IMAGE_ANALYSIS, "image"),
    BenchmarkCase("OCR recognition of this receipt", ExecutionStrategyType.TOOL_CALLING, TaskType.OCR, "ocr"),

    # ========================
    # Edge Cases (5 cases)
    # ========================
    BenchmarkCase("", ExecutionStrategyType.DIRECT_LLM, TaskType.CHAT, "edge"),
    BenchmarkCase("Apple dividend yield analysis", ExecutionStrategyType.RAG, TaskType.DOCUMENT_QA, "edge"),
    BenchmarkCase("Compare the market strategies of Apple and Tesla", ExecutionStrategyType.PARALLEL, TaskType.COMPARISON, "edge"),
    BenchmarkCase("What is the P/E ratio of Apple?", ExecutionStrategyType.RAG, TaskType.DOCUMENT_QA, "edge"),
    BenchmarkCase("Analyze the risk assessment of Tesla", ExecutionStrategyType.RAG, TaskType.DOCUMENT_QA, "edge"),
]


# ============================================================
# Benchmark Result
# ============================================================

@dataclass
class BenchmarkResult:
    total: int = 0
    passed: int = 0
    failed: int = 0
    dispatch_accuracy: float = 0.0
    total_dispatch_time_ms: float = 0.0
    avg_dispatch_time_ms: float = 0.0
    avg_runtime_ms: float = 0.0
    strategy_distribution: Dict[str, int] = field(default_factory=dict)
    handler_coverage: Dict[str, bool] = field(default_factory=dict)
    failures: List[Tuple[str, str, str]] = field(default_factory=list)


# ============================================================
# Benchmark Test Class
# ============================================================

class TestExecutionBenchmark:

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

    # ============================================================
    # Individual Case Tests
    # ============================================================

    @pytest.mark.parametrize("case", BENCHMARK_CASES, ids=[f"{c.expected_strategy.value}:{c.prompt[:30]}" for c in BENCHMARK_CASES])
    def test_case_strategy_accuracy(self, case: BenchmarkCase):
        result = self.runtime.run(case.prompt)
        assert result.execution is not None, f"No execution result for: {case.prompt}"
        actual = result.execution["strategy"]
        expected = case.expected_strategy.value
        assert actual == expected, (
            f"Strategy mismatch for '{case.prompt}': "
            f"expected={expected}, actual={actual}"
        )

    @pytest.mark.parametrize("case", BENCHMARK_CASES, ids=[f"{c.expected_strategy.value}:{c.prompt[:30]}" for c in BENCHMARK_CASES])
    def test_case_task_type_accuracy(self, case: BenchmarkCase):
        result = self.runtime.run(case.prompt)
        assert result.planning is not None, f"No planning for: {case.prompt}"
        actual = result.planning["task_type"]
        expected = case.expected_task_type.value
        assert actual == expected, (
            f"Task type mismatch for '{case.prompt}': "
            f"expected={expected}, actual={actual}"
        )

    @pytest.mark.parametrize("case", BENCHMARK_CASES, ids=[f"{c.expected_strategy.value}:{c.prompt[:30]}" for c in BENCHMARK_CASES])
    def test_case_execution_success(self, case: BenchmarkCase):
        result = self.runtime.run(case.prompt)
        assert isinstance(result, RuntimeResult)
        assert result.execution is not None
        assert "confidence" in result.execution
        assert result.execution["confidence"] > 0
        assert result.planning is not None

    # ============================================================
    # Full Benchmark Run
    # ============================================================

    @pytest.mark.perf
    def test_full_benchmark(self):
        results: BenchmarkResult = BenchmarkResult()
        dispatch_times: List[float] = []
        runtime_times: List[float] = []
        strategy_counts: Dict[str, int] = {}
        handler_used: Dict[str, bool] = {
            "RagHandler": False,
            "DirectLLMHandler": False,
            "ParallelHandler": False,
            "MultiStepHandler": False,
            "ToolCallingHandler": False,
        }

        for case in BENCHMARK_CASES:
            results.total += 1

            t0 = time.perf_counter()
            result = self.runtime.run(case.prompt)
            runtime_elapsed = (time.perf_counter() - t0) * 1000
            runtime_times.append(runtime_elapsed)

            if result.execution is None:
                results.failed += 1
                results.failures.append((case.prompt, "N/A", "No execution result"))
                continue

            actual = result.execution["strategy"]
            expected = case.expected_strategy.value

            strategy_counts[actual] = strategy_counts.get(actual, 0) + 1

            if actual == expected:
                results.passed += 1
            else:
                results.failed += 1
                results.failures.append((case.prompt, expected, actual))

            # Measure dispatch time
            t1 = time.perf_counter()
            plan, task_result, complexity_result = self.runtime.planner.plan(
                PlanningContext(question=case.prompt, companies=[])
            )
            routing_context = self.runtime.planner.build_routing_context(
                task_result, complexity_result
            )
            exec_ctx = ExecutionContext(
                task=task_result,
                complexity=complexity_result,
                routing=routing_context,
            )
            strategy_result = self.strategy_engine.execute(exec_ctx)
            handler_ctx = ExecutionHandlerContext(
                plan=plan,
                executor=self.runtime.executor,
            )
            t2 = time.perf_counter()
            output = self.dispatcher.dispatch(strategy_result, handler_ctx)
            dispatch_elapsed = (time.perf_counter() - t2) * 1000
            dispatch_times.append(dispatch_elapsed)

            assert isinstance(output, ExecutionOutput)

            # Track handler coverage
            handler_name = ExecutionHandlerRegistry.get(
                strategy_result.strategy
            ).__name__
            if handler_name in handler_used:
                handler_used[handler_name] = True

        # Aggregate
        results.dispatch_accuracy = results.passed / results.total if results.total > 0 else 0.0
        results.total_dispatch_time_ms = sum(dispatch_times)
        results.avg_dispatch_time_ms = results.total_dispatch_time_ms / len(dispatch_times) if dispatch_times else 0.0
        results.avg_runtime_ms = sum(runtime_times) / len(runtime_times) if runtime_times else 0.0
        results.strategy_distribution = strategy_counts
        results.handler_coverage = handler_used

        # Print report
        print("\n" + "=" * 70)
        print("  V5 Phase 3 Sprint 2 — Execution Benchmark Report")
        print("=" * 70)
        print(f"  Total Cases:          {results.total}")
        print(f"  Passed:               {results.passed}")
        print(f"  Failed:               {results.failed}")
        print(f"  Dispatch Accuracy:    {results.dispatch_accuracy:.1%}")
        print(f"  Avg Dispatch Time:    {results.avg_dispatch_time_ms:.3f} ms")
        print(f"  Avg Runtime:          {results.avg_runtime_ms:.3f} ms")
        print("-" * 70)
        print("  Strategy Distribution:")
        for strategy, count in sorted(strategy_counts.items()):
            bar = "█" * count
            print(f"    {strategy:<20s} {count:>2d}  {bar}")
        print("-" * 70)
        print("  Handler Coverage:")
        for handler, used in sorted(handler_used.items()):
            status = "✅" if used else "❌"
            print(f"    {handler:<25s} {status}")
        print("-" * 70)
        if results.failures:
            print("  Failures:")
            for prompt, expected, actual in results.failures:
                print(f"    '{prompt[:50]}' → expected={expected}, actual={actual}")
        print("=" * 70 + "\n")

        # Assertions
        assert results.dispatch_accuracy >= 0.90, (
            f"Dispatch accuracy {results.dispatch_accuracy:.1%} below 90% threshold"
        )
        assert results.passed >= 36, (
            f"Only {results.passed}/{results.total} passed (minimum 36 required)"
        )
        assert all(handler_used.values()), (
            f"Not all handlers covered: {handler_used}"
        )
        assert results.avg_dispatch_time_ms < 10.0, (
            f"Avg dispatch time {results.avg_dispatch_time_ms:.3f}ms exceeds 10ms threshold"
        )

    # ============================================================
    # Distribution Tests
    # ============================================================

    def test_strategy_distribution(self):
        distribution: Dict[str, int] = {}
        for case in BENCHMARK_CASES:
            result = self.runtime.run(case.prompt)
            strategy = result.execution["strategy"]
            distribution[strategy] = distribution.get(strategy, 0) + 1

        assert distribution.get("direct_llm", 0) >= 10, "Missing DirectLLM coverage"
        assert distribution.get("rag", 0) >= 10, "Missing RAG coverage"
        assert distribution.get("parallel", 0) >= 5, "Missing Parallel coverage"
        assert distribution.get("multi_step", 0) >= 5, "Missing MultiStep coverage"
        assert distribution.get("tool_calling", 0) >= 5, "Missing ToolCalling coverage"

    def test_handler_coverage(self):
        used: Dict[str, bool] = {
            "RagHandler": False,
            "DirectLLMHandler": False,
            "ParallelHandler": False,
            "MultiStepHandler": False,
            "ToolCallingHandler": False,
        }

        for case in BENCHMARK_CASES:
            result = self.runtime.run(case.prompt)
            strategy = ExecutionStrategyType(result.execution["strategy"])
            handler_name = ExecutionHandlerRegistry.get(strategy).__name__
            if handler_name in used:
                used[handler_name] = True

        for handler_name, is_used in used.items():
            assert is_used, f"Handler {handler_name} was never used"

    @pytest.mark.perf
    def test_dispatch_latency(self):
        latencies: List[float] = []
        for case in BENCHMARK_CASES[:10]:
            plan, task_result, complexity_result = self.runtime.planner.plan(
                PlanningContext(question=case.prompt, companies=[])
            )
            routing_context = self.runtime.planner.build_routing_context(
                task_result, complexity_result
            )
            exec_ctx = ExecutionContext(
                task=task_result,
                complexity=complexity_result,
                routing=routing_context,
            )
            strategy_result = self.strategy_engine.execute(exec_ctx)
            handler_ctx = ExecutionHandlerContext(
                plan=plan,
                executor=self.runtime.executor,
            )
            t0 = time.perf_counter()
            self.dispatcher.dispatch(strategy_result, handler_ctx)
            elapsed = (time.perf_counter() - t0) * 1000
            latencies.append(elapsed)

        avg = sum(latencies) / len(latencies)
        assert avg < 5.0, f"Dispatch latency {avg:.3f}ms exceeds 5ms threshold"

    def test_execution_success_rate(self):
        success = 0
        total = 0
        for case in BENCHMARK_CASES:
            total += 1
            try:
                result = self.runtime.run(case.prompt)
                if result.execution is not None and result.planning is not None:
                    success += 1
            except Exception:
                pass

        rate = success / total
        assert rate >= 0.95, f"Success rate {rate:.1%} below 95% threshold"

    # ============================================================
    # Regression: Planner + Router still work
    # ============================================================

    def test_planner_no_regression_during_benchmark(self):
        result = self.runtime.run("What is Apple's revenue?")
        assert result.planning is not None
        assert "task_type" in result.planning
        assert "complexity" in result.planning

    def test_router_no_regression_during_benchmark(self):
        result = self.runtime.run("Hello")
        assert result.routing is not None
        assert "provider" in result.routing
