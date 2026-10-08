from collections.abc import Mapping
from typing import Any, Dict, List, Optional

from evaluation.metrics import (
    answer_quality_score,
    calculate_overall_score,
    categorical_match_score,
    claim_coverage_score,
    hallucination_score,
    ranked_retrieval_metrics,
    retrieval_score,
    tool_selection_score,
)

_OFFLINE_CONTRACT_FIELDS = (
    ("expected_intent", "intent"),
    ("expected_companies", "companies"),
    ("expected_task_type", "task_type"),
    ("expected_workflow", "workflow_type"),
    ("expected_strategy", "strategy"),
    ("expected_tools", "tools_used"),
    ("expected_use_retrieval", "use_retrieval"),
    ("expected_use_tools", "use_tools"),
)


def evaluate_offline_contract_case(
    case: Mapping[str, Any],
    observation: Mapping[str, Any],
) -> Dict[str, Any]:
    """Evaluate deterministic planning contracts without scoring model output.

    This evaluator deliberately excludes answer, citation, retrieval-quality,
    latency, and model-quality metrics.  The offline runner never invokes an
    LLM or vector store, so assigning scores to those dimensions would create
    misleading evidence.  Every returned check corresponds to an explicit
    expectation in the versioned golden dataset.
    """

    checks: list[Dict[str, Any]] = []
    issues: list[Dict[str, Any]] = []

    for expected_field, observed_field in _OFFLINE_CONTRACT_FIELDS:
        if expected_field not in case:
            continue

        expected = case[expected_field]
        actual = observation.get(observed_field)
        matched = _offline_values_match(expected, actual)
        check = {
            "field": observed_field,
            "expected": expected,
            "actual": actual,
            "matched": matched,
        }
        checks.append(check)
        if not matched:
            issues.append(
                {
                    "type": f"{observed_field}_contract",
                    "severity": "high",
                    "message": (
                        f"Expected {observed_field}={expected!r}, "
                        f"got {actual!r}"
                    ),
                }
            )

    if not checks:
        issues.append(
            {
                "type": "missing_offline_contract",
                "severity": "critical",
                "message": "Case has no deterministic planning expectations",
            }
        )
        score = 0.0
    else:
        matched_count = sum(1 for check in checks if check["matched"])
        score = round(matched_count / len(checks) * 100, 1)

    return {
        "contract_score": score,
        "passed": bool(checks) and not issues,
        "checks": checks,
        "issues": issues,
        "scored_dimensions": [check["field"] for check in checks],
        "unmeasured_dimensions": [
            "answer_quality",
            "citation_faithfulness",
            "retrieval_quality",
            "model_quality",
        ],
    }


def _offline_values_match(expected: Any, actual: Any) -> bool:
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False
        return sorted(_normalise_offline_value(item) for item in expected) == sorted(
            _normalise_offline_value(item) for item in actual
        )
    if isinstance(expected, str):
        return isinstance(actual, str) and _normalise_offline_value(expected) == _normalise_offline_value(actual)
    return expected == actual


def _normalise_offline_value(value: Any) -> str:
    return str(value).strip().lower()


def evaluate_agent_response(
    answer: str,
    question: str,
    tools_used: List[str],
    sources: List[Dict[str, Any]],
    companies: List[str],
    expected_tools: List[str],
    expected_sources: List[str],
    criteria: List[str],
    weights: Optional[Dict[str, float]] = None,
    intent: Optional[str] = None,
    workflow_type: Optional[str] = None,
    strategy: Optional[str] = None,
    retrieved_ids: Optional[List[str]] = None,
    expected_intent: Optional[str] = None,
    expected_workflow: Optional[str] = None,
    expected_strategy: Optional[str] = None,
    expected_retrieval_ids: Optional[List[str]] = None,
    reference_claims: Optional[List[str]] = None,
) -> Dict[str, Any]:
    retrieval_s = retrieval_score(sources, expected_sources)
    tool_s = tool_selection_score(tools_used, expected_tools)
    quality_s = answer_quality_score(answer, question, criteria)
    hallucination_s = hallucination_score(answer, sources, companies)
    ranked_metrics = ranked_retrieval_metrics(
        retrieved_ids or [],
        expected_retrieval_ids or [],
    )
    intent_s = categorical_match_score(intent, expected_intent)
    workflow_s = categorical_match_score(workflow_type, expected_workflow)
    strategy_s = categorical_match_score(strategy, expected_strategy)
    claim_coverage_s = claim_coverage_score(answer, reference_claims or [])

    overall = calculate_overall_score(
        retrieval_s=retrieval_s,
        tool_s=tool_s,
        quality_s=quality_s,
        hallucination_s=hallucination_s,
        weights=weights,
    )

    issues = []

    if retrieval_s < 50:
        issues.append({
            "type": "retrieval",
            "severity": "high" if retrieval_s < 30 else "medium",
            "message": f"Low retrieval score ({retrieval_s}): expected {expected_sources}, got {len(sources)} sources",
        })

    if tool_s < 50:
        issues.append({
            "type": "tool_selection",
            "severity": "high" if tool_s < 30 else "medium",
            "message": f"Low tool selection score ({tool_s}): expected {expected_tools}, used {tools_used}",
        })

    if quality_s < 40:
        issues.append({
            "type": "answer_quality",
            "severity": "high",
            "message": f"Low answer quality score ({quality_s}): answer may be too short or incomplete",
        })
    elif quality_s < 60:
        issues.append({
            "type": "answer_quality",
            "severity": "medium",
            "message": f"Moderate answer quality score ({quality_s}): consider improving completeness",
        })

    if hallucination_s < 70:
        issues.append({
            "type": "hallucination",
            "severity": "high",
            "message": f"Hallucination risk detected (score: {hallucination_s})",
        })

    contract_checks = (
        ("intent", intent, intent_s, expected_intent),
        ("workflow", workflow_type, workflow_s, expected_workflow),
        ("strategy", strategy, strategy_s, expected_strategy),
    )
    for name, actual, score, expected in contract_checks:
        if expected and score < 100:
            issues.append({
                "type": f"{name}_contract",
                "severity": "high",
                "message": f"Expected {name}={expected!r}, got {actual!r}",
            })

    if expected_retrieval_ids and ranked_metrics["recall_at_k"] < 100:
        issues.append({
            "type": "ranked_retrieval",
            "severity": "high" if ranked_metrics["recall_at_k"] < 50 else "medium",
            "message": (
                "Golden retrieval ids were not fully recovered "
                f"(Recall@k={ranked_metrics['recall_at_k']})"
            ),
        })

    if reference_claims and claim_coverage_s < 100:
        issues.append({
            "type": "claim_coverage",
            "severity": "medium",
            "message": f"Reference claim coverage is {claim_coverage_s}",
        })

    if not answer or not answer.strip():
        issues.append({
            "type": "empty_response",
            "severity": "critical",
            "message": "Agent returned empty response",
        })

    fallback_markers = ["unable to process", "fallback", "cannot process"]
    if any(marker in answer.lower() for marker in fallback_markers):
        issues.append({
            "type": "fallback",
            "severity": "high",
            "message": "Agent used fallback response",
        })

    return {
        "score": overall,
        "retrieval_score": retrieval_s,
        "tool_score": tool_s,
        "quality_score": quality_s,
        "hallucination_score": hallucination_s,
        "ranked_retrieval": ranked_metrics,
        "intent_score": intent_s,
        "workflow_score": workflow_s,
        "strategy_score": strategy_s,
        "claim_coverage_score": claim_coverage_s,
        "issues": issues,
        "passed": overall >= 60.0 and len([i for i in issues if i["severity"] in ("critical", "high")]) == 0,
    }


def evaluate_batch(
    results: List[Dict[str, Any]],
    weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    if not results:
        return {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "average_score": 0.0,
            "results": [],
        }

    passed = sum(1 for r in results if r.get("passed", False))
    failed = len(results) - passed
    avg_score = sum(r.get("score", 0.0) for r in results) / len(results)

    metric_averages = {}
    for key in (
        "retrieval_score",
        "tool_score",
        "quality_score",
        "hallucination_score",
        "intent_score",
        "workflow_score",
        "strategy_score",
        "claim_coverage_score",
    ):
        values = [r.get(key, 0.0) for r in results if key in r]
        if values:
            metric_averages[key] = round(sum(values) / len(values), 1)

    return {
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "average_score": round(avg_score, 1),
        "metric_averages": metric_averages,
        "results": results,
    }
