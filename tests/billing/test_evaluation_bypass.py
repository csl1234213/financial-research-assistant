import pytest

from services import plan_service


class TestEvaluationPlanLimitBypass:
    @pytest.mark.parametrize("value", [None, "true", "1", "yes", "on", "bad"])
    def test_chat_limits_default_to_enabled(self, monkeypatch, value):
        if value is None:
            monkeypatch.delenv("CHAT_PLAN_LIMITS_ENABLED", raising=False)
        else:
            monkeypatch.setenv("CHAT_PLAN_LIMITS_ENABLED", value)
        assert plan_service.chat_plan_limits_enabled() is True

    @pytest.mark.parametrize("value", ["false", "0", "no", "off"])
    def test_chat_limits_can_be_disabled_explicitly(self, monkeypatch, value):
        monkeypatch.setenv("CHAT_PLAN_LIMITS_ENABLED", value)
        assert plan_service.chat_plan_limits_enabled() is False

    def test_missing_configuration_is_disabled(self, monkeypatch):
        monkeypatch.delenv("EVALUATION_BYPASS_PLAN_LIMITS", raising=False)
        monkeypatch.delenv("EVALUATION_BYPASS_TENANT_IDS", raising=False)
        assert plan_service.should_bypass_plan_limit(7) is False

    def test_allowlisted_tenant_bypasses_when_enabled(self, monkeypatch):
        monkeypatch.setenv("EVALUATION_BYPASS_PLAN_LIMITS", "yes")
        monkeypatch.setenv("EVALUATION_BYPASS_TENANT_IDS", "7, 8")
        assert plan_service.should_bypass_plan_limit(7) is True
        assert plan_service.should_bypass_plan_limit(9) is False

    @pytest.mark.parametrize("value", ["false", "0", "no", "off", ""])
    def test_false_values_disable_bypass(self, monkeypatch, value):
        monkeypatch.setenv("EVALUATION_BYPASS_PLAN_LIMITS", value)
        monkeypatch.setenv("EVALUATION_BYPASS_TENANT_IDS", "7")
        assert plan_service.should_bypass_plan_limit(7) is False

    def test_invalid_tenant_ids_are_ignored(self, monkeypatch):
        monkeypatch.setenv("EVALUATION_BYPASS_PLAN_LIMITS", "true")
        monkeypatch.setenv("EVALUATION_BYPASS_TENANT_IDS", "bad, 7x, 12")
        assert plan_service.should_bypass_plan_limit(12) is True
        assert plan_service.should_bypass_plan_limit(7) is False

    def test_can_chat_bypass_does_not_change_usage_recording(self, monkeypatch):
        monkeypatch.setenv("EVALUATION_BYPASS_PLAN_LIMITS", "true")
        monkeypatch.setenv("EVALUATION_BYPASS_TENANT_IDS", "7")
        called = {"value": False}

        def unexpected_limit_check(*args, **kwargs):
            called["value"] = True
            return False

        monkeypatch.setattr(plan_service, "check_plan_limit", unexpected_limit_check)
        assert plan_service.can_chat(object(), 7) is True
        assert called["value"] is False
