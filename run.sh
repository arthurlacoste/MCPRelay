#!/bin/bash
# ─────────────────────────────────────────────────────────────────────
# run.sh  –  MCP Gateway + ngrok tunnel manager
#
# Usage:
#   ./run.sh            Interactive mode (Ctrl+C stops everything)
#   ./run.sh start      Daemon mode (background)
#   ./run.sh stop       Stop the daemon
#   ./run.sh status     Check if daemon is running
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="/tmp/mcp_gateway.pid"
NGROK_PORT=8761     # unified gateway sert MCP + OAuth sur ce port

# ── helpers ─────────────────────────────────────────────────────────
_cleanup() {
    echo ""
    echo "⟶ arrêt du gateway…"
    kill "$SERVICES_PID" 2>/dev/null && wait "$SERVICES_PID" 2>/dev/null || true
    echo "✓ gateway arrêté"
}

# ── interactive (Ctrl+C stop) ──────────────────────────────────────
run_interactive() {
    cd "$PROJECT_DIR"
    source .venv/bin/activate

    # Lance le gateway en arrière-plan
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

    ngrok http "$NGROK_PORT"
}

# ── daemon ─────────────────────────────────────────────────────────
start_daemon() {
    if [ -f "$PID_FILE" ]; then
        echo "✗ Daemon already running (PID file $PID_FILE exists)"
        exit 1
    fi

    cd "$PROJECT_DIR"
    source .venv/bin/activate

    nohup python3 start_services.py > /dev/null 2>&1 &
    SERVICES_PID=$!
    sleep 2

    nohup ngrok http "$NGROK_PORT" > /dev/null 2>&1 &
    NGROK_PID=$!

    echo "$SERVICES_PID:$NGROK_PID" > "$PID_FILE"
    echo "✓ Gateway started  (PID $SERVICES_PID)"
    echo "✓ ngrok tunnel     (PID $NGROK_PID)"
    echo ""
    echo "  Stop with:  ./run.sh stop"
    echo "  Status:     ./run.sh status"
}

# ── stop daemon ────────────────────────────────────────────────────
stop_daemon() {
    if [ ! -f "$PID_FILE" ]; then
        echo "ℹ No daemon running"
        exit 0
    fi

    read -r SERVICES_PID NGROK_PID < "$PID_FILE"

    echo "⟶ stopping ngrok (PID $NGROK_PID)…"
    kill "$NGROK_PID" 2>/dev/null || true

    echo "⟶ stopping gateway (PID $SERVICES_PID)…"
    kill "$SERVICES_PID" 2>/dev/null || true

    # Attendre que le processus se termine vraiment
    for i in 1 2 3 4 5; do
        if ! kill -0 "$SERVICES_PID" 2>/dev/null; then
            break
        fi
        sleep 1
    done

    # Force kill si nécessaire
    kill -9 "$SERVICES_PID" 2>/dev/null || true

    rm -f "$PID_FILE"
    echo "✓ Gateway stopped"
}

# ── status ─────────────────────────────────────────────────────────
status() {
    if [ ! -f "$PID_FILE" ]; then
        echo "ℹ Daemon not running"
        exit 0
    fi

    read -r SERVICES_PID NGROK_PID < "$PID_FILE"

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

# ── dispatch ──────────────────────────────────────────────────────
case "${1:-}" in
    start)   start_daemon ;;
    stop)    stop_daemon  ;;
    status)  status       ;;
    *)
        # Si un argument inconnu est passé, on montre l'aide
        if [ $# -gt 0 ]; then
            echo "Usage: $0 {start|stop|status}"
            echo ""
            echo "  (no arg)  Interactive mode – Ctrl+C stops everything"
            exit 1
        fi
        run_interactive
        ;;
esac
