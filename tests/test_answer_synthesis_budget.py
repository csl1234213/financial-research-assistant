import pytest

from core.answer_synthesis_budget import NarrativeTimeBudget


@pytest.mark.parametrize("total,per_call", [
    (True, 120), (float("nan"), 120), (float("inf"), 120),
    (0, 120), (601, 120), ("240", 120), (240, False),
])
def test_invalid_time_policy_is_rejected(total, per_call):
    with pytest.raises(ValueError, match="INVALID_NARRATIVE_TIME_BUDGET"):
        NarrativeTimeBudget(total, per_call)


def test_provider_owns_default_per_call_timeout():
    budget = NarrativeTimeBudget(total_seconds=240)
    assert budget.allowance(deadline=240, now=0) == 240
    assert budget.allowance(deadline=240, now=200) == 40
    assert budget.allowance(deadline=240, now=241) == 0
    assert NarrativeTimeBudget().total_seconds == 120
    assert NarrativeTimeBudget(300, 240).allowance(deadline=300, now=0) == 240


@pytest.mark.parametrize("now", [True, float("inf"), float("nan"), "0"])
def test_invalid_clock_values_are_not_allowed(now):
    with pytest.raises(ValueError, match="INVALID_NARRATIVE_CLOCK"):
        NarrativeTimeBudget().allowance(deadline=120, now=now)
