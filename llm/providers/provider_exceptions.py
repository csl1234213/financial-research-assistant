# ============================================================
# Provider Exceptions — Unified error hierarchy
# ============================================================
# All providers throw exceptions from this hierarchy.
# Upper layers (Agent Runtime, API) only catch ProviderError.
# ============================================================


class ProviderError(Exception):
    generation_status = "PROVIDER_ERROR"
    usage_status = "UNAVAILABLE"
    failure_class = "PROVIDER_ERROR"


class ProviderNotFound(ProviderError):
    pass


class AuthenticationError(ProviderError):
    pass


class RateLimitError(ProviderError):
    pass


class ModelNotFoundError(ProviderError):
    pass


class ProviderConnectionError(ProviderError):
    pass


class ProviderTimeoutError(ProviderError):
    """The provider exceeded the request's total deadline."""

    def __init__(self, message, *, timeout_source="HTTP_TIMEOUT", cancellation_guaranteed=False):
        super().__init__(message)
        self.generation_status = "TIMEOUT"
        self.usage_status = "UNAVAILABLE"
        self.failure_class = "TIMEOUT"
        self.timeout_source = timeout_source
        self.cancellation_guaranteed = cancellation_guaranteed


class StructuredOutputError(ProviderError, ValueError):
    """Transport completed, but the existing Answer schema rejected its content."""

    generation_status = "STRUCTURED_OUTPUT_ERROR"
    failure_class = "STRUCTURED_OUTPUT_ERROR"


class InvalidProviderResponseError(ProviderError, ValueError):
    generation_status = "INVALID_RESPONSE"
    failure_class = "INVALID_RESPONSE"
