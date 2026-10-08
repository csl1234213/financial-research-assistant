import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from agent.tools.base_tool import BaseTool
from agent.tools.implementations import (
    HttpTool,
    PythonTool,
    RetrievalTool,
    SQLTool,
)
from agent.tools.retrieval_contract import trusted_retrieval_adapter
from agent.tools.tool_context import ToolContext
from agent.tools.tool_enums import ToolStatus, ToolType
from agent.tools.tool_exceptions import (
    ToolError,
    ToolNotFound,
    ToolRegistrationError,
)
from agent.tools.tool_factory import ToolFactory
from agent.tools.tool_models import ToolMetadata
from agent.tools.tool_registry import ToolRegistry
from agent.tools.tool_result import ToolResult


class TestToolExceptions:

    def setup_method(self):
        ToolRegistry.clear()

    def teardown_method(self):
        ToolRegistry.clear()

    def test_tool_error_is_base(self):
        assert issubclass(ToolError, Exception)

    def test_tool_not_found_is_tool_error(self):
        assert issubclass(ToolNotFound, ToolError)

    def test_tool_registration_error_is_tool_error(self):
        assert issubclass(ToolRegistrationError, ToolError)

    def test_tool_not_found_message(self):
        with pytest.raises(ToolNotFound, match="sql"):
            ToolRegistry.get("sql")

    def test_tool_registration_error_message(self):
        class NotATool:
            pass
        with pytest.raises(ToolRegistrationError, match="NotATool"):
            ToolRegistry.register("bad", NotATool)


class TestToolRegistry:

    def setup_method(self):
        ToolRegistry.clear()

    def teardown_method(self):
        ToolRegistry.clear()

    def test_register_and_get(self):
        ToolRegistry.register("retrieval", RetrievalTool)
        assert ToolRegistry.get("retrieval") == RetrievalTool

    def test_register_with_metadata(self):
        meta = ToolMetadata(
            name="custom",
            tool_type=ToolType.CUSTOM,
            description="Custom tool",
            version="1.0.0",
        )
        ToolRegistry.register("custom", RetrievalTool, metadata=meta)
        assert ToolRegistry.get_metadata("custom") == meta

    def test_has_tool_positive(self):
        ToolRegistry.register("sql", SQLTool)
        assert ToolRegistry.has_tool("sql") is True

    def test_has_tool_negative(self):
        assert ToolRegistry.has_tool("nonexistent") is False

    def test_list_tools_empty(self):
        assert ToolRegistry.list_tools() == []

    def test_list_tools_after_register(self):
        ToolRegistry.register("retrieval", RetrievalTool)
        ToolRegistry.register("sql", SQLTool)
        assert sorted(ToolRegistry.list_tools()) == ["retrieval", "sql"]

    def test_get_not_found(self):
        with pytest.raises(ToolNotFound):
            ToolRegistry.get("nonexistent")

    def test_get_metadata_not_found(self):
        ToolRegistry.register("retrieval", RetrievalTool)
        with pytest.raises(ToolNotFound):
            ToolRegistry.get_metadata("retrieval")

    def test_clear(self):
        ToolRegistry.register("retrieval", RetrievalTool)
        ToolRegistry.register("sql", SQLTool)
        ToolRegistry.clear()
        assert ToolRegistry.list_tools() == []

    def test_clear_also_clears_metadata(self):
        ToolRegistry.register("retrieval", RetrievalTool, metadata=RetrievalTool().metadata)
        ToolRegistry.clear()
        assert ToolRegistry.list_tools() == []
        with pytest.raises(ToolNotFound):
            ToolRegistry.get_metadata("retrieval")

    def test_register_invalid_subclass(self):
        class FakeClass:
            pass
        with pytest.raises(ToolRegistrationError):
            ToolRegistry.register("fake", FakeClass)

    def test_list_tools_by_type(self):
        ToolRegistry.register("retrieval", RetrievalTool, metadata=RetrievalTool().metadata)
        ToolRegistry.register("sql", SQLTool, metadata=SQLTool().metadata)
        ToolRegistry.register("http", HttpTool, metadata=HttpTool().metadata)

        retrieval_tools = ToolRegistry.list_tools_by_type(ToolType.RETRIEVAL)
        assert "retrieval" in retrieval_tools
        assert "sql" not in retrieval_tools

        sql_tools = ToolRegistry.list_tools_by_type(ToolType.SQL)
        assert "sql" in sql_tools

    def test_register_duplicate_overwrites(self):
        ToolRegistry.register("retrieval", RetrievalTool)
        ToolRegistry.register("retrieval", SQLTool)
        assert ToolRegistry.get("retrieval") == SQLTool


class TestToolFactory:

    def setup_method(self):
        ToolRegistry.clear()
        ToolFactory._default_tool = None
        ToolRegistry.register("retrieval", RetrievalTool, metadata=RetrievalTool().metadata)
        ToolRegistry.register("python", PythonTool, metadata=PythonTool().metadata)
        ToolRegistry.register("sql", SQLTool, metadata=SQLTool().metadata)
        ToolRegistry.register("http", HttpTool, metadata=HttpTool().metadata)

    def teardown_method(self):
        ToolRegistry.clear()
        ToolFactory._default_tool = None

    def test_create_by_string(self):
        tool = ToolFactory.create("sql")
        assert isinstance(tool, SQLTool)
        assert isinstance(tool, BaseTool)

    def test_create_by_tool_type(self):
        tool = ToolFactory.create(ToolType.PYTHON)
        assert isinstance(tool, PythonTool)

    def test_create_by_tool_type_value(self):
        tool = ToolFactory.create(ToolType.RETRIEVAL)
        assert isinstance(tool, RetrievalTool)

    def test_create_all_types(self):
        for name, expected_cls in [
            ("retrieval", RetrievalTool),
            ("python", PythonTool),
            ("sql", SQLTool),
            ("http", HttpTool),
        ]:
            tool = ToolFactory.create(name)
            assert isinstance(tool, expected_cls)

    def test_set_default_and_create_default(self):
        ToolFactory.set_default("http")
        tool = ToolFactory.create_default()
        assert isinstance(tool, HttpTool)

    def test_set_default_by_tool_type(self):
        ToolFactory.set_default(ToolType.SQL)
        assert ToolFactory.get_default() == "sql"

    def test_create_default_without_setting(self):
        with pytest.raises(RuntimeError, match="No default tool set"):
            ToolFactory.create_default()

    def test_set_default_nonexistent(self):
        with pytest.raises(KeyError, match="nonexistent"):
            ToolFactory.set_default("nonexistent")

    def test_get_default_none(self):
        assert ToolFactory.get_default() is None


class TestToolImplementations:

    def test_retrieval_tool_metadata(self):
        tool = RetrievalTool()
        meta = tool.metadata
        assert meta.name == "retrieval"
        assert meta.tool_type == ToolType.RETRIEVAL
        assert meta.version == "2.0.0"
        assert meta.capability.supports_parallel is True
        assert meta.capability.supports_async is False

    def test_python_tool_metadata(self):
        tool = PythonTool()
        meta = tool.metadata
        assert meta.name == "python"
        assert meta.tool_type == ToolType.PYTHON
        assert meta.capability.supports_parallel is False
        assert meta.metadata["availability"] == "disabled"

    def test_sql_tool_metadata(self):
        tool = SQLTool()
        meta = tool.metadata
        assert meta.name == "sql"
        assert meta.tool_type == ToolType.SQL
        assert meta.metadata["availability"] == "disabled"

    def test_http_tool_metadata(self):
        tool = HttpTool()
        meta = tool.metadata
        assert meta.name == "http"
        assert meta.tool_type == ToolType.HTTP
        assert meta.metadata["availability"] == "disabled"

    def test_retrieval_tool_supports(self):
        tool = RetrievalTool()
        assert tool.supports(ToolContext()) is True

    def test_retrieval_tool_requires_a_real_contract(self):
        tool = RetrievalTool()
        result = tool.execute(ToolContext())
        assert isinstance(result, ToolResult)
        assert result.status == ToolStatus.FAILED
        assert result.metadata["tool"] == "RetrievalTool"
        assert result.metadata["failure_code"] == "invalid_request"

    def test_retrieval_tool_uses_explicit_trusted_adapter(self):
        adapter = trusted_retrieval_adapter(
            lambda request: [{"content": request.query, "source": "report.pdf", "score": 0.8}],
            name="test_adapter",
        )
        result = RetrievalTool().execute(
            ToolContext(
                tenant_id=8,
                parameters={"query": "Revenue growth", "retrieval_adapter": adapter},
            )
        )
        assert result.status == ToolStatus.SUCCESS
        assert result.output["evidence"][0]["source_filename"] == "report.pdf"

    def test_python_tool_execute(self):
        tool = PythonTool()
        result = tool.execute(ToolContext())
        assert isinstance(result, ToolResult)
        assert result.status == ToolStatus.SKIPPED
        assert result.metadata["availability"] == "disabled"

    def test_sql_tool_execute(self):
        tool = SQLTool()
        result = tool.execute(ToolContext())
        assert isinstance(result, ToolResult)
        assert result.status == ToolStatus.SKIPPED
        assert result.metadata["availability"] == "disabled"

    def test_http_tool_execute(self):
        tool = HttpTool()
        result = tool.execute(ToolContext())
        assert isinstance(result, ToolResult)
        assert result.status == ToolStatus.SKIPPED
        assert result.metadata["availability"] == "disabled"

    def test_all_tools_are_base_tool_subclass(self):
        for tool_cls in [RetrievalTool, PythonTool, SQLTool, HttpTool]:
            assert issubclass(tool_cls, BaseTool)

    def test_all_tools_can_be_instantiated(self):
        for tool_cls in [RetrievalTool, PythonTool, SQLTool, HttpTool]:
            instance = tool_cls()
            assert isinstance(instance, BaseTool)


class TestToolRegistryNoRuntimeCoupling:

    def _check_no_runtime_import(self, module):
        source = module.__file__
        with open(source, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""'):
                continue
            if "from agent.agent_runtime" in stripped or "import agent.agent_runtime" in stripped:
                return False
        return True

    def test_tool_registry_no_runtime_import(self):
        import agent.tools.tool_registry as m
        assert self._check_no_runtime_import(m)

    def test_tool_factory_no_runtime_import(self):
        import agent.tools.tool_factory as m
        assert self._check_no_runtime_import(m)

    def test_tool_exceptions_no_runtime_import(self):
        import agent.tools.tool_exceptions as m
        assert self._check_no_runtime_import(m)
