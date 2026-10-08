import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


from retrieval.retrieval_context import RetrievalContext


class TestRetrievalContext:
    def test_default_values(self):
        ctx = RetrievalContext(question="What is revenue?")
        assert ctx.question == "What is revenue?"
        assert ctx.company is None
        assert ctx.document_ids is None
        assert ctx.top_k == 5
        assert ctx.collection == "financial_reports"
        assert ctx.filters == {}

    def test_with_company(self):
        ctx = RetrievalContext(question="What is revenue?", company="Apple")
        assert ctx.company == "Apple"

    def test_with_document_ids(self):
        ctx = RetrievalContext(
            question="Revenue analysis",
            document_ids=["apple_q2_2026", "nvidia_q1_2027"],
        )
        assert ctx.document_ids == ["apple_q2_2026", "nvidia_q1_2027"]

    def test_with_top_k(self):
        ctx = RetrievalContext(question="Test", top_k=10)
        assert ctx.top_k == 10

    def test_with_collection(self):
        ctx = RetrievalContext(question="Test", collection="custom_reports")
        assert ctx.collection == "custom_reports"

    def test_with_filters(self):
        ctx = RetrievalContext(
            question="Test",
            filters={"year": "2025", "quarter": "Q2"},
        )
        assert ctx.filters == {"year": "2025", "quarter": "Q2"}

    def test_full_context(self):
        ctx = RetrievalContext(
            question="Compare Apple and NVIDIA revenue",
            company="Apple",
            document_ids=["apple_q2_2026"],
            top_k=8,
            collection="earnings",
            filters={"year": "2026"},
        )
        assert ctx.question == "Compare Apple and NVIDIA revenue"
        assert ctx.company == "Apple"
        assert ctx.document_ids == ["apple_q2_2026"]
        assert ctx.top_k == 8
        assert ctx.collection == "earnings"
        assert ctx.filters == {"year": "2026"}

    def test_immutability_pattern(self):
        ctx1 = RetrievalContext(question="Q1", top_k=3)
        ctx2 = RetrievalContext(question="Q1", top_k=5)
        assert ctx1.top_k == 3
        assert ctx2.top_k == 5
