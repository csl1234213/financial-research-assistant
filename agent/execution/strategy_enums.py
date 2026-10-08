# ============================================================
# Execution Strategy Enums
# ============================================================
# Unified enums for execution strategy types.
# All Execution components use these enums to avoid string
# typos and ensure consistent semantics across the system.
# ============================================================

from enum import Enum


class ExecutionStrategyType(str, Enum):
    DIRECT_LLM = "direct_llm"

    RAG = "rag"

    MULTI_DOCUMENT = "multi_document"

    MULTI_STEP = "multi_step"

    PARALLEL = "parallel"

    HYBRID = "hybrid"

    TOOL_CALLING = "tool_calling"

    AGENT_WORKFLOW = "agent_workflow"
