from copy import deepcopy

from evaluation.live_100 import smoke_passed


def successful_smoke():
    record = {
        "status_code": 200,
        "actual_answer": "Grounded answer",
        "category": "single_company",
        "citations": [{"source": "public.pdf"}],
        "response": {
            "execution": {"strategy": "rag", "use_retrieval": True},
            "reasoning": {"evidence_count": 1},
        },
    }
    return [deepcopy(record) for _ in range(5)]


def test_valid_rag_smoke_passes():
    assert smoke_passed(successful_smoke())


def test_http_200_direct_llm_is_not_rag_success():
    records = successful_smoke()
    records[0]["response"]["execution"] = {
        "strategy": "direct_llm",
        "use_retrieval": False,
    }
    assert not smoke_passed(records)


def test_missing_citations_fail_closed():
    records = successful_smoke()
    records[0]["citations"] = []
    assert not smoke_passed(records)


def test_incomplete_smoke_cannot_start_100_questions():
    assert not smoke_passed(successful_smoke()[:4])


def test_direct_chat_requires_no_financial_citations():
    records = successful_smoke()
    records[0]["category"] = "direct_chat"
    records[0]["response"]["execution"] = {
        "strategy": "direct_llm",
        "use_retrieval": False,
    }
    records[0]["citations"] = []
    assert smoke_passed(records)
    records[0]["citations"] = [{"source": "irrelevant.pdf"}]
    assert not smoke_passed(records)


def test_failed_request_cannot_pass_smoke():
    records = successful_smoke()
    records[0]["status_code"] = 429
    assert not smoke_passed(records)
