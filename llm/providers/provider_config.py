# ============================================================
# ProviderConfig — Configuration-driven provider init
# ============================================================
# Each provider is created from a ProviderConfig, not from
# scattered environment variable reads inside the provider.
# ============================================================

from dataclasses import dataclass


def timeout_budget_for_provider(
    provider: str,
    *,
    timeout: int,
    read_timeout: float | None,
    total_deadline: float | None,
) -> tuple[int, float | None]:
    """Preserve deployment configuration; adapters apply the shared deadline cap.

    The legacy wiring signature remains compatible. A local model is not a
    reason to silently increase configured generation or read timeouts.
    """
    return timeout, read_timeout


@dataclass(slots=True)
class ProviderConfig:
    provider: str
    model: str
    api_key: str
    base_url: str | None = None
    temperature: float = 0.0
    max_tokens: int = 4096
    timeout: int = 60
    stream: bool = False
    connect_timeout: float | None = None
    read_timeout: float | None = None
    total_deadline: float | None = None
