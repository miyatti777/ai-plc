#!/usr/bin/env bash
set -euo pipefail

# AI-PLC Universal Installer
# Detects environment (Claude Code / Cursor) and runs the appropriate installer.
# Usage: ./install.sh [--dry-run] [--target /path/to/project] [cc|cursor|both]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION="$(cat "$SCRIPT_DIR/.ai-plc-version" 2>/dev/null || echo "unknown")"
DRY_RUN=""
TARGET_ARGS=""
ENV_MODE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN="--dry-run"; shift ;;
        --target) TARGET_ARGS="--target $2"; shift 2 ;;
        cc|cursor|both) ENV_MODE="$1"; shift ;;
        -h|--help)
            echo "AI-PLC Universal Installer v${VERSION}"
            echo ""
            echo "Usage: $0 [OPTIONS] [cc|cursor|both]"
            echo ""
            echo "Environments:"
            echo "  cc       Install for Claude Code only"
            echo "  cursor   Install for Cursor only"
            echo "  both     Install for both environments"
            echo "  (none)   Auto-detect and prompt"
            echo ""
            echo "Options:"
            echo "  --dry-run          Show what would be done without making changes"
            echo "  --target PATH      Install to specified project directory"
            echo "  -h, --help         Show this help message"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

echo ""
echo "🚀 AI-PLC Universal Installer v${VERSION}"
echo ""

if [[ -z "$ENV_MODE" ]]; then
    TARGET_DIR="${TARGET_ARGS#--target }"
    if [[ -z "$TARGET_DIR" ]]; then
        TARGET_DIR="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
    fi

    HAS_CC=false
    HAS_CURSOR=false
    [[ -d "$TARGET_DIR/.claude" ]] && HAS_CC=true
    [[ -d "$TARGET_DIR/.cursor" ]] && HAS_CURSOR=true

    echo "Detected environment:"
    $HAS_CC && echo "  ✅ Claude Code (.claude/ found)"
    $HAS_CURSOR && echo "  ✅ Cursor (.cursor/ found)"
    ! $HAS_CC && ! $HAS_CURSOR && echo "  📁 No existing config detected (will create new)"
    echo ""

    echo "Select installation target:"
    echo "  1) Claude Code only"
    echo "  2) Cursor only"
    echo "  3) Both"
    echo ""
    read -r -p "Enter choice [1-3]: " choice

    case "$choice" in
        1) ENV_MODE="cc" ;;
        2) ENV_MODE="cursor" ;;
        3) ENV_MODE="both" ;;
        *) echo "Invalid choice."; exit 1 ;;
    esac
fi

case "$ENV_MODE" in
    cc)
        bash "$SCRIPT_DIR/install-cc.sh" $DRY_RUN $TARGET_ARGS
        ;;
    cursor)
        bash "$SCRIPT_DIR/install-cursor.sh" $DRY_RUN $TARGET_ARGS
        ;;
    both)
        echo "=== Installing for Claude Code ==="
        bash "$SCRIPT_DIR/install-cc.sh" $DRY_RUN $TARGET_ARGS
        echo ""
        echo "=== Installing for Cursor ==="
        bash "$SCRIPT_DIR/install-cursor.sh" $DRY_RUN $TARGET_ARGS
        ;;
esac
