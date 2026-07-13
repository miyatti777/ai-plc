#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MODE="both"
MODE_SET=false
ARGS=()

usage() {
    echo "AI-PLC Uninstaller"
    echo
    echo "Usage: $0 [OPTIONS] [cc|cursor|both|codex|all]"
    echo
    echo "Modes: cc, cursor, both (default), codex, all"
    echo "Options:"
    echo "  --dry-run       Show a read-only removal plan"
    echo "  --plan-only     Emit a machine-readable plan"
    echo "  --target PATH   Use the specified project directory"
    echo "  --yes           Confirm non-interactive operation"
    echo "  -h, --help      Show this help message"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        cc|cursor|both|codex|all)
            $MODE_SET && { echo "[ERROR] multiple modes specified" >&2; exit 1; }
            MODE="$1"; MODE_SET=true; shift ;;
        --target)
            [[ $# -ge 2 ]] || { echo "[ERROR] --target requires a value" >&2; exit 1; }
            ARGS+=("$1" "$2"); shift 2 ;;
        --dry-run|--plan-only|--yes) ARGS+=("$1"); shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "[ERROR] Unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
done

command -v python3 >/dev/null 2>&1 || { echo "[ERROR] python3 is required" >&2; exit 2; }
exec python3 "$SCRIPT_DIR/lib/ai_plc_multi_env.py" uninstall "$MODE" "${ARGS[@]}"
