import importlib
import logging
import multiprocessing
import socket
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime, timezone
from multiprocessing.connection import Connection
from typing import Any, TypeAlias

from config.worker import (
    HEARTBEAT_INTERVAL,
    MAX_TASK_RUNTIME,
    WORKER_CONCURRENCY,
    WORKER_ID,
    WORKER_POLL_TIMEOUT,
)
from models.task import TaskStatus
from tasks.broker import TaskBroker, get_broker
from tasks.heartbeat import get_heartbeat
from tasks.models import TaskType as TaskTypeEnum
from tasks.repository import get_task_repository
from tasks.retry import get_retry_count, should_retry

logger = logging.getLogger(__name__)

TaskHandler: TypeAlias = Callable[[str], None]
HandlerReference: TypeAlias = str | TaskHandler

_HANDLERS: dict[TaskTypeEnum, HandlerReference] = {
    TaskTypeEnum.PROCESS_DOCUMENT: "tasks.knowledge_tasks:process_document_task",
    TaskTypeEnum.FORMAL_READY_DOCUMENT: "tasks.formal_ready_tasks:process_formal_ready_task",
    TaskTypeEnum.AGENT_TASK: "tasks.agent_tasks:agent_task_handler",
}

STALE_RECOVERY_INTERVAL_SECONDS = 60
PENDING_RECLAIM_INTERVAL_SECONDS = 15
PENDING_RECLAIM_MIN_IDLE_MS = 60_000
PROCESS_STOP_GRACE_SECONDS = 5
STALE_RECOVERY_GRACE_SECONDS = max(60, HEARTBEAT_INTERVAL * 2)


class TaskExecutionError(RuntimeError):
    """Raised when an isolated task handler does not finish successfully."""


def _resolve_handler(handler_reference: HandlerReference) -> TaskHandler:
    if callable(handler_reference):
        return handler_reference

    module_name, function_name = handler_reference.split(":", maxsplit=1)
    module = importlib.import_module(module_name)
    return getattr(module, function_name)


def _run_handler_process(
    handler_reference: HandlerReference,
    task_public_id: str,
    result_connection: Connection,
) -> None:
    """Execute one registered handler in an isolated, terminable process."""
    try:
        handler = _resolve_handler(handler_reference)
        handler(task_public_id)
        result_connection.send((True, None))
    except BaseException as exc:
        result_connection.send((False, f"{type(exc).__name__}: {exc}"[:1000]))
    finally:
        result_connection.close()


class TaskWorker:
    def __init__(self, worker_id: str | None = None):
        self._running = False
        self._threads: list[threading.Thread] = []
        self._worker_id = worker_id or WORKER_ID
        self._hostname = socket.gethostname()
        self._last_recovery = datetime.now(timezone.utc)
        self._pending_messages: deque[dict[str, Any]] = deque()
        self._pending_reclaim_lock = threading.Lock()
        self._next_pending_reclaim = 0.0
        self._stop_event = threading.Event()
        self._health_thread: threading.Thread | None = None
        self._heartbeat = get_heartbeat(self._worker_id, self._hostname)

    def start(self):
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._heartbeat.send()

        self._threads = []
        for i in range(WORKER_CONCURRENCY):
            t = threading.Thread(
                target=self._run_thread,
                name=f"worker-{self._worker_id}-{i}",
                daemon=True,
            )
            t.start()
            self._threads.append(t)

        self._health_thread = threading.Thread(
            target=self._health_loop,
            name=f"worker-health-{self._worker_id}",
            daemon=True,
        )
        self._health_thread.start()

        logger.info(f"TaskWorker started: {self._worker_id} with {WORKER_CONCURRENCY} threads")

    def stop(self):
        self._running = False
        self._stop_event.set()
        for t in self._threads:
            t.join(timeout=10)
        if self._health_thread is not None:
            self._health_thread.join(timeout=10)
        self._heartbeat.clear_health_signal()
        logger.info(f"TaskWorker stopped: {self._worker_id}")

    def _health_loop(self):
        while self._running:
            self._heartbeat.send()
            if self._stop_event.wait(HEARTBEAT_INTERVAL):
                return

    def _run_thread(self):
        while self._running:
            try:
                self._recover_stale_if_needed()
                self._process_next_task()
            except Exception as e:
                logger.exception(f"Worker {self._worker_id} error: {e}")
                time.sleep(1)

    def _recover_stale_if_needed(self):
        now = datetime.now(timezone.utc)
        if (now - self._last_recovery).total_seconds() < STALE_RECOVERY_INTERVAL_SECONDS:
            return
        self._last_recovery = now
        repo = get_task_repository()
        try:
            recovered = repo.recover_stale_tasks(
                stale_after_seconds=(
                    max(1, MAX_TASK_RUNTIME) + STALE_RECOVERY_GRACE_SECONDS
                )
            )
            if recovered > 0:
                logger.info(f"Worker {self._worker_id} recovered {recovered} stale tasks")
        finally:
            repo._db.close()

    def _process_next_task(self):
        broker = get_broker()
        message = None

        if broker.enabled:
            broker.set_consumer_name(self._worker_id)
            message = self._claim_pending_message(broker)
            if message is None:
                message = broker.consume_task(timeout=WORKER_POLL_TIMEOUT)
            if message is not None:
                task_id = message.get("task_id")
                message_id = message.get("_message_id")
                if task_id:
                    self._execute_task(
                        task_id,
                        message_id=message_id,
                    )
                    return
                logger.warning("Acknowledging malformed task message %s", message_id)
                broker.ack_task("", message_id)

        # The database remains the source of truth.  Polling it also handles
        # tasks created while Redis is temporarily unavailable.
        repo = get_task_repository()
        try:
            task = repo.claim_task()
            if task is None:
                time.sleep(1)
                return
            task_public_id = task.public_id
        finally:
            repo._db.close()

        self._execute_task(task_public_id, already_claimed=True)

    def _claim_pending_message(
        self,
        broker: TaskBroker,
    ) -> dict[str, Any] | None:
        """Reclaim abandoned Redis Stream deliveries without losing the batch."""
        with self._pending_reclaim_lock:
            if self._pending_messages:
                return self._pending_messages.popleft()

            now = time.monotonic()
            if now < self._next_pending_reclaim:
                return None

            self._next_pending_reclaim = now + PENDING_RECLAIM_INTERVAL_SECONDS
            claimed = broker.claim_pending_tasks(
                min_idle_ms=PENDING_RECLAIM_MIN_IDLE_MS,
                count=max(10, WORKER_CONCURRENCY * 2),
            )
            self._pending_messages.extend(claimed)
            if self._pending_messages:
                return self._pending_messages.popleft()
            return None

    def _run_handler_with_timeout(
        self,
        task_type: TaskTypeEnum,
        task_public_id: str,
    ) -> None:
        if MAX_TASK_RUNTIME <= 0:
            raise TaskExecutionError("MAX_TASK_RUNTIME must be greater than zero")

        context = multiprocessing.get_context("spawn")
        handler_reference = _HANDLERS[task_type]
        result_reader, result_writer = context.Pipe(duplex=False)
        process = context.Process(
            target=_run_handler_process,
            args=(handler_reference, task_public_id, result_writer),
            name=f"task-{task_public_id}",
        )
        try:
            process.start()
        except Exception as exc:
            result_reader.close()
            result_writer.close()
            process.close()
            raise TaskExecutionError(
                f"Failed to start task handler process: {exc}"
            ) from exc
        result_writer.close()
        deadline = time.monotonic() + MAX_TASK_RUNTIME

        try:
            while process.is_alive():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._terminate_task_process(process)
                    raise TaskExecutionError(
                        f"Task exceeded MAX_TASK_RUNTIME ({MAX_TASK_RUNTIME}s)"
                    )
                if not self._running:
                    self._terminate_task_process(process)
                    raise TaskExecutionError("Worker stopped before task completed")
                process.join(timeout=min(0.2, remaining))

            outcome = result_reader.recv() if result_reader.poll() else None
            if outcome and outcome[0]:
                return

            error = outcome[1] if outcome else None
            detail = error or f"handler process exited with code {process.exitcode}"
            raise TaskExecutionError(detail)
        finally:
            result_reader.close()
            if process.is_alive():
                self._terminate_task_process(process)
            process.close()

    @staticmethod
    def _terminate_task_process(process) -> None:
        process.terminate()
        process.join(timeout=PROCESS_STOP_GRACE_SECONDS)
        if process.is_alive():
            process.kill()
            process.join(timeout=PROCESS_STOP_GRACE_SECONDS)

    @staticmethod
    def _formal_authority_allows_retry(repo, task) -> bool:
        if task.task_type != TaskTypeEnum.FORMAL_READY_DOCUMENT.value:
            return True

        from sqlalchemy.orm import Session

        from tasks.formal_ingestion_ledger import FormalIngestionLedger

        # Read the existing, owner-scoped checkpoint authority, not exception
        # text or the queue status (which may reflect a process interruption).
        # Status does not read artifacts; do not initialize delivery/providers.
        ledger = FormalIngestionLedger(
            lambda: Session(bind=repo._db.get_bind()), artifact_store=None,
        )
        state = ledger.status(task.public_id, task.tenant_id, task.user_id)
        return state["status"] not in {"failed", "quarantined", "ready"}

    def _execute_task(
        self,
        task_public_id: str,
        *,
        already_claimed: bool = False,
        message_id: str | None = None,
    ):
        broker = get_broker()
        repo = get_task_repository()
        try:
            task = repo.get_task(task_public_id)
            if task is None:
                logger.warning(f"Task {task_public_id} not found in DB")
                broker.ack_task(task_public_id, message_id)
                return

            if already_claimed:
                if task.status != TaskStatus.RUNNING.value:
                    return
            elif task.status != TaskStatus.PENDING.value:
                # A database poller may already have processed a task whose
                # broker message was delivered later.  Ack it to prevent a
                # permanent pending message.
                broker.ack_task(task_public_id, message_id)
                return

            if not already_claimed:
                claimed = repo.claim_task(task_public_id)
            else:
                claimed = task

            if claimed is None:
                logger.warning(f"Worker {self._worker_id} failed to claim task {task_public_id}")
                broker.ack_task(task_public_id, message_id)
                return

            claimed.worker_id = self._worker_id
            claimed.locked_at = datetime.now(timezone.utc)
            repo._db.commit()

            try:
                task_type = TaskTypeEnum(claimed.task_type)
            except ValueError:
                task_type = None

            handler = _HANDLERS.get(task_type) if task_type is not None else None
            if handler is None:
                repo.update_task(
                    task_public_id,
                    status=TaskStatus.FAILED,
                    error_message=f"No handler for task type: {claimed.task_type}",
                )
            else:
                try:
                    self._run_handler_with_timeout(task_type, task_public_id)
                except Exception as exc:
                    logger.exception("Worker %s failed task %s", self._worker_id, task_public_id)
                    repo.update_task(
                        task_public_id,
                        status=TaskStatus.FAILED,
                        error_message=str(exc),
                    )

            repo._db.expire_all()
            updated_task = repo.get_task(task_public_id)
            if updated_task and updated_task.status == TaskStatus.FAILED.value:
                retry_count = get_retry_count(updated_task)
                if self._formal_authority_allows_retry(repo, updated_task) and should_retry(retry_count):
                    updated_task.retry_count = retry_count + 1
                    repo._db.commit()
                    logger.info(
                        f"Worker {self._worker_id} retrying task {task_public_id} "
                        f"(attempt {updated_task.retry_count})"
                    )
                    repo.update_task(task_public_id, status=TaskStatus.PENDING)
                    broker.retry_task(
                        task_id=task_public_id,
                        tenant_id=updated_task.tenant_id,
                        task_type=updated_task.task_type,
                    )
            broker.ack_task(task_public_id, message_id)
        finally:
            repo._db.close()


_worker: TaskWorker = None


def get_worker() -> TaskWorker:
    global _worker
    if _worker is None:
        _worker = TaskWorker()
    return _worker


def start_worker():
    get_worker().start()


def stop_worker():
    global _worker
    if _worker:
        _worker.stop()
        _worker = None
