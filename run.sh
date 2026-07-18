#!/usr/bin/env bash
# Gate gateway + ngrok tunnel manager
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="${GATE_PID_FILE:-/tmp/mcp_gateway.pid}"
NGROK_PORT=8761
CONFIG_ROOT="${MCP_CONFIG_ROOT:-$PROJECT_DIR/config}"
CONFIG_FILE="$CONFIG_ROOT/.env"
NGROK_LOG="${MCP_LOG_ROOT:-$PROJECT_DIR/logs}/ngrok.log"
NGROK_INSPECT_URL="http://127.0.0.1:4040"
ONBOARDING_NGROK_PID=""
ONBOARDING_PUBLIC_URL=""
CHATGPT_CONNECTOR_URL="https://chatgpt.com/plugins#settings/Connectors?create-connector=true&redirectAfter=%2Fplugins"

info() { printf '\n\033[1;34m%s\033[0m\n' "$*"; }
ok() { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m! %s\033[0m\n' "$*"; }
die() { printf '\033[1;31mError: %s\033[0m\n' "$*" >&2; exit 1; }

ensure_python_environment() {
    local python="$PROJECT_DIR/.venv/bin/python"
    local requirements="$PROJECT_DIR/requirements.txt"

    command -v python3 >/dev/null 2>&1 || die "Python 3 is required."
    [ -f "$requirements" ] || die "Missing requirements.txt."

    if [ ! -x "$python" ]; then
        info "Creating Python environment"
        python3 -m venv "$PROJECT_DIR/.venv" ||
            die "Could not create .venv. On Debian/Ubuntu, install python3-venv."
    fi

    if ! "$python" -c 'import argon2' >/dev/null 2>&1; then
        info "Installing Python dependencies"
        "$python" -m pip install -r "$requirements" ||
            die "Could not install Python dependencies."
        ok "Python dependencies installed"
    fi
}

env_value() {
    local key="$1" line value=""
    [ -f "$CONFIG_FILE" ] || return 0

    while IFS= read -r line || [ -n "$line" ]; do
        line="${line%$'\r'}"
        line="${line#"${line%%[![:space:]]*}"}"
        if [[ "$line" =~ ^export[[:space:]]+(.+)$ ]]; then
            line="${BASH_REMATCH[1]}"
        fi
        if [[ "$line" =~ ^${key}[[:space:]]*=(.*)$ ]]; then
            value="${BASH_REMATCH[1]}"
        fi
    done < "$CONFIG_FILE"
    printf '%s' "$value"
}

set_env_values() {
    local tmp key
    tmp="$(mktemp "$CONFIG_ROOT/.env.tmp.XXXXXX")"
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

ensure_env_notes() {
    local renew_note="# Rotate OAuth access secret: ./run.sh renew-secret"
    [ -f "$CONFIG_FILE" ] || return 0
    grep -Fqx "$renew_note" "$CONFIG_FILE" || printf '\n%s\n' "$renew_note" >> "$CONFIG_FILE"
    chmod 600 "$CONFIG_FILE"
}


ensure_skills_directory() {
    local configured skills_dir
    configured="$(env_value MCP_SKILLS_ROOT)"

    case "$configured" in
        "") skills_dir="$HOME/.gate/skills" ;;
        "~") skills_dir="$HOME" ;;
        "~/"*) skills_dir="$HOME/${configured#\~/}" ;;
        *) skills_dir="$configured" ;;
    esac

    mkdir -p "$skills_dir" || die "Could not create Agent Skills directory: $skills_dir"
}

show_ngrok_inspector() {
    printf '  ngrok inspector → %s\n' "$NGROK_INSPECT_URL"
}

ngrok_pids() {
    pgrep -f "(^|[ /])ngrok[[:space:]]+http[[:space:]]+${NGROK_PORT}([[:space:]]|$)" 2>/dev/null || true
}

signal_ngrok_pids() {
    local signal="$1" pid
    while IFS= read -r pid; do
        [[ "$pid" =~ ^[0-9]+$ ]] || continue
        [ "$pid" = "$$" ] || kill "-$signal" "$pid" 2>/dev/null || true
    done
}

cleanup_stale_ngrok() {
    local pids remaining
    pids="$(ngrok_pids)"
    [ -n "$pids" ] || return 0

    warn "Stopping stale ngrok processes for port $NGROK_PORT."
    printf '%s\n' "$pids" | signal_ngrok_pids TERM

    for _ in $(seq 1 20); do
        remaining="$(ngrok_pids)"
        [ -z "$remaining" ] && {
            ok "Stale ngrok processes stopped"
            return 0
        }
        sleep 0.1
    done

    warn "Forcing stale ngrok processes to stop."
    printf '%s\n' "$remaining" | signal_ngrok_pids KILL

    for _ in $(seq 1 20); do
        remaining="$(ngrok_pids)"
        [ -z "$remaining" ] && {
            ok "Stale ngrok processes killed"
            return 0
        }
        sleep 0.1
    done

    die "Could not stop stale ngrok processes: $(printf '%s' "$remaining" | tr '\n' ' ')"
}

show_banner() {
    local line index=0
    local -a colors=(31 33 32 36 34 35)

    while IFS= read -r line; do
        if [ -t 1 ]; then
            printf '\033[1;%sm%s\033[0m\n' "${colors[$index]}" "$line"
        else
            printf '%s\n' "$line"
        fi
        index=$(( (index + 1) % ${#colors[@]} ))
    done <<'EOF'
oooooo     oooo ooooo  .oooooo..o ooooo   .oooooo.   ooooo      ooo
 `888.     .8'  `888' d8P'    `Y8 `888'  d8P'  `Y8b  `888b.     `8'
  `888.   .8'    888  Y88bo.       888  888      888  8 `88b.    8
   `888. .8'     888   `"Y8888o.   888  888      888  8   `88b.  8
    `888.8'      888       `"Y88b  888  888      888  8     `88b.8
     `888'       888  oo     .d8P  888  `88b    d88'  8       `888
      `8'       o888o 8""88888P'  o888o  `Y8bood8P'  o8o        `8

formerly Gate, made with <3 by arthak

EOF
}

clear_screen() {
    if [ -t 1 ]; then
        printf '\033[2J\033[H'
    fi
}

show_connection_details() {
    local public_url access_secret
    public_url="$(env_value MCP_BASE_URL)"
    access_secret="$(env_value OAUTH_ACCESS_SECRET)"

    if [ -z "$public_url" ] || [ -z "$access_secret" ]; then
        warn "OAuth setup incomplete. Run: ./run.sh setup"
        return 1
    fi

    info "Connection details"
    printf 'Public MCP:      %s/mcp\n' "$public_url"
    printf 'Public OAuth:    %s/oauth\n' "$public_url"
    printf 'Local MCP:       http://127.0.0.1:%s/mcp\n' "$NGROK_PORT"
    printf 'Local OAuth:     http://127.0.0.1:%s/oauth\n' "$NGROK_PORT"
    printf 'OAuth health:    http://127.0.0.1:%s/oauth/health\n' "$NGROK_PORT"
    printf 'ngrok inspector: %s\n' "$NGROK_INSPECT_URL"
    printf 'ChatGPT setup:   %s\n' "$CHATGPT_CONNECTOR_URL"
    printf 'Access secret:   %s\n' "$access_secret"
}

copy_access_secret() {
    local secret="$1"
    if command -v pbcopy >/dev/null 2>&1; then
        printf '%s' "$secret" | pbcopy
    elif command -v wl-copy >/dev/null 2>&1; then
        printf '%s' "$secret" | wl-copy
    elif command -v xclip >/dev/null 2>&1; then
        printf '%s' "$secret" | xclip -selection clipboard
    elif command -v xsel >/dev/null 2>&1; then
        printf '%s' "$secret" | xsel --clipboard --input
    else
        return 1
    fi
    printf 'Secret copied to clipboard.\n'
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
    local public_url=""
    mkdir -p "$(dirname "$NGROK_LOG")"
    : > "$NGROK_LOG"
    ngrok http "$NGROK_PORT" --log=stdout > "$NGROK_LOG" 2>&1 &
    ONBOARDING_NGROK_PID=$!

    for _ in $(seq 1 20); do
        public_url="$(curl -fsS http://127.0.0.1:4040/api/tunnels 2>/dev/null \
            | python3 -c 'import json,sys; data=json.load(sys.stdin); print(next((t["public_url"] for t in data.get("tunnels", []) if t.get("proto") == "https"), ""))' \
            2>/dev/null || true)"
        if [ -n "$public_url" ]; then
            ONBOARDING_PUBLIC_URL="$public_url"
            export GATE_EXISTING_NGROK_PID="$ONBOARDING_NGROK_PID"
            return 0
        fi
        kill -0 "$ONBOARDING_NGROK_PID" 2>/dev/null || break
        sleep 1
    done

    kill "$ONBOARDING_NGROK_PID" 2>/dev/null || true
    wait "$ONBOARDING_NGROK_PID" 2>/dev/null || true
    ONBOARDING_NGROK_PID=""
    return 1
}

ensure_onboarding() {
    local renew_secret="${1:-false}" public_url access_secret access_hash

    public_url="$(env_value MCP_BASE_URL)"
    access_secret="$(env_value OAUTH_ACCESS_SECRET)"
    access_hash="$(env_value OAUTH_ACCESS_SECRET_HASH)"
    ensure_skills_directory

    if [ "$renew_secret" != true ] && [ -n "$public_url" ] && [ -n "$access_secret" ] && [[ "$access_hash" == \$argon2id\$* ]]; then
        ensure_env_notes
        return 0
    fi

    [ -x "$PROJECT_DIR/.venv/bin/python" ] || die "Missing .venv. Complete the installation first."
    mkdir -p "$CONFIG_ROOT"

    if [ "$renew_secret" = true ]; then
        warn "Renewing OAuth access secret."
        access_secret=""
    else
        warn "OAuth configuration incomplete. Starting setup."
        command -v ngrok >/dev/null 2>&1 || die "ngrok is required. Install it before running Gate."
        command -v curl >/dev/null 2>&1 || die "curl is required."

        info "First-run setup"
        if ! ngrok config check >/dev/null 2>&1; then
            prompt_ngrok_token || die "The ngrok authtoken cannot be empty."
        fi

        info "Detecting your ngrok URL"
        open_temporary_ngrok || {
            cat "$NGROK_LOG" >&2 || true
            die "Could not obtain the ngrok HTTPS URL. Check your ngrok token."
        }
        public_url="$ONBOARDING_PUBLIC_URL"
        ok "Public URL: $public_url"
    fi

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
    ensure_env_notes

    printf '\nGate is configured.\n'
    copy_access_secret "$access_secret" || true
    show_connection_details
    printf '\n'
    printf 'The access secret is stored locally in config/.env with mode 600.\n'
}

daemon_pid_is_alive() {
    local services_pid=""
    [ -f "$PID_FILE" ] || return 1
    IFS=: read -r services_pid _ < "$PID_FILE"
    [[ "$services_pid" =~ ^[0-9]+$ ]] || return 1
    kill -0 "$services_pid" 2>/dev/null
}

reconcile_pid_file() {
    [ -f "$PID_FILE" ] || return 1
    if daemon_pid_is_alive; then
        return 0
    fi
    warn "Removing stale daemon PID file: $PID_FILE"
    rm -f "$PID_FILE"
    return 1
}

run_interactive() {
    cd "$PROJECT_DIR"
    if reconcile_pid_file; then
        IFS=: read -r SERVICES_PID NGROK_PID < "$PID_FILE"
        echo "✓ Gate already running (PID $SERVICES_PID)"
        if [ -n "${NGROK_PID:-}" ] && kill -0 "$NGROK_PID" 2>/dev/null; then
            echo "✓ ngrok tunnel     (PID $NGROK_PID)"
            show_ngrok_inspector
        fi
        echo ""
        echo "  Stop with:  ./run.sh stop"
        echo "  Status:     ./run.sh status"
        return 0
    fi
    cleanup_stale_ngrok
    ensure_python_environment
    ensure_onboarding
    source .venv/bin/activate
    "$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/src/interactive_launcher.py"
}

start_daemon() {
    cd "$PROJECT_DIR"
    if [ -f "$PID_FILE" ]; then
        echo "✗ Daemon already running (PID file $PID_FILE exists)"
        exit 1
    fi

    cleanup_stale_ngrok
    ensure_python_environment
    ensure_onboarding

    source .venv/bin/activate

    nohup python3 start_services.py > /dev/null 2>&1 &
    SERVICES_PID=$!
    sleep 2

    if [ -n "${GATE_EXISTING_NGROK_PID:-}" ] && kill -0 "$GATE_EXISTING_NGROK_PID" 2>/dev/null; then
        NGROK_PID="$GATE_EXISTING_NGROK_PID"
        KEEP_AWAKE_LABEL="onboarding tunnel reused"
    elif command -v caffeinate >/dev/null 2>&1; then
        nohup caffeinate -i ngrok http "$NGROK_PORT" > /dev/null 2>&1 &
        NGROK_PID=$!
        KEEP_AWAKE_LABEL="caffeinate active"
    else
        nohup ngrok http "$NGROK_PORT" > /dev/null 2>&1 &
        NGROK_PID=$!
        KEEP_AWAKE_LABEL="sleep inhibition inactive"
    fi

    echo "$SERVICES_PID:$NGROK_PID" > "$PID_FILE"
    echo "✓ Gateway started  (PID $SERVICES_PID)"
    echo "✓ ngrok tunnel     (PID $NGROK_PID) [$KEEP_AWAKE_LABEL]"
    show_ngrok_inspector
    echo ""
    echo "  Stop with:  ./run.sh stop"
    echo "  Status:     ./run.sh status"
}

gateway_port_pids() {
    if command -v fuser >/dev/null 2>&1; then
        fuser -n tcp "$NGROK_PORT" 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+$' || true
        return
    fi

    if command -v lsof >/dev/null 2>&1; then
        lsof -nP -tiTCP:"$NGROK_PORT" -sTCP:LISTEN 2>/dev/null || true
        return
    fi

    if command -v ss >/dev/null 2>&1; then
        ss -ltnp "sport = :$NGROK_PORT" 2>/dev/null \
            | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' \
            | sort -u
    fi
}

signal_gateway_processes() {
    local signal="$1"

    if command -v pkill >/dev/null 2>&1; then
        pkill "-$signal" -f "$PROJECT_DIR/src/mcp_gateway.py" 2>/dev/null || true
        pkill "-$signal" -f "$PROJECT_DIR/start_services.py" 2>/dev/null || true
    fi

    if command -v fuser >/dev/null 2>&1; then
        fuser -k "-$signal" "$NGROK_PORT/tcp" >/dev/null 2>&1 || true
    fi
}

stop_gateway_port() {
    local remaining

    signal_gateway_processes TERM

    for _ in 1 2 3 4 5; do
        remaining="$(gateway_port_pids)"
        [ -z "$remaining" ] && return 0
        sleep 1
    done

    warn "Forcing process on port $NGROK_PORT to stop."
    signal_gateway_processes KILL

    for _ in 1 2 3 4 5; do
        remaining="$(gateway_port_pids)"
        [ -z "$remaining" ] && return 0
        sleep 0.2
    done

    die "Could not free gateway port $NGROK_PORT. Try: sudo fuser -k -9 $NGROK_PORT/tcp"
}

stop_daemon() {
    local SERVICES_PID="" NGROK_PID=""

    if [ -f "$PID_FILE" ]; then
        IFS=: read -r SERVICES_PID NGROK_PID < "$PID_FILE"
    fi

    if [ -n "$NGROK_PID" ]; then
        echo "⟶ stopping ngrok (PID $NGROK_PID)…"
        kill "$NGROK_PID" 2>/dev/null || true
    fi

    if [ -n "$SERVICES_PID" ]; then
        echo "⟶ stopping gateway (PID $SERVICES_PID)…"
        kill "$SERVICES_PID" 2>/dev/null || true

        for _ in 1 2 3 4 5; do
            kill -0 "$SERVICES_PID" 2>/dev/null || break
            sleep 1
        done
        kill -9 "$SERVICES_PID" 2>/dev/null || true
    fi

    stop_gateway_port
    cleanup_stale_ngrok
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
        show_ngrok_inspector
    else
        echo "✗ ngrok not running"
    fi

    echo ""
    echo "  Logs:"
    echo "    gateway → $PROJECT_DIR/logs/services/gateway.log"
    echo "  PIDs:"
    echo "    $SERVICES_PID:$NGROK_PID"
}

parse_runtime_args() {
    RUNTIME_COMMAND=""
    local widget=false realtime=false arg
    for arg in "$@"; do
        case "$arg" in
            --widget) widget=true ;;
            --realtime) realtime=true ;;
            start|stop|status|setup|renew-secret)
                [ -z "$RUNTIME_COMMAND" ] || die "Only one command may be specified."
                RUNTIME_COMMAND="$arg"
                ;;
            *) die "Unknown option or command: $arg" ;;
        esac
    done

    case "$RUNTIME_COMMAND" in
        stop|status|setup|renew-secret)
            if [ "$widget" = true ] || [ "$realtime" = true ]; then
                die "Runtime flags are only valid when starting Gate."
            fi
            ;;
    esac

    export MCP_REALTIME_STATUS_ENABLED=false
    if [ "$widget" = true ]; then
        export MCP_WIDGET_ENABLED=true
    fi
    if [ "$realtime" = true ] || [ "$widget" = true ]; then
        export MCP_REALTIME_STATUS_ENABLED=true
    fi
}

parse_runtime_args "$@"
if [ -n "$RUNTIME_COMMAND" ]; then
    set -- "$RUNTIME_COMMAND"
else
    set --
fi

clear_screen
show_banner

case "${1:-}" in
    start)   start_daemon ;;
    stop)    stop_daemon  ;;
    status)  status       ;;
    setup)   ensure_python_environment; ensure_onboarding ;;
    renew-secret) ensure_python_environment; ensure_onboarding true ;;
    *)
        if [ $# -gt 0 ]; then
            echo "Usage: $0 [start] [--realtime] [--widget]"
            echo "       $0 {stop|status|setup|renew-secret}"
            echo ""
            echo "  (no arg)  Interactive mode – Ctrl+C stops everything"
            exit 1
        fi
        run_interactive
        ;;
esac
