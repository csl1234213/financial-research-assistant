from evaluation.p1_quality import _failure_layer, _numeric_tokens


def test_numeric_gate_ignores_citation_labels_and_years():
    assert _numeric_tokens("Evidence 1; Q2 2025; revenue $81.6B; margin 74.9%") == {
        "81.6",
        "74.9%",
    }


def test_failure_diff_classifies_empty_current_retrieval():
    old = {"citations": [{"chunk_id": "a"}], "error": None}
    new = {"citations": [], "error": None}
    assert _failure_layer(old, new, ["Tesla_Q2_2025.pdf"]) == "RETRIEVAL_RECALL"
