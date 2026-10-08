"""Public import contract for application and graph checkpoint persistence."""

from langgraph.checkpoint.postgres import PostgresSaver as LangGraphPostgresSaver

from storage.agent import AgentCheckpointStore
from storage.agent import PostgresSaver as PackageLegacyPostgresSaver
from storage.agent.checkpoint import PostgresSaver as ModuleLegacyPostgresSaver


def test_legacy_checkpoint_imports_are_exact_store_aliases() -> None:
    assert ModuleLegacyPostgresSaver is AgentCheckpointStore
    assert PackageLegacyPostgresSaver is AgentCheckpointStore


def test_application_store_is_not_the_langgraph_postgres_saver() -> None:
    assert AgentCheckpointStore is not LangGraphPostgresSaver
