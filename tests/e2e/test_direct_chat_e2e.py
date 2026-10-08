import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from core.core_engine import run_rag

pytestmark = pytest.mark.live

@pytest.mark.e2e
class TestDirectChatE2E:

    def test_hello_routes_to_direct_chat(self):
        report, citations, context, mode, intent, evidence, plan, routing, planning, execution, workflow = run_rag(
            "Hello"
        )

        assert workflow["type"] == "direct_chat"
        assert execution["use_retrieval"] is False
        assert "# Research Report" not in report
        assert len(report) > 0

    def test_what_is_ai_routes_to_direct_chat(self):
        report, citations, context, mode, intent, evidence, plan, routing, planning, execution, workflow = run_rag(
            "What is AI?"
        )

        assert workflow["type"] == "direct_chat"
        assert execution["use_retrieval"] is False
        assert "# Research Report" not in report
        assert len(report) > 20

    def test_intent_is_direct_chat(self):
        report, citations, context, mode, intent, evidence, plan, routing, planning, execution, workflow = run_rag(
            "Hello"
        )

        assert intent["intent"] == "DIRECT_CHAT"

    def test_direct_chat_has_no_citations(self):
        report, citations, context, mode, intent, evidence, plan, routing, planning, execution, workflow = run_rag(
            "Explain Python"
        )

        assert len(citations) == 0
