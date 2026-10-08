# ============================================================
# Workflow Exceptions — Unified error hierarchy
# ============================================================
# All Workflow Layer components throw exceptions from this
# hierarchy. Upper layers (Agent Runtime, API) only catch
# WorkflowError.
#
# Mirrors llm.providers.provider_exceptions:
#   WorkflowError ↔ ProviderError
# ============================================================


class WorkflowError(Exception):
    pass


class WorkflowNotFound(WorkflowError):
    pass


class WorkflowRegistrationError(WorkflowError):
    pass
