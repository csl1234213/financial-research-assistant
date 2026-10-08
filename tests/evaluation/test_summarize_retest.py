"""Rerun reporting must retain failures and unknown costs."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from evaluation.summarize_retest import apply_citation_override, percentile, scope_metrics, summarize


class TestRerunMetrics(unittest.TestCase):
    def test_manual_override_does_not_turn_unused_context_into_a_cited_claim(self):
        self.assertEqual(
            apply_citation_override("UNUSED_RETRIEVED_CONTEXT", 2, [2]),
            "UNUSED_RETRIEVED_CONTEXT",
        )
        self.assertEqual(apply_citation_override("VALID_BUT_NOT_SUPPORTED", 2, [2]), "VALID_SUPPORTED")

    def test_failure_is_in_strict_denominator_and_latency(self):
        rows = [
            {"answer_grade": "CORRECT", "latency_ms": 100, "estimated_cost_usd": 0.01},
            {"answer_grade": "FAILED", "latency_ms": 10, "estimated_cost_usd": None},
        ]
        result = scope_metrics(rows)
        self.assertEqual(result["correct_over_valid"], 1)
        self.assertEqual(result["strict_correct_over_requested"], 0.5)
        self.assertEqual(result["latency_ms"]["mean"], 55)
        self.assertIsNone(result["full_list_price_cost_usd"])
        self.assertEqual(result["unknown_cost_queries"], 1)

    def test_unknown_grade_is_not_silently_correct_or_failed(self):
        rows = [
            {"answer_grade": "CORRECT", "latency_ms": 10, "estimated_cost_usd": 0},
            {
                "answer_grade": "UNKNOWN_REVIEW_FAILED",
                "latency_ms": 20,
                "estimated_cost_usd": 0,
            },
        ]
        result = scope_metrics(rows)
        self.assertEqual(result["valid_completed"], 2)
        self.assertEqual(result["correct_over_valid"], 0.5)
        self.assertEqual(result["grades"]["UNKNOWN_REVIEW_FAILED"], 1)

    def test_percentile_uses_linear_interpolation(self):
        self.assertEqual(percentile([100, 10], 50), 55)
        self.assertEqual(percentile([100, 10], 90), 91)

    def test_incomplete_run_fails_before_report_generation(self):
        with TemporaryDirectory(prefix="financial-rag-report-test-") as directory:
            root = Path(directory)
            (root / "evaluation_100_results.jsonl").write_text("", encoding="utf-8")
            (root / "dataset.json").write_text("[]", encoding="utf-8")
            (root / "dataset_freeze.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "100 unique real requests"):
                summarize(root)
            self.assertFalse((root / "report.md").exists())
            self.assertFalse((root / "evaluation_100_summary.json").exists())


if __name__ == "__main__":
    unittest.main()
