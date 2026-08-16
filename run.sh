#!/usr/bin/env bash
# Gate gateway + configurable tunnel manager
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
ONBOARDING_TAILSCALE_PID=""
ONBOARDING_CLOUDFLARED_PID=""
CHATGPT_CONNECTOR_URL="https://chatgpt.com/plugins#settings/Connectors?create-connector=true&redirectAfter=%2Fplugins"

resolve_ngrok_target() {
    PYTHONPATH="$PROJECT_DIR/src" "$PROJECT_DIR/.venv/bin/python" -c \
        'from ngrok_target import resolve_ngrok_target; print(resolve_ngrok_target(8761))'
}

info() { printf '\n\033[1;34m%s\033[0m\n' "$*"; }
ok() { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m! %s\033[0m\n' "$*"; }
die() { printf '\033[1;31mError: %s\033[0m\n' "$*" >&2; exit 1; }

find_compatible_python() {
    local candidate
    for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
        command -v "$candidate" >/dev/null 2>&1 || continue
        if "$candidate" -c 'import sys; exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

ensure_python_environment() {
    local python="$PROJECT_DIR/.venv/bin/python"
    local requirements="$PROJECT_DIR/requirements.txt"

    [ -f "$requirements" ] || die "Missing requirements.txt."

    if [ ! -x "$python" ]; then
        local python_bin
        python_bin="$(find_compatible_python)" \
            || die "Python >= 3.10 is required. Install python3.10+ and retry."
        info "Creating Python environment"
        "$python_bin" -m venv "$PROJECT_DIR/.venv" ||
            die "Could not create .venv. On Debian/Ubuntu, install python3-venv."
    fi

    if ! "$python" -c 'import _ssl' >/dev/null 2>&1; then
        die "Python was compiled without SSL support (missing _ssl module).
Install libssl-dev and recompile, or use a different Python:
  pyenv install 3.12
  sudo apt install python3.12-venv"
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



configured_tunnel_provider() {
    local provider
    provider="${TUNNEL_PROVIDER:-$(env_value TUNNEL_PROVIDER)}"
    provider="${provider:-ngrok}"
    case "$provider" in
        ngrok|tailscale|cloudflare|external) printf '%s' "$provider" ;;
        *) die "Unsupported TUNNEL_PROVIDER=$provider. Use ngrok, tailscale, cloudflare, or external." ;;
    esac
}

ensure_tunnel_provider() {
    local provider="$1"
    case "$provider" in
        ngrok)
            command -v ngrok >/dev/null 2>&1 || die "ngrok is required. Install it and configure its authtoken."
            ;;
        tailscale)
            command -v tailscale >/dev/null 2>&1 || die "Tailscale CLI is required. Install Tailscale, run 'tailscale up', then retry."
            tailscale status --json 2>/dev/null | grep -q '"BackendState"[[:space:]]*:[[:space:]]*"Running"' \
                || die "Tailscale is not authenticated or running. Run 'tailscale up' and retry."
            ;;
        cloudflare)
            command -v cloudflared >/dev/null 2>&1 || die "cloudflared is required. Install it (macOS: brew install cloudflared), then retry."
            local tunnel_name
            tunnel_name="${CLOUDFLARED_TUNNEL_NAME:-$(env_value CLOUDFLARED_TUNNEL_NAME)}"
            if [ -n "$tunnel_name" ]; then
                cloudflared tunnel list >/dev/null 2>&1 \
                    || die "cloudflared is not logged in to Cloudflare. Run 'cloudflared tunnel login', then retry."
                cloudflared tunnel list 2>/dev/null | grep -qw "$tunnel_name" \
                    || die "Cloudflare tunnel '$tunnel_name' does not exist. Run 'cloudflared tunnel create $tunnel_name' or './run.sh setup'."
            fi
            ;;
        external) ;;
    esac
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
    pgrep -f "(^|[ /])ngrok[[:space:]]+http[[:space:]]+([^[:space:]]*:)?${NGROK_PORT}([[:space:]]|$)" 2>/dev/null || true
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

cloudflared_pids() {
    pgrep -f "(^|[ /])cloudflared[[:space:]]+tunnel[[:space:]]+.*127\.0\.0\.1:${NGROK_PORT}" 2>/dev/null || true
}

cleanup_stale_cloudflared() {
    local pids remaining
    pids="$(cloudflared_pids)"
    [ -n "$pids" ] || return 0

    warn "Stopping stale cloudflared processes for port $NGROK_PORT."
    printf '%s\n' "$pids" | signal_ngrok_pids TERM

    for _ in $(seq 1 20); do
        remaining="$(cloudflared_pids)"
        [ -z "$remaining" ] && {
            ok "Stale cloudflared processes stopped"
            return 0
        }
        sleep 0.1
    done

    warn "Forcing stale cloudflared processes to stop."
    printf '%s\n' "$remaining" | signal_ngrok_pids KILL

    for _ in $(seq 1 20); do
        remaining="$(cloudflared_pids)"
        [ -z "$remaining" ] && {
            ok "Stale cloudflared processes killed"
            return 0
        }
        sleep 0.1
    done

    die "Could not stop stale cloudflared processes: $(printf '%s' "$remaining" | tr '\n' ' ')"
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
    printf 'Public realtime: %s/rt\n' "$public_url"
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
    local public_url="" raw_response
    mkdir -p "$(dirname "$NGROK_LOG")"
    : > "$NGROK_LOG"
    ngrok http "${GATE_NGROK_TARGET:-$NGROK_PORT}" --log=stdout > "$NGROK_LOG" 2>&1 &
    ONBOARDING_NGROK_PID=$!

    for _ in $(seq 1 20); do
        raw_response="$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null || true)"

        if printf '%s' "$raw_response" | grep -q "Rejected host"; then
            warn "ngrok inspection API is blocking localhost."
            warn "Add '127.0.0.1' and 'localhost' to web_allow_hosts in:"
            warn "  ~/.config/ngrok/ngrok.yml"
            kill "$ONBOARDING_NGROK_PID" 2>/dev/null || true
            wait "$ONBOARDING_NGROK_PID" 2>/dev/null || true
            ONBOARDING_NGROK_PID=""
            return 1
        fi

        public_url="$(printf '%s' "$raw_response" \
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

tailscale_funnel_url_from_json() {
    # Extract the public HTTPS URL from `tailscale funnel status --json`.
    "$PROJECT_DIR/.venv/bin/python" -c 'import json,sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(1)
for section in ("Foreground", "serve"):
    for entry in (data.get(section) or {}).values():
        for key in (entry.get("Web") or {}):
            host = key.split(":", 1)[0]
            if host:
                print("https://" + host)
                sys.exit(0)
sys.exit(1)'
}

active_tailscale_funnel_url() {
    # Public HTTPS URL of an already-active Funnel serving NGROK_PORT, if any.
    # Useful when a Funnel was started outside Gate (e.g. 'tailscale funnel' in
    # another terminal or as root) and owns the 443 listener.
    local json url
    json="$(timeout 10s tailscale funnel status --json 2>/dev/null || true)"
    [ -n "$json" ] || return 1
    printf '%s' "$json" | grep -qE "\"Proxy\"[[:space:]]*:[[:space:]]*\"http://127\\.0\\.0\\.1:${NGROK_PORT}\"" || return 1
    url="$(printf '%s' "$json" | tailscale_funnel_url_from_json 2>/dev/null || true)"
    [ -n "$url" ] || return 1
    printf '%s' "$url"
}

wait_for_tailscale_url() {
    # Poll for an active Funnel URL until it appears or the given PID exits.
    local pid="$1" output url=""
    for _ in $(seq 1 20); do
        output="$(timeout 10s tailscale funnel status --json 2>&1 || true)"
        url="$(printf '%s' "$output" | tailscale_funnel_url_from_json 2>/dev/null || true)"
        if [ -z "$url" ]; then
            url="$(printf '%s' "$output" | grep -Eo 'https://[^[:space:]"'"'"']+' | head -n1 | sed 's#[/.,;)]$##')"
        fi
        [ -n "$url" ] && { printf '%s' "$url"; return 0; }
        kill -0 "$pid" 2>/dev/null || break
        sleep 1
    done
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
    ONBOARDING_TAILSCALE_PID=""
    return 1
}

kill_stale_tailscale_funnels() {
    # Stop leftover `tailscale funnel --bg=false <port>` processes. They are
    # often root-owned (started with sudo), so escalate when a plain kill fails.
    local pids remaining
    pids="$(pgrep -f "tailscale[[:space:]]+funnel[[:space:]]+--bg=false[[:space:]]+${NGROK_PORT}" 2>/dev/null || true)"
    [ -n "$pids" ] || return 0
    warn "Stopping stale Tailscale Funnel processes for port $NGROK_PORT."
    if [ "$(id -u)" = "0" ]; then
        printf '%s\n' "$pids" | xargs kill 2>/dev/null || true
    else
        printf '%s\n' "$pids" | xargs sudo -n kill 2>/dev/null \
            || printf '%s\n' "$pids" | xargs kill 2>/dev/null || true
    fi
    for _ in $(seq 1 10); do
        remaining="$(pgrep -f "tailscale[[:space:]]+funnel[[:space:]]+--bg=false[[:space:]]+${NGROK_PORT}" 2>/dev/null || true)"
        [ -z "$remaining" ] && { ok "Stale Tailscale Funnel processes stopped"; return 0; }
        sleep 0.2
    done
    warn "Could not stop stale Tailscale Funnel processes."
}

open_temporary_tailscale() {
    local public_url=""
    # Prefer an already-active Funnel serving our port.
    if public_url="$(active_tailscale_funnel_url)"; then
        ONBOARDING_PUBLIC_URL="$public_url"
        warn "Reusing the active Tailscale Funnel."
        return 0
    fi
    mkdir -p "${MCP_LOG_ROOT:-$PROJECT_DIR/logs}"
    : > "${MCP_LOG_ROOT:-$PROJECT_DIR/logs}/tailscale.log"
    tailscale funnel --bg=false "$NGROK_PORT" > "${MCP_LOG_ROOT:-$PROJECT_DIR/logs}/tailscale.log" 2>&1 &
    ONBOARDING_TAILSCALE_PID=$!
    if public_url="$(wait_for_tailscale_url "$ONBOARDING_TAILSCALE_PID")"; then
        ONBOARDING_PUBLIC_URL="$public_url"
        export GATE_EXISTING_TAILSCALE_PID="$ONBOARDING_TAILSCALE_PID"
        return 0
    fi
    # The Funnel failed to start, usually because an untracked process owns the
    # listener ("listener already exists for port 443"). Clear stale Funnels
    # and retry once before giving up.
    warn "Could not start a Tailscale Funnel. Clearing stale Funnel processes and retrying."
    kill_stale_tailscale_funnels
    tailscale funnel --bg=false "$NGROK_PORT" > "${MCP_LOG_ROOT:-$PROJECT_DIR/logs}/tailscale.log" 2>&1 &
    ONBOARDING_TAILSCALE_PID=$!
    if public_url="$(wait_for_tailscale_url "$ONBOARDING_TAILSCALE_PID")"; then
        ONBOARDING_PUBLIC_URL="$public_url"
        export GATE_EXISTING_TAILSCALE_PID="$ONBOARDING_TAILSCALE_PID"
        return 0
    fi
    return 1
}

open_temporary_cloudflared() {
    local log public_url=""
    log="${MCP_LOG_ROOT:-$PROJECT_DIR/logs}/cloudflared.log"
    mkdir -p "$(dirname "$log")"
    : > "$log"
    cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:$NGROK_PORT" > "$log" 2>&1 &
    ONBOARDING_CLOUDFLARED_PID=$!

    for _ in $(seq 1 30); do
        public_url="$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' "$log" 2>/dev/null | head -n1)"
        if [ -n "$public_url" ]; then
            ONBOARDING_PUBLIC_URL="$public_url"
            export GATE_EXISTING_CLOUDFLARED_PID="$ONBOARDING_CLOUDFLARED_PID"
            return 0
        fi
        kill -0 "$ONBOARDING_CLOUDFLARED_PID" 2>/dev/null || break
        sleep 1
    done

    kill "$ONBOARDING_CLOUDFLARED_PID" 2>/dev/null || true
    wait "$ONBOARDING_CLOUDFLARED_PID" 2>/dev/null || true
    ONBOARDING_CLOUDFLARED_PID=""
    return 1
}

setup_cloudflared_connect() {
    local tunnel_name="$1" cf_hostname="" raw route_output
    info "Setting up your Cloudflare connect tunnel '$tunnel_name'"
    if ! cloudflared tunnel list >/dev/null 2>&1; then
        info "Log in to Cloudflare (a browser window will open)."
        cloudflared tunnel login || die "Cloudflare login failed. Run 'cloudflared tunnel login' manually, then retry."
    fi
    if ! cloudflared tunnel list 2>/dev/null | grep -qw "$tunnel_name"; then
        cloudflared tunnel create "$tunnel_name" || die "Could not create Cloudflare tunnel '$tunnel_name'."
    fi
    cf_hostname="${MCP_BASE_URL:-$(env_value MCP_BASE_URL)}"
    if [ -z "$cf_hostname" ] && [ -t 0 ] && [ -t 1 ]; then
        printf 'Public hostname (e.g. mcp.example.com): ' > /dev/tty
        IFS= read -r raw < /dev/tty || raw=""
        cf_hostname="$raw"
    fi
    cf_hostname="$(printf '%s' "$cf_hostname" | sed -E 's#^https?://##; s#/.*$##')"
    [ -n "$cf_hostname" ] || die "A public hostname is required for a Cloudflare connect tunnel."
    # A completed 'gate connect cf' already routed this hostname and stored
    # CLOUDFLARED_TUNNEL_NAME + MCP_BASE_URL. Re-running setup to finish OAuth
    # must not route DNS again: the CNAME already exists and Cloudflare rejects
    # a second provisioning of the same hostname.
    if [ -n "$(env_value CLOUDFLARED_TUNNEL_NAME)" ] && [ -n "$(env_value MCP_BASE_URL)" ]; then
        info "Reusing already-configured Cloudflare connect hostname '$cf_hostname'."
    else
        route_output="$(cloudflared tunnel route dns "$tunnel_name" "$cf_hostname" 2>&1)"
        if [ $? -ne 0 ]; then
            if printf '%s' "$route_output" | grep -qiE "already exists|duplicate|record exists"; then
                warn "DNS record for '$cf_hostname' already exists; reusing it."
            else
                printf '%s\n' "$route_output" >&2
                die "Could not route DNS for '$cf_hostname'. Confirm the domain is on your Cloudflare account."
            fi
        fi
    fi
    ONBOARDING_PUBLIC_URL="https://$cf_hostname"
}

ensure_command_guard() {
    local provider bin_dir choice
    if [ "${MCP_COMMAND_GUARD_PROVIDER:-}" = "disabled" ]; then
        warn "Command guard disabled for this launch."
        return 0
    fi
    provider="$(env_value MCP_COMMAND_GUARD_PROVIDER)"
    [ -n "$provider" ] && return 0
    provider="${GATE_COMMAND_GUARD_PROVIDER:-}"
    if [ -z "$provider" ] && [ "${RUNTIME_COMMAND:-}" = setup ] && [ -t 0 ] && [ -t 1 ]; then
        printf '\nCommand safety guard\n1. Built-in guard (default)\n2. Destructive Command Guard (dcg)\nChoose [1/2]: ' > /dev/tty
        IFS= read -r choice < /dev/tty || choice=""
        provider="builtin"
        [ "$choice" = "2" ] && provider="dcg"
    fi
    provider="${provider:-builtin}"
    bin_dir="${GATE_ROOT:-$HOME/.gate}/runtime/bin"
    if [ ! -f "$PROJECT_DIR/src/dcg_installer.py" ]; then
        set_env_values MCP_COMMAND_GUARD_PROVIDER builtin MCP_COMMAND_GUARD_FALLBACK builtin
        return 0
    fi
    "$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/src/dcg_installer.py" \
        --config-root "$CONFIG_ROOT" --bin-dir "$bin_dir" --provider "$provider" || {
        warn "Command guard setup failed; using builtin."
        set_env_values MCP_COMMAND_GUARD_PROVIDER builtin MCP_COMMAND_GUARD_FALLBACK builtin
    }
}

ensure_ngrok_web_allow_hosts() {
    local ngrok_cfg="$HOME/.config/ngrok/ngrok.yml"
    [ -f "$ngrok_cfg" ] || return 0
    grep -q '127\.0\.0\.1' "$ngrok_cfg" && return 0
    warn "Adding 127.0.0.1 and localhost to ngrok web_allow_hosts."
    sed -i '/web_allow_hosts:/a\        - 127.0.0.1\n        - localhost' "$ngrok_cfg"
}

ensure_onboarding() {
    local renew_secret="${1:-false}" public_url access_secret access_hash provider choice cloudflared_tunnel_name mode tunnel_name_input

    mkdir -p "$CONFIG_ROOT"
    ensure_command_guard
    public_url="$(env_value MCP_BASE_URL)"
    provider="$(configured_tunnel_provider)"
    cloudflared_tunnel_name="${CLOUDFLARED_TUNNEL_NAME:-$(env_value CLOUDFLARED_TUNNEL_NAME)}"
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
        command -v curl >/dev/null 2>&1 || die "curl is required."
        if [ -z "${TUNNEL_PROVIDER:-$(env_value TUNNEL_PROVIDER)}" ] && [ -t 0 ] && [ -t 1 ]; then
            printf '\nTunnel provider\n1. ngrok (default)\n2. Tailscale Funnel\n3. Cloudflare Tunnel\nChoose [1/2/3]: ' > /dev/tty
            IFS= read -r choice < /dev/tty || choice=""
            provider="ngrok"
            [ "$choice" = "2" ] && provider="tailscale"
            [ "$choice" = "3" ] && provider="cloudflare"
        fi
        ensure_tunnel_provider "$provider"

        info "First-run setup"
        case "$provider" in
            ngrok)
                if ! ngrok config check >/dev/null 2>&1; then
                    prompt_ngrok_token || die "The ngrok authtoken cannot be empty."
                fi
                ensure_ngrok_web_allow_hosts
                info "Detecting your ngrok URL"
                open_temporary_ngrok || { cat "$NGROK_LOG" >&2 || true; die "Could not obtain the ngrok HTTPS URL. Check your ngrok token."; }
                public_url="$ONBOARDING_PUBLIC_URL"
                ;;
            tailscale)
                info "Detecting your Tailscale Funnel URL"
                open_temporary_tailscale || die "Could not obtain a public Tailscale Funnel HTTPS URL. Confirm Funnel is enabled for this tailnet."
                public_url="$ONBOARDING_PUBLIC_URL"
                ;;
            cloudflare)
                if [ -z "$cloudflared_tunnel_name" ] && [ -t 0 ] && [ -t 1 ]; then
                    printf '\nCloudflare Tunnel mode\n1. Temporary quick tunnel (random URL, no account)\n2. Cloudflare connect (named tunnel, stable URL, custom domain)\nChoose [1/2]: ' > /dev/tty
                    IFS= read -r mode < /dev/tty || mode=""
                    if [ "$mode" = "2" ]; then
                        printf 'Tunnel name [gate]: ' > /dev/tty
                        IFS= read -r tunnel_name_input < /dev/tty || tunnel_name_input=""
                        cloudflared_tunnel_name="${tunnel_name_input:-gate}"
                    fi
                fi
                if [ -n "$cloudflared_tunnel_name" ]; then
                    setup_cloudflared_connect "$cloudflared_tunnel_name"
                    public_url="$ONBOARDING_PUBLIC_URL"
                else
                    info "Detecting your Cloudflare Tunnel URL"
                    open_temporary_cloudflared || { cat "${MCP_LOG_ROOT:-$PROJECT_DIR/logs}/cloudflared.log" >&2 || true; die "Could not obtain a Cloudflare quick-tunnel HTTPS URL. Check that cloudflared is installed and that ~/.cloudflared has no config.yml/config.yaml blocking quick tunnels."; }
                    public_url="$ONBOARDING_PUBLIC_URL"
                fi
                ;;
            external)
                public_url="${MCP_BASE_URL:-$(env_value MCP_BASE_URL)}"
                [ -n "$public_url" ] || die "TUNNEL_PROVIDER=external requires MCP_BASE_URL=https://..."
                [[ "$public_url" == https://* ]] || die "MCP_BASE_URL must be a public HTTPS URL."
                ;;
        esac
        ok "Public URL: $public_url"
    fi

    if [ -z "$access_secret" ]; then
        access_secret="$($PROJECT_DIR/.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"
    fi
    access_hash="$(OAUTH_ACCESS_SECRET="$access_secret" "$PROJECT_DIR/.venv/bin/python" -c 'import os; from argon2 import PasswordHasher; print(PasswordHasher().hash(os.environ["OAUTH_ACCESS_SECRET"]))')"

    set_env_values \
        TUNNEL_PROVIDER "$provider" \
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
    [ -n "$cloudflared_tunnel_name" ] && set_env_values CLOUDFLARED_TUNNEL_NAME "$cloudflared_tunnel_name"

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
        IFS=: read -r SERVICES_PID TUNNEL_PID TUNNEL_PROVIDER_PID < "$PID_FILE"
        echo "✓ Gate already running (PID $SERVICES_PID)"
        if [ -n "${TUNNEL_PID:-}" ] && kill -0 "$TUNNEL_PID" 2>/dev/null; then
            echo "✓ ${TUNNEL_PROVIDER_PID:-ngrok} tunnel     (PID $TUNNEL_PID)"
            [ "${TUNNEL_PROVIDER_PID:-ngrok}" != ngrok ] || show_ngrok_inspector
        fi
        echo ""
        echo "  Stop with:  ./run.sh stop"
        echo "  Status:     ./run.sh status"
        return 0
    fi
    cleanup_stale_ngrok
    [ "$(configured_tunnel_provider)" = cloudflare ] && cleanup_stale_cloudflared
    ensure_python_environment
    export GATE_NGROK_TARGET="${GATE_NGROK_TARGET:-$(resolve_ngrok_target)}"
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
    [ "$(configured_tunnel_provider)" = cloudflare ] && cleanup_stale_cloudflared
    ensure_python_environment
    export GATE_NGROK_TARGET="${GATE_NGROK_TARGET:-$(resolve_ngrok_target)}"
    ensure_onboarding

    source .venv/bin/activate

    nohup "$PROJECT_DIR/.venv/bin/python" start_services.py > /dev/null 2>&1 &
    SERVICES_PID=$!
    sleep 2

    provider="$(configured_tunnel_provider)"
    TUNNEL_PID=""
    KEEP_AWAKE_LABEL="user managed"
    if [ "$provider" = ngrok ] && [ -n "${GATE_EXISTING_NGROK_PID:-}" ] && kill -0 "$GATE_EXISTING_NGROK_PID" 2>/dev/null; then
        TUNNEL_PID="$GATE_EXISTING_NGROK_PID"
        KEEP_AWAKE_LABEL="onboarding tunnel reused"
    elif [ "$provider" = tailscale ] && [ -n "${GATE_EXISTING_TAILSCALE_PID:-}" ] && kill -0 "$GATE_EXISTING_TAILSCALE_PID" 2>/dev/null; then
        TUNNEL_PID="$GATE_EXISTING_TAILSCALE_PID"
        KEEP_AWAKE_LABEL="onboarding tunnel reused"
    elif [ "$provider" = tailscale ] && [ -n "$(active_tailscale_funnel_url)" ]; then
        # An untracked Funnel already serves our port; Gate must not start a
        # second one ("listener already exists"). Nothing to manage or kill.
        KEEP_AWAKE_LABEL="existing funnel reused"
    elif [ "$provider" = cloudflare ] && [ -n "${GATE_EXISTING_CLOUDFLARED_PID:-}" ] && kill -0 "$GATE_EXISTING_CLOUDFLARED_PID" 2>/dev/null; then
        TUNNEL_PID="$GATE_EXISTING_CLOUDFLARED_PID"
        KEEP_AWAKE_LABEL="onboarding tunnel reused"
    elif [ "$provider" != external ]; then
        case "$provider" in
            ngrok) tunnel_cmd=(ngrok http "$GATE_NGROK_TARGET") ;;
            cloudflare)
                tunnel_name="${CLOUDFLARED_TUNNEL_NAME:-$(env_value CLOUDFLARED_TUNNEL_NAME)}"
                if [ -n "$tunnel_name" ]; then
                    tunnel_cmd=(cloudflared tunnel --no-autoupdate run --url "http://127.0.0.1:$NGROK_PORT" "$tunnel_name")
                else
                    tunnel_cmd=(cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:$NGROK_PORT")
                fi
                ;;
            *) tunnel_cmd=(tailscale funnel --bg=false "$NGROK_PORT") ;;
        esac
        if command -v caffeinate >/dev/null 2>&1; then
            tunnel_cmd=(caffeinate -i "${tunnel_cmd[@]}")
            KEEP_AWAKE_LABEL="caffeinate active"
        else
            KEEP_AWAKE_LABEL="sleep inhibition inactive"
        fi
        nohup "${tunnel_cmd[@]}" > /dev/null 2>&1 &
        TUNNEL_PID=$!
    fi

    echo "$SERVICES_PID:$TUNNEL_PID:$provider" > "$PID_FILE"
    echo "✓ Gateway started  (PID $SERVICES_PID)"
    if [ -n "$TUNNEL_PID" ]; then echo "✓ $provider tunnel (PID $TUNNEL_PID) [$KEEP_AWAKE_LABEL]"; else echo "✓ external tunnel managed by user"; fi
    [ "$provider" != ngrok ] || show_ngrok_inspector
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
    local SERVICES_PID="" TUNNEL_PID="" TUNNEL_PROVIDER_PID=""

    if [ -f "$PID_FILE" ]; then
        IFS=: read -r SERVICES_PID TUNNEL_PID TUNNEL_PROVIDER_PID < "$PID_FILE"
    fi

    if [ -n "$TUNNEL_PID" ]; then
        echo "⟶ stopping tunnel (PID $TUNNEL_PID)…"
        kill "$TUNNEL_PID" 2>/dev/null || true
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
    cleanup_stale_cloudflared
    rm -f "$PID_FILE"
    echo "✓ Gateway stopped"
}

status() {
    if [ ! -f "$PID_FILE" ]; then
        echo "ℹ Daemon not running"
        exit 0
    fi

    IFS=: read -r SERVICES_PID TUNNEL_PID TUNNEL_PROVIDER_PID < "$PID_FILE"
    if kill -0 "$SERVICES_PID" 2>/dev/null; then
        echo "✓ Gateway running  (PID $SERVICES_PID)"
    else
        echo "✗ Gateway not running (stale PID file)"
        rm -f "$PID_FILE"
        exit 1
    fi

    if [ "${TUNNEL_PROVIDER_PID:-ngrok}" = external ]; then
        echo "✓ external tunnel managed by user"
    elif [ -n "$TUNNEL_PID" ] && kill -0 "$TUNNEL_PID" 2>/dev/null; then
        echo "✓ ${TUNNEL_PROVIDER_PID:-ngrok} tunnel     (PID $TUNNEL_PID)"
        [ "${TUNNEL_PROVIDER_PID:-ngrok}" != ngrok ] || show_ngrok_inspector
    elif [ "${TUNNEL_PROVIDER_PID:-ngrok}" = tailscale ] && [ -n "$(active_tailscale_funnel_url)" ]; then
        echo "✓ tailscale tunnel (existing funnel reused)"
    else
        echo "✗ tunnel not running"
    fi

    echo ""
    echo "  Logs:"
    echo "    gateway → $PROJECT_DIR/logs/services/gateway.log"
    echo "  PIDs:"
    echo "    $SERVICES_PID:$TUNNEL_PID"
}

parse_runtime_args() {
    RUNTIME_COMMAND=""
    local widget=false queue=false arg
    for arg in "$@"; do
        case "$arg" in
            --widget) widget=true ;;
            --queue|--realtime) queue=true ;;
            start|stop|status|setup|renew-secret)
                [ -z "$RUNTIME_COMMAND" ] || die "Only one command may be specified."
                RUNTIME_COMMAND="$arg"
                ;;
            *) die "Unknown option or command: $arg" ;;
        esac
    done

    case "$RUNTIME_COMMAND" in
        stop|status|setup|renew-secret)
            if [ "$widget" = true ] || [ "$queue" = true ]; then
                die "Runtime flags are only valid when starting Gate."
            fi
            ;;
    esac

    export MCP_COMMAND_QUEUE_ENABLED=false
    if [ "$widget" = true ]; then
        export MCP_WIDGET_ENABLED=true
    fi
    if [ "$queue" = true ] || [ "$widget" = true ]; then
        export MCP_COMMAND_QUEUE_ENABLED=true
    fi
}

if [ "${1:-}" = "connect" ]; then
    shift
    ensure_python_environment
    export GATE_PROJECT_DIR="${GATE_PROJECT_DIR:-$PROJECT_DIR}"
    export PYTHONPATH="$PROJECT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
    exec "$PROJECT_DIR/.venv/bin/python" -m gate_cli connect "$@"
fi

parse_runtime_args "$@"
if [ -n "$RUNTIME_COMMAND" ]; then
    set -- "$RUNTIME_COMMAND"
else
    set --
fi

case "${1:-}" in
    start)   start_daemon ;;
    stop)    stop_daemon  ;;
    status)  status       ;;
    setup)   ensure_python_environment; ensure_onboarding ;;
    renew-secret) ensure_python_environment; ensure_onboarding true ;;
    *)
        if [ $# -gt 0 ]; then
        echo "Usage: $0 [start] [--queue] [--widget]"
        echo "       $0 {stop|status|setup|renew-secret}"
        echo "       $0 connect {cf|ts} [--name NAME] [--hostname HOST] [--yes]"
            echo ""
            echo "  (no arg)  Interactive mode – Ctrl+C stops everything"
            exit 1
        fi
        run_interactive
        ;;
esac
