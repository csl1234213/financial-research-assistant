"""Explicit formal ingestion composition; no experimental persistence imports."""

from datetime import datetime, timezone

from api.app_factory import create_app
from api.routers.upload_sessions import build_upload_session_router
from services.ready_promotion import ReadyPromotionService
from services.upload_session_service import UploadSessionService
from storage.database import _import_models
from storage.ingestion_artifacts import IngestionArtifactStore
from storage.upload_session_repository import UploadSessionRepository
from tasks.formal_ingestion_ledger import FormalIngestionLedger
from tasks.formal_ingestion_source import FormalUploadSource
from tasks.ingestion_index_stage import CoreIndexBuilder
from tasks.ingestion_stage_executor import IngestionStageExecutor
from tasks.ingestion_task_runner import IngestionTaskRunner
from tasks.task_dispatcher import TaskDispatcher


class FormalIngestionComposition:
    def __init__(
        self, session_factory, *, storage_root, artifact_root, vectors, embedder, embedding_identity, clock=None
    ):
        # Register canonical ORM relationship targets in a fresh runtime process.
        # This imports metadata only: no create_all, seed, migration, or SQL write.
        _import_models()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.repository = UploadSessionRepository(session_factory)
        self.upload = UploadSessionService(self.repository, storage_root)
        self.artifacts = IngestionArtifactStore(artifact_root)
        self.ledger = FormalIngestionLedger(session_factory, artifact_store=self.artifacts)
        self.dispatcher = TaskDispatcher(session_factory)
        self.index = CoreIndexBuilder(self.artifacts, vectors, embedder=embedder, embedding_identity=embedding_identity)
        self.ready = ReadyPromotionService(session_factory, artifact_store=self.artifacts, vector_store=vectors)
        self.executor = IngestionStageExecutor(
            self.ledger,
            source_resolver=FormalUploadSource(session_factory, storage_root),
            clock=self.clock,
            index_operator=self.index,
        )
        self.runner = IngestionTaskRunner(self.executor, ready_promotion=self.ready, clock=self.clock)

    def app(self, *, transport_protocol="legacy_multipart", completed_transport=None):
        router = build_upload_session_router(
            self.upload,
            ingestion_ledger=self.ledger,
            transport_protocol=transport_protocol,
            completed_transport=completed_transport,
        )
        return create_app(profile="ingestion", ingestion_routers=(router,))
