import json

import pytest

from training.dataset import (
    SUPERVISED_DATASET_SCHEMA_VERSION,
    TrainingDatasetValidationError,
    load_supervised_dataset,
    parse_supervised_dataset,
)


def _valid_dataset():
    return {
        "schema_version": SUPERVISED_DATASET_SCHEMA_VERSION,
        "dataset_id": "unit-training-dataset",
        "records": [
            {
                "id": "unit-record-001",
                "metadata": {"split": "train", "task": "unit_test"},
                "messages": [
                    {"role": "system", "content": "Give grounded answers."},
                    {"role": "user", "content": "Summarize the supplied evidence."},
                    {"role": "assistant", "content": "The evidence supports only the stated summary."},
                ],
            }
        ],
    }


def test_source_controlled_supervised_dataset_is_valid():
    dataset = load_supervised_dataset("training/datasets/financial_sft_v1.json")

    assert dataset.schema_version == SUPERVISED_DATASET_SCHEMA_VERSION
    assert dataset.dataset_id == "financial-sft-v1"
    assert len(dataset.records) == 3
    assert len(dataset.split("train")) == 2
    assert dataset.records[0].target
    assert "<|assistant|>" in dataset.records[0].format_for_causal_lm()


def test_dataset_rejects_invalid_conversation_order():
    raw = _valid_dataset()
    raw["records"][0]["messages"] = [
        {"role": "user", "content": "Question"},
        {"role": "user", "content": "Another question"},
        {"role": "assistant", "content": "Answer"},
    ]

    with pytest.raises(TrainingDatasetValidationError, match="alternate"):
        parse_supervised_dataset(raw)


@pytest.mark.parametrize(
    ("unsafe_text", "expected_label"),
    [
        ("Contact analyst@example.com for details.", "email address"),
        ("Use credential token=sk-abcdefghijklmnopqrstuvwxyz.", "OpenAI-style API key"),
        ("A customer identifier is 11010519491231002X.", "government identifier"),
        ("Card number 4111 1111 1111 1111 should be removed.", "payment card"),
    ],
)
def test_dataset_rejects_pii_and_secrets_without_echoing_values(unsafe_text, expected_label):
    raw = _valid_dataset()
    raw["records"][0]["messages"][1]["content"] = unsafe_text

    with pytest.raises(TrainingDatasetValidationError, match=expected_label) as exc_info:
        parse_supervised_dataset(raw)

    assert unsafe_text not in str(exc_info.value)


def test_dataset_rejects_unknown_fields_and_duplicate_ids():
    raw = _valid_dataset()
    raw["unexpected"] = True
    with pytest.raises(TrainingDatasetValidationError, match="unsupported fields"):
        parse_supervised_dataset(raw)

    raw = _valid_dataset()
    raw["records"].append(json.loads(json.dumps(raw["records"][0])))
    with pytest.raises(TrainingDatasetValidationError, match="Duplicate record id"):
        parse_supervised_dataset(raw)
