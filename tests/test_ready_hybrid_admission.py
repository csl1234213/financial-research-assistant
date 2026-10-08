from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from retrieval.hybrid_retriever import HybridRetriever
from retrieval.ingestion_ready_hybrid import IngestionReadyHybridRetriever


@pytest.mark.parametrize("mutation", ["owner", "version", "tenant", "count"])
def test_invalid_ready_corpus_never_invokes_hybrid_or_embedding(mutation):
    manifest = {"embedding_identity": "test", "collection": "only-admitted",
                "verified_chunk_count": 1, "document_id": 42, "source_sha256": "a" * 64}
    metadata = {"tenant_id": 1, "document_id": "42", "source_sha256": "a" * 64,
                "embedding_identity": "test"}
    ledger = Mock()
    ledger.ready_index.return_value = manifest
    ledger.ready_document_metadata.return_value = {"document_id": 42, "source_sha256": "a" * 64,
                                                   "filename": "report.pdf"}
    if mutation == "owner":
        ledger.ready_index.side_effect = PermissionError("wrong owner")
    elif mutation == "version":
        metadata["source_sha256"] = "b" * 64
    elif mutation == "tenant":
        metadata["tenant_id"] = True
    collection = SimpleNamespace(count=lambda: 2 if mutation == "count" else 1,
        get=lambda **_: {"ids": ["c1"], "documents": ["source text"], "metadatas": [metadata]})
    vectors = SimpleNamespace(client=SimpleNamespace(get_collection=lambda name: collection))
    hybrid = HybridRetriever()
    hybrid.retrieve = Mock()
    resolver = IngestionReadyHybridRetriever(ledger, vectors, embedding_identity="test",
                                             hybrid_retriever=hybrid)
    with pytest.raises((PermissionError, ValueError)):
        resolver.search_question_evidence("job", tenant_id=1, user_id=2, question="说明业务")
    hybrid.retrieve.assert_not_called()
