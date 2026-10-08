import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from evaluation.runner import load_dataset


class TestDatasetLoader:
    def test_load_dataset_returns_list(self):
        data = load_dataset("financial_qa.json")
        assert isinstance(data, list)
        assert len(data) > 0

    def test_dataset_has_required_fields(self):
        data = load_dataset("financial_qa.json")
        required_fields = {"id", "question", "expected_tools", "expected_sources", "criteria"}

        for item in data:
            missing = required_fields - set(item.keys())
            assert not missing, f"Item {item.get('id', '?')} missing fields: {missing}"

    def test_dataset_has_at_least_20_questions(self):
        data = load_dataset("financial_qa.json")
        assert len(data) >= 20, f"Expected at least 20 questions, got {len(data)}"

    def test_dataset_questions_are_non_empty(self):
        data = load_dataset("financial_qa.json")
        for item in data:
            assert item["question"].strip(), f"Item {item.get('id', '?')} has empty question"

    def test_dataset_ids_are_unique(self):
        data = load_dataset("financial_qa.json")
        ids = [item["id"] for item in data]
        assert len(ids) == len(set(ids)), "Duplicate IDs found in dataset"

    def test_dataset_covers_categories(self):
        data = load_dataset("financial_qa.json")
        categories = set()
        for item in data:
            for criterion in item.get("criteria", []):
                if "growth" in criterion or "revenue" in criterion:
                    categories.add("financial_analysis")
                if "risk" in criterion or "debt" in criterion or "volatility" in criterion:
                    categories.add("risk_analysis")
                if "valuation" in criterion or "ratio" in criterion or "pe_" in criterion:
                    categories.add("valuation_analysis")
                if "error" in criterion or "hallucination" in criterion:
                    categories.add("error_handling")

        assert "financial_analysis" in categories, "Missing financial analysis category"
        assert "risk_analysis" in categories, "Missing risk analysis category"
        assert "error_handling" in categories, "Missing error handling test case"

    def test_dataset_has_nonexistent_company_test(self):
        data = load_dataset("financial_qa.json")
        nonexistent = [item for item in data if "不存在的" in item["question"] or "XYZ" in item["question"]]
        assert len(nonexistent) >= 1, "Missing nonexistent company test case"

    def test_load_nonexistent_dataset_raises(self):
        with pytest.raises(FileNotFoundError):
            load_dataset("nonexistent_dataset.json")

    def test_expected_tools_are_valid(self):
        data = load_dataset("financial_qa.json")
        valid_tools = {"search", "financial_analysis", "risk_analysis", "valuation_analysis"}

        for item in data:
            for tool in item.get("expected_tools", []):
                assert tool in valid_tools, f"Unknown tool '{tool}' in {item['id']}"
