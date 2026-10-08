# ============================================================
# Tool Exceptions — Unified error hierarchy
# ============================================================
# All Tool Layer components throw exceptions from this
# hierarchy. Upper layers (Agent Runtime, API) only catch
# ToolError.
#
# Mirrors:
#   ToolError ↔ MemoryError ↔ WorkflowError ↔ ProviderError
# ============================================================


class ToolError(Exception):
    pass


class ToolNotFound(ToolError):
    pass


class ToolRegistrationError(ToolError):
    pass


class ToolNotSupported(ToolError):
    pass


class ToolAuthorizationDenied(ToolError):
    pass
