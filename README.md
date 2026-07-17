![VISION](docs/assets/vision.webp)

# Gate — Local MCP Gateway

A local MCP (Model Context Protocol) gateway with configurable MCP subservers, shell access, file sharing and built-in OAuth authentication.

The goal of this tool is to let ChatGPT work through your local machine and browser instead of pushing everything through OpenAI or Codex context.

## Installation and usage

Install Gate on macOS, Linux or WSL:

```bash
curl -fsSL https://raw.githubusercontent.com/arthurlacoste/gate/main/install.sh | bash
```

Then run:

```bash
gate
```

See the **[installation and usage guide](docs/installation.md)**.

---

## 🛠️ Available MCP Tools

### 🔐 Authentication
| Tool | Description |
|---|---|
| `auth_status` | OAuth status: issuer, audience, base_url |

### 📁 File Sharing
| Tool | Description |
|---|---|
| `public_file_share` | Share a file via a public URL |
| `public_file_list` | List active shares |
| `public_file_revoke` | Revoke a share |

### 🔌 Configurable MCP subservers

Servers from `config/mcp.json` are exposed directly with namespaced tools. The included example configures Computer Use as `computer_use_*`.

### 💻 Commands
| Tool | Description |
|---|---|
| `run_command` | Execute a shell command with streaming |

---

## 🧪 Tests

### OAuth unit tests (29 tests — no external dependencies)

```bash
pytest tests/test_oauth.py -v
```

Covers: metadata, client registration, authorization, token exchange, PKCE (S256), JWKS, JWT validation, expired codes, code reuse, edge cases.

### MCP integration tests (7 tests — requires the gateway to be running)

```bash
# Gateway must be running (./run.sh start), then:
pytest tests/test_mcp_endpoint.py -v
```

Covers: reachability, OAuth health, discovery, live JWKS, full OAuth flow (register → authorize → token), JSON-RPC call (`initialize` + `tools/list`).

### Full test suite

```bash
pytest tests/ -v
```

> MCP integration tests are automatically **skipped** if the gateway is unreachable (localhost:8761). No false failures in CI or offline.

---

## ⚠️ Security

- `run_command` executes shell commands **without restrictions** — use with caution
- OAuth tokens are signed with a local RSA key (generated in `data/oauth_private_key.pem`)
- Files shared via `public_file_share` are accessible without authentication
- Command logs contain all input/output — do not expose logs


## 📝 License

This project is licensed under the MIT License.
