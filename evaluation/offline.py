"""Deterministic, provider-free golden dataset contract evaluation.

This module exercises the real intent, planning, execution-strategy, and
workflow selection components.  It intentionally stops before retrieval and
generation: no model, embedding service, vector store, network client, or
runtime database is imported or called.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

from agent.execution.execution_context import ExecutionContext
from agent.execution.execution_engine import StrategyExecutionEngine
from agent.execution.strategies.direct_llm_strategy import DirectLLMStrategy
from agent.execution.strategies.multi_step_strategy import MultiStepStrategy
from agent.execution.strategies.parallel_strategy import ParallelStrategy
from agent.execution.strategies.rag_strategy import RagStrategy
from agent.execution.strategies.tool_calling_strategy import ToolCallingStrategy
from agent.execution.strategy_registry import StrategyRegistry
from agent.planning import PlanningContext
from agent.query_planner import QueryPlanner
from agent.workflow.workflow_context import WorkflowContext
from agent.workflow.workflow_engine import WorkflowEngine
from agent.workflow.workflow_registry import WorkflowRegistry
from agent.workflow.workflows.comparison_workflow import ComparisonWorkflow
from agent.workflow.workflows.direct_chat_workflow import DirectChatWorkflow
from agent.workflow.workflows.rag_workflow import RAGWorkflow
from agent.workflow.workflows.research_workflow import ResearchWorkflow
from core.intent_analyzer import IntentAnalyzer
from evaluation.dataset import GoldenDatasetValidationError, load_golden_dataset
from evaluation.evaluator import evaluate_offline_contract_case

OFFLINE_REPORT_SCHEMA_VERSION = "1.0"
OFFLINE_EVALUATOR_VERSION = "planning-contract-v1"
DEFAULT_DATASET_PATH = Path(__file__).resolve().parent / "datasets" / "financial_golden_v1.json"

_LIVE_ONLY_EXPECTATION_FIELDS = (
    "expected_sources",
    "expected_retrieval_ids",
    "reference_answer",
    "reference_claims",
    "criteria",
)


@dataclass(frozen=True)
class OfflinePlanningObservation:
    """Output of the deterministic runtime stages exercised by this runner."""

    intent: str
    companies: list[str]
    task_type: str
    workflow_type: str
    strategy: str
    tools_used: list[str]
    use_retrieval: bool
    use_tools: bool


def observe_planning_contract(question: str) -> OfflinePlanningObservation:
    """Run production planning components without crossing an I/O boundary."""

    _register_offline_components()
    intent_result = IntentAnalyzer().analyze(question)
    companies = intent_result.get("companies") or []

    planner = QueryPlanner()
    _plan, task_result, complexity_result = planner.plan(
        PlanningContext(
            question=question,
            companies=companies,
        )
    )
    routing_context = planner.build_routing_context(
        task_result,
        complexity_result,
    )
    execution = StrategyExecutionEngine().execute(
        ExecutionContext(
            task=task_result,
            complexity=complexity_result,
            routing=routing_context,
        )
    )
    workflow = WorkflowEngine().build(
        WorkflowContext(
            task=task_result,
            complexity=complexity_result,
            execution=execution,
            routing=routing_context,
        )
    )

    tools_used: list[str] = []
    if execution.use_retrieval:
        tools_used.append("retrieval")
    if execution.use_tools:
        tools_used.append("tool_calling")

    return OfflinePlanningObservation(
        intent=str(intent_result.get("intent", "")),
        companies=list(companies),
        task_type=task_result.task.task_type.value,
        workflow_type=workflow.workflow.value,
        strategy=execution.strategy.value,
        tools_used=tools_used,
        use_retrieval=execution.use_retrieval,
        use_tools=execution.use_tools,
    )


def run_offline_golden_evaluation(
    dataset_path: str | Path = DEFAULT_DATASET_PATH,
    *,
    threshold: float = 100.0,
) -> dict[str, Any]:
    """Evaluate all deterministic case contracts and return a stable report."""

    validated_threshold = _validate_threshold(threshold)
    source_path = Path(dataset_path)
    dataset = load_golden_dataset(source_path)

    results: list[dict[str, Any]] = []
    for case in dataset.cases:
        observation = asdict(observe_planning_contract(case["question"]))
        evaluation = evaluate_offline_contract_case(case, observation)
        metadata = case.get("metadata", {})
        scenario = metadata.get("scenario") if isinstance(metadata, dict) else None
        results.append(
            {
                "id": case["id"],
                "scenario": scenario,
                "question": case["question"],
                "observation": observation,
                "evaluation": evaluation,
                "live_only_expectations": {
                    field: case[field]
                    for field in _LIVE_ONLY_EXPECTATION_FIELDS
                    if field in case
                },
            }
        )

    scores = [result["evaluation"]["contract_score"] for result in results]
    average_score = round(sum(scores) / len(scores), 1) if scores else 0.0
    passed_cases = sum(1 for result in results if result["evaluation"]["passed"])
    threshold_passed = bool(results) and average_score >= validated_threshold

    return {
        "schema_version": OFFLINE_REPORT_SCHEMA_VERSION,
        "report_type": "offline_planning_contract",
        "execution_mode": "offline_deterministic",
        "evaluator_version": OFFLINE_EVALUATOR_VERSION,
        "dataset": {
            "id": dataset.dataset_id,
            "schema_version": dataset.schema_version,
            "filename": source_path.name,
            "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "case_count": len(dataset.cases),
        },
        "assurance_boundary": {
            "llm_invoked": False,
            "retriever_invoked": False,
            "network_required": False,
            "model_quality_claimed": False,
            "scored_scope": [
                "intent",
                "companies",
                "task_type",
                "workflow_type",
                "strategy",
                "tools_used",
                "use_retrieval",
                "use_tools",
            ],
            "unmeasured_scope": [
                "answer_quality",
                "citation_faithfulness",
                "retrieval_quality",
                "latency",
                "model_quality",
            ],
        },
        "threshold": validated_threshold,
        "summary": {
            "total_cases": len(results),
            "passed_cases": passed_cases,
            "failed_cases": len(results) - passed_cases,
            "average_contract_score": average_score,
            "threshold_passed": threshold_passed,
        },
        "results": results,
    }


def save_offline_report(report: dict[str, Any], output_path: str | Path) -> Path:
    """Write a stable JSON artifact to the caller-selected location."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run deterministic intent/planning/workflow contracts from a "
            "versioned golden dataset without calling an LLM or retriever."
        )
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET_PATH,
        help="Path to the versioned golden dataset JSON file.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        required=True,
        help="Destination for the deterministic JSON report.",
    )
    parser.add_argument(
        "--threshold",
        type=_threshold_argument,
        default=100.0,
        help="Minimum average planning-contract score required for exit code 0.",
    )
    args = parser.parse_args(argv)

    try:
        report = run_offline_golden_evaluation(
            args.dataset,
            threshold=args.threshold,
        )
        report_path = save_offline_report(report, args.report)
    except (
        FileNotFoundError,
        GoldenDatasetValidationError,
        json.JSONDecodeError,
        OSError,
        ValueError,
    ) as exc:
        print(f"offline evaluation failed: {exc}", file=sys.stderr)
        return 2

    summary = report["summary"]
    print(
        "offline evaluation: "
        f"{summary['passed_cases']}/{summary['total_cases']} cases passed; "
        f"contract score={summary['average_contract_score']}; "
        f"threshold={report['threshold']}; "
        f"report={report_path}"
    )
    return 0 if summary["threshold_passed"] else 1


def _register_offline_components() -> None:
    """Restore deterministic built-ins if another test cleared a registry."""

    strategies = {
        "rag": RagStrategy,
        "direct_llm": DirectLLMStrategy,
        "parallel": ParallelStrategy,
        "multi_step": MultiStepStrategy,
        "tool_calling": ToolCallingStrategy,
    }
    for name, strategy in strategies.items():
        if not StrategyRegistry.has_strategy(name):
            StrategyRegistry.register(name, strategy)

    workflows = {
        "direct_chat": DirectChatWorkflow,
        "rag": RAGWorkflow,
        "multi_step": ResearchWorkflow,
        "parallel": ComparisonWorkflow,
    }
    for name, workflow in workflows.items():
        if not WorkflowRegistry.has_workflow(name):
            WorkflowRegistry.register(name, workflow)


def _threshold_argument(value: str) -> float:
    try:
        return _validate_threshold(float(value))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _validate_threshold(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("threshold must be numeric")
    threshold = float(value)
    if not 0.0 <= threshold <= 100.0:
        raise ValueError("threshold must be between 0 and 100")
    return threshold


if __name__ == "__main__":
    raise SystemExit(main())
