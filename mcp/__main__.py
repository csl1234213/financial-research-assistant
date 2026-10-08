"""Run the Financial Agent MCP server over stdio."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from .app import SUPPORTED_MCP_TOOLS, build_mcp_server
from .server import serve_stdio


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m mcp",
        description="Run the default-deny Financial Agent MCP stdio server.",
    )
    parser.add_argument(
        "--tenant-id",
        type=int,
        help="Trusted tenant scope for enabled tools.",
    )
    parser.add_argument(
        "--allow-tool",
        action="append",
        choices=sorted(SUPPORTED_MCP_TOOLS),
        default=[],
        help="Explicitly allow a tool; may be supplied more than once.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.allow_tool and (args.tenant_id is None or args.tenant_id <= 0):
        parser.error("--tenant-id must be positive when a tool is enabled")

    server = build_mcp_server(
        tenant_id=args.tenant_id,
        allowed_tools=args.allow_tool,
    )
    serve_stdio(server)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
