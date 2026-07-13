#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION="$(cat "$SCRIPT_DIR/.ai-plc-version" 2>/dev/null || echo unknown)"
MODE=""
ARGS=()

usage() {
    echo "AI-PLC Universal Installer v${VERSION}"
    echo
    echo "Usage: $0 [OPTIONS] [cc|cursor|both|codex|all]"
    echo
    echo "Environments:"
    echo "  cc       Install for Claude Code only"
    echo "  cursor   Install for Cursor only"
    echo "  both     Install for Claude Code and Cursor (backward compatible)"
    echo "  codex    Install for Codex only"
    echo "  all      Install for Claude Code, Cursor, and Codex"
    echo "  (none)   Detect existing configuration and prompt"
    echo
    echo "Options:"
    echo "  --dry-run                  Show a read-only plan"
    echo "  --plan-only                Emit a machine-readable plan"
    echo "  --target PATH              Use the specified project directory"
    echo "  --migrate-legacy VERSION   Adopt a verified legacy release"
    echo "  --yes                      Confirm non-interactive operation"
    echo "  -h, --help                 Show this help message"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        cc|cursor|both|codex|all)
            [[ -z "$MODE" ]] || { echo "[ERROR] multiple modes specified" >&2; exit 1; }
            MODE="$1"; shift ;;
        --target|--migrate-legacy)
            [[ $# -ge 2 ]] || { echo "[ERROR] $1 requires a value" >&2; exit 1; }
            ARGS+=("$1" "$2"); shift 2 ;;
        --dry-run|--plan-only|--yes) ARGS+=("$1"); shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "[ERROR] Unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
done

if [[ -z "$MODE" ]]; then
    echo "Select installation target:"
    echo "  1) Claude Code only"
    echo "  2) Cursor only"
    echo "  3) Both (Claude Code + Cursor)"
    echo "  4) Codex only"
    echo "  5) All (Claude Code + Cursor + Codex)"
    read -r -p "Enter choice [1-5]: " choice
    case "$choice" in
        1) MODE=cc ;; 2) MODE=cursor ;; 3) MODE=both ;; 4) MODE=codex ;; 5) MODE=all ;;
        *) echo "[ERROR] Invalid choice" >&2; exit 1 ;;
    esac
fi

case "$MODE" in
    cc) exec bash "$SCRIPT_DIR/install-cc.sh" "${ARGS[@]}" ;;
    cursor) exec bash "$SCRIPT_DIR/install-cursor.sh" "${ARGS[@]}" ;;
    codex) exec bash "$SCRIPT_DIR/install-codex.sh" "${ARGS[@]}" ;;
    both|all)
        command -v python3 >/dev/null 2>&1 || { echo "[ERROR] python3 is required" >&2; exit 2; }
        exec python3 "$SCRIPT_DIR/lib/ai_plc_multi_env.py" install "$MODE" "${ARGS[@]}"
        ;;
esac
