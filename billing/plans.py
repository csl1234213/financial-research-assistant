from dataclasses import dataclass
from typing import Dict


@dataclass
class PlanLimits:
    agent_chats_per_month: int = 50
    max_tokens_per_request: int = 4096
    max_documents: int = 10
    max_chats_per_day: int = 50
    max_embeddings: int = 1000
    priority_support: bool = False
    custom_tools: bool = False


PLANS: Dict[str, PlanLimits] = {
    "free": PlanLimits(
        agent_chats_per_month=50,
        max_tokens_per_request=4096,
        max_documents=10,
        max_chats_per_day=50,
        max_embeddings=1000,
        priority_support=False,
        custom_tools=False,
    ),
    "pro": PlanLimits(
        agent_chats_per_month=2000,
        max_tokens_per_request=16384,
        max_documents=100,
        max_chats_per_day=500,
        max_embeddings=10000,
        priority_support=True,
        custom_tools=False,
    ),
    "enterprise": PlanLimits(
        agent_chats_per_month=-1,
        max_tokens_per_request=32768,
        max_documents=1000,
        max_chats_per_day=5000,
        max_embeddings=100000,
        priority_support=True,
        custom_tools=True,
    ),
}

PLAN_PRICES: Dict[str, float] = {
    "free": 0.0,
    "pro": 29.99,
    "enterprise": 99.99,
}

TOKEN_PRICE_PER_1K_INPUT = 0.0015
TOKEN_PRICE_PER_1K_OUTPUT = 0.006
TOOL_CALL_PRICE = 0.001


def get_plan_limits(plan_slug: str) -> PlanLimits:
    return PLANS.get(plan_slug, PLANS["free"])


def get_plan_price(plan_slug: str) -> float:
    return PLAN_PRICES.get(plan_slug, 0.0)


def is_enterprise(plan_slug: str) -> bool:
    limits = get_plan_limits(plan_slug)
    return limits.agent_chats_per_month == -1


def get_plan_list() -> list:
    return [
        {
            "slug": slug,
            "name": slug.capitalize(),
            "price": PLAN_PRICES.get(slug, 0.0),
            "limits": {
                "agent_chats_per_month": limits.agent_chats_per_month,
                "max_tokens_per_request": limits.max_tokens_per_request,
                "max_documents": limits.max_documents,
                "max_chats_per_day": limits.max_chats_per_day,
                "max_embeddings": limits.max_embeddings,
                "priority_support": limits.priority_support,
                "custom_tools": limits.custom_tools,
            },
        }
        for slug, limits in PLANS.items()
    ]
