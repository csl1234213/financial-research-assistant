# ============================================================
# Tool Models
# ============================================================
# Core data models for the Tool Layer.
# ToolCapability 和 ToolMetadata 是 Tool 的描述层。
#
# 设计原则：
#   - ToolCapability 描述 Tool 的能力，供 Runtime 自动调度
#   - ToolMetadata 描述 Tool 本身，不保存执行数据
#   - 不引用 TaskResult / ExecutionResult 等复杂对象
#   - 不包含 Runtime / Provider / ToolEngine 依赖
#
# 保持与 ProviderCapability 风格一致。
# ============================================================

from dataclasses import dataclass, field
from typing import Any, Dict

from .tool_enums import ToolType


@dataclass(slots=True)
class ToolCapability:
    supports_parallel: bool = False
    supports_stream: bool = False
    supports_retry: bool = False
    supports_async: bool = False


@dataclass(slots=True)
class ToolMetadata:
    name: str
    tool_type: ToolType
    description: str
    version: str
    capability: ToolCapability = field(default_factory=ToolCapability)
    metadata: Dict[str, Any] = field(default_factory=dict)
