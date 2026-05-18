# MCPRelay — Local MCP Gateway

MCPRelay is a local MCP (Model Context Protocol) gateway with vision, filesystem, puppeteer tools and built-in OAuth authentication.

Its purpose is to bypass token limitation by using front end Chrome ChatGPT access. The included ChatGPT userscript can detect a ChatGPT MCP app configured with a matching name, then relay requests through the browser session.

## 📦 Prerequisites

- Python 3.10+
- Node.js 18+ (for `npx`)
- [ngrok](https://ngrok.com/) (to expose the service over HTTPS)
- [Tampermonkey](https://www.tampermonkey.net/) or Violentmonkey in Chrome
- Install the included ChatGPT userscript from this repository
- **Screen Recording** permission (macOS) for vision/screenshot tools

## 🚀 Installation

### 1. Create the venv and install dependencies

```bash
# From the project root
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install fastmcp python-dotenv fastapi uvicorn pyjwt cryptography python-multipart pyautogui pillow
```

### 2. Configure environment variables

Create a `config/.env` file at the root (or copy an existing `.env`):

```bash
# Required
MCP_BASE_URL=https://your-subdomain.ngrok-free.dev

# OAuth (optional, defaults provided)
OAUTH_ISSUER=https://your-subdomain.ngrok-free.dev/oauth
OAUTH_AUDIENCE=https://mcp.local
OAUTH_PORT=8762
OAUTH_TOKEN_TTL_SECONDS=3600

# OAuth on/off
ENABLE_OAUTH=true

# OAuth key (auto-generated if missing)
OAUTH_KEY_ID=local-dev-key
```

> ⚠️ `MCP_BASE_URL` and `OAUTH_ISSUER` must point to your ngrok URL.

## 🏁 Getting Started

### Option A — `run.sh` all-in-one (recommended)

```bash
# Interactive mode — Ctrl+C stops gateway + ngrok
./run.sh

# Daemon mode (background)
./run.sh start

# Stop the daemon
./run.sh stop

# Check daemon status
./run.sh status
```

The script handles everything: venv activation, gateway startup, ngrok tunnel.

### Option B — Simple automated launch

```bash
python3 start_services.py
```

Starts the single **Gateway** service (MCP + OAuth integrated) on port `8761`.

Logs are written to `logs/services/gateway.log`.

### Option C — Manual launch

```bash
source .venv/bin/activate
python3 src/mcp_gateway.py
# → http://localhost:8761/mcp
# → http://localhost:8761/oauth/...
```

## 🌐 Exposing via ngrok

```bash
# A single tunnel is enough — the gateway serves MCP + OAuth on the same port
ngrok http 8761
# → https://xxxx-xxxx-xxxx.ngrok-free.dev
```

The generated URL becomes your `MCP_BASE_URL` in `config/.env`.

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

## 📂 Project Structure

```
MCPRelay/
├── config/
│   └── .env                 # Environment variables
├── data/
│   ├── oauth_clients.json
│   ├── oauth_codes.json
│   ├── oauth_private_key.pem
│   └── public_file_shares.json
├── logs/
│   ├── commands/            # Executed command logs
│   ├── services/            # Gateway logs
│   └── vision/              # Screenshots
├── src/
│   ├── mcp_gateway.py       # Unified MCP + OAuth server (port 8761)
│   └── lightweight_oauth.py # OAuth module (imported by the gateway)
├── tests/
│   ├── conftest.py          # Shared fixtures
│   ├── test_oauth.py        # 29 OAuth unit tests
│   └── test_mcp_endpoint.py # 7 MCP integration tests
├── docs/
│   └── plans-dev/           # Development plans
├── run.sh                   # All-in-one manager (interactive + daemon)
├── start_services.py        # Single service launcher
├── pytest.ini               # Pytest configuration
├── .env                     # Environment variables (fallback)
└── README.md
```

## 🔗 Connecting from an MCP Client

### Example with ChatGPT (OAuth connector)

1. Start ngrok on port **8761**
2. Set `MCP_BASE_URL` to your ngrok URL
3. In ChatGPT, create a new MCP app with a name that starts with `MCP DL`, for example `MCP DL`. This prefix is required so the userscript can detect it.
4. In ChatGPT, use the URL:
   ```
   https://your-url.ngrok-free.dev/mcp
   ```
5. OAuth is handled automatically via the endpoint mounted at `/oauth`

### Example with `fastmcp` CLI

```bash
fastmcp dev src/mcp_gateway.py
```

Or directly over HTTP:

```bash
curl -X POST https://your-url.ngrok-free.dev/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/list",
    "id": 1
  }'
```

## 🧪 Verify Everything is Running

```bash
# OAuth service health
curl http://localhost:8762/oauth/health

# OAuth metadata
curl http://localhost:8762/oauth/.well-known/oauth-authorization-server

# JWKS
curl http://localhost:8762/oauth/jwks.json
```

## ⚠️ Security

- `run_command` executes shell commands **without restrictions** — use with caution
- OAuth tokens are signed with a local RSA key (generated in `data/oauth_private_key.pem`)
- Files shared via `public_file_share` are accessible without authentication
- Command logs contain all input/output — do not expose logs

## ChatGPT Userscript Helpers

This project also includes a small merged userscript for ChatGPT automation.

Features:
- Auto-send prompts from `?prompt=` URLs
- Auto-open the latest conversation from the homepage
- Auto-approve MCP action cards
- Detect ChatGPT MCP apps whose name starts with `MCP DL`

Example:

```txt
https://chatgpt.com/?prompt=Explain%20this%20repository
```

The script is designed for Tampermonkey / Violentmonkey and is intentionally lightweight.
