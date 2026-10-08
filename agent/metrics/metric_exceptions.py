# ============================================================
# Metric Exceptions — Unified error hierarchy
# ============================================================
# All Metrics Layer components throw exceptions from this
# hierarchy. Upper layers (Agent Runtime, API) only catch
# MetricError.
#
# Mirrors:
#   MetricError ↔ TraceError ↔ ToolError ↔ MemoryError ↔ WorkflowError
# ============================================================


class MetricError(Exception):
    pass


class MetricNotFound(MetricError):
    pass


class MetricRegistrationError(MetricError):
    pass
