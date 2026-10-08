# ============================================================
# Trace Result
# ============================================================
# Unified output of the Tracing Layer.
# 描述一次完整 Trace 的结果 — spans, events, duration,
# 成功状态 — 供 UI Dashboard 和 Export 消费。
#
# 不包含 Provider（模型选择是 Routing 的职责）。
# 不包含 Runtime 逻辑。
# 保留 spans 和 events 用于 Timeline 展示。
# ============================================================

from dataclasses import dataclass, field
from typing import List

from .trace_models import TraceEvent, TraceSpan


@dataclass
class TraceResult:
    spans: List[TraceSpan] = field(default_factory=list)

    events: List[TraceEvent] = field(default_factory=list)

    duration_ms: float = 0.0

    success: bool = True
