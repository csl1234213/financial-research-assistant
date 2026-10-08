# ============================================================
# Metric Enums
# ============================================================
# Unified enums for metric type, scope, and status.
# 不依赖 Runtime / Provider / Tool。
# 独立领域模型，与 Prometheus / OpenTelemetry 设计对齐。
#
# MetricType  → 指标类型（Counter / Gauge / Histogram / Timer）
# MetricScope → 统计范围（哪个模块产生的指标）
# MetricStatus → 指标启用状态
# ============================================================

from enum import Enum


class MetricType(Enum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    TIMER = "timer"


class MetricScope(Enum):
    RUNTIME = "runtime"
    WORKFLOW = "workflow"
    EXECUTION = "execution"
    TOOL = "tool"
    PROVIDER = "provider"
    MEMORY = "memory"


class MetricStatus(Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
