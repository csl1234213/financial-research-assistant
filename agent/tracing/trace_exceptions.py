# ============================================================
# Trace Exceptions — Unified error hierarchy
# ============================================================
# All Tracing Layer components throw exceptions from this
# hierarchy. Upper layers (Agent Runtime, API) only catch
# TraceError.
#
# Mirrors:
#   TraceError ↔ MemoryError ↔ ToolError ↔ WorkflowError ↔ ProviderError
# ============================================================


class TraceError(Exception):
    pass


class TracerNotFound(TraceError):
    pass


class TracerRegistrationError(TraceError):
    pass
