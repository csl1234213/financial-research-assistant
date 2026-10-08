# ============================================================
# Trace Enums
# ============================================================
# Unified enums for tracing level, status, and type.
# 不依赖 Runtime / Provider / Tool。
# 独立领域模型，与 OpenTelemetry 设计对齐。
# ============================================================

from enum import Enum


class TraceLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class TraceStatus(str, Enum):
    STARTED = "started"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class TraceType(str, Enum):
    RUNTIME = "runtime"
    WORKFLOW = "workflow"
    EXECUTION = "execution"
    TOOL = "tool"
    PROVIDER = "provider"
    MEMORY = "memory"
    PLANNING = "planning"
