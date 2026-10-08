# ============================================================
# Tool Layer
# ============================================================
# Tool Layer 是 Agent 的第五个核心 Layer。
# 它提供统一的外部工具调用接口，支持 Retrieval、
# OCR、Python、SQL、HTTP、File 等工具类型。
#
# Sprint 1 Step 1：Tool Models（数据模型与抽象接口）
# Sprint 1 Step 2：Tool Registry & Factory（组织层）
# ============================================================

from .base_tool import BaseTool
from .mcp_adapter import ToolEngineMCPAdapter
from .retrieval_contract import (
    RetrievalAdapter,
    RetrievalContractError,
    RetrievalEvidence,
    RetrievalRequest,
    TrustedRetrievalAdapter,
    trusted_retrieval_adapter,
)
from .tool_authorization import ToolAuthorizationDecision, ToolAuthorizationHook
from .tool_bridge import ToolBridge
from .tool_context import ToolContext
from .tool_engine import ToolEngine
from .tool_enums import ToolPriority, ToolStatus, ToolType
from .tool_exceptions import (
    ToolAuthorizationDenied,
    ToolError,
    ToolNotFound,
    ToolNotSupported,
    ToolRegistrationError,
)
from .tool_factory import ToolFactory
from .tool_models import ToolCapability, ToolMetadata
from .tool_registry import ToolRegistry
from .tool_result import ToolResult

__all__ = [
    "BaseTool",
    "ToolBridge",
    "ToolAuthorizationDecision",
    "ToolAuthorizationDenied",
    "ToolAuthorizationHook",
    "ToolCapability",
    "ToolContext",
    "ToolEngine",
    "ToolEngineMCPAdapter",
    "RetrievalAdapter",
    "RetrievalContractError",
    "RetrievalEvidence",
    "RetrievalRequest",
    "TrustedRetrievalAdapter",
    "ToolError",
    "ToolFactory",
    "ToolMetadata",
    "ToolNotFound",
    "ToolNotSupported",
    "ToolPriority",
    "ToolRegistrationError",
    "ToolRegistry",
    "ToolResult",
    "ToolStatus",
    "ToolType",
    "trusted_retrieval_adapter",
]
