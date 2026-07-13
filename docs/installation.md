# Install and use MCPRelay with ChatGPT

Cross-platform guide for macOS, Linux, and Windows. The local gateway listens on port `8761`. ngrok exposes this port over HTTPS. ChatGPT connects to `/mcp` and handles the OAuth flow automatically.

## 1. Requirements

- GitHub account with repository access.
- Python 3.10 or newer.
- Node.js 18 or newer.
- [ngrok](https://dashboard.ngrok.com/signup) account.
- ChatGPT web. Full MCP support depends on your plan and workspace permissions.
- A logged-in graphical desktop session for screenshot, keyboard, and mouse tools.

Check installed versions:

```text
git --version
python --version
node --version
```

## 2. Clone the repository

HTTPS:

```bash
git clone https://github.com/arthurlacoste/MCPRelay.git myMCP
cd myMCP
```

## 3. Install Python dependencies

### macOS and Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Windows PowerShell

```powershell
py -3 -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`requirements.txt` is the single source of truth for Python dependencies. `start_services.py` installs from this file at startup, so package names and versions are not duplicated.

## 4. Install and connect ngrok

### macOS

```bash
brew install ngrok
```

### Debian or Ubuntu Linux

```bash
curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc \
  | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
echo "deb https://ngrok-agent.s3.amazonaws.com bookworm main" \
  | sudo tee /etc/apt/sources.list.d/ngrok.list
sudo apt update
sudo apt install ngrok
```

For other Linux distributions and CPU architectures, use the [official Linux download page](https://ngrok.com/download/linux).

### Windows PowerShell

```powershell
winget install ngrok -s msstore
```

Alternative: use the [official Windows installer or standalone executable](https://ngrok.com/download/windows).

### Connect the ngrok account

Create an ngrok account. Open [Your Authtoken](https://dashboard.ngrok.com/get-started/your-authtoken). Copy the displayed token. Then run:

```bash
ngrok config add-authtoken YOUR_NGROK_AUTHTOKEN
ngrok config check
ngrok version
```

`NGROK_AUTHTOKEN` is an ngrok secret. It stays in your local ngrok configuration. Never put it in `.env`, GitHub, or ChatGPT.

Official documentation: [ngrok installation](https://ngrok.com/docs/getting-started/) and [`add-authtoken` command](https://ngrok.com/docs/agent/cli/#ngrok-config-add-authtoken). The ngrok agent supports macOS, Linux, and Windows.

## 5. Open the tunnel once

Terminal 1:

```bash
ngrok http 8761
```

Copy the HTTPS URL shown after `Forwarding`. Example:

```text
https://example.ngrok-free.dev
```

On the free plan, this URL may change after a restart. When it changes, update `config/.env` and the ChatGPT MCP plugin.

## 6. Configure the gateway

macOS or Linux:

```bash
mkdir -p config
cp .env.example config/.env
```

Windows PowerShell:

```powershell
New-Item -ItemType Directory -Force config | Out-Null
Copy-Item .env.example config/.env
```

Edit `config/.env`:

```dotenv
MCP_BASE_URL=https://example.ngrok-free.dev
OAUTH_ISSUER=https://example.ngrok-free.dev/oauth
LOCAL_OAUTH_ISSUER=https://example.ngrok-free.dev/oauth
OAUTH_AUDIENCE=https://mcp.local
MCP_AUDIENCE=https://mcp.local
OAUTH_TOKEN_TTL_SECONDS=3600
OAUTH_AUTO_REGISTER_AUTH_CLIENTS=true
ENABLE_OAUTH=true
```

All three public URL values must use the exact same ngrok domain. Do not append `/mcp` to `MCP_BASE_URL`.

Git ignores `config/.env`. Never add the ngrok token to it.

## 7. Start the server

### macOS

```bash
./run.sh
```

This starts the gateway and ngrok. When available, `run.sh` automatically uses macOS `caffeinate` to prevent sleep. `Ctrl+C` stops both.

### Linux

```bash
./run.sh
```

`run.sh` works without `caffeinate` on Linux. Sleep prevention is optional; see the next section.

### Windows PowerShell

```powershell
.\run.ps1
```

This starts the gateway and ngrok. `Ctrl+C` stops the launcher and its process tree.

Keep this terminal open while using `mcp dl` in ChatGPT. Copy the HTTPS URL displayed by ngrok.

Background mode is available on macOS and Linux:

```bash
./run.sh start
./run.sh status
./run.sh stop
```

Manual alternative on macOS and Linux:

```bash
source .venv/bin/activate
python3 start_services.py
```

Then, in a second terminal:

```bash
ngrok http 8761
```

Manual alternative on Windows, terminal 1:

```powershell
.\.venv\Scripts\Activate.ps1
python start_services.py
```

Windows terminal 2:

```powershell
ngrok http 8761
```

## 8. Prevent the computer from sleeping

Sleep prevention matters because sleep stops the gateway, ngrok tunnel, and GUI automation.

### macOS: `caffeinate`

`run.sh` detects and uses the built-in `caffeinate` command automatically. No extra installation is required.

### Linux: `systemd-inhibit`

On systemd-based distributions:

```bash
systemd-inhibit --what=sleep --why="MCPRelay is running" ./run.sh
```

`systemd-inhibit` holds a sleep inhibitor only while `run.sh` is running. It is optional. Other init systems need their own equivalent.

### Windows: PowerToys Awake

Use [Microsoft PowerToys Awake](https://learn.microsoft.com/en-us/windows/powertoys/awake). Enable **Keep awake indefinitely** while MCPRelay is running. Enable **Keep screen on** when testing vision or GUI automation.

PowerToys Awake works only while the user is signed in. GUI automation also requires an unlocked interactive desktop.

## 9. Check the endpoints

macOS or Linux:

```bash
curl -fsS http://localhost:8761/oauth/health
curl -fsS http://localhost:8761/oauth/.well-known/oauth-authorization-server
```

Public, using your domain:

```bash
export MCP_PUBLIC_URL=https://example.ngrok-free.dev
curl -fsS "$MCP_PUBLIC_URL/oauth/health"
curl -fsS "$MCP_PUBLIC_URL/oauth/.well-known/oauth-authorization-server"
```

Expected health-check response: JSON containing `"ok": true`.

Logs:

```bash
tail -f logs/services/gateway.log
```

Windows PowerShell:

```powershell
Invoke-RestMethod http://localhost:8761/oauth/health
Invoke-RestMethod http://localhost:8761/oauth/.well-known/oauth-authorization-server
Get-Content logs/services/gateway.log -Wait
```

## 10. Platform compatibility

| Capability | macOS | Linux | Windows |
|---|---:|---:|---:|
| Gateway, OAuth, ngrok | Yes | Yes | Yes |
| Filesystem and shell | Yes | Yes | Yes |
| Screenshot, mouse, keyboard | Yes | X11 recommended | Yes |
| One-command launcher | `run.sh` | `run.sh` | `run.ps1` |
| Automatic sleep prevention | `caffeinate` | Optional `systemd-inhibit` | Optional PowerToys Awake |

Platform notes:

- macOS: grant **Screen Recording** and **Accessibility** permissions to Terminal, Python, or the service process.
- Linux: install `scrot` and `python3-tk` when screenshot or GUI tools require them. Wayland may block synthetic input or screenshots; use an X11 session for best compatibility.
- Windows: run inside a normal unlocked desktop session. Windows service/session isolation prevents GUI automation.
- `CHATGPT_STARTUP_BROWSER_ASSIST` uses AppleScript and is macOS-only. It is disabled by default. Core MCP features do not depend on it.
- Shell commands use the native operating-system shell. Commands written for Bash will not automatically work in Windows `cmd.exe`.
- `run_command` tracks files created under the project root by default. Set `MCP_COMMAND_SCAN_ROOT` in `config/.env` to scan another absolute path.

## 11. Enable ChatGPT developer mode

The interface changes over time. Use ChatGPT web.

Current user path:

1. Open [ChatGPT Settings](https://chatgpt.com/#settings/Personalization).
2. Go to **Apps** → **Advanced settings**.
3. Enable **Developer mode**.

Depending on your plan and role, an admin may need to allow this feature first:

- Business: admin/owner.
- Enterprise/Edu: **Workspace settings** → **Permissions & roles** → **Connected data**. The user then enables developer mode in their own settings.
- Pro: MCP may be limited to read/fetch actions, depending on OpenAI rollout.

Official reference: [Developer mode and MCP apps in ChatGPT](https://help.openai.com/en/articles/12584461-developer-mode-and-full-mcp-connectors-in-chatgpt-beta%29).

## 12. Add the `mcp dl` plugin

The interface may call it a **Plugin**, **App**, or **custom MCP app**.

1. Open ChatGPT in your browser.
2. Open **Plugins**.
3. Click the **+** button to the right of the search field.

![Plus button used to add a plugin](assets/chatgpt-plugins-add-button.webp)

4. Complete the **New Plugin** form:

   - **Name**: `mcp dl`
   - **Description**: `Local computer tools through MCPRelay` (optional)
   - **Connection**: `Server URL`
   - **Server URL**: your ngrok URL followed by `/mcp`
   - **Authentication**: `OAuth`

   Example URL:

   ```text
   https://example.ngrok-free.dev/mcp
   ```

![New Plugin form for mcp dl](assets/chatgpt-new-plugin-form.webp)

5. Wait for OAuth settings discovery. Open **Advanced OAuth settings** only if ChatGPT reports an error.
6. Check **I understand and want to continue**. This server provides access to your computer. Continue only if you own and trust this repository and tunnel.
7. Click **Create**.
8. Accept the OAuth redirect. MCPRelay creates and exchanges the token automatically.

The plugin is ready when `mcp dl` appears in the installed plugins list.

### OAuth token: nothing to paste

Do not confuse these values:

| Item | Created by | Destination |
|---|---|---|
| ngrok token | ngrok dashboard | `ngrok config add-authtoken ...` on the local computer |
| ngrok URL | `ngrok http 8761` | Plugin/app URL field: URL + `/mcp` |
| OAuth code and access token | Generated automatically by MCPRelay during connection | Automatic exchange between ChatGPT and `/oauth/token` |

ChatGPT automatically registers an OAuth client, opens `/oauth/authorize`, then exchanges the code for an access token. Never copy an OAuth JWT into the plugin settings.

## 13. Permissions: safe or YOLO

Two separate settings may be available:

- **Action control**: which actions are available. Choose **read actions only** or a custom selection to limit risk. Choose **all actions** to expose every MCP action.
- **App permissions**: when ChatGPT requests confirmation. **Important actions** is the safer setting. **Never ask** disables confirmations when available.

Mapping from older labels:

- `Low risk actions` ≈ read/low-impact actions with confirmations.
- `All actions` exposes everything, but may still request confirmation.
- Full YOLO mode = `All actions` + `Never ask`.

**Danger: MCPRelay exposes shell, filesystem, keyboard, mouse, and browser controls. `All actions` + `Never ask` may run commands, modify/delete files, or control the computer without confirmation. Use it only on a test machine, with a non-admin user and no sensitive data.**

OpenAI may still block especially risky actions. Reference: [app permissions and controls](https://help.openai.com/en/articles/11509118-admin-controls-security-and-compliance-for-plugins-and-apps).

## 14. Use `mcp dl` in a prompt

Start with a safe request:

```text
Use mcp dl to call auth_status, then list available tools. Do not modify anything.
```

Then test a read-only action:

```text
Use mcp dl to read the screen size. Do not click or type anything.
```

Short form for every request:

```text
Use mcp dl to <action>.
```

Example:

```text
Use mcp dl to take a screenshot and tell me which app is open.
```

If ChatGPT does not use the plugin, select `mcp dl` from the chat tools menu and repeat the prompt.

## 15. Troubleshooting

### `ERR_NGROK_6022`

Missing or invalid ngrok token:

```bash
ngrok config add-authtoken YOUR_NGROK_AUTHTOKEN
ngrok config check
```

### ChatGPT does not detect OAuth

Check that metadata, issuer, and public URL use the same domain:

```bash
curl -fsS "$MCP_PUBLIC_URL/oauth/.well-known/oauth-authorization-server"
```

`issuer` must equal `https://your-domain/oauth`.

### `invalid_redirect_uri`

Delete and recreate the ChatGPT app. If needed, stop the gateway and remove the affected local OAuth client before reconnecting. Never publish the contents of `data/`.

### Tunnel active, gateway unreachable

macOS or Linux:

```bash
lsof -nP -iTCP:8761 -sTCP:LISTEN
tail -n 100 logs/services/gateway.log
```

Windows PowerShell:

```powershell
Get-NetTCPConnection -LocalPort 8761
Get-Content logs/services/gateway.log -Tail 100
```

### ngrok URL changed

1. Update `config/.env`.
2. Restart MCPRelay.
3. Recreate or update the ChatGPT app with the new URL + `/mcp`.

## 16. Stop the server

Interactive mode: `Ctrl+C`.

macOS/Linux background mode:

```bash
./run.sh stop
```

Stop the public tunnel whenever it is not in use.
