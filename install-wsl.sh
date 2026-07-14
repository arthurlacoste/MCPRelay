#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="https://github.com/arthurlacoste/MCPRelay.git"
DEFAULT_INSTALL_DIR="$HOME/MCPRelay"
NODE_VERSION="22"
NGROK_PORT="8761"

info() { printf '\n\033[1;34m%s\033[0m\n' "$*"; }
ok() { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m! %s\033[0m\n' "$*"; }
die() { printf '\033[1;31mError: %s\033[0m\n' "$*" >&2; exit 1; }

is_wsl() {
  grep -qiE '(microsoft|wsl)' /proc/version 2>/dev/null || [ -n "${WSL_DISTRO_NAME:-}" ]
}

prompt_default() {
  local prompt="$1" default="$2" value
  read -r -p "$prompt [$default]: " value
  printf '%s' "${value:-$default}"
}

cleanup_ngrok() {
  if [ -n "${TEMP_NGROK_PID:-}" ]; then
    kill "$TEMP_NGROK_PID" 2>/dev/null || true
  fi
}
trap cleanup_ngrok EXIT

is_wsl || die "Run this script inside Ubuntu/WSL, not PowerShell."
command -v sudo >/dev/null 2>&1 || die "sudo is required."

info "MCPRelay WSL installer"
echo "This installs MCPRelay, Python dependencies, Node.js 22 and ngrok."
echo "GUI automation from WSL can be limited. Filesystem, shell, OAuth and MCP work normally."

INSTALL_DIR="$(prompt_default "Installation directory" "$DEFAULT_INSTALL_DIR")"
FILESYSTEM_ROOTS="$(prompt_default "Directories exposed to MCPRelay" "$HOME")"

info "Installing system packages"
sudo apt-get update
sudo apt-get install -y \
  ca-certificates \
  curl \
  git \
  jq \
  build-essential \
  python3 \
  python3-pip \
  python3-venv \
  python3-tk \
  scrot
ok "System packages installed"

info "Installing Node.js $NODE_VERSION with nvm"
if [ ! -s "$HOME/.nvm/nvm.sh" ]; then
  curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/master/install.sh | bash
fi
export NVM_DIR="$HOME/.nvm"
# shellcheck source=/dev/null
. "$NVM_DIR/nvm.sh"
nvm install "$NODE_VERSION"
nvm alias default "$NODE_VERSION"
nvm use "$NODE_VERSION"
ok "Node $(node --version) active"

info "Installing ngrok"
if ! command -v ngrok >/dev/null 2>&1; then
  curl -fsSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc \
    | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
  echo "deb https://ngrok-agent.s3.amazonaws.com bookworm main" \
    | sudo tee /etc/apt/sources.list.d/ngrok.list >/dev/null
  sudo apt-get update
  sudo apt-get install -y ngrok
fi
ok "ngrok $(ngrok version | head -n1) installed"

info "Preparing repository"
if [ -d "$INSTALL_DIR/.git" ]; then
  warn "Repository already exists. Pulling latest changes."
  git -C "$INSTALL_DIR" pull --ff-only
else
  [ ! -e "$INSTALL_DIR" ] || die "$INSTALL_DIR exists but is not a Git repository."
  git clone "$REPO_URL" "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"
ok "Repository ready at $INSTALL_DIR"

info "Creating Python environment"
python3 -m venv .venv
# shellcheck source=/dev/null
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
ok "Python dependencies installed"

info "Connecting ngrok"
if ! ngrok config check >/dev/null 2>&1; then
  echo "Create an account at: https://dashboard.ngrok.com/signup"
  echo "Get the token at:    https://dashboard.ngrok.com/get-started/your-authtoken"
  read -r -s -p "Paste your ngrok authtoken: " NGROK_AUTHTOKEN
  echo
  [ -n "$NGROK_AUTHTOKEN" ] || die "ngrok token cannot be empty."
  ngrok config add-authtoken "$NGROK_AUTHTOKEN" >/dev/null
  unset NGROK_AUTHTOKEN
fi
ngrok config check >/dev/null
ok "ngrok account connected"

info "Opening a temporary ngrok tunnel"
ngrok http "$NGROK_PORT" --log=stdout > /tmp/mcprelay-ngrok-install.log 2>&1 &
TEMP_NGROK_PID=$!

PUBLIC_URL=""
for _ in $(seq 1 30); do
  PUBLIC_URL="$(curl -fsS http://127.0.0.1:4040/api/tunnels 2>/dev/null \
    | jq -r '.tunnels[]? | select(.proto == "https") | .public_url' \
    | head -n1 || true)"
  [ -n "$PUBLIC_URL" ] && break
  sleep 1
done

if [ -z "$PUBLIC_URL" ]; then
  cat /tmp/mcprelay-ngrok-install.log >&2 || true
  die "Could not obtain the ngrok HTTPS URL."
fi
ok "Public URL: $PUBLIC_URL"

info "Writing config/.env"
mkdir -p config
cat > config/.env <<EOF
MCP_BASE_URL=$PUBLIC_URL
OAUTH_ISSUER=$PUBLIC_URL/oauth
LOCAL_OAUTH_ISSUER=$PUBLIC_URL/oauth
OAUTH_AUDIENCE=https://mcp.local
MCP_AUDIENCE=https://mcp.local
OAUTH_TOKEN_TTL_SECONDS=3600
OAUTH_AUTO_REGISTER_AUTH_CLIENTS=true
ENABLE_OAUTH=true
MCP_FILESYSTEM_ROOTS=$FILESYSTEM_ROOTS
MCP_COMMAND_SCAN_ROOT=$FILESYSTEM_ROOTS
CHATGPT_STARTUP_BROWSER_ASSIST=false
EOF
chmod 600 config/.env
ok "Configuration saved"

kill "$TEMP_NGROK_PID" 2>/dev/null || true
wait "$TEMP_NGROK_PID" 2>/dev/null || true
TEMP_NGROK_PID=""

info "Installation complete"
printf '%s\n' \
  "Project:     $INSTALL_DIR" \
  "MCP URL:     $PUBLIC_URL/mcp" \
  "Auth:        OAuth" \
  "Name:        mcp dl" \
  "Description: Local computer tools through MCPRelay"

echo
echo "Start MCPRelay:"
echo "  cd \"$INSTALL_DIR\" && ./run.sh"
echo
echo "Then in ChatGPT web:"
echo "  Settings > Apps > Advanced settings > Developer mode"
echo "  Add a custom MCP app/plugin with:"
echo "    Server URL: $PUBLIC_URL/mcp"
echo "    Authentication: OAuth"
echo
echo "The free ngrok URL can change after restart. If it changes, update:"
echo "  $INSTALL_DIR/config/.env"
echo "  and the Server URL in ChatGPT."
echo
echo "WSL note: keep Windows awake and unlocked while MCPRelay is running."
