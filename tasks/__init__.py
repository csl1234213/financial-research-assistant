from importlib import import_module
from typing import Any

_EXPORTS = {
    "agent_task_handler": ("tasks.agent_tasks", "agent_task_handler"),
    "TaskBroker": ("tasks.broker", "TaskBroker"),
    "get_broker": ("tasks.broker", "get_broker"),
    "WorkerHeartbeat": ("tasks.heartbeat", "WorkerHeartbeat"),
    "get_heartbeat": ("tasks.heartbeat", "get_heartbeat"),
    "TaskStatusEnum": ("tasks.models", "TaskStatus"),
    "TaskTypeEnum": ("tasks.models", "TaskType"),
    "TaskRepository": ("tasks.repository", "TaskRepository"),
    "get_task_repository": ("tasks.repository", "get_task_repository"),
    "get_retry_count": ("tasks.retry", "get_retry_count"),
    "should_retry": ("tasks.retry", "should_retry"),
    "TaskWorker": ("tasks.worker", "TaskWorker"),
    "get_worker": ("tasks.worker", "get_worker"),
    "start_worker": ("tasks.worker", "start_worker"),
    "stop_worker": ("tasks.worker", "stop_worker"),
}

__all__ = [
    "agent_task_handler",
    "TaskBroker",
    "get_broker",
    "WorkerHeartbeat",
    "get_heartbeat",
    "TaskStatusEnum",
    "TaskTypeEnum",
    "TaskRepository",
    "get_task_repository",
    "get_retry_count",
    "should_retry",
    "TaskWorker",
    "get_worker",
    "start_worker",
    "stop_worker",
]


def __getattr__(name: str) -> Any:
    """Load public task APIs on demand so worker probes stay lightweight."""
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value
