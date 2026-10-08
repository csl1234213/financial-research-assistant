# ============================================================
# Reliability Result
# ============================================================
# Unified output of the Reliability Layer.
# 描述一次可靠性策略执行的结果 — 成功状态、策略类型、
# 重试次数、延迟、错误信息。
#
# 不包含 Provider（模型选择是 Routing 的职责）。
# 不包含 Runtime 逻辑。
#
# Mirrors:
#   ReliabilityResult ↔ MetricResult ↔ TraceResult ↔ ToolResult ↔ MemoryResult
# ============================================================

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .reliability_enums import ReliabilityType


@dataclass
class PipelineResult:
    success: bool = True

    results: Dict[str, "ReliabilityResult"] = field(default_factory=dict)

    total_latency_ms: float = 0.0

    pipeline_order: list = field(default_factory=list)

    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReliabilityResult:
    success: bool = True

    policy: Optional[ReliabilityType] = None

    retry_count: int = 0

    latency_ms: float = 0.0

    error: Optional[str] = None

    timeout_occurred: bool = False

    circuit_state: Optional[str] = None

    metadata: Dict[str, Any] = field(default_factory=dict)
