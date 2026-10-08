import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from unittest.mock import MagicMock

import pytest

from agent.reasoning_models import Evidence
from core.context_builder import build_context, build_context_from_evidence


@pytest.mark.unit
class TestBuildContext:
    def test_build_context_empty(self):
        result = MagicMock()
        result.chunks = []
        result.scores = []
        result.top_k = []

        context, citations = build_context(result, "test question")

        assert context == ""
        assert citations == []

    def _make_score(self, value):
        m = MagicMock()
        m.item.return_value = value
        return m

    def test_build_context_single_chunk(self):
        result = MagicMock()
        result.chunks = [
            {"text": "Revenue grew 10%.", "source": "apple.pdf", "chunk_id": "apple_0"}
        ]
        result.scores = [self._make_score(0.95)]
        result.top_k = [0]

        context, citations = build_context(result, "test question")

        assert len(citations) == 1
        assert citations[0]["rank"] == 1
        assert citations[0]["source"] == "apple.pdf"
        assert citations[0]["chunk_id"] == "apple_0"
        assert citations[0]["similarity"] == 0.95
        assert "Revenue grew 10%." in citations[0]["preview"]
        assert "[Evidence 1]" in context
        assert "Source: apple.pdf" in context

    def test_build_context_out_of_range_index_skipped(self):
        result = MagicMock()
        result.chunks = [
            {"text": "Revenue grew 10%.", "source": "apple.pdf", "chunk_id": "apple_0"}
        ]
        result.scores = [self._make_score(0.95)]
        result.top_k = [99]

        context, citations = build_context(result, "test question")

        assert citations == []
        assert context == ""

    def test_build_context_multiple_chunks(self):
        result = MagicMock()
        result.chunks = [
            {"text": "Apple revenue.", "source": "apple.pdf", "chunk_id": "apple_0"},
            {"text": "Tesla revenue.", "source": "tesla.pdf", "chunk_id": "tesla_0"},
        ]
        result.top_k = [0, 1]
        result.scores = [self._make_score(0.95), self._make_score(0.90)]

        context, citations = build_context(result, "test question")

        assert len(citations) == 2
        assert citations[0]["rank"] == 1
        assert citations[0]["source"] == "apple.pdf"
        assert citations[1]["rank"] == 2
        assert citations[1]["source"] == "tesla.pdf"
        assert "[Evidence 1]" in context
        assert "[Evidence 2]" in context

    def test_build_context_missing_score(self):
        result = MagicMock()
        result.chunks = [
            {"text": "Revenue grew.", "source": "apple.pdf", "chunk_id": "apple_0"}
        ]
        result.scores = []
        result.top_k = [0]

        context, citations = build_context(result, "test question")

        assert citations[0]["similarity"] == 0.0


@pytest.mark.unit
class TestBuildContextFromEvidence:
    def test_build_from_evidence_empty(self):
        context, citations = build_context_from_evidence([])

        assert context == ""
        assert citations == []

    def test_build_from_evidence_single(self):
        ev = Evidence(
            content="Revenue grew 10%.",
            source="apple.pdf",
            company="Apple",
            confidence=0.95,
            metadata={"chunk_id": "apple_0"},
        )

        context, citations = build_context_from_evidence([ev])

        assert len(citations) == 1
        assert citations[0]["rank"] == 1
        assert citations[0]["source"] == "apple.pdf"
        assert citations[0]["chunk_id"] == "apple_0"
        assert citations[0]["similarity"] == 0.95
        assert citations[0]["preview"] == "Revenue grew 10%."
        assert "[Evidence 1]" in context
        assert "Source: apple.pdf" in context

    def test_build_from_evidence_multiple(self):
        ev1 = Evidence(
            content="Apple Q2 revenue.",
            source="apple.pdf",
            confidence=0.95,
            metadata={"chunk_id": "apple_0"},
        )
        ev2 = Evidence(
            content="Tesla Q2 revenue.",
            source="tesla.pdf",
            confidence=0.90,
            metadata={"chunk_id": "tesla_0"},
        )

        context, citations = build_context_from_evidence([ev1, ev2])

        assert len(citations) == 2
        assert citations[0]["rank"] == 1
        assert citations[0]["source"] == "apple.pdf"
        assert citations[1]["rank"] == 2
        assert citations[1]["source"] == "tesla.pdf"
        assert "[Evidence 1]" in context
        assert "[Evidence 2]" in context

    def test_build_from_evidence_no_metadata(self):
        ev = Evidence(
            content="Revenue data.",
            source="apple.pdf",
            confidence=0.85,
        )

        context, citations = build_context_from_evidence([ev])

        assert citations[0]["chunk_id"] == ""
        assert citations[0]["similarity"] == 0.85

    def test_build_from_evidence_preview_truncation(self):
        ev = Evidence(
            content="A" * 200,
            source="apple.pdf",
            confidence=0.80,
        )

        context, citations = build_context_from_evidence([ev])

        assert len(citations[0]["preview"]) == 150

    def test_build_from_evidence_preserves_document_provenance(self):
        ev = Evidence(
            content="OCR recovered revenue evidence.",
            source="tesla-scan.pdf",
            confidence=0.88,
            metadata={
                "chunk_id": "tesla-scan-1",
                "page": 4,
                "section": "Revenue",
                "ocr_used": True,
                "parser_version": "pymupdf-blocks-ocr-v1",
                "chunker_version": "page-block-section-v2",
            },
        )

        _, citations = build_context_from_evidence([ev])

        assert citations[0]["page"] == 4
        assert citations[0]["section"] == "Revenue"
        assert citations[0]["ocr_used"] is True
        assert citations[0]["parser_version"] == "pymupdf-blocks-ocr-v1"
        assert citations[0]["chunker_version"] == "page-block-section-v2"
