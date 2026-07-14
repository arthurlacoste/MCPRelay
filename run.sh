#!/usr/bin/env bash
# MCPRelay gateway + ngrok tunnel manager
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="/tmp/mcp_gateway.pid"
NGROK_PORT=8761
CONFIG_FILE="$PROJECT_DIR/config/.env"
NGROK_LOG="/tmp/mcprelay-ngrok-run.log"
CHATGPT_CONNECTOR_URL="https://chatgpt.com/plugins#settings/Connectors?create-connector=true&redirectAfter=%2Fplugins"

info() { printf '\n\033[1;34m%s\033[0m\n' "$*"; }
ok() { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m! %s\033[0m\n' "$*"; }
die() { printf '\033[1;31mError: %s\033[0m\n' "$*" >&2; exit 1; }

env_value() {
    local key="$1"
    [ -f "$CONFIG_FILE" ] || return 0
    sed -n "s/^${key}=//p" "$CONFIG_FILE" | tail -n1
}

set_env_values() {
    local tmp key
    tmp="$(mktemp "$PROJECT_DIR/config/.env.tmp.XXXXXX")"
    chmod 600 "$tmp"

    if [ -f "$CONFIG_FILE" ]; then
        cp "$CONFIG_FILE" "$tmp"
    fi

    while [ "$#" -gt 0 ]; do
        key="$1"
        shift
        grep -v "^${key}=" "$tmp" > "${tmp}.next" || true
        mv "${tmp}.next" "$tmp"
        printf '%s=%s\n' "$key" "$1" >> "$tmp"
        shift
    done

    mv "$tmp" "$CONFIG_FILE"
    chmod 600 "$CONFIG_FILE"
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

open_temporary_ngrok() {
    local public_url="" temp_pid
    : > "$NGROK_LOG"
    ngrok http "$NGROK_PORT" --log=stdout > "$NGROK_LOG" 2>&1 &
    temp_pid=$!

    for _ in $(seq 1 20); do
        public_url="$(curl -fsS http://127.0.0.1:4040/api/tunnels 2>/dev/null \
            | python3 -c 'import json,sys; data=json.load(sys.stdin); print(next((t["public_url"] for t in data.get("tunnels", []) if t.get("proto") == "https"), ""))' \
            2>/dev/null || true)"
        if [ -n "$public_url" ]; then
            kill "$temp_pid" 2>/dev/null || true
            wait "$temp_pid" 2>/dev/null || true
            printf '%s' "$public_url"
            return 0
        fi
        kill -0 "$temp_pid" 2>/dev/null || break
        sleep 1
    done

    kill "$temp_pid" 2>/dev/null || true
    wait "$temp_pid" 2>/dev/null || true
    return 1
}

ensure_onboarding() {
    local public_url access_secret access_hash

    command -v ngrok >/dev/null 2>&1 || die "ngrok is required. Install it before running MCPRelay."
    command -v curl >/dev/null 2>&1 || die "curl is required."
    [ -x "$PROJECT_DIR/.venv/bin/python" ] || die "Missing .venv. Complete the installation first."
    mkdir -p "$PROJECT_DIR/config"

    public_url="$(env_value MCP_BASE_URL)"
    access_secret="$(env_value OAUTH_ACCESS_SECRET)"
    access_hash="$(env_value OAUTH_ACCESS_SECRET_HASH)"

    if [ -n "$public_url" ] && [ -n "$access_secret" ] && [[ "$access_hash" == \$argon2id\$* ]]; then
        return 0
    fi

    info "First-run setup"

    if ! ngrok config check >/dev/null 2>&1; then
        prompt_ngrok_token || die "The ngrok authtoken cannot be empty."
    fi

    info "Detecting your ngrok URL"
    public_url="$(open_temporary_ngrok)" || {
        cat "$NGROK_LOG" >&2 || true
        die "Could not obtain the ngrok HTTPS URL. Check your ngrok token."
    }
    ok "Public URL: $public_url"

    if [ -z "$access_secret" ]; then
        access_secret="$($PROJECT_DIR/.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"
    fi
    access_hash="$(OAUTH_ACCESS_SECRET="$access_secret" "$PROJECT_DIR/.venv/bin/python" -c 'import os; from argon2 import PasswordHasher; print(PasswordHasher().hash(os.environ["OAUTH_ACCESS_SECRET"]))')"

    set_env_values \
        MCP_BASE_URL "$public_url" \
        OAUTH_ISSUER "$public_url/oauth" \
        LOCAL_OAUTH_ISSUER "$public_url/oauth" \
        OAUTH_AUDIENCE "https://mcp.local" \
        MCP_AUDIENCE "https://mcp.local" \
        OAUTH_ACCESS_SECRET "$access_secret" \
        OAUTH_ACCESS_SECRET_HASH "$access_hash" \
        OAUTH_TOKEN_TTL_SECONDS "2592000" \
        OAUTH_LOGIN_MAX_ATTEMPTS "5" \
        OAUTH_TRUSTED_PROXY_NETWORKS "127.0.0.0/8,::1/128" \
        OAUTH_AUTO_REGISTER_AUTH_CLIENTS "true" \
        ENABLE_OAUTH "true" \
        CHATGPT_STARTUP_BROWSER_ASSIST "false"

    printf '\nMCPRelay is configured.\n\n'
    printf 'Connector URL: %s/mcp\n' "$public_url"
    printf 'Access secret: %s\n' "$access_secret"
    printf 'ChatGPT setup: %s\n\n' "$CHATGPT_CONNECTOR_URL"
    printf 'The access secret is stored locally in config/.env with mode 600.\n'
}

_cleanup() {
    echo ""
    echo "⟶ stopping gateway…"
    kill "${SERVICES_PID:-}" 2>/dev/null && wait "${SERVICES_PID:-}" 2>/dev/null || true
    echo "✓ gateway stopped"
}

run_interactive() {
    cd "$PROJECT_DIR"
    ensure_onboarding
    source .venv/bin/activate

    python3 start_services.py &
    SERVICES_PID=$!
    trap _cleanup EXIT INT TERM
    sleep 2

    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║  MCP Gateway ready                                     ║"
    echo "║    MCP   → http://localhost:$NGROK_PORT/mcp               ║"
    echo "║    OAuth → http://localhost:$NGROK_PORT/oauth/...        ║"
    echo "║                                                        ║"
    echo "║  ngrok tunnel will open in a moment…                   ║"
    echo "║  Press Ctrl+C to stop everything.                      ║"
    echo "╚══════════════════════════════════════════════════════════╝"
    if command -v caffeinate >/dev/null 2>&1; then
        echo "⚡ caffeinate active — sleep is inhibited while MCPRelay runs."
        caffeinate -i ngrok http "$NGROK_PORT"
    else
        echo "ℹ Sleep inhibition inactive. See docs for Linux alternatives."
        ngrok http "$NGROK_PORT"
    fi
}

start_daemon() {
    if [ -f "$PID_FILE" ]; then
        echo "✗ Daemon already running (PID file $PID_FILE exists)"
        exit 1
    fi

    cd "$PROJECT_DIR"
    ensure_onboarding
    source .venv/bin/activate

    nohup python3 start_services.py > /dev/null 2>&1 &
    SERVICES_PID=$!
    sleep 2

    if command -v caffeinate >/dev/null 2>&1; then
        nohup caffeinate -i ngrok http "$NGROK_PORT" > /dev/null 2>&1 &
        KEEP_AWAKE_LABEL="caffeinate active"
    else
        nohup ngrok http "$NGROK_PORT" > /dev/null 2>&1 &
        KEEP_AWAKE_LABEL="sleep inhibition inactive"
    fi
    NGROK_PID=$!

    echo "$SERVICES_PID:$NGROK_PID" > "$PID_FILE"
    echo "✓ Gateway started  (PID $SERVICES_PID)"
    echo "✓ ngrok tunnel     (PID $NGROK_PID) [$KEEP_AWAKE_LABEL]"
    echo ""
    echo "  Stop with:  ./run.sh stop"
    echo "  Status:     ./run.sh status"
}

stop_daemon() {
    if [ ! -f "$PID_FILE" ]; then
        echo "ℹ No daemon running"
        exit 0
    fi

    IFS=: read -r SERVICES_PID NGROK_PID < "$PID_FILE"
    echo "⟶ stopping ngrok (PID $NGROK_PID)…"
    kill "$NGROK_PID" 2>/dev/null || true
    echo "⟶ stopping gateway (PID $SERVICES_PID)…"
    kill "$SERVICES_PID" 2>/dev/null || true

    for _ in 1 2 3 4 5; do
        kill -0 "$SERVICES_PID" 2>/dev/null || break
        sleep 1
    done
    kill -9 "$SERVICES_PID" 2>/dev/null || true
    rm -f "$PID_FILE"
    echo "✓ Gateway stopped"
}

status() {
    if [ ! -f "$PID_FILE" ]; then
        echo "ℹ Daemon not running"
        exit 0
    fi

    IFS=: read -r SERVICES_PID NGROK_PID < "$PID_FILE"
    if kill -0 "$SERVICES_PID" 2>/dev/null; then
        echo "✓ Gateway running  (PID $SERVICES_PID)"
    else
        echo "✗ Gateway not running (stale PID file)"
        rm -f "$PID_FILE"
        exit 1
    fi

    if kill -0 "$NGROK_PID" 2>/dev/null; then
        echo "✓ ngrok tunnel     (PID $NGROK_PID)"
    else
        echo "✗ ngrok not running"
    fi

    echo ""
    echo "  Logs:"
    echo "    gateway → $PROJECT_DIR/logs/services/gateway.log"
    echo "  PIDs:"
    echo "    $SERVICES_PID:$NGROK_PID"
}

case "${1:-}" in
    start)   start_daemon ;;
    stop)    stop_daemon  ;;
    status)  status       ;;
    *)
        if [ $# -gt 0 ]; then
            echo "Usage: $0 {start|stop|status}"
            echo ""
            echo "  (no arg)  Interactive mode – Ctrl+C stops everything"
            exit 1
        fi
        run_interactive
        ;;
esac
