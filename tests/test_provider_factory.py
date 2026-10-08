import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from llm.factory.provider_factory import ProviderFactory
from llm.providers.provider_config import ProviderConfig
from llm.providers.provider_registry import ProviderRegistry


@pytest.fixture(autouse=True)
def reset_provider_factory_and_registry():
    ProviderRegistry.clear()
    ProviderFactory._default_provider = None
    yield
    ProviderRegistry.clear()
    ProviderFactory._default_provider = None


class MockProvider:
    def __init__(self, config):
        self.config = config


@pytest.mark.unit
class TestProviderFactoryCreate:
    def test_create_with_config(self):
        ProviderRegistry.register("deepseek", MockProvider)
        config = ProviderConfig(
            provider="deepseek",
            model="deepseek-v4-flash",
            api_key="sk-123",
        )
        provider = ProviderFactory.create(config)
        assert isinstance(provider, MockProvider)

    def test_create_with_string(self):
        ProviderRegistry.register("deepseek", MockProvider)
        provider = ProviderFactory.create("deepseek")
        assert isinstance(provider, MockProvider)

    def test_create_unknown_provider_raises(self):
        with pytest.raises(Exception):
            ProviderFactory.create("unknown_provider")


@pytest.mark.unit
class TestProviderFactoryDefault:
    def test_set_default_valid(self):
        ProviderRegistry.register("deepseek", MockProvider)
        ProviderFactory.set_default("deepseek")
        assert ProviderFactory.get_default() == "deepseek"

    def test_set_default_invalid_raises(self):
        with pytest.raises(Exception):
            ProviderFactory.set_default("unknown_provider")

    def test_get_default_none(self):
        assert ProviderFactory.get_default() is None

    def test_create_default_when_set(self):
        ProviderRegistry.register("deepseek", MockProvider)
        ProviderFactory.set_default("deepseek")
        provider = ProviderFactory.create_default()
        assert isinstance(provider, MockProvider)

    def test_create_default_when_none_raises(self):
        ProviderFactory._default_provider = None
        with pytest.raises(Exception):
            ProviderFactory.create_default()


@pytest.mark.unit
class TestProviderFactoryList:
    def test_list_providers(self):
        ProviderRegistry.register("deepseek", MockProvider)
        ProviderRegistry.register("gemini", MockProvider)
        providers = ProviderFactory.list_providers()
        assert "deepseek" in providers
        assert "gemini" in providers
        assert len(providers) == 2

    def test_list_providers_empty(self):
        providers = ProviderFactory.list_providers()
        assert providers == []
