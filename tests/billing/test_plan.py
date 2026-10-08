import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


from billing.plans import (
    PLANS,
    get_plan_limits,
    get_plan_list,
    get_plan_price,
    is_enterprise,
)

PLAN_SLUGS = ["free", "pro", "enterprise"]


class TestPlanConfig:
    def test_all_plans_defined(self):
        for slug in PLAN_SLUGS:
            assert slug in PLANS, f"Plan {slug} should be defined"

    def test_free_plan_is_most_restrictive(self):
        free = get_plan_limits("free")
        pro = get_plan_limits("pro")
        ent = get_plan_limits("enterprise")

        assert free.agent_chats_per_month < pro.agent_chats_per_month
        assert free.max_tokens_per_request < pro.max_tokens_per_request
        assert free.max_documents < pro.max_documents

    def test_enterprise_has_unlimited_chats(self):
        ent = get_plan_limits("enterprise")
        assert ent.agent_chats_per_month == -1

    def test_pro_better_than_free(self):
        free = get_plan_limits("free")
        pro = get_plan_limits("pro")
        assert pro.agent_chats_per_month > free.agent_chats_per_month
        assert pro.max_tokens_per_request > free.max_tokens_per_request
        assert pro.max_documents > free.max_documents
        assert pro.priority_support is True
        assert free.priority_support is False

    def test_plan_list_returns_all_plans(self):
        plans = get_plan_list()
        assert len(plans) == 3
        slugs = [p["slug"] for p in plans]
        assert "free" in slugs
        assert "pro" in slugs
        assert "enterprise" in slugs

    def test_plan_list_has_required_fields(self):
        plans = get_plan_list()
        for plan in plans:
            assert "slug" in plan
            assert "name" in plan
            assert "price" in plan
            assert "limits" in plan
            assert "agent_chats_per_month" in plan["limits"]

    def test_plan_price_ordering(self):
        free_price = get_plan_price("free")
        pro_price = get_plan_price("pro")
        ent_price = get_plan_price("enterprise")
        assert free_price < pro_price < ent_price

    def test_is_enterprise_on_non_enterprise(self):
        assert is_enterprise("free") is False
        assert is_enterprise("pro") is False
        assert is_enterprise("enterprise") is True
