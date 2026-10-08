import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from core.core_engine import refresh_knowledge_base, run_rag

pytestmark = pytest.mark.live

@pytest.mark.e2e
class TestRAGE2E:

    @pytest.fixture(autouse=True)
    def _ensure_knowledge_base(self):
        try:
            refresh_knowledge_base()
        except Exception:
            pytest.skip("Knowledge base not available (no PDFs or ChromaDB)")

    def test_tesla_revenue_routes_to_rag(self):
        report, citations, context, mode, intent, evidence, plan, routing, planning, execution, workflow = run_rag(
            "Analyze Tesla revenue growth"
        )

        assert workflow["type"] == "rag"
        assert len(citations) > 0
        assert "# Research Report" in report

    def test_tesla_risk_analysis_has_citations(self):
        report, citations, context, mode, intent, evidence, plan, routing, planning, execution, workflow = run_rag(
            "Tesla risk analysis"
        )

        assert workflow["type"] == "rag"
        assert len(citations) > 0
        assert len(report) > 50

    def test_intent_is_single_company(self):
        report, citations, context, mode, intent, evidence, plan, routing, planning, execution, workflow = run_rag(
            "Tesla risk analysis"
        )

        assert intent["intent"] == "SINGLE_COMPANY"
