# Official MCP SDK conformance gate

This package is deliberately isolated from the Python application dependency
graph. The application already owns a top-level `mcp` Python package, while the
official Python SDK also imports as `mcp`. Installing both into the same Python
environment would make import resolution depend on `sys.path` ordering.

The harness therefore uses the official stable v1 TypeScript SDK as a local
stdio client. It starts the repository's Python server as a child process and
verifies, without an LLM or network transport:

- `initialize` and `notifications/initialized` through `Client.connect()`;
- server identity, capabilities, and instructions returned by initialization;
- `tools/list`;
- a successful `tools/call` for the side-effect-free financial metrics tool;
- the default-deny governance response for a non-allowlisted call.

Install and run the gate from the repository root:

```bash
npm ci --ignore-scripts --prefix tests/mcp/official_sdk
npm test --prefix tests/mcp/official_sdk
```

The Python executable defaults to `python3` on POSIX and `python` on Windows.
Set `MCP_CONFORMANCE_PYTHON` when the application environment uses a different
executable:

```bash
MCP_CONFORMANCE_PYTHON=/path/to/python \
  npm test --prefix tests/mcp/official_sdk
```

Dependency installation may contact the npm registry. The conformance test
itself performs only local stdio subprocess communication.
