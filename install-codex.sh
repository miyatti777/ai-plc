#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERROR] python3 is required by the AI-PLC safe installer." >&2
    exit 2
fi

exec python3 "$SCRIPT_DIR/lib/ai_plc_safe_fs.py" "$@"
