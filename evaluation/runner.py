import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from evaluation.dataset import load_golden_dataset
from evaluation.evaluator import evaluate_agent_response, evaluate_batch
from services.agent_runtime.runtime import run_agent

logger = logging.getLogger(__name__)

_DATASET_DIR = Path(__file__).resolve().parent / "datasets"
_REPORTS_DIR = Path(__file__).resolve().parent / "reports"


def load_dataset(dataset_name: str = "financial_qa.json") -> List[Dict[str, Any]]:
    dataset_path = _DATASET_DIR / dataset_name
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    dataset = load_golden_dataset(dataset_path)
    logger.info(
        "Loaded %d questions from %s (schema=%s)",
        len(dataset.cases),
        dataset_name,
        dataset.schema_version,
    )
    return dataset.cases


def run_single_evaluation(
    question: str,
    expected_tools: List[str],
    expected_sources: List[str],
    criteria: List[str],
    thread_id: str = "eval",
    tenant_id: Optional[int] = None,
    user_id: Optional[int] = None,
    expected_intent: Optional[str] = None,
    expected_workflow: Optional[str] = None,
    expected_strategy: Optional[str] = None,
    expected_retrieval_ids: Optional[List[str]] = None,
    reference_claims: Optional[List[str]] = None,
) -> Dict[str, Any]:
    t0 = time.time()
    result = run_agent(
        question=question,
        thread_id=thread_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    duration = round(time.time() - t0, 3)
    intent_data = result.get("intent")
    workflow_data = result.get("workflow")
    execution_data = result.get("execution")
    intent = intent_data.get("intent") if isinstance(intent_data, dict) else intent_data
    workflow_type = workflow_data.get("type") if isinstance(workflow_data, dict) else workflow_data
    strategy = execution_data.get("strategy") if isinstance(execution_data, dict) else execution_data
    retrieved_ids = [
        source.get("chunk_id", "")
        for source in result.get("sources", [])
        if isinstance(source, dict)
    ]

    evaluation = evaluate_agent_response(
        answer=result.get("answer", ""),
        question=question,
        tools_used=result.get("tools_used", []),
        sources=result.get("sources", []),
        companies=result.get("companies", []),
        expected_tools=expected_tools,
        expected_sources=expected_sources,
        criteria=criteria,
        intent=intent,
        workflow_type=workflow_type,
        strategy=strategy,
        retrieved_ids=retrieved_ids,
        expected_intent=expected_intent,
        expected_workflow=expected_workflow,
        expected_strategy=expected_strategy,
        expected_retrieval_ids=expected_retrieval_ids,
        reference_claims=reference_claims,
    )

    return {
        "question": question,
        "answer": result.get("answer", ""),
        "tools_used": result.get("tools_used", []),
        "sources": result.get("sources", []),
        "companies": result.get("companies", []),
        "duration": duration,
        "evaluation": evaluation,
    }


def run_dataset_evaluation(
    dataset_name: str = "financial_qa.json",
    tenant_id: Optional[int] = None,
    user_id: Optional[int] = None,
    limit: Optional[int] = None,
    verbose: bool = False,
) -> Dict[str, Any]:
    dataset = load_dataset(dataset_name)

    if limit:
        dataset = dataset[:limit]
        logger.info(f"Limited to {limit} questions")

    results = []
    t0 = time.time()

    for i, item in enumerate(dataset):
        qid = item.get("id", f"q{i}")
        question = item["question"]
        expected_tools = item.get("expected_tools", [])
        expected_sources = item.get("expected_sources", [])
        criteria = item.get("criteria", [])

        logger.info(f"[{i+1}/{len(dataset)}] Evaluating: {qid}")

        try:
            single_result = run_single_evaluation(
                question=question,
                expected_tools=expected_tools,
                expected_sources=expected_sources,
                criteria=criteria,
                thread_id=f"eval_{qid}",
                tenant_id=tenant_id,
                user_id=user_id,
                expected_intent=item.get("expected_intent"),
                expected_workflow=item.get("expected_workflow"),
                expected_strategy=item.get("expected_strategy"),
                expected_retrieval_ids=item.get("expected_retrieval_ids", []),
                reference_claims=item.get("reference_claims", []),
            )
            single_result["id"] = qid
            results.append(single_result)

            if verbose:
                eval_result = single_result["evaluation"]
                logger.info(
                    f"  Score: {eval_result['score']} | "
                    f"Retrieval: {eval_result['retrieval_score']} | "
                    f"Tool: {eval_result['tool_score']} | "
                    f"Quality: {eval_result['quality_score']} | "
                    f"Hallucination: {eval_result['hallucination_score']}"
                )
        except Exception as e:
            logger.error(f"  FAILED: {qid} - {e}")
            results.append({
                "id": qid,
                "question": question,
                "answer": "",
                "tools_used": [],
                "sources": [],
                "companies": [],
                "duration": 0,
                "evaluation": {
                    "score": 0.0,
                    "retrieval_score": 0.0,
                    "tool_score": 0.0,
                    "quality_score": 0.0,
                    "hallucination_score": 0.0,
                    "issues": [{"type": "error", "severity": "critical", "message": str(e)}],
                    "passed": False,
                },
            })

    total_duration = round(time.time() - t0, 3)
    batch_result = evaluate_batch([r["evaluation"] for r in results])

    report = {
        "dataset": dataset_name,
        "total_questions": len(results),
        "duration": total_duration,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "passed": batch_result["passed"],
            "failed": batch_result["failed"],
            "average_score": batch_result["average_score"],
            "metric_averages": batch_result.get("metric_averages", {}),
        },
        "results": results,
    }

    return report


def save_report(report: Dict[str, Any], filename: str = None) -> Path:
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    if filename is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"eval_report_{timestamp}.json"

    report_path = _REPORTS_DIR / filename
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    logger.info(f"Report saved: {report_path}")
    return report_path
