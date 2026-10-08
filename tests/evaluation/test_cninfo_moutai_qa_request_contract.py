from evaluation.run_cninfo_moutai_10q_qa import _case_request_payload


def test_frontend_contract_omits_company_and_reuses_thread_for_followups():
    case = {
        "id": "MT-ZH-008",
        "question": "2025年直销和批发代理模式的收入分别是多少？各自同比如何变化？",
    }

    payload = _case_request_payload(case, "ui-thread", frontend_contract=True)

    assert payload == {
        "question": case["question"],
        "thread_id": "ui-thread",
        "answer_language": "zh-CN",
    }
    assert "company" not in payload


def test_frozen_evaluation_contract_keeps_explicit_company_and_isolated_thread():
    case = {"id": "MT-ZH-007", "question": "贵州茅台2025年国内收入是多少？"}

    payload = _case_request_payload(case, "run", frontend_contract=False)

    assert payload["company"] == "贵州茅台"
    assert payload["thread_id"] == "run-MT-ZH-007"
