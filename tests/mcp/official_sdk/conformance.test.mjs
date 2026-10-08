import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const HARNESS_DIRECTORY = path.dirname(fileURLToPath(import.meta.url));
const REPOSITORY_ROOT = path.resolve(HARNESS_DIRECTORY, "..", "..", "..");
const PYTHON_COMMAND =
  process.env.MCP_CONFORMANCE_PYTHON ??
  (process.platform === "win32" ? "python" : "python3");
const TEST_TIMEOUT_MS = 20_000;

function createClientAndTransport(serverArguments = []) {
  const client = new Client(
    {
      name: "financial-agent-official-sdk-conformance",
      version: "1.0.0",
    },
    {
      capabilities: {},
    },
  );
  const transport = new StdioClientTransport({
    command: PYTHON_COMMAND,
    args: ["-m", "mcp", ...serverArguments],
    cwd: REPOSITORY_ROOT,
    stderr: "pipe",
  });
  return { client, transport };
}

async function withConnectedClient(serverArguments, assertion) {
  const { client, transport } = createClientAndTransport(serverArguments);
  let stderr = "";
  transport.stderr?.on("data", (chunk) => {
    stderr += chunk.toString();
  });

  try {
    await client.connect(transport);
    await assertion(client);
  } catch (error) {
    if (stderr.trim()) {
      error.message = `${error.message}\nMCP server stderr:\n${stderr.trim()}`;
    }
    throw error;
  } finally {
    await client.close();
  }
}

test(
  "official SDK initializes, discovers, and calls the governed stdio tool",
  { timeout: TEST_TIMEOUT_MS },
  async () => {
    await withConnectedClient(
      [
        "--tenant-id",
        "17",
        "--allow-tool",
        "financial_metrics",
      ],
      async (client) => {
        const serverVersion = client.getServerVersion();
        const capabilities = client.getServerCapabilities();

        assert.equal(serverVersion?.name, "financial-agent-tools");
        assert.match(serverVersion?.version ?? "", /^\d+\.\d+\.\d+$/);
        assert.equal(capabilities?.tools?.listChanged, false);
        assert.match(
          client.getInstructions() ?? "",
          /tenant-scoped and default-deny/i,
        );

        const listed = await client.listTools();
        assert.deepEqual(
          listed.tools.map((tool) => tool.name),
          ["financial_metrics"],
        );
        assert.equal(
          listed.tools[0].inputSchema.properties.operation.type,
          "string",
        );

        const called = await client.callTool({
          name: "financial_metrics",
          arguments: {
            operation: "growth_rate",
            current: 125,
            previous: 100,
            precision: 2,
          },
        });

        assert.equal(called.isError, false);
        assert.equal(called.structuredContent.status, "success");
        assert.equal(called.structuredContent.output.value, 25);
        assert.equal(called.structuredContent.metadata.side_effects, "none");
      },
    );
  },
);

test(
  "official SDK observes the server's default-deny governance boundary",
  { timeout: TEST_TIMEOUT_MS },
  async () => {
    await withConnectedClient([], async (client) => {
      const listed = await client.listTools();
      assert.deepEqual(listed.tools, []);

      await assert.rejects(
        client.callTool({
          name: "financial_metrics",
          arguments: {
            operation: "growth_rate",
            current: 125,
            previous: 100,
          },
        }),
        (error) => {
          assert.equal(error.code, -32001);
          assert.match(error.message, /not in the allowlist/i);
          return true;
        },
      );
    });
  },
);
