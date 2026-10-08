from collections import defaultdict
from typing import Dict, List

from agent.execution_result import ExecutionResult
from agent.reasoning_models import Evidence, ReasoningResult


class ReasoningEngine:
    """
    V3 Reasoning Engine

    Responsibilities:
    1. Aggregate execution outputs
    2. Convert outputs into structured Evidence
    3. Organize evidence by company
    4. Produce a structured ReasoningResult

    NOTE:
    This version is rule-based.
    Later versions can introduce LLM reasoning.
    """

    def analyze(self, results: List[ExecutionResult]) -> ReasoningResult:
        evidences = self._collect_evidence(results)

        facts = self._extract_facts(evidences)

        risks = self._extract_risks(evidences)

        opportunities = self._extract_opportunities(evidences)

        conclusion = self._build_conclusion(facts, risks, opportunities)

        return ReasoningResult(facts=facts, risks=risks, opportunities=opportunities, conclusion=conclusion)

    # =====================================================
    # Step 1
    # =====================================================

    def _collect_evidence(self, results: List[ExecutionResult]) -> List[Evidence]:
        evidences = []

        for result in results:
            if not result.success:
                continue

            output = result.output

            if output is None:
                continue

            if isinstance(output, list):
                for item in output:
                    if isinstance(item, Evidence):
                        evidences.append(item)

            elif isinstance(output, Evidence):
                evidences.append(output)

        return evidences

    # =====================================================
    # Step 2
    # =====================================================

    def _extract_facts(self, evidences: List[Evidence]) -> List[str]:
        facts = []

        for e in evidences:
            if "revenue" in e.content.lower():
                facts.append(e.content)

            elif "profit" in e.content.lower():
                facts.append(e.content)

            elif "margin" in e.content.lower():
                facts.append(e.content)

        return facts

    # =====================================================
    # Step 3
    # =====================================================

    def _extract_risks(self, evidences: List[Evidence]) -> List[str]:
        risks = []

        keywords = ["risk", "uncertain", "decline", "decrease", "weak", "challenge"]

        for e in evidences:
            text = e.content.lower()

            if any(k in text for k in keywords):
                risks.append(e.content)

        return risks

    # =====================================================
    # Step 4
    # =====================================================

    def _extract_opportunities(self, evidences: List[Evidence]) -> List[str]:
        opportunities = []

        keywords = ["growth", "increase", "expand", "strong", "guidance"]

        for e in evidences:
            text = e.content.lower()

            if any(k in text for k in keywords):
                opportunities.append(e.content)

        return opportunities

    # =====================================================
    # Step 5
    # =====================================================

    def _build_conclusion(self, facts: List[str], risks: List[str], opportunities: List[str]) -> str:
        return (
            f"Collected {len(facts)} financial facts, "
            f"{len(risks)} risk signals, "
            f"and {len(opportunities)} opportunity signals."
        )

    # =====================================================
    # Future Extension
    # =====================================================

    def group_by_company(self, evidences: List[Evidence]) -> Dict[str, List[Evidence]]:
        grouped = defaultdict(list)

        for evidence in evidences:
            grouped[evidence.company].append(evidence)

        return grouped
