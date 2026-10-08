from agent.reasoning_models import Evidence
from core.fact_ledger import FactLedger
from core.required_fact_plan import RequiredFactSpec
from evaluation.current_source_retrieval_audit import _source_fact_for_spec
from evaluation.replay_historical_answers_current_retrieval import _projected_source_facts


def test_source_targets_and_replay_projection_preserve_margin_basis_identity():
    row = Evidence(
        content=(
            "For Q1 FY2027, GAAP and non-GAAP gross margins were "
            "74.9% and 75.0%, respectively."
        ),
        source="NVIDIA_sample.pdf",
        company="NVIDIA",
        metadata={"quarter": "Q1_FY2027", "chunk_id": "nvidia-q1-margin-pair"},
    )
    ledger = FactLedger.from_evidence([row])
    specs = {
        basis: RequiredFactSpec(
            "nvidia", "gross_margin", "Q1_FY2027", "regression", basis
        )
        for basis in ("gaap", "non_gaap")
    }
    facts = {
        basis: _source_fact_for_spec(spec, ledger, "NVIDIA Q1 FY2027 margins")
        for basis, spec in specs.items()
    }

    assert {basis: str(fact.normalized_value) for basis, fact in facts.items()} == {
        "gaap": "74.9",
        "non_gaap": "75.0",
    }

    targets = [
        {
            "key": spec.key,
            "company": spec.company,
            "metric_id": spec.metric_id,
            "period": spec.period,
            "accounting_basis": spec.accounting_basis,
            "normalized_value": str(facts[basis].normalized_value),
        }
        for basis, spec in specs.items()
    ]
    correct_answer = (
        "NVIDIA Q1 FY2027 GAAP gross margin was 74.9%.\n"
        "NVIDIA Q1 FY2027 non-GAAP gross margin was 75.0%."
    )
    assert _projected_source_facts(targets, correct_answer, ledger) == {
        specs["gaap"].key,
        specs["non_gaap"].key,
    }

    swapped_basis_answer = (
        "NVIDIA Q1 FY2027 GAAP gross margin was 75.0%.\n"
        "NVIDIA Q1 FY2027 non-GAAP gross margin was 74.9%."
    )
    assert _projected_source_facts(targets, swapped_basis_answer, ledger) == set()
