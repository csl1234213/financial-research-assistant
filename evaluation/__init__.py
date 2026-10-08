from importlib import import_module

from evaluation.evaluator import (
    evaluate_agent_response,
    evaluate_batch,
    evaluate_offline_contract_case,
)
from evaluation.metrics import (
    answer_quality_score,
    calculate_overall_score,
    hallucination_score,
    retrieval_score,
    tool_selection_score,
)

_LAZY_EXPORTS = {
    "load_dataset": ("evaluation.runner", "load_dataset"),
    "run_dataset_evaluation": ("evaluation.runner", "run_dataset_evaluation"),
    "run_single_evaluation": ("evaluation.runner", "run_single_evaluation"),
    "save_report": ("evaluation.runner", "save_report"),
    "observe_planning_contract": (
        "evaluation.offline",
        "observe_planning_contract",
    ),
    "run_offline_golden_evaluation": (
        "evaluation.offline",
        "run_offline_golden_evaluation",
    ),
    "save_offline_report": ("evaluation.offline", "save_offline_report"),
    "load_retrieval_dataset": (
        "evaluation.retrieval_dataset",
        "load_retrieval_dataset",
    ),
    "run_retrieval_evaluation": (
        "evaluation.retrieval_gate",
        "run_retrieval_evaluation",
    ),
    "save_retrieval_report": (
        "evaluation.retrieval_gate",
        "save_retrieval_report",
    ),
}


def __getattr__(name: str):
    """Preserve public exports without importing the online runtime eagerly."""

    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value

__all__ = [
    "retrieval_score",
    "tool_selection_score",
    "answer_quality_score",
    "hallucination_score",
    "calculate_overall_score",
    "evaluate_agent_response",
    "evaluate_batch",
    "evaluate_offline_contract_case",
    "load_dataset",
    "load_retrieval_dataset",
    "observe_planning_contract",
    "run_single_evaluation",
    "run_dataset_evaluation",
    "run_offline_golden_evaluation",
    "run_retrieval_evaluation",
    "save_report",
    "save_retrieval_report",
    "save_offline_report",
]
