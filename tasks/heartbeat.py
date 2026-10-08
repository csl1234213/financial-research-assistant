import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from models.worker_node import WorkerNode
from storage.database import SessionLocal

logger = logging.getLogger(__name__)

DEFAULT_WORKER_HEALTH_FILE = Path(tempfile.gettempdir()) / "financial-agent-worker-health.json"


def _health_file_path() -> Path:
    configured = os.environ.get("WORKER_HEALTH_FILE")
    return Path(configured) if configured else DEFAULT_WORKER_HEALTH_FILE


def _is_process_running(pid: int) -> bool:
    if pid <= 0:
        return False

    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.OpenProcess(
            process_query_limited_information,
            False,
            pid,
        )
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD()
            success = kernel32.GetExitCodeProcess(
                handle,
                ctypes.byref(exit_code),
            )
            return bool(success) and exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_worker_health(
    *,
    max_age_seconds: float,
    health_file: Path | None = None,
) -> tuple[bool, str]:
    """Validate the durable signal emitted after a successful DB heartbeat."""
    path = health_file or _health_file_path()
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False, f"worker health signal not found: {path}"
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"worker health signal is unreadable: {exc}"

    if not isinstance(payload, dict):
        return False, "worker health signal must be a JSON object"

    try:
        timestamp = float(payload["timestamp"])
        pid = int(payload["pid"])
        worker_id = str(payload["worker_id"])
    except (KeyError, TypeError, ValueError) as exc:
        return False, f"worker health signal is invalid: {exc}"

    age_seconds = datetime.now(timezone.utc).timestamp() - timestamp
    if age_seconds < -5:
        return False, "worker health signal timestamp is in the future"
    if age_seconds > max_age_seconds:
        return False, f"worker heartbeat is stale ({age_seconds:.1f}s)"

    if not _is_process_running(pid):
        return False, f"worker process is not running (pid={pid})"

    return True, f"worker {worker_id} is healthy"


class WorkerHeartbeat:
    def __init__(
        self,
        worker_id: str,
        hostname: str,
        *,
        health_file: Path | None = None,
    ):
        self._worker_id = worker_id
        self._hostname = hostname
        self._db = None
        self._health_file = health_file or _health_file_path()

    def send(self) -> bool:
        if self._db is not None:
            success = self._send_with_db(self._db)
        else:
            db = SessionLocal()
            try:
                success = self._send_with_db(db)
            finally:
                db.close()

        if success:
            self._write_health_signal()
        return success

    def _send_with_db(self, db) -> bool:
        try:
            node = db.query(WorkerNode).filter(
                WorkerNode.worker_id == self._worker_id
            ).first()

            if node is None:
                node = WorkerNode(
                    worker_id=self._worker_id,
                    hostname=self._hostname,
                    status="online",
                )
                db.add(node)
                db.commit()
                db.refresh(node)
                logger.info(f"Registered worker node: {self._worker_id}")

            node.last_seen = datetime.now(timezone.utc)
            node.updated_at = datetime.now(timezone.utc)
            db.commit()
            return True
        except Exception as e:
            logger.error(f"Heartbeat failed for {self._worker_id}: {e}")
            db.rollback()
            return False

    def _write_health_signal(self) -> None:
        payload = {
            "worker_id": self._worker_id,
            "hostname": self._hostname,
            "pid": os.getpid(),
            "timestamp": datetime.now(timezone.utc).timestamp(),
        }
        temporary = self._health_file.with_name(
            f".{self._health_file.name}.{os.getpid()}.tmp"
        )
        try:
            self._health_file.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(payload), encoding="utf-8")
            temporary.replace(self._health_file)
        except OSError as exc:
            logger.error(
                "Failed to write worker health signal %s: %s",
                self._health_file,
                exc,
            )
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def clear_health_signal(self) -> None:
        try:
            self._health_file.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning(
                "Failed to clear worker health signal %s: %s",
                self._health_file,
                exc,
            )


def get_heartbeat(worker_id: str, hostname: str) -> WorkerHeartbeat:
    return WorkerHeartbeat(worker_id, hostname)
