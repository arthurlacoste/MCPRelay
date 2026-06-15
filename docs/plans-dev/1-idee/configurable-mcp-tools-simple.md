# Configurable MCP tools, simple version

## Context

Project: `/Users/art/Dropbox/dev/myMCP/`.

Goal: allow choosing which gateway tools and downstream MCP tools are available, without reintroducing DeepSeek, agents, scheduler, watchdog, or web UI complexity.

## Implemented approach

- `src/tool_registry.py`: small TOML config loader and enable/disable helpers.
- `config/tools.toml.example`: documented example config.
- `tests/test_tool_registry.py`: focused unit tests.
- `src/mcp_gateway.py`: uses `@configurable_tool(mcp)` instead of `@mcp.tool()` and checks downstream tool calls before execution.

## Config behavior

- Missing config means everything stays enabled.
- `[tools] my_tool = false` prevents gateway tool registration.
- `[downstream_mcp.<name>] enabled = false` disables an entire downstream MCP namespace.
- `[downstream_mcp.<name>.tools] tool_name = false` blocks one downstream tool.

## Risks

- Gateway must be restarted after config changes, because registration happens at import/startup.
- Downstream tool names must match names returned by the downstream MCP server.

## Tests

Current full suite result after implementation: `38 passed, 7 skipped, 1 warning`.
