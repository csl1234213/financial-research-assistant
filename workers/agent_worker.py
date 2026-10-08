"""
Agent Worker — entrypoint for async agent task execution.

Usage:
    python -m workers.agent_worker

Consumes agent tasks from the task queue (Redis + DB fallback),
executes run_agent(), and persists results.
"""

import logging
import os
import signal
import sys
import time

from config.worker import HEARTBEAT_INTERVAL
from tasks.heartbeat import read_worker_health
from tasks.worker import TaskWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("agent_worker")


def _healthcheck() -> int:
    configured_max_age = os.environ.get("WORKER_HEALTH_MAX_AGE")
    try:
        max_age = (
            float(configured_max_age)
            if configured_max_age is not None
            else max(60.0, HEARTBEAT_INTERVAL * 3.0)
        )
    except ValueError:
        print("WORKER_HEALTH_MAX_AGE must be a number")
        return 2
    if max_age <= 0:
        print("WORKER_HEALTH_MAX_AGE must be greater than zero")
        return 2

    healthy, message = read_worker_health(max_age_seconds=max_age)
    print(message)
    return 0 if healthy else 1


def main() -> int:
    if "--healthcheck" in sys.argv[1:]:
        return _healthcheck()

    worker = TaskWorker()
    logger.info("Starting Agent Worker...")

    worker.start()

    running = True

    def shutdown(signum, frame):
        nonlocal running
        logger.info(f"Received signal {signum}, shutting down...")
        running = False

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    while running:
        time.sleep(1)

    worker.stop()
    logger.info("Agent Worker stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
