"""HTTP release wiring with explicit fixture ports; not Provider quality evidence."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers.grounded_answers import build_grounded_answer_router
from auth.dependencies import get_current_user
from core.answer_synthesis_budget import NarrativeTimeBudget
from core.answer_synthesis_semantic import EntailmentVerdict, semantic_input_digest
from tests.test_narrative_workflow import fixture_ports


@pytest.mark.parametrize("state", ["supported", "unsupported", "disabled", "review_error"])
def test_narrative_http_releases_only_reviewed_complete_answer(state):
    source, generator, reviewer, review = fixture_ports()
    item = source.evidence[0]
    item = replace(item, payload={**item.payload, "provenance": {
        **item.payload["provenance"], "content_sha256": "a" * 64},
        "source_locator": {"page": 52, "locator": "fixture:block-1"}})
    source = replace(source, evidence=(item,))
    buffered = generator.generate.return_value.buffered
    review = replace(review, input_digest=semantic_input_digest(source, buffered.plan, buffered.text))
    reviewer.review.return_value = review
    manifest = {"document_id": item.document_id,
                "source_sha256": item.payload["provenance"]["content_sha256"]}
    ledger = Mock()
    ledger.ready_index.return_value = manifest
    if state == "unsupported":
        reviewer.review.return_value = replace(review, claims=tuple(
            replace(claim, verdict=EntailmentVerdict.UNSUPPORTED) for claim in review.claims))
    elif state == "review_error":
        reviewer.review.side_effect = TimeoutError("private reviewer failure")
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(tenant_id=source.tenant_id, id=2)
    app.include_router(build_grounded_answer_router(ledger, source_resolver=lambda **_: source,
        narrative_generator=generator, semantic_reviewer=reviewer, narrative_enabled=state != "disabled",
        narrative_time_budget=NarrativeTimeBudget(total_seconds=300, per_call_seconds=45)))
    with TestClient(app) as client:
        response = client.post("/grounded-chat", json={"ingestion_job_id": "ready",
            "question": source.query, "answer_language": source.locale, "stream": True})
    if state == "supported":
        assert response.status_code == 200
        assert "event: delta" in response.text and "event: complete" in response.text
        assert '"verified": true' in response.text
        assert '"answer_tokens": 270' in response.text
        assert '"usage_complete": true' in response.text
        assert '"generation_calls": 1' in response.text
        assert '"reviewer_calls": 1' in response.text
        assert '"synthesis_latency":' in response.text
        assert '"verify_latency":' in response.text
        assert item.evidence_id in response.text
        assert generator.generate.call_count == reviewer.review.call_count == 1
        assert generator.generate.call_args.kwargs["max_seconds"] == 45
        assert reviewer.review.call_args.kwargs["max_seconds"] == 45
    else:
        assert response.status_code == 409
        assert response.json() == {"detail": "GROUNDED_ANSWER_NOT_AVAILABLE"}
        assert "event: delta" not in response.text
        assert "Revenue fell" not in response.text and "private reviewer" not in response.text
        if state == "disabled":
            generator.generate.assert_not_called()
            reviewer.review.assert_not_called()
        elif state == "unsupported":
            assert generator.generate.call_count == reviewer.review.call_count == 2
        else:
            assert generator.generate.call_count == reviewer.review.call_count == 1
