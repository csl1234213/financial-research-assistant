"""Typed source authority uses real P1.3 rows, never invented block ids."""

import copy
import json
from dataclasses import asdict, replace

import pytest

from core.financial_facts import FinancialFactFactory
from services.financial_fact_provenance import bind_table_rows, canonical_json, validate_table_row
from tests.test_financial_facts import CONTEXT, _eligible_row, moutai_rows  # noqa: F401


@pytest.fixture
def provenance_case(moutai_rows):  # noqa: F811
    row, _ = _eligible_row(moutai_rows, "资产总计", "balance_sheet")
    row = replace(row, document_id="7", source="a" * 64)
    fact = json.loads(canonical_json(asdict(FinancialFactFactory().create(row, context=CONTEXT))))
    payload = {"tenant_id": 1, "document_id": 7, "source_sha256": "a" * 64,
        "parse_artifact_sha256": "b" * 64, "facts": [fact]}
    parsed = {"schema": "financial-ingestion-parse.v1", "tenant_id": 1, "document_id": 7,
        "source_sha256": "a" * 64, "chunks": [{"financial_table_rows": [asdict(row)]}]}
    return payload, parsed


def test_real_row_binding_stable_after_json_reload(provenance_case):
    payload, parsed = provenance_case
    bound = bind_table_rows(payload, parsed, context=CONTEXT)["facts"][0]
    loaded = bind_table_rows(json.loads(canonical_json(payload)), json.loads(canonical_json(parsed)),
                            context=CONTEXT)["facts"][0]
    assert bound == loaded
    proof = validate_table_row(bound, tenant_id=1, document_id=7, source_sha256="a" * 64)
    assert proof["page"] == 57 and proof["row_id"] == "43"
    assert proof["source_region"] and proof["row_digest"]
    assert "source_block_ids" not in proof


@pytest.mark.parametrize("field,value", [("document_id", "8"), ("document_version", "e" * 64),
    ("source_sha256", "e" * 64), ("table_id", "wrong-table"), ("row_id", "99"),
    ("page", 99), ("row_digest", "e" * 64)])
def test_wrong_typed_identity_rejected(provenance_case, field, value):
    payload, parsed = provenance_case
    fact = bind_table_rows(payload, parsed, context=CONTEXT)["facts"][0]
    fact["table_row_provenance"][field] = value
    with pytest.raises(ValueError, match="VERIFIED_TABLE_ROW_PROVENANCE_INVALID"):
        validate_table_row(fact, tenant_id=1, document_id=7, source_sha256="a" * 64)


def test_missing_proof_rejected(provenance_case):
    fact = provenance_case[0]["facts"][0]
    with pytest.raises(ValueError, match="VERIFIED_TABLE_ROW_PROVENANCE_REQUIRED"):
        validate_table_row(fact, tenant_id=1, document_id=7, source_sha256="a" * 64)


@pytest.mark.parametrize("field,value", [("normalized_value", "1"), ("table_id", "wrong"),
    ("row_id", "99"), ("page", 99), ("source_text", "tampered")])
def test_artifact_fact_cannot_replace_its_source_row(provenance_case, field, value):
    payload, parsed = copy.deepcopy(provenance_case)
    payload["facts"][0][field] = value
    with pytest.raises(ValueError, match="UNIQUE_VERIFIED_FACT_ROW_REQUIRED"):
        bind_table_rows(payload, parsed, context=CONTEXT)
