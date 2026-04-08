#!/usr/bin/env bash
set -euo pipefail

# AI-PLC Uninstaller
# Removes AI-PLC files from Claude Code and/or Cursor project.
# Usage: ./uninstall.sh [--dry-run] [--target /path/to/project]

DRY_RUN=false
TARGET_DIR=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=true; shift ;;
        --target) TARGET_DIR="$2"; shift 2 ;;
        -h|--help)
            echo "AI-PLC Uninstaller"
            echo ""
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --dry-run          Show what would be removed without making changes"
            echo "  --target PATH      Uninstall from specified project directory"
            echo "  -h, --help         Show this help message"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ -z "$TARGET_DIR" ]]; then
    TARGET_DIR="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
fi

info()  { echo "  ✅ $1"; }
dry()   { echo "  🔍 [dry-run] $1"; }

safe_remove() {
    local target="$1"
    if [[ ! -e "$target" ]]; then
        return
    fi
    if [[ "$DRY_RUN" == true ]]; then
        dry "remove $target"
        return
    fi
    rm -rf "$target"
    info "Removed: $target"
}

remove_markers() {
    local file="$1"
    local marker_start="<!-- AI-PLC START -->"
    local marker_end="<!-- AI-PLC END -->"

    if [[ ! -f "$file" ]]; then
        return
    fi

    if ! grep -q "$marker_start" "$file" 2>/dev/null; then
        return
    fi

    if [[ "$DRY_RUN" == true ]]; then
        dry "remove AI-PLC section from $file"
        return
    fi

    local tmp
    tmp="$(mktemp)"
    awk -v start="$marker_start" -v end="$marker_end" '
        $0 ~ start { skip=1; next }
        $0 ~ end { skip=0; next }
        skip==0 { print }
    ' "$file" > "$tmp"
    mv "$tmp" "$file"
    info "Removed AI-PLC section from: $file"
}

echo ""
echo "🗑️  AI-PLC Uninstaller"
echo "   Target: $TARGET_DIR"
if [[ "$DRY_RUN" == true ]]; then
    echo "   Mode: DRY RUN"
fi
echo ""

echo "Claude Code files:"
safe_remove "$TARGET_DIR/.claude/skills/ai-plc"
for rule in "$TARGET_DIR"/.claude/rules/ai-plc-*.md; do
    safe_remove "$rule"
done
remove_markers "$TARGET_DIR/CLAUDE.md"
remove_markers "$TARGET_DIR/AGENTS.md"

echo ""
echo "Cursor files:"
safe_remove "$TARGET_DIR/.cursor/skills/ai-plc"
for rule in "$TARGET_DIR"/.cursor/rules/ai-plc-*.mdc; do
    safe_remove "$rule"
done

echo ""
echo "Shared files:"
safe_remove "$TARGET_DIR/.ai-plc-version"

echo ""
echo "⚠️  The following files were NOT removed (may contain your customizations):"
echo "   .claude/soul.md, .claude/user.md, .claude/memory.md, .claude/wiki/"
echo "   .claude/commands/, .claude/agents/"
echo ""
echo "✨ AI-PLC uninstalled."
