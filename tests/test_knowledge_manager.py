import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from core.knowledge_manager import (
    get_company_list,
    get_document_count,
    get_documents,
    get_sources,
    get_statistics,
    refresh_registry,
)
from core.knowledge_models import KnowledgeSource, KnowledgeStatistics


@pytest.mark.unit
class TestGetDocuments:
    def test_pdf_dir_not_exists(self):
        with patch("core.knowledge_manager.PDF_DIR") as mock_dir:
            mock_dir.exists.return_value = False
            result = get_documents()
            assert result == []

    def test_pdf_dir_empty(self):
        with patch("core.knowledge_manager.PDF_DIR") as mock_dir:
            mock_dir.exists.return_value = True
            mock_dir.glob.return_value = []
            result = get_documents()
            assert result == []

    def test_pdf_dir_with_files(self):
        with patch("core.knowledge_manager.PDF_DIR") as mock_dir:
            mock_dir.exists.return_value = True
            mock_pdf = MagicMock()
            mock_pdf.name = "Tesla_Q2_2025.pdf"
            mock_dir.glob.return_value = [mock_pdf]
            result = get_documents()
            assert result == ["Tesla_Q2_2025.pdf"]


@pytest.mark.unit
class TestGetDocumentCount:
    def test_returns_count(self):
        with patch("core.knowledge_manager.get_documents") as mock_get:
            mock_get.return_value = ["a.pdf", "b.pdf", "c.pdf"]
            result = get_document_count()
            assert result == 3

    def test_returns_zero_when_empty(self):
        with patch("core.knowledge_manager.get_documents") as mock_get:
            mock_get.return_value = []
            result = get_document_count()
            assert result == 0


@pytest.mark.unit
class TestRefreshRegistry:
    def test_refresh_returns_documents(self):
        with patch("core.knowledge_manager.get_documents") as mock_get:
            mock_get.return_value = ["a.pdf", "b.pdf"]
            result = refresh_registry()
            assert result == ["a.pdf", "b.pdf"]


@pytest.mark.unit
class TestGetCompanyList:
    def test_single_company(self):
        with patch("core.knowledge_manager.PDF_DIR") as mock_dir:
            mock_pdf = MagicMock()
            mock_pdf.name = "Tesla_Q2_2025.pdf"
            mock_dir.glob.return_value = [mock_pdf]
            with patch("core.knowledge_manager.get_company") as mock_company:
                mock_company.return_value = "Tesla"
                result = get_company_list()
                assert result == ["Tesla"]

    def test_multiple_companies_sorted(self):
        with patch("core.knowledge_manager.PDF_DIR") as mock_dir:
            mock_pdf1 = MagicMock()
            mock_pdf1.name = "Tesla.pdf"
            mock_pdf2 = MagicMock()
            mock_pdf2.name = "Apple.pdf"
            mock_dir.glob.return_value = [mock_pdf1, mock_pdf2]
            with patch("core.knowledge_manager.get_company") as mock_company:
                mock_company.side_effect = ["Tesla", "Apple"]
                result = get_company_list()
                assert result == ["Apple", "Tesla"]

    def test_empty_dir(self):
        with patch("core.knowledge_manager.PDF_DIR") as mock_dir:
            mock_dir.glob.return_value = []
            result = get_company_list()
            assert result == []


@pytest.mark.unit
class TestGetSources:
    def test_single_source(self):
        with patch("core.knowledge_manager.PDF_DIR") as mock_dir:
            mock_pdf = MagicMock()
            mock_pdf.name = "Tesla_Q2_2025.pdf"
            mock_pdf.stem = "Tesla_Q2_2025"
            mock_dir.glob.return_value = [mock_pdf]
            with patch("core.knowledge_manager.get_company") as mock_company:
                mock_company.return_value = "Tesla"
                result = get_sources()
                assert len(result) == 1
                assert isinstance(result[0], KnowledgeSource)
                assert result[0].company == "Tesla"
                assert result[0].filename == "Tesla_Q2_2025.pdf"
                assert result[0].period == "Q2_2025"
                assert result[0].report_type == "Financial Report"

    def test_source_no_period(self):
        with patch("core.knowledge_manager.PDF_DIR") as mock_dir:
            mock_pdf = MagicMock()
            mock_pdf.name = "Tesla.pdf"
            mock_pdf.stem = "Tesla"
            mock_dir.glob.return_value = [mock_pdf]
            with patch("core.knowledge_manager.get_company") as mock_company:
                mock_company.return_value = "Tesla"
                result = get_sources()
                assert result[0].period == "Unknown"

    def test_source_document_id_format(self):
        with patch("core.knowledge_manager.PDF_DIR") as mock_dir:
            mock_pdf = MagicMock()
            mock_pdf.name = "Tesla_Q2_2025.pdf"
            mock_pdf.stem = "Tesla_Q2_2025"
            mock_dir.glob.return_value = [mock_pdf]
            with patch("core.knowledge_manager.get_company") as mock_company:
                mock_company.return_value = "Tesla"
                result = get_sources()
                assert result[0].document_id == "tesla_q2_2025"

    def test_multiple_sources(self):
        with patch("core.knowledge_manager.PDF_DIR") as mock_dir:
            mock_pdf1 = MagicMock()
            mock_pdf1.name = "Tesla.pdf"
            mock_pdf1.stem = "Tesla"
            mock_pdf2 = MagicMock()
            mock_pdf2.name = "Apple.pdf"
            mock_pdf2.stem = "Apple"
            mock_dir.glob.return_value = [mock_pdf1, mock_pdf2]
            with patch("core.knowledge_manager.get_company") as mock_company:
                mock_company.side_effect = ["Tesla", "Apple"]
                result = get_sources()
                assert len(result) == 2


@pytest.mark.unit
class TestGetStatistics:
    def test_returns_statistics(self):
        with patch("core.knowledge_manager.get_company_list") as mock_companies:
            mock_companies.return_value = ["Tesla", "Apple"]
            with patch("core.knowledge_manager.get_sources") as mock_sources:
                mock_sources.return_value = [
                    KnowledgeSource("t", "Tesla", "Financial Report", "Q2", "t.pdf"),
                    KnowledgeSource("a", "Apple", "Financial Report", "Q2", "a.pdf"),
                ]
                result = get_statistics([1, 2, 3])
                assert isinstance(result, KnowledgeStatistics)
                assert result.companies == 2
                assert result.reports == 2
                assert result.chunks == 3
