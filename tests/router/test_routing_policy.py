import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from llm.router import RoutingPolicy
from llm.router.base_policy import BaseRoutingPolicy
from llm.router.routing_context import RoutingContext
from llm.router.routing_enums import TaskType
from llm.router.routing_result import RoutingResult


class _MockInnerPolicy(BaseRoutingPolicy):
    def __init__(self):
        self.calls = []

    def select(self, context, providers=None):
        self.calls.append((context, providers))
        return RoutingResult(
            provider="deepseek",
            model="deepseek-v4-flash",
            reason="test",
            confidence=0.9,
        )


class TestRoutingPolicy:

    @pytest.fixture
    def context(self):
        return RoutingContext(task=TaskType.CHAT)

    def test_delegates_to_inner_policy(self, context):
        inner = _MockInnerPolicy()

        policy = RoutingPolicy(inner)
        result = policy.select(context)

        assert isinstance(result, RoutingResult)
        assert result.provider == "deepseek"
        assert len(inner.calls) == 1
        assert inner.calls[0][0] is context
        assert inner.calls[0][1] is None

    def test_delegates_providers_to_inner_policy(self, context):
        inner = _MockInnerPolicy()

        policy = RoutingPolicy(inner)
        result = policy.select(context, providers=["deepseek", "gemini"])

        assert isinstance(result, RoutingResult)
        assert result.provider == "deepseek"
        assert len(inner.calls) == 1
        assert inner.calls[0][0] is context
        assert inner.calls[0][1] == ["deepseek", "gemini"]
