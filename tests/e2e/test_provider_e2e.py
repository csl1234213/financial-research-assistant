import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from core.core_engine import run_rag

pytestmark = pytest.mark.live

@pytest.mark.e2e
class TestProviderE2E:

    def test_deepseek_provider_returns_response(self):
        report, citations, context, mode, intent, evidence, plan, routing, planning, execution, workflow = run_rag(
            "Hello"
        )

        assert len(report) > 0
        assert "DEEPSEEK_API_KEY not set" not in report

    def test_routing_selects_deepseek(self):
        report, citations, context, mode, intent, evidence, plan, routing, planning, execution, workflow = run_rag(
            "Hello"
        )

        assert routing["provider"] == "deepseek"
        assert routing["model"] == "deepseek-v4-flash"

    def test_routing_has_confidence(self):
        report, citations, context, mode, intent, evidence, plan, routing, planning, execution, workflow = run_rag(
            "Hello"
        )

        assert "confidence" in routing
        assert routing["confidence"] > 0
