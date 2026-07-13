# MCPRelay agent guide

## Purpose

MCPRelay is a local MCP gateway exposed to ChatGPT through ngrok. It provides OAuth, filesystem access, shell execution, browser automation, public file sharing, screenshots, keyboard control, and mouse control.

User-facing installation and usage belong in `docs/installation.md`. Keep `README.md` short and product-focused.

## Project structure

```text
myMCP/
├── AGENTS.md                         # Agent and maintainer context
├── README.md                         # Short user-facing overview
├── requirements.txt                  # Canonical pinned Python dependencies
├── .env.example                      # Documented environment variables
├── config/
│   └── tools.toml.example            # Optional MCP tool enable/disable config
├── src/
│   ├── mcp_gateway.py                # MCP server, tools, logging, file sharing
│   ├── lightweight_oauth.py          # OAuth/OIDC endpoints and JWT creation
│   ├── tool_registry.py              # Configurable tool registry
│   └── userscript/
│       └── chatgpt-tools.user.js     # Optional ChatGPT browser userscript
├── tests/
│   ├── conftest.py                   # Shared OAuth fixtures
│   ├── test_oauth.py                 # OAuth unit tests
│   ├── test_mcp_endpoint.py          # Live endpoint integration tests
│   ├── test_conversation_logging.py  # Conversation logging tests
│   ├── test_run_command_conversation.py
│   ├── test_start_services.py        # Startup and platform path tests
│   └── test_tool_registry.py         # Tool configuration tests
├── docs/
│   ├── installation.md               # Cross-platform installation and usage
│   └── assets/                       # Lean WebP documentation screenshots
├── start_services.py                 # Cross-platform gateway supervisor
├── run.sh                            # macOS/Linux launcher
├── run.ps1                           # Windows launcher
└── pytest.ini                        # Pytest configuration
```

Runtime-only directories:

- `config/.env`: local secrets and public URL configuration.
- `data/`: OAuth state, private key, and file-share state.
- `logs/`: service, command, conversation, and screenshot logs.
- `.venv/`: Python environment.
- `node_modules/`: downloaded Node dependencies.

These must remain ignored by Git.

## Architecture

- Port `8761` serves MCP at `/mcp` and OAuth at `/oauth/*`.
- `start_services.py` creates the platform-specific virtualenv and installs `requirements.txt`.
- `run.sh` launches the supervisor and ngrok on macOS/Linux. It uses `caffeinate` when available.
- `run.ps1` launches the same processes on Windows.
- ChatGPT connects to the public ngrok URL followed by `/mcp`.
- OAuth client registration and token exchange are automatic. The ngrok authtoken never goes into ChatGPT.
- Tool availability is controlled through `config/tools.toml` when present.

## Discovery

Prefer codebase-memory MCP graph tools for code discovery:

1. `search_graph`
2. `trace_path`
3. `get_code_snippet`
4. `query_graph`
5. `get_architecture`

Use `rg` for literals, configs, documentation, shell scripts, and insufficient graph results.

## Development rules

- Keep files focused. Avoid expanding `src/mcp_gateway.py`; extract coherent features into modules when changing substantial behavior.
- Treat `requirements.txt` as the only Python dependency list. Do not duplicate package names in docs or startup code.
- Keep macOS, Linux, and Windows behavior aligned.
- Use `run.sh` for Unix-specific behavior and `run.ps1` for Windows-specific behavior.
- Never commit tokens, OAuth state, private keys, personal IDs, client data, logs, screenshots containing secrets, or user-specific absolute paths.

## Tests

Install:

```bash
python -m pip install -r requirements.txt
```

Run full suite:

```bash
pytest -q
```

Live MCP tests skip automatically when the local gateway is unavailable.

After code changes:

- Add or update focused pytest unit tests.
- For useful UI/form flows, add browserless coverage and screenshots.
- Run `git diff --check`.
- Validate `run.sh` with `bash -n run.sh` after shell changes.
- Note when Windows PowerShell validation was static because `pwsh` was unavailable.
