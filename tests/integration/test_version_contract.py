"""Cross-boundary release version consistency checks."""

from pathlib import Path

from agent.__version__ import BASE_VERSION, __version__
from config import APP_VERSION as CONFIG_VERSION
from config.app import APP_VERSION as APP_CONFIG_VERSION
from mcp import MCP_PROTOCOL_VERSION
from mcp.app import build_mcp_server

ROOT = Path(__file__).resolve().parents[2]


def _env_value(path: Path, name: str) -> str:
    prefix = f"{name}="
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            return line.removeprefix(prefix)
    raise AssertionError(f"{name} is missing from {path}")


def test_runtime_configuration_uses_the_release_version_authority() -> None:
    assert BASE_VERSION == "8.2.0"
    assert CONFIG_VERSION == __version__
    assert APP_CONFIG_VERSION == __version__


def test_environment_templates_track_the_source_release_version() -> None:
    assert _env_value(ROOT / ".env.example", "APP_VERSION") == BASE_VERSION
    assert _env_value(ROOT / "deploy" / ".env.example", "APP_VERSION") == BASE_VERSION
    assert _env_value(ROOT / "deploy" / ".env.dev", "APP_VERSION") == BASE_VERSION
    assert _env_value(ROOT / "deploy" / ".env.prod", "APP_VERSION") == BASE_VERSION


def test_mcp_initialize_reports_the_runtime_release_version() -> None:
    server = build_mcp_server(tenant_id=None)

    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "version-contract-test",
                    "version": "1.0.0",
                },
            },
        }
    )

    assert response is not None
    assert response["result"]["serverInfo"]["version"] == __version__
