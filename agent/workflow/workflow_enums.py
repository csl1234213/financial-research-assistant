# ============================================================
# Workflow Type Enums
# ============================================================
# Unified enums for workflow types and status.
# Workflow 不关心模型（Gemini / DeepSeek / …）。
# 它只描述「多个 Execution 如何组成一个完整任务」。
# ============================================================

from enum import Enum


class WorkflowType(str, Enum):
    DIRECT_CHAT = "direct_chat"

    RAG = "rag"

    RETRIEVE_THEN_REASON = "retrieve_then_reason"

    MULTI_STEP = "multi_step"

    PARALLEL = "parallel"

    VERIFY = "verify"

    SUMMARIZE = "summarize"

    TOOL_PIPELINE = "tool_pipeline"


class WorkflowStatus(str, Enum):
    PENDING = "pending"

    RUNNING = "running"

    DONE = "done"

    FAILED = "failed"
