# ============================================================
# BaseProvider — Abstract interface for all LLM providers
# ============================================================
# Every concrete provider (DeepSeek, Claude, Gemini, etc.)
# must implement this interface.
# ============================================================

from abc import ABC, abstractmethod
from typing import List

from .provider_models import ChatRequest, ChatResponse, ProviderCapability


class BaseProvider(ABC):
    @abstractmethod
    def chat(self, request: ChatRequest) -> ChatResponse:
        pass

    @abstractmethod
    def health(self) -> bool:
        pass

    @abstractmethod
    def list_models(self) -> List[str]:
        pass

    @abstractmethod
    def get_capability(self) -> ProviderCapability:
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass
