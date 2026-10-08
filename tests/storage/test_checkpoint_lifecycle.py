from unittest.mock import patch

from services.agent_runtime import checkpointing


def test_delete_scoped_checkpoint_uses_opaque_principal_key(monkeypatch):
    monkeypatch.setattr(checkpointing.storage_config, "use_postgres", False)

    with patch.object(
        checkpointing._memory_checkpointer,
        "delete_thread",
    ) as delete_thread:
        deleted = checkpointing.delete_scoped_checkpoint_thread(
            tenant_id=7,
            user_id=42,
            thread_id="default",
        )

    assert deleted is True
    delete_thread.assert_called_once_with(
        checkpointing.scoped_checkpoint_thread_id(7, 42, "default")
    )
