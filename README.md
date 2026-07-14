![VISION](docs/assets/vision.webp)

# MCPRelay — Local MCP Gateway

A local MCP (Model Context Protocol) gateway with vision, filesystem, browser automation, shell access, file sharing and built-in OAuth authentication.

The goal of this tool is to let ChatGPT work through your local machine and browser instead of pushing everything through OpenAI or Codex context.

## Installation and usage

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

### 🖥️ Filesystem & Puppeteer (via npx)
| Tool | Description |
|---|---|
| `list_filesystem_available_tools` | List filesystem server tools |
| `list_puppeteer_available_tools` | List puppeteer server tools |
| `filesystem_execute_tool` | Execute a filesystem tool |
| `puppeteer_execute_tool` | Execute a puppeteer tool |

### 👁️ Vision & Automation
| Tool | Description |
|---|---|
| `vision_screen_size` | Screen dimensions |
| `vision_screenshot` | Take a screenshot (file) |
| `vision_screenshot_as_base64` | Take a screenshot (base64) |
| `mouse_position` | Current mouse position |
| `mouse_move` | Move the mouse |
| `mouse_click_at` | Click at a specific position |
| `mouse_click_current` | Click at the current position |
| `mouse_drag` | Drag the mouse |
| `mouse_scroll` | Scroll |
| `keyboard_type` | Type text |
| `keyboard_press` | Press a key |
| `keyboard_hotkey` | Key combination |

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
