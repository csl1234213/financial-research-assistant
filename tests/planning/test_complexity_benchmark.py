# ============================================================
# Planner Benchmark — Accuracy, Latency, Distribution
# ============================================================
# Validates the Planner (TaskAnalyzer + ComplexityAnalyzer)
# against a curated set of 40 prompts spanning LOW / MEDIUM /
# HIGH complexity levels.
# ============================================================

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from agent.planning import (
    ComplexityAnalyzer,
    ComplexityLevel,
    PlanningContext,
    TaskAnalyzer,
)

# ============================================================
# Benchmark Dataset: 40 prompts with expected complexity
# ============================================================

BENCHMARK_PROMPTS = [
    # ----------------------------------------
    # LOW (16 prompts)
    # ----------------------------------------
    ("Hello", ComplexityLevel.LOW),
    ("Hi", ComplexityLevel.LOW),
    ("How are you?", ComplexityLevel.LOW),
    ("What is your name?", ComplexityLevel.LOW),
    ("Thanks", ComplexityLevel.LOW),
    ("Goodbye", ComplexityLevel.LOW),
    ("What is 2+2?", ComplexityLevel.LOW),
    ("Help", ComplexityLevel.LOW),
    ("Who are you?", ComplexityLevel.LOW),
    ("Tell me a joke", ComplexityLevel.LOW),
    ("OCR this invoice", ComplexityLevel.LOW),
    ("Extract text from this image", ComplexityLevel.LOW),
    ("OCR receipt", ComplexityLevel.LOW),
    ("Extract table from screenshot", ComplexityLevel.LOW),
    ("Summarize this financial document", ComplexityLevel.LOW),
    ("Research AI chip manufacturing capacity", ComplexityLevel.LOW),

    # ----------------------------------------
    # MEDIUM (10 prompts)
    # ----------------------------------------
    ("Analyze Apple 10-K report", ComplexityLevel.MEDIUM),
    ("Summarize Microsoft annual report", ComplexityLevel.MEDIUM),
    ("What is Tesla revenue?", ComplexityLevel.MEDIUM),
    ("Analyze Apple revenue 2024", ComplexityLevel.MEDIUM),
    ("Summarize NVIDIA earnings", ComplexityLevel.MEDIUM),
    ("What were Apple profits in 2023?", ComplexityLevel.MEDIUM),
    ("Analyze Tesla balance sheet", ComplexityLevel.MEDIUM),
    ("Analyze Microsoft profit margins", ComplexityLevel.MEDIUM),
    ("What is Apple P/E ratio?", ComplexityLevel.MEDIUM),
    ("Analyze Apple income statement", ComplexityLevel.MEDIUM),

    # ----------------------------------------
    # HIGH (14 prompts)
    # ----------------------------------------
    ("Analyze Apple financial performance", ComplexityLevel.HIGH),
    ("Analyze Tesla growth rate", ComplexityLevel.HIGH),
    ("Analyze NVIDIA GPU business", ComplexityLevel.HIGH),
    ("Compare Apple and Tesla revenue", ComplexityLevel.HIGH),
    ("Compare Apple, Microsoft, Tesla (2020-2025)", ComplexityLevel.HIGH),
    ("Research global AI infrastructure trends", ComplexityLevel.HIGH),
    ("Compare Apple, Tesla, Microsoft, NVIDIA, Amazon", ComplexityLevel.HIGH),
    ("Research semiconductor industry outlook", ComplexityLevel.HIGH),
    ("Compare NVIDIA and AMD GPU market share", ComplexityLevel.HIGH),
    ("Research renewable energy investment trends", ComplexityLevel.HIGH),
    ("Compare Apple, Microsoft, Google cloud revenue", ComplexityLevel.HIGH),
    ("Research global EV market 2024-2030", ComplexityLevel.HIGH),
    ("Compare Tesla, BYD, NIO, Rivian EV sales", ComplexityLevel.HIGH),
    ("Research fintech disruption in banking", ComplexityLevel.HIGH),
]


class TestPlannerBenchmark:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.task_analyzer = TaskAnalyzer()
        self.complexity_analyzer = ComplexityAnalyzer()
        self.results = []

    # ============================================================
    # Run all benchmarks
    # ============================================================

    @pytest.mark.perf
    def test_benchmark_all(self):
        self._run_all()
        self._assert_accuracy()
        self._assert_distribution_balanced()
        self._assert_latency_under_threshold()
        self._print_report()

    # ============================================================
    # Core execution
    # ============================================================

    def _run_all(self):
        self.results = []
        self.latencies = []

        for prompt, expected in BENCHMARK_PROMPTS:
            ctx = PlanningContext(
                question=prompt,
                companies=[],
                years=[],
            )

            t0 = time.perf_counter()
            task_result = self.task_analyzer.analyze(ctx)
            complexity_result = self.complexity_analyzer.analyze(task_result)
            elapsed_ms = (time.perf_counter() - t0) * 1000

            actual = complexity_result.complexity.level
            score = complexity_result.complexity.score
            tokens = complexity_result.complexity.estimated_tokens
            cost = complexity_result.complexity.estimated_cost
            latency_ms = complexity_result.complexity.estimated_latency_ms
            task_type = task_result.task.task_type

            self.results.append({
                "prompt": prompt,
                "expected": expected,
                "actual": actual,
                "score": score,
                "tokens": tokens,
                "cost": cost,
                "latency_ms": latency_ms,
                "task_type": task_type,
                "correct": actual == expected,
            })
            self.latencies.append(elapsed_ms)

    # ============================================================
    # Accuracy
    # ============================================================

    def _assert_accuracy(self):
        correct = sum(1 for r in self.results if r["correct"])
        total = len(self.results)
        accuracy = correct / total * 100

        self._accuracy = accuracy
        self._correct = correct
        self._total = total

        assert accuracy >= 85.0, (
            f"Planner accuracy {accuracy:.1f}% below 85% threshold"
        )

    # ============================================================
    # Distribution
    # ============================================================

    def _assert_distribution_balanced(self):
        levels = [r["actual"] for r in self.results]
        counts = {
            level: levels.count(level)
            for level in ComplexityLevel
        }
        total = len(levels)

        self._distribution = {
            level.value: counts[level] / total * 100
            for level in ComplexityLevel
        }

        for level, pct in self._distribution.items():
            assert 10.0 <= pct <= 60.0, (
                f"Distribution {level}={pct:.1f}% outside 10-60% range"
            )

    # ============================================================
    # Latency
    # ============================================================

    def _assert_latency_under_threshold(self):
        avg = sum(self.latencies) / len(self.latencies)
        p99 = sorted(self.latencies)[int(len(self.latencies) * 0.99)]

        self._avg_latency = avg
        self._p99_latency = p99

        assert avg < 5.0, (
            f"Average planner latency {avg:.2f}ms exceeds 5ms threshold"
        )
        assert p99 < 20.0, (
            f"P99 planner latency {p99:.2f}ms exceeds 20ms threshold"
        )

    # ============================================================
    # Report
    # ============================================================

    def _print_report(self):
        print("\n" + "=" * 70)
        print("  PLANNER BENCHMARK REPORT")
        print("=" * 70)

        # ---- Accuracy ----
        print(f"\n  Accuracy:    {self._correct}/{self._total} "
              f"({self._accuracy:.1f}%)")
        if self._accuracy >= 95.0:
            print("  Verdict:     PASS")
        else:
            print("  Verdict:     PASS (above 85% threshold)")

        # ---- Score Stats ----
        scores = [r["score"] for r in self.results]
        avg_score = sum(scores) / len(scores)
        print("\n  Score Stats:")
        print(f"    Mean:   {avg_score:.4f}")
        print(f"    Min:    {min(scores):.4f}")
        print(f"    Max:    {max(scores):.4f}")

        # ---- Distribution ----
        print("\n  Distribution:")
        for level, pct in self._distribution.items():
            bar = "#" * int(pct / 2)
            print(f"    {level:<8s} {pct:5.1f}%  {bar}")

        # ---- Latency ----
        print("\n  Latency:")
        print(f"    Average:  {self._avg_latency:.2f} ms")
        print(f"    P99:      {self._p99_latency:.2f} ms")

        # ---- Token Reasonableness ----
        tokens = [r["tokens"] for r in self.results]
        print("\n  Token Estimate:")
        print(f"    Mean:     {sum(tokens) / len(tokens):.0f}")
        print(f"    Range:    {min(tokens)} - {max(tokens)}")

        # ---- Cost ----
        costs = [r["cost"] for r in self.results]
        print("\n  Cost Estimate:")
        print(f"    Mean:     ${sum(costs) / len(costs):.4f}")
        print(f"    Range:    ${min(costs):.4f} - ${max(costs):.4f}")

        # ---- Error Detail ----
        errors = [r for r in self.results if not r["correct"]]
        if errors:
            print(f"\n  Misclassifications ({len(errors)}):")
            for e in errors:
                print(
                    f"    [{e['expected'].value}] → [{e['actual'].value}] "
                    f"score={e['score']:.4f}  \"{e['prompt'][:60]}\""
                )

        # ---- Per-Level Accuracy ----
        print("\n  Per-Level Accuracy:")
        for level in ComplexityLevel:
            subset = [r for r in self.results if r["expected"] == level]
            if subset:
                correct = sum(1 for r in subset if r["correct"])
                pct = correct / len(subset) * 100
                print(f"    {level.value:<8s} {correct}/{len(subset)} "
                      f"({pct:.1f}%)")

        print("\n" + "=" * 70)
        print("  BENCHMARK COMPLETE")
        print("=" * 70 + "\n")


# ============================================================
# Detail Benchmarks
# ============================================================

class TestPlannerDetailBenchmarks:

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.task_analyzer = TaskAnalyzer()
        self.complexity_analyzer = ComplexityAnalyzer()

    # ============================================================
    # Token Error
    # ============================================================

    def test_token_estimate_reasonableness(self):
        min_expected = {
            ComplexityLevel.LOW: 100,
            ComplexityLevel.MEDIUM: 200,
            ComplexityLevel.HIGH: 300,
        }
        max_expected = {
            ComplexityLevel.LOW: 600,
            ComplexityLevel.MEDIUM: 1200,
            ComplexityLevel.HIGH: 3000,
        }

        for prompt, expected_level in BENCHMARK_PROMPTS:
            ctx = PlanningContext(question=prompt, companies=[], years=[])
            task_result = self.task_analyzer.analyze(ctx)
            complexity_result = self.complexity_analyzer.analyze(task_result)

            tokens = complexity_result.complexity.estimated_tokens
            level = complexity_result.complexity.level

            assert tokens >= min_expected[level], (
                f"Token estimate {tokens} below min {min_expected[level]} "
                f"for '{prompt}' [{level.value}]"
            )
            assert tokens <= max_expected[level], (
                f"Token estimate {tokens} above max {max_expected[level]} "
                f"for '{prompt}' [{level.value}]"
            )

    # ============================================================
    # Complexity Accuracy
    # ============================================================

    def test_complexity_accuracy_per_level(self):
        level_correct = {level: 0 for level in ComplexityLevel}
        level_total = {level: 0 for level in ComplexityLevel}

        for prompt, expected_level in BENCHMARK_PROMPTS:
            ctx = PlanningContext(question=prompt, companies=[], years=[])
            task_result = self.task_analyzer.analyze(ctx)
            complexity_result = self.complexity_analyzer.analyze(task_result)

            actual = complexity_result.complexity.level
            level_total[expected_level] += 1
            if actual == expected_level:
                level_correct[expected_level] += 1

        for level in ComplexityLevel:
            if level_total[level] > 0:
                accuracy = level_correct[level] / level_total[level] * 100
                assert accuracy >= 80.0, (
                    f"{level.value} accuracy {accuracy:.1f}% below 80%"
                )

    # ============================================================
    # Score Monotonicity
    # ============================================================

    def test_score_monotonic_by_level(self):
        level_scores = {level: [] for level in ComplexityLevel}

        for prompt, _ in BENCHMARK_PROMPTS:
            ctx = PlanningContext(question=prompt, companies=[], years=[])
            task_result = self.task_analyzer.analyze(ctx)
            complexity_result = self.complexity_analyzer.analyze(task_result)

            level_scores[complexity_result.complexity.level].append(
                complexity_result.complexity.score
            )

        assert max(level_scores[ComplexityLevel.LOW]) <= 0.30
        assert max(level_scores[ComplexityLevel.MEDIUM]) <= 0.55

        if level_scores[ComplexityLevel.LOW]:
            assert min(level_scores[ComplexityLevel.MEDIUM]) > max(
                level_scores[ComplexityLevel.LOW]
            )
        if level_scores[ComplexityLevel.MEDIUM]:
            assert min(level_scores[ComplexityLevel.HIGH]) > max(
                level_scores[ComplexityLevel.MEDIUM]
            )

    # ============================================================
    # Latency Stability
    # ============================================================

    @pytest.mark.perf
    def test_latency_stability(self):
        latencies = []
        for _ in range(20):
            for prompt, _ in BENCHMARK_PROMPTS[:5]:
                ctx = PlanningContext(question=prompt, companies=[], years=[])
                t0 = time.perf_counter()
                self.task_analyzer.analyze(ctx)
                latencies.append((time.perf_counter() - t0) * 1000)

        avg = sum(latencies) / len(latencies)
        std = (
            sum((l - avg) ** 2 for l in latencies) / len(latencies)
        ) ** 0.5

        assert avg < 3.0, (
            f"Latency stability avg {avg:.2f}ms exceeds 3ms"
        )
        assert std < 5.0, (
            f"Latency stability std {std:.2f}ms exceeds 5ms"
        )
