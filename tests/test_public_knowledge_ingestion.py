from unittest.mock import Mock

import core.core_engine as core_engine


def test_public_refresh_batches_passages_and_preserves_ingestion_profile(
    monkeypatch,
):
    content_sha256 = "b" * 64
    chunks = [
        {
            "source": "Tesla_Q2_2025.pdf",
            "chunk_id": 0,
            "company": "Tesla",
            "quarter": "Q2_2025",
            "document_id": "tesla_q2_2025",
            "text": "Tesla automotive revenue increased.",
            "page": 4,
            "section": "Revenue",
            "ocr_used": False,
            "parser_version": "pymupdf-blocks-ocr-v1",
            "chunker_version": "page-block-section-v2",
            "content_sha256": content_sha256,
        }
    ]
    monkeypatch.setattr(core_engine, "load_documents", lambda _folder: chunks)

    model = Mock()
    model.encode.return_value = [[0.1, 0.2, 0.3]]
    monkeypatch.setattr(core_engine, "_get_model", lambda: model)

    store = Mock()
    monkeypatch.setattr(core_engine, "_get_store", lambda: store)

    core_engine.refresh_knowledge_base()

    encode_call = model.encode.call_args
    assert encode_call.args[0] == [
        "passage: Tesla automotive revenue increased."
    ]
    assert encode_call.kwargs["normalize_embeddings"] is True
    assert encode_call.kwargs["batch_size"] > 0

    inserted = store.add_documents.call_args.args[0]
    assert len(inserted) == 1
    vector_document = inserted[0]
    assert vector_document.chunk_id == f"public_{content_sha256}_0"
    assert vector_document.metadata["page"] == 4
    assert vector_document.metadata["section"] == "Revenue"
    assert vector_document.metadata["ocr_used"] is False
    assert vector_document.metadata["parser_version"] == (
        "pymupdf-blocks-ocr-v1"
    )
    assert vector_document.metadata["chunker_version"] == (
        "page-block-section-v2"
    )
    assert vector_document.metadata["embedding_model"] == (
        "intfloat/multilingual-e5-small"
    )
    assert vector_document.metadata["content_sha256"] == content_sha256
