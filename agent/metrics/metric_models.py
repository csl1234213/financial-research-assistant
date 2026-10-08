# ============================================================
# Metric Models
# ============================================================
# Core data models for the Metrics Layer.
#
# MetricRecord    — 一次指标采集的实际数据点。
# MetricDefinition — 指标元数据，描述指标含义。
#
# 设计原则：
#   - Label-driven Design：通过 labels 区分维度（如 provider=gemini）
#     而不是为每个维度创建新指标名。
#   - 与 Prometheus / OpenTelemetry 数据模型对齐
#   - metadata 保持轻量，不引用复杂运行时对象
#   - 不包含 Runtime / Provider / Export 逻辑
#
# Mirrors:
#   MetricRecord ↔ TraceEvent
#   MetricDefinition ↔ TracerMetadata
# ============================================================

from dataclasses import dataclass, field
from typing import Any, Dict

from .metric_enums import MetricScope, MetricType


@dataclass(slots=True)
class MetricRecord:
    name: str
    metric_type: MetricType
    value: float
    scope: MetricScope
    timestamp: float
    labels: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MetricDefinition:
    name: str
    metric_type: MetricType
    description: str = ""
    unit: str = ""
    labels: Dict[str, str] = field(default_factory=dict)
