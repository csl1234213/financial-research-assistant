# ============================================================
# Trace Models
# ============================================================
# Core data models for the Tracing Layer.
#
# TraceSpan  — 类似 OpenTelemetry Span，描述一个操作区间。
# TraceEvent — 类似 Log Event，记录 Span 内的关键事件。
#
# 设计原则：
#   - TraceSpan 是 Trace → Span → Event 三层模型的核心
#   - 天然兼容 OpenTelemetry / Jaeger / Tempo 数据模型
#   - metadata 保持轻量，不引用复杂运行时对象
#   - 不包含 Runtime / Provider / Export 逻辑
# ============================================================

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .trace_enums import TraceLevel, TraceStatus, TraceType


@dataclass(slots=True)
class TraceSpan:
    id: str

    trace_type: TraceType

    name: str

    parent_id: Optional[str] = None

    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    end_time: Optional[datetime] = None

    duration_ms: float = 0.0

    status: TraceStatus = TraceStatus.STARTED

    metadata: Dict[str, Any] = field(default_factory=dict)

    events: List["TraceEvent"] = field(default_factory=list)


@dataclass(slots=True)
class TraceEvent:
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    level: TraceLevel = TraceLevel.INFO

    message: str = ""

    metadata: Dict[str, Any] = field(default_factory=dict)
