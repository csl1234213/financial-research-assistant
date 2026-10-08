# ============================================================
# Tool Type Enums
# ============================================================
# Unified enums for tool type, status, and priority.
# Tool 不关心 Provider / Runtime / Business Logic。
# 它只描述「工具的类别、执行状态和优先级」。
#
# ToolPriority 为后续 Scheduler / Queue / Parallel
# Execution 提供调度基础。
# ============================================================

from enum import Enum


class ToolType(str, Enum):
    RETRIEVAL = "retrieval"
    OCR = "ocr"
    PYTHON = "python"
    SQL = "sql"
    HTTP = "http"
    FILE = "file"
    CUSTOM = "custom"


class ToolStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class ToolPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"
