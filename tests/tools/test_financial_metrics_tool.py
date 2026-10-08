from agent.tools import ToolContext, ToolEngine, ToolStatus


def test_growth_rate_is_calculated_deterministically():
    result = ToolEngine().execute(
        ToolContext(
            parameters={
                "operation": "growth_rate",
                "current": 125,
                "previous": 100,
                "precision": 2,
            }
        ),
        "financial_metrics",
    )

    assert result.status is ToolStatus.SUCCESS
    assert result.output == {
        "operation": "growth_rate",
        "value": 25.0,
        "unit": "percent",
        "precision": 2,
        "inputs": {"current": 125.0, "previous": 100.0},
    }
    assert result.metadata["deterministic"] is True


def test_margin_ratio_and_cagr_are_supported():
    engine = ToolEngine()

    margin = engine.execute(
        ToolContext(
            parameters={
                "operation": "margin",
                "numerator": 30,
                "denominator": 120,
            }
        ),
        "financial_metrics",
    )
    ratio = engine.execute(
        ToolContext(
            parameters={
                "operation": "ratio",
                "numerator": 150,
                "denominator": 100,
            }
        ),
        "financial_metrics",
    )
    cagr = engine.execute(
        ToolContext(
            parameters={
                "operation": "cagr",
                "starting_value": 100,
                "ending_value": 121,
                "periods": 2,
                "precision": 2,
            }
        ),
        "financial_metrics",
    )

    assert margin.output["value"] == 25.0
    assert ratio.output["value"] == 1.5
    assert cagr.output["value"] == 10.0


def test_invalid_or_unsafe_inputs_fail_closed():
    engine = ToolEngine()

    zero_denominator = engine.execute(
        ToolContext(
            parameters={
                "operation": "ratio",
                "numerator": 1,
                "denominator": 0,
            }
        ),
        "financial_metrics",
    )
    non_finite = engine.execute(
        ToolContext(
            parameters={
                "operation": "growth_rate",
                "current": float("inf"),
                "previous": 1,
            }
        ),
        "financial_metrics",
    )

    assert zero_denominator.status is ToolStatus.FAILED
    assert "non-zero" in zero_denominator.error
    assert non_finite.status is ToolStatus.FAILED
    assert "finite" in non_finite.error
