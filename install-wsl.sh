#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="https://github.com/arthurlacoste/MCPRelay.git"
DEFAULT_INSTALL_DIR="$HOME/MCPRelay"
NODE_VERSION="22"
PYTHON_VERSION="3.12"
NGROK_PORT="8761"
NGROK_LOG="/tmp/mcprelay-ngrok-install.log"
DOCS_URL="https://github.com/arthurlacoste/MCPRelay/blob/main/docs/installation.md#12-add-the-mcp-dl-plugin"
CHATGPT_CONNECTOR_URL="https://chatgpt.com/plugins#settings/Connectors?create-connector=true&redirectAfter=%2Fplugins"

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

prompt_yes_no() {
  local prompt="$1" default="${2:-y}" answer
  read -r -p "$prompt [$default]: " answer
  answer="${answer:-$default}"
  [[ "$answer" =~ ^[Yy]([Ee][Ss])?$ ]]
}

cleanup_ngrok() {
  if [ -n "${TEMP_NGROK_PID:-}" ]; then
    kill "$TEMP_NGROK_PID" 2>/dev/null || true
    wait "$TEMP_NGROK_PID" 2>/dev/null || true
  fi
}

wait_for_ngrok_release() {
  for _ in $(seq 1 15); do
    if ! curl -fsS http://127.0.0.1:4040/api/tunnels >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  sleep 2
}

fix_obsolete_bullseye_backports() {
  local source_file backup_file changed=0

  while IFS= read -r -d '' source_file; do
    grep -q 'bullseye-backports' "$source_file" || continue
    backup_file="${source_file}.mcprelay-backup"
    sudo cp -n "$source_file" "$backup_file"

    case "$source_file" in
      *.sources)
        sudo awk '
          BEGIN { RS=""; ORS="\n\n" }
          /Suites:.*bullseye-backports/ {
            print "# Disabled by MCPRelay installer: obsolete bullseye-backports stanza"
            next
          }
          { print }
        ' "$source_file" | sudo tee "${source_file}.tmp" >/dev/null
        sudo mv "${source_file}.tmp" "$source_file"
        ;;
      *)
        sudo sed -i '/bullseye-backports/s/^/# Disabled by MCPRelay installer: /' "$source_file"
        ;;
    esac

    warn "Disabled obsolete bullseye-backports entries in $source_file"
    changed=1
  done < <(
    find /etc/apt -maxdepth 2 -type f \
      \( -name 'sources.list' -o -name '*.list' -o -name '*.sources' \) \
      -print0 2>/dev/null
  )

  if [ "$changed" -eq 1 ]; then
    echo "Backups were saved with the .mcprelay-backup suffix."
  fi
}

prompt_ngrok_token() {
  local token
  echo "Create an account at: https://dashboard.ngrok.com/signup"
  echo "Get the token at:    https://dashboard.ngrok.com/get-started/your-authtoken"
  read -r -s -p "Paste your ngrok authtoken: " token
  echo
  [ -n "$token" ] || return 1
  ngrok config add-authtoken "$token" >/dev/null
  unset token
}

open_ngrok_tunnel() {
  local public_url=""
  : > "$NGROK_LOG"
  ngrok http "$NGROK_PORT" --log=stdout > "$NGROK_LOG" 2>&1 &
  TEMP_NGROK_PID=$!

  for _ in $(seq 1 20); do
    public_url="$(curl -fsS http://127.0.0.1:4040/api/tunnels 2>/dev/null \
      | jq -r '.tunnels[]? | select(.proto == "https") | .public_url' \
      | head -n1 || true)"
    [ -n "$public_url" ] && {
      printf '%s' "$public_url"
      return 0
    }
    kill -0 "$TEMP_NGROK_PID" 2>/dev/null || break
    sleep 1
  done

  cleanup_ngrok
  TEMP_NGROK_PID=""
  return 1
}

trap cleanup_ngrok EXIT

is_wsl || die "Run this script inside Ubuntu/WSL, not PowerShell."
command -v sudo >/dev/null 2>&1 || die "sudo is required."

info "MCPRelay WSL installer"
echo "This installs MCPRelay, Python $PYTHON_VERSION, Node.js $NODE_VERSION and ngrok."
echo "GUI automation from WSL can be limited. Filesystem, shell, OAuth and MCP work normally."

INSTALL_DIR="$(prompt_default "Installation directory" "$DEFAULT_INSTALL_DIR")"
FILESYSTEM_ROOTS="$(prompt_default "Directories exposed to MCPRelay" "$HOME")"

if [ "$FILESYSTEM_ROOTS" = "/" ]; then
  warn "You selected /. MCPRelay will be able to access the entire WSL filesystem."
fi

info "Checking Debian package sources"
fix_obsolete_bullseye_backports

info "Installing system packages"
sudo apt-get update
sudo apt-get install -y ca-certificates curl git jq build-essential python3-tk scrot
ok "System packages installed"

info "Installing Node.js $NODE_VERSION with nvm"
if [ ! -s "$HOME/.nvm/nvm.sh" ]; then
  curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/master/install.sh | bash
fi
export NVM_DIR="$HOME/.nvm"
. "$NVM_DIR/nvm.sh"
nvm install "$NODE_VERSION"
nvm alias default "$NODE_VERSION"
nvm use "$NODE_VERSION"
ok "Node $(node --version) active"

info "Installing Python $PYTHON_VERSION with uv"
if [ ! -x "$HOME/.local/bin/uv" ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
command -v uv >/dev/null 2>&1 || die "uv installation failed."
uv python install "$PYTHON_VERSION"
ok "Python $PYTHON_VERSION installed"

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

info "Creating Python $PYTHON_VERSION environment"
rm -rf .venv
uv venv --python "$PYTHON_VERSION" .venv
uv pip install --python .venv/bin/python -r requirements.txt
mkdir -p logs/services
ok "Python dependencies installed with $(.venv/bin/python --version)"

info "Connecting ngrok"
PUBLIC_URL=""
for attempt in 1 2 3; do
  if [ "$attempt" -gt 1 ] || ! ngrok config check >/dev/null 2>&1; then
    prompt_ngrok_token || {
      warn "The ngrok token cannot be empty."
      continue
    }
  fi

  info "Opening a temporary ngrok tunnel"
  if PUBLIC_URL="$(open_ngrok_tunnel)"; then
    break
  fi

  if grep -q 'ERR_NGROK_105\|authentication failed' "$NGROK_LOG"; then
    warn "The saved ngrok authtoken is invalid. Copy the full token from the ngrok dashboard."
    continue
  fi

  cat "$NGROK_LOG" >&2 || true
  die "Could not obtain the ngrok HTTPS URL."
done

[ -n "$PUBLIC_URL" ] || {
  cat "$NGROK_LOG" >&2 || true
  die "ngrok authentication failed after 3 attempts."
}
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

cleanup_ngrok
TEMP_NGROK_PID=""
wait_for_ngrok_release

info "Installation complete"
printf '%s\n' \
  "Project:     $INSTALL_DIR" \
  "MCP URL:     $PUBLIC_URL/mcp" \
  "Auth:        OAuth" \
  "Name:        mcp dl" \
  "Description: Local computer tools through MCPRelay"

echo
echo "ChatGPT setup guide:"
echo "  $DOCS_URL"
echo
echo "Open the ChatGPT connector form:"
echo "  $CHATGPT_CONNECTOR_URL"
echo
echo "Enter:"
echo "  Server URL: $PUBLIC_URL/mcp"
echo "  Authentication: OAuth"
echo
echo "ChatGPT does not currently expose documented URL parameters to prefill these fields."
echo "The free ngrok URL can change after restart. Update config/.env and ChatGPT when it changes."
echo "WSL note: keep Windows awake and unlocked while MCPRelay is running."

if prompt_yes_no "Start MCPRelay now?" "y"; then
  echo
  echo "Starting MCPRelay. Press Ctrl+C to stop it."
  trap - EXIT
  exec ./run.sh
fi

echo
echo "Start later with:"
echo "  cd \"$INSTALL_DIR\" && ./run.sh"
