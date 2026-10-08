import logging
import signal
import time

from storage.database import init_db
from tasks.worker import TaskWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("worker_runner")


def main():
    init_db()

    worker = TaskWorker()
    worker.start()

    running = True

    def _shutdown(signum, frame):
        nonlocal running
        running = False
        logger.info("Shutdown signal received")

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info("Worker runner started, waiting for tasks...")
    while running:
        time.sleep(1)

    worker.stop()
    logger.info("Worker runner stopped")


if __name__ == "__main__":
    main()
