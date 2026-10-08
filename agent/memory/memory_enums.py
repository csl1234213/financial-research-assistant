# ============================================================
# Memory Type Enums
# ============================================================
# Unified enums for memory lifecycle and importance.
# Memory 不关心 Provider / Runtime / Tool。
# 它只描述「记忆的生命周期和重要性」。
# ============================================================

from enum import Enum


class MemoryType(str, Enum):
    SHORT_TERM = "short_term"

    SESSION = "session"

    WORKFLOW = "workflow"

    LONG_TERM = "long_term"


class MemoryImportance(str, Enum):
    LOW = "low"

    MEDIUM = "medium"

    HIGH = "high"

    CRITICAL = "critical"
