#!/bin/bash
# setup-cron.sh - Install local scheduler/watchdog cron jobs.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="${PROJECT_DIR}/.venv"
PYTHON="${VENV}/bin/python"
DRY_RUN=0
UNINSTALL=0

usage() {
    cat <<EOF
Usage: ./setup-cron.sh [--dry-run] [--uninstall]

Options:
  --dry-run    Print the crontab that would be installed.
  --uninstall  Remove myMCP scheduler/watchdog cron jobs.
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

if [[ ! -x "$PYTHON" ]]; then
    echo "Virtual environment Python not found: $PYTHON" >&2
    echo "Create it first, then install project dependencies." >&2
    exit 1
fi

mkdir -p "${PROJECT_DIR}/logs"

BEGIN_MARKER="# BEGIN myMCP scheduler"
END_MARKER="# END myMCP scheduler"
SCHEDULER_JOB="0 * * * * cd '${PROJECT_DIR}' && '${PYTHON}' src/agent_scheduler.py --task-source configured >> logs/scheduler_cron.log 2>&1"
WATCHDOG_JOB="*/5 * * * * cd '${PROJECT_DIR}' && '${PYTHON}' src/watchdog.py >> logs/watchdog_cron.log 2>&1"

existing_crontab="$(crontab -l 2>/dev/null || true)"
kept_crontab="$(
    printf '%s\n' "$existing_crontab" | awk "
        \$0 == \"${BEGIN_MARKER}\" {skip=1; next}
        \$0 == \"${END_MARKER}\" {skip=0; next}
        skip != 1 {print}
    "
)"

if [[ "$UNINSTALL" -eq 1 ]]; then
    new_crontab="$kept_crontab"
else
    new_crontab="$(
        printf '%s\n' "$kept_crontab"
        printf '%s\n' "$BEGIN_MARKER"
        printf '%s\n' "$SCHEDULER_JOB"
        printf '%s\n' "$WATCHDOG_JOB"
        printf '%s\n' "$END_MARKER"
    )"
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
    printf '%s\n' "$new_crontab"
    exit 0
fi

printf '%s\n' "$new_crontab" | crontab -

if [[ "$UNINSTALL" -eq 1 ]]; then
    echo "myMCP scheduler/watchdog cron jobs removed."
else
    echo "myMCP scheduler/watchdog cron jobs installed."
    crontab -l | awk "
        \$0 == \"${BEGIN_MARKER}\" {show=1}
        show == 1 {print}
        \$0 == \"${END_MARKER}\" {show=0}
    "
fi
