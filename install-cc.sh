#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
command -v python3 >/dev/null 2>&1 || { echo "[ERROR] python3 is required" >&2; exit 2; }
exec python3 "$SCRIPT_DIR/lib/ai_plc_multi_env.py" install cc "$@"
