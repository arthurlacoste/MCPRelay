#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ARG="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -n "$PROJECT_ARG" ] && [ -f "$PROJECT_ARG/run.sh" ]; then
  PROJECT_DIR="$(cd "$PROJECT_ARG" && pwd)"
elif [ -f "$PWD/run.sh" ]; then
  PROJECT_DIR="$PWD"
elif [ "$SCRIPT_DIR" != "/tmp" ] && [ -f "$SCRIPT_DIR/../run.sh" ]; then
  PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
elif [ -f "$HOME/gate/run.sh" ]; then
  PROJECT_DIR="$HOME/gate"
else
  printf 'Error: Gate project not found. Pass its path as the first argument.\n' >&2
  exit 1
fi

ENV_FILE="$PROJECT_DIR/config/.env"
NGROK_PORT="8761"
NGROK_API_URL="http://127.0.0.1:4040/api/tunnels"
NGROK_LOG="/tmp/gate-ngrok-change.log"
NGROK_PID=""

info() { printf '\n\033[1;34m%s\033[0m\n' "$*"; }
ok() { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m! %s\033[0m\n' "$*"; }
die() { printf '\033[1;31mError: %s\033[0m\n' "$*" >&2; exit 1; }

cleanup() {
  if [ -n "$NGROK_PID" ]; then
    kill "$NGROK_PID" 2>/dev/null || true
    wait "$NGROK_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

stop_running_ngrok() {
  local pids
  pids="$(pgrep -x ngrok 2>/dev/null || true)"
  [ -n "$pids" ] || return 0

  warn "Stopping existing ngrok process(es): $(echo "$pids" | tr '\n' ' ')"
  kill $pids 2>/dev/null || true

  for _ in $(seq 1 10); do
    pgrep -x ngrok >/dev/null 2>&1 || return 0
    sleep 1
  done

  pids="$(pgrep -x ngrok 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    warn "Forcing remaining ngrok process(es) to stop."
    kill -9 $pids 2>/dev/null || true
  fi

  for _ in $(seq 1 5); do
    pgrep -x ngrok >/dev/null 2>&1 || return 0
    sleep 1
  done

  die "Could not stop the existing ngrok process."
}

command -v ngrok >/dev/null 2>&1 || die "ngrok is not installed."
command -v curl >/dev/null 2>&1 || die "curl is required."
command -v jq >/dev/null 2>&1 || die "jq is required."
command -v pgrep >/dev/null 2>&1 || die "pgrep is required."

mkdir -p "$PROJECT_DIR/config"

info "Change ngrok account"
echo "Project: $PROJECT_DIR"
echo "Get the new token at: https://dashboard.ngrok.com/get-started/your-authtoken"
read -r -s -p "Paste the new ngrok authtoken: " NGROK_AUTHTOKEN
echo
[ -n "$NGROK_AUTHTOKEN" ] || die "The token cannot be empty."

ngrok config add-authtoken "$NGROK_AUTHTOKEN" >/dev/null
unset NGROK_AUTHTOKEN
ok "ngrok token updated"

info "Stopping the current ngrok tunnel"
stop_running_ngrok
ok "No previous ngrok tunnel is running"

info "Discovering the new public endpoint"
: > "$NGROK_LOG"
ngrok http "$NGROK_PORT" --log=stdout > "$NGROK_LOG" 2>&1 &
NGROK_PID=$!

PUBLIC_URL=""
for _ in $(seq 1 20); do
  PUBLIC_URL="$(curl -fsS "$NGROK_API_URL" 2>/dev/null \
    | jq -r '.tunnels[]? | select(.proto == "https") | .public_url' \
    | head -n1 || true)"
  [ -n "$PUBLIC_URL" ] && break
  kill -0 "$NGROK_PID" 2>/dev/null || break
  sleep 1
done

if [ -z "$PUBLIC_URL" ]; then
  cat "$NGROK_LOG" >&2 || true
  die "Could not obtain the new ngrok HTTPS URL."
fi

ok "New public URL: $PUBLIC_URL"

info "Updating config/.env"
[ -f "$ENV_FILE" ] || touch "$ENV_FILE"
cp "$ENV_FILE" "$ENV_FILE.bak"

update_env() {
  local key="$1" value="$2"
  if grep -qE "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
}

update_env MCP_BASE_URL "$PUBLIC_URL"
update_env OAUTH_ISSUER "$PUBLIC_URL/oauth"
update_env LOCAL_OAUTH_ISSUER "$PUBLIC_URL/oauth"
chmod 600 "$ENV_FILE"

ok "Updated $ENV_FILE"
echo "Backup: $ENV_FILE.bak"
echo
echo "New MCP URL: $PUBLIC_URL/mcp"
echo "Update the ChatGPT connector with this URL."
echo "https://chatgpt.com/plugins#settings/Connectors?create-connector=true&redirectAfter=%2Fplugins"
echo
echo "The temporary ngrok tunnel will now stop. Start Gate with:"
echo "  cd \"$PROJECT_DIR\" && ./run.sh"
