import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from core.citation_formatter import format_citations


@pytest.mark.unit
class TestFormatCitations:
    def test_formats_single_citation(self):
        result = format_citations([
            {
                "rank": 1,
                "source": "apple.pdf",
                "chunk_id": "apple_0",
                "similarity": 0.95,
                "preview": "Revenue grew 10%.",
            },
        ])
        assert "Evidence References" in result
        assert "[Evidence 1]" in result
        assert "Source: apple.pdf" in result
        assert "Chunk: apple_0" in result
        assert "Confidence: 0.95" in result
        assert "Revenue grew 10%." in result

    def test_formats_multiple_citations(self):
        result = format_citations([
            {
                "rank": 1,
                "source": "apple.pdf",
                "chunk_id": "apple_0",
                "similarity": 0.95,
                "preview": "Apple revenue.",
            },
            {
                "rank": 2,
                "source": "tesla.pdf",
                "chunk_id": "tesla_0",
                "similarity": 0.90,
                "preview": "Tesla revenue.",
            },
        ])
        assert "[Evidence 1]" in result
        assert "[Evidence 2]" in result
        assert "Source: apple.pdf" in result
        assert "Source: tesla.pdf" in result

    def test_empty_citations_returns_header_only(self):
        result = format_citations([])
        assert "Evidence References" in result
        assert "[Evidence" not in result

    def test_returns_string(self):
        result = format_citations([
            {"rank": 1, "source": "test.pdf", "chunk_id": "t_0", "similarity": 0.5, "preview": "test"},
        ])
        assert isinstance(result, str)
