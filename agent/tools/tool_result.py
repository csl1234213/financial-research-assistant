# ============================================================
# Tool Result
# ============================================================
# Unified output of the Tool Layer.
# 描述一次 Tool 执行的结果。
#
# 设计原则：
#   - output 是主要输出（文本、JSON 等）
#   - artifacts 是附加产物（文件、图像、CSV、PDF 等）
#   - latency_ms 用于性能监控
#   - 不包含 Provider / Runtime / Business Logic
#
# artifacts 字段为后续 Tool Pipeline 和 UI 展示
# 预留扩展能力。
# ============================================================

from dataclasses import dataclass, field
from typing import Any, List, Optional

from .tool_enums import ToolStatus


@dataclass(slots=True)
class ToolResult:
    status: ToolStatus

    output: Any = None

    artifacts: List[Any] = field(default_factory=list)

    latency_ms: float = 0.0

    error: Optional[str] = None

    metadata: dict[str, Any] = field(default_factory=dict)
