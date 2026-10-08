# ============================================================
# Memory Exceptions — Unified error hierarchy
# ============================================================
# All Memory Layer components throw exceptions from this
# hierarchy. Upper layers (Agent Runtime, API) only catch
# MemoryError.
#
# Mirrors:
#   MemoryError ↔ WorkflowError ↔ ProviderError
# ============================================================


class MemoryError(Exception):
    pass


class MemoryNotFound(MemoryError):
    pass


class MemoryRegistrationError(MemoryError):
    pass
