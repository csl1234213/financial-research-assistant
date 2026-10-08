"""Lazy formal delivery dependencies shared by default API and worker processes."""

import os
from functools import lru_cache
from pathlib import Path


class LazyVectors:
    def __init__(self):
        self.store = None

    def __getattr__(self, name):
        if self.store is None:
            from storage.chroma_store import ChromaEmbeddingStore

            self.store = ChromaEmbeddingStore()
        return getattr(self.store, name)


@lru_cache(maxsize=1)
def get_delivery():
    from config import EMBEDDING_MODEL, EMBEDDING_MODEL_REVISION
    from services.formal_ingestion_composition import FormalIngestionComposition
    from storage.database import SessionLocal

    root = Path(os.environ.get("UPLOAD_DIR", "storage/uploads")).resolve()

    def embed(texts):
        from embedding import embed_passages, load_embedding_model

        return embed_passages(load_embedding_model(), texts).tolist()

    return FormalIngestionComposition(
        SessionLocal, storage_root=root / "formal", artifact_root=root / "formal-artifacts",
        vectors=LazyVectors(), embedder=embed,
        embedding_identity=f"{EMBEDDING_MODEL}@{EMBEDDING_MODEL_REVISION}",
    )


class LazyUploadService:
    def __getattr__(self, name):
        return getattr(get_delivery().upload, name)


class LazyLedger:
    def __getattr__(self, name):
        return getattr(get_delivery().ledger, name)


def source_service():
    from services.source_documents import SourceDocumentService

    delivery = get_delivery()
    return SourceDocumentService(delivery.repository.session_factory, delivery.upload.storage_root)


def resolve_grounded_source(**parameters):
    from services.ready_fact_synthesis_source import ReadyFactSynthesisSource

    def narrative(**query):
        from embedding import load_embedding_model
        from retrieval.hybrid_retriever import HybridRetriever
        from retrieval.ingestion_ready_hybrid import IngestionReadyHybridRetriever
        from services.ready_narrative_synthesis_source import ReadyNarrativeSynthesisSource

        delivery = get_delivery()
        retriever = IngestionReadyHybridRetriever(
            delivery.ledger, delivery.index.vectors,
            embedding_identity=delivery.index.embedding_identity,
            hybrid_retriever=HybridRetriever(model=load_embedding_model()),
        )
        return ReadyNarrativeSynthesisSource(retriever)(**query)

    return ReadyFactSynthesisSource(get_delivery().ledger, fallback_resolver=narrative)(**parameters)


def resolve_narrative_ports(*, tenant_id, user_id):
    """Request-owned configured provider; never cross-user or unverified fallback."""
    from config.llm import LLM_CONNECT_TIMEOUT, LLM_READ_TIMEOUT, LLM_TIMEOUT, LLM_TOTAL_DEADLINE
    from core.answer_provider_port import AnswerRequestPurpose
    from core.answer_synthesis_budget import NarrativeTimeBudget
    from core.answer_synthesis_narrative_ollama import LocalQwenNarrativeGenerator
    from core.answer_synthesis_semantic_ollama import LocalQwenEntailmentReviewer
    from llm.factory.provider_factory import ProviderFactory
    from llm.providers.provider_config import ProviderConfig
    from services.llm_settings_service import get_runtime_llm_settings

    with get_delivery().repository.session_factory() as db:
        settings = get_runtime_llm_settings(db, tenant_id=tenant_id, user_id=user_id)
    name = settings.default_provider
    if not name or name not in settings.provider_configs or not settings.provider_models.get(name):
        raise ValueError("NARRATIVE_PROVIDER_NOT_CONFIGURED")
    options = settings.provider_configs[name]
    config = ProviderConfig(provider=name, model=settings.provider_models[name],
        api_key=options.get("api_key", ""), base_url=options.get("base_url"),
        temperature=0, max_tokens=1024, timeout=LLM_TIMEOUT,
        connect_timeout=LLM_CONNECT_TIMEOUT, read_timeout=LLM_READ_TIMEOUT,
        total_deadline=LLM_TOTAL_DEADLINE, stream=False)
    provider = ProviderFactory.create(config)
    budget = NarrativeTimeBudget(total_seconds=LLM_TOTAL_DEADLINE, per_call_seconds=LLM_TIMEOUT)
    return (LocalQwenNarrativeGenerator(provider=provider, enabled=True, compact_references=True,
                request_purpose=AnswerRequestPurpose.STRUCTURED_GENERATION),
            LocalQwenEntailmentReviewer(provider=provider, enabled=True, compact_references=True,
                request_purpose=AnswerRequestPurpose.STRUCTURED_REVIEW), budget)
