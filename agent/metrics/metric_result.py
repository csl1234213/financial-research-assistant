# ============================================================
# Metric Result
# ============================================================
# Unified output of the Metrics Layer.
# 描述一次指标采集的完整结果 — records, count, 成功状态。
#
# 不包含 Provider（模型选择是 Routing 的职责）。
# 不包含 Runtime 逻辑。
#
# Mirrors:
#   MetricResult ↔ TraceResult ↔ ToolResult ↔ MemoryResult
# ============================================================

from dataclasses import dataclass, field
from typing import List

from .metric_models import MetricRecord


@dataclass
class MetricResult:
    records: List[MetricRecord] = field(default_factory=list)

    count: int = 0

    success: bool = True
