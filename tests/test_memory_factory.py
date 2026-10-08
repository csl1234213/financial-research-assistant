import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from agent.memory.base_memory import BaseMemory
from agent.memory.memory_enums import MemoryType
from agent.memory.memory_factory import MemoryFactory
from agent.memory.memory_registry import MemoryRegistry


class MockMemory(BaseMemory):
    @property
    def memory_name(self) -> str:
        return "mock"

    def supports(self, context):
        return True

    def store(self, context):
        return None

    def retrieve(self, context):
        return None


@pytest.fixture(autouse=True)
def reset_memory_factory_and_registry():
    MemoryRegistry.clear()
    MemoryFactory._default_memory = None
    yield
    MemoryRegistry.clear()
    MemoryFactory._default_memory = None


@pytest.mark.unit
class TestMemoryFactoryCreate:
    def test_create_with_string(self):
        MemoryRegistry.register("session", MockMemory)
        memory = MemoryFactory.create("session")
        assert isinstance(memory, MockMemory)

    def test_create_with_enum(self):
        MemoryRegistry.register("session", MockMemory)
        memory = MemoryFactory.create(MemoryType.SESSION)
        assert isinstance(memory, MockMemory)

    def test_create_with_workflow_enum(self):
        MemoryRegistry.register("workflow", MockMemory)
        memory = MemoryFactory.create(MemoryType.WORKFLOW)
        assert isinstance(memory, MockMemory)


@pytest.mark.unit
class TestMemoryFactoryDefault:
    def test_set_default_string(self):
        MemoryRegistry.register("session", MockMemory)
        MemoryFactory.set_default("session")
        assert MemoryFactory.get_default() == "session"

    def test_set_default_enum(self):
        MemoryRegistry.register("session", MockMemory)
        MemoryFactory.set_default(MemoryType.SESSION)
        assert MemoryFactory.get_default() == "session"

    def test_set_default_invalid_string_raises(self):
        with pytest.raises(KeyError):
            MemoryFactory.set_default("unknown")

    def test_set_default_invalid_enum_raises(self):
        with pytest.raises(KeyError):
            MemoryFactory.set_default(MemoryType.SHORT_TERM)

    def test_get_default_none(self):
        assert MemoryFactory.get_default() is None

    def test_create_default_when_set(self):
        MemoryRegistry.register("session", MockMemory)
        MemoryFactory.set_default("session")
        memory = MemoryFactory.create_default()
        assert isinstance(memory, MockMemory)

    def test_create_default_when_none_raises(self):
        MemoryFactory._default_memory = None
        with pytest.raises(RuntimeError):
            MemoryFactory.create_default()
