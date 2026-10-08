import json
import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from storage.agent.repository import AgentRepository

logger = logging.getLogger(__name__)


class PostgresSaver:
    """Persist application checkpoint snapshots through ``AgentRepository``.

    This adapter backs the application audit/session tables.  It is not the
    LangGraph runtime checkpointer; production graph persistence is selected
    by ``services.agent_runtime.checkpointing`` and uses LangGraph's official
    PostgreSQL saver.
    """

    def __init__(self, db: Session, tenant_id: int, user_id: Optional[int] = None):
        self.repo = AgentRepository(db)
        self.tenant_id = tenant_id
        self.user_id = user_id

    def put(
        self,
        config: Dict[str, Any],
        checkpoint: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        thread_id = self._extract_thread_id(config)
        checkpoint_data = {
            "checkpoint": checkpoint,
            "metadata": metadata or {},
            "config": {"configurable": config.get("configurable", {})},
        }
        cp = self.repo.save_checkpoint(
            self.tenant_id,
            thread_id,
            checkpoint_data,
            user_id=self.user_id,
        )
        return {"configurable": {"thread_id": thread_id, "checkpoint_id": str(cp.id)}}

    def get(self, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        thread_id = self._extract_thread_id(config)
        cp = self.repo.get_latest_checkpoint(
            self.tenant_id,
            thread_id,
            user_id=self.user_id,
        )
        if cp is None:
            return None
        data = json.loads(cp.checkpoint_data)
        return {
            "configurable": {"thread_id": thread_id, "checkpoint_id": str(cp.id)},
            "checkpoint": data.get("checkpoint", {}),
            "metadata": data.get("metadata", {}),
        }

    def list(self, config: Optional[Dict[str, Any]] = None, limit: int = 10) -> list:
        return []

    def _extract_thread_id(self, config: Dict[str, Any]) -> str:
        if isinstance(config, dict):
            configurable = config.get("configurable", {})
            if isinstance(configurable, dict):
                return configurable.get("thread_id", "default")
        return "default"

    def get_tuple(self, config: Dict[str, Any]):
        result = self.get(config)
        if result is None:
            return None
        return result

    def put_writes(self, config: Dict[str, Any], writes: list, task_id: str):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


# Explicit application-layer name for new callers.  The implementation stays
# at the historical path so existing imports and serialized references remain
# stable.
AgentCheckpointStore = PostgresSaver

__all__ = ["AgentCheckpointStore", "PostgresSaver"]
