# ============================================================
# Reliability Exceptions — Unified error hierarchy
# ============================================================
# All Reliability Layer components throw exceptions from this
# hierarchy. Upper layers (Agent Runtime, API) only catch
# ReliabilityError.
#
# Mirrors:
#   ReliabilityError ↔ MetricError ↔ TraceError ↔ ToolError ↔ MemoryError ↔ WorkflowError
# ============================================================


class ReliabilityError(Exception):
    pass


class ReliabilityNotFound(ReliabilityError):
    pass


class ReliabilityRegistrationError(ReliabilityError):
    pass


class ReliabilityNotSupported(ReliabilityError):
    pass
