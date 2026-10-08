import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from core.research_analyzer import analyze_evidence


@pytest.mark.unit
class TestAnalyzeEvidence:
    def test_counts_single_source(self):
        result = analyze_evidence([
            {"source": "apple.pdf", "chunk_id": "a_0"},
            {"source": "apple.pdf", "chunk_id": "a_1"},
            {"source": "apple.pdf", "chunk_id": "a_2"},
        ])
        assert result == {"apple.pdf": 3}

    def test_counts_multiple_sources(self):
        result = analyze_evidence([
            {"source": "apple.pdf", "chunk_id": "a_0"},
            {"source": "tesla.pdf", "chunk_id": "t_0"},
            {"source": "apple.pdf", "chunk_id": "a_1"},
        ])
        assert result == {"apple.pdf": 2, "tesla.pdf": 1}

    def test_empty_citations_returns_empty_dict(self):
        result = analyze_evidence([])
        assert result == {}

    def test_returns_dict(self):
        result = analyze_evidence([
            {"source": "test.pdf", "chunk_id": "t_0"},
        ])
        assert isinstance(result, dict)
