#!/bin/bash
# setup-startup.sh - Install the myMCP gateway LaunchAgent for macOS login.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.mymcp.gateway"
SOURCE_PLIST="${PROJECT_DIR}/config/${LABEL}.plist"
TARGET_DIR="${HOME}/Library/LaunchAgents"
TARGET_PLIST="${TARGET_DIR}/${LABEL}.plist"
DRY_RUN=0
UNINSTALL=0
LOAD_NOW=0

usage() {
    cat <<EOF
Usage: ./setup-startup.sh [--dry-run] [--uninstall] [--load-now]

Options:
  --dry-run    Print the actions without changing LaunchAgents.
  --uninstall  Remove the LaunchAgent.
  --load-now   Load the LaunchAgent immediately after installation.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        --uninstall)
            UNINSTALL=1
            shift
            ;;
        --load-now)
            LOAD_NOW=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ ! -f "$SOURCE_PLIST" ]]; then
    echo "Missing plist template: $SOURCE_PLIST" >&2
    exit 1
fi

if ! plutil -lint "$SOURCE_PLIST" >/dev/null; then
    echo "Invalid plist: $SOURCE_PLIST" >&2
    exit 1
fi

mkdir -p "${PROJECT_DIR}/logs"

if [[ "$UNINSTALL" -eq 1 ]]; then
    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "Would unload and remove: $TARGET_PLIST"
        exit 0
    fi
    launchctl bootout "gui/$(id -u)" "$TARGET_PLIST" 2>/dev/null || true
    rm -f "$TARGET_PLIST"
    echo "Removed LaunchAgent: $TARGET_PLIST"
    exit 0
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "Would install: $SOURCE_PLIST -> $TARGET_PLIST"
    if [[ "$LOAD_NOW" -eq 1 ]]; then
        echo "Would load now with launchctl bootstrap gui/$(id -u) $TARGET_PLIST"
    fi
    exit 0
fi

mkdir -p "$TARGET_DIR"
cp "$SOURCE_PLIST" "$TARGET_PLIST"
chmod 644 "$TARGET_PLIST"
echo "Installed LaunchAgent: $TARGET_PLIST"

if [[ "$LOAD_NOW" -eq 1 ]]; then
    launchctl bootout "gui/$(id -u)" "$TARGET_PLIST" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$TARGET_PLIST"
    echo "Loaded LaunchAgent now."
else
    echo "It will run at next macOS login."
fi
