import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from abc import ABC
from dataclasses import is_dataclass

import pytest

from agent.tools.base_tool import BaseTool
from agent.tools.tool_context import ToolContext
from agent.tools.tool_enums import ToolPriority, ToolStatus, ToolType
from agent.tools.tool_models import ToolCapability, ToolMetadata
from agent.tools.tool_result import ToolResult


class TestToolEnums:

    def test_tool_type_values(self):
        assert ToolType.RETRIEVAL.value == "retrieval"
        assert ToolType.OCR.value == "ocr"
        assert ToolType.PYTHON.value == "python"
        assert ToolType.SQL.value == "sql"
        assert ToolType.HTTP.value == "http"
        assert ToolType.FILE.value == "file"
        assert ToolType.CUSTOM.value == "custom"
        assert len(ToolType) == 7

    def test_tool_type_is_str_enum(self):
        assert isinstance(ToolType.RETRIEVAL, str)
        assert ToolType.RETRIEVAL == "retrieval"

    def test_tool_status_values(self):
        assert ToolStatus.PENDING.value == "pending"
        assert ToolStatus.RUNNING.value == "running"
        assert ToolStatus.SUCCESS.value == "success"
        assert ToolStatus.FAILED.value == "failed"
        assert ToolStatus.SKIPPED.value == "skipped"
        assert len(ToolStatus) == 5

    def test_tool_status_is_str_enum(self):
        assert isinstance(ToolStatus.SUCCESS, str)
        assert ToolStatus.SUCCESS == "success"

    def test_tool_priority_values(self):
        assert ToolPriority.LOW.value == "low"
        assert ToolPriority.NORMAL.value == "normal"
        assert ToolPriority.HIGH.value == "high"
        assert ToolPriority.CRITICAL.value == "critical"
        assert len(ToolPriority) == 4

    def test_tool_priority_is_str_enum(self):
        assert isinstance(ToolPriority.HIGH, str)
        assert ToolPriority.HIGH == "high"


class TestToolModels:

    def test_tool_capability_defaults(self):
        cap = ToolCapability()
        assert cap.supports_parallel is False
        assert cap.supports_stream is False
        assert cap.supports_retry is False
        assert cap.supports_async is False

    def test_tool_capability_custom(self):
        cap = ToolCapability(
            supports_parallel=True,
            supports_stream=True,
            supports_retry=True,
            supports_async=True,
        )
        assert cap.supports_parallel is True
        assert cap.supports_stream is True
        assert cap.supports_retry is True
        assert cap.supports_async is True

    def test_tool_capability_is_dataclass(self):
        assert is_dataclass(ToolCapability)

    def test_tool_capability_has_slots(self):
        cap = ToolCapability()
        with pytest.raises(AttributeError):
            cap.non_existent = 1

    def test_tool_metadata_creation(self):
        cap = ToolCapability(supports_parallel=True)
        meta = ToolMetadata(
            name="test_tool",
            tool_type=ToolType.PYTHON,
            description="A test tool for unit testing",
            version="1.0.0",
            capability=cap,
            metadata={"author": "test"},
        )
        assert meta.name == "test_tool"
        assert meta.tool_type == ToolType.PYTHON
        assert meta.description == "A test tool for unit testing"
        assert meta.version == "1.0.0"
        assert meta.capability == cap
        assert meta.metadata == {"author": "test"}

    def test_tool_metadata_default_capability(self):
        meta = ToolMetadata(
            name="minimal",
            tool_type=ToolType.CUSTOM,
            description="Minimal tool",
            version="0.0.1",
        )
        assert isinstance(meta.capability, ToolCapability)
        assert meta.metadata == {}

    def test_tool_metadata_is_dataclass(self):
        assert is_dataclass(ToolMetadata)

    def test_tool_metadata_has_slots(self):
        meta = ToolMetadata(
            name="test",
            tool_type=ToolType.CUSTOM,
            description="test",
            version="0.0.1",
        )
        with pytest.raises(AttributeError):
            meta.non_existent = 1


class TestToolContext:

    def test_tool_context_defaults(self):
        ctx = ToolContext()
        assert ctx.runtime_state is None
        assert ctx.workflow is None
        assert ctx.execution is None
        assert ctx.memory is None
        assert ctx.parameters == {}

    def test_tool_context_with_parameters(self):
        ctx = ToolContext(parameters={"key": "value", "num": 42})
        assert ctx.parameters == {"key": "value", "num": 42}

    def test_tool_context_is_dataclass(self):
        assert is_dataclass(ToolContext)

    def test_tool_context_has_slots(self):
        ctx = ToolContext()
        with pytest.raises(AttributeError):
            ctx.non_existent = 1

    def test_tool_context_type_hints_are_optional(self):
        ann = ToolContext.__annotations__
        assert "runtime_state" in ann
        assert "workflow" in ann
        assert "execution" in ann
        assert "memory" in ann
        assert "parameters" in ann


class TestToolResult:

    def test_tool_result_success(self):
        result = ToolResult(
            status=ToolStatus.SUCCESS,
            output="Execution completed",
            latency_ms=42.5,
        )
        assert result.status == ToolStatus.SUCCESS
        assert result.output == "Execution completed"
        assert result.latency_ms == 42.5
        assert result.error is None
        assert result.artifacts == []
        assert result.metadata == {}

    def test_tool_result_failure(self):
        result = ToolResult(
            status=ToolStatus.FAILED,
            error="Connection timeout",
            latency_ms=1000.0,
        )
        assert result.status == ToolStatus.FAILED
        assert result.error == "Connection timeout"
        assert result.output is None

    def test_tool_result_with_artifacts(self):
        result = ToolResult(
            status=ToolStatus.SUCCESS,
            output="Chart generated",
            artifacts=["chart.png", "data.csv"],
            metadata={"rows": 100},
        )
        assert len(result.artifacts) == 2
        assert "chart.png" in result.artifacts
        assert "data.csv" in result.artifacts
        assert result.metadata == {"rows": 100}

    def test_tool_result_is_dataclass(self):
        assert is_dataclass(ToolResult)

    def test_tool_result_has_slots(self):
        result = ToolResult(status=ToolStatus.SUCCESS)
        with pytest.raises(AttributeError):
            result.non_existent = 1

    def test_tool_result_default_latency(self):
        result = ToolResult(status=ToolStatus.SUCCESS)
        assert result.latency_ms == 0.0


class TestBaseTool:

    def test_base_tool_is_abstract(self):
        assert issubclass(BaseTool, ABC)

    def test_base_tool_cannot_instantiate(self):
        with pytest.raises(TypeError):
            BaseTool()

    def test_base_tool_has_metadata_property(self):
        assert hasattr(BaseTool, "metadata")
        ann = BaseTool.metadata.fget.__annotations__
        assert ann["return"] == ToolMetadata

    def test_base_tool_has_supports_method(self):
        assert hasattr(BaseTool, "supports")

    def test_base_tool_has_execute_method(self):
        assert hasattr(BaseTool, "execute")

    def test_concrete_tool_implementation(self):
        class FakeTool(BaseTool):
            @property
            def metadata(self) -> ToolMetadata:
                return ToolMetadata(
                    name="fake",
                    tool_type=ToolType.CUSTOM,
                    description="Fake tool for testing",
                    version="0.0.1",
                )

            def supports(self, context: ToolContext) -> bool:
                return True

            def execute(self, context: ToolContext) -> ToolResult:
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    output="Fake executed",
                    latency_ms=1.0,
                )

        tool = FakeTool()
        assert isinstance(tool, BaseTool)
        assert tool.metadata.name == "fake"
        assert tool.metadata.tool_type == ToolType.CUSTOM

        ctx = ToolContext(parameters={"input": "test"})
        assert tool.supports(ctx) is True

        result = tool.execute(ctx)
        assert result.status == ToolStatus.SUCCESS
        assert result.output == "Fake executed"
        assert result.latency_ms == 1.0


class TestToolLayerNoRuntimeCoupling:

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

    def test_tool_enums_no_runtime_import(self):
        import agent.tools.tool_enums as m
        assert self._check_no_runtime_import(m)

    def test_tool_models_no_runtime_import(self):
        import agent.tools.tool_models as m
        assert self._check_no_runtime_import(m)

    def test_tool_result_no_runtime_import(self):
        import agent.tools.tool_result as m
        assert self._check_no_runtime_import(m)

    def test_base_tool_no_runtime_import(self):
        import agent.tools.base_tool as m
        assert self._check_no_runtime_import(m)
