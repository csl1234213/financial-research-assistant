import os
import socket
import uuid

WORKER_CONCURRENCY = int(os.environ.get("WORKER_CONCURRENCY", "4"))
WORKER_POLL_TIMEOUT = float(os.environ.get("WORKER_POLL_TIMEOUT", "1.0"))
MAX_TASK_RUNTIME = int(os.environ.get("MAX_TASK_RUNTIME", "3600"))

WORKER_ID = os.environ.get("WORKER_ID", f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}")

HEARTBEAT_INTERVAL = int(os.environ.get("WORKER_HEARTBEAT_INTERVAL", "30"))

__all__ = [
    "WORKER_CONCURRENCY",
    "WORKER_POLL_TIMEOUT",
    "MAX_TASK_RUNTIME",
    "WORKER_ID",
    "HEARTBEAT_INTERVAL",
]
