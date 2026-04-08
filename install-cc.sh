#!/usr/bin/env bash
set -euo pipefail

# AI-PLC Installer for Claude Code
# Installs AI-PLC pipeline skills, rules, commands, and agents into a Claude Code project.
# Usage: ./install-cc.sh [--dry-run] [--target /path/to/project]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION="$(cat "$SCRIPT_DIR/.ai-plc-version" 2>/dev/null || echo "unknown")"
DRY_RUN=false
TARGET_DIR=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=true; shift ;;
        --target) TARGET_DIR="$2"; shift 2 ;;
        -h|--help)
            echo "AI-PLC Installer for Claude Code v${VERSION}"
            echo ""
            echo "Usage: $0 [OPTIONS]"
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

if [[ -z "$TARGET_DIR" ]]; then
    TARGET_DIR="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
fi

BACKUP_SUFFIX=".bak.$(date +%Y%m%d)"

info()  { echo "  ✅ $1"; }
warn()  { echo "  ⚠️  $1"; }
skip()  { echo "  ⏭️  $1 (already exists, skipping)"; }
dry()   { echo "  🔍 [dry-run] $1"; }

safe_copy() {
    local src="$1" dst="$2"
    if [[ "$DRY_RUN" == true ]]; then
        dry "copy $src → $dst"
        return
    fi
    if [[ -f "$dst" ]]; then
        cp "$dst" "${dst}${BACKUP_SUFFIX}"
        warn "Backed up existing: ${dst}${BACKUP_SUFFIX}"
    fi
    mkdir -p "$(dirname "$dst")"
    cp "$src" "$dst"
}

safe_copy_dir() {
    local src="$1" dst="$2"
    if [[ "$DRY_RUN" == true ]]; then
        dry "copy directory $src → $dst"
        return
    fi
    mkdir -p "$dst"
    cp -r "$src"/* "$dst"/ 2>/dev/null || true
}

safe_copy_if_missing() {
    local src="$1" dst="$2"
    if [[ -f "$dst" ]]; then
        skip "$dst"
        return
    fi
    if [[ "$DRY_RUN" == true ]]; then
        dry "copy $src → $dst (new)"
        return
    fi
    mkdir -p "$(dirname "$dst")"
    cp "$src" "$dst"
    info "Created: $dst"
}

merge_with_markers() {
    local template="$1" target="$2" marker_start="<!-- AI-PLC START -->" marker_end="<!-- AI-PLC END -->"

    if [[ "$DRY_RUN" == true ]]; then
        if [[ -f "$target" ]]; then
            dry "merge AI-PLC section into existing $target"
        else
            dry "create $target from template"
        fi
        return
    fi

    if [[ ! -f "$target" ]]; then
        cp "$template" "$target"
        info "Created: $target"
        return
    fi

    cp "$target" "${target}${BACKUP_SUFFIX}"

    if grep -q "$marker_start" "$target" 2>/dev/null; then
        local tmp
        tmp="$(mktemp)"
        awk -v start="$marker_start" -v end="$marker_end" -v tpl="$template" '
            BEGIN { skip=0 }
            $0 ~ start { skip=1; while((getline line < tpl) > 0) print line; next }
            $0 ~ end { skip=0; next }
            skip==0 { print }
        ' "$target" > "$tmp"
        mv "$tmp" "$target"
        info "Updated AI-PLC section in: $target"
    else
        echo "" >> "$target"
        cat "$template" >> "$target"
        info "Appended AI-PLC section to: $target"
    fi
}

echo ""
echo "🚀 AI-PLC Installer for Claude Code v${VERSION}"
echo "   Target: $TARGET_DIR"
if [[ "$DRY_RUN" == true ]]; then
    echo "   Mode: DRY RUN (no changes will be made)"
fi
echo ""

echo "📦 Step 1/6: Installing skills..."
safe_copy_dir "$SCRIPT_DIR/core/skills" "$TARGET_DIR/.claude/skills"
info "Skills installed: .claude/skills/ai-plc/"

echo ""
echo "📏 Step 2/6: Installing rules..."
for rule in "$SCRIPT_DIR"/core/rules/ai-plc-*.md; do
    fname="$(basename "$rule")"
    safe_copy "$rule" "$TARGET_DIR/.claude/rules/$fname"
done
info "Rules installed: .claude/rules/ai-plc-*.md"

echo ""
echo "⌨️  Step 3/6: Installing commands..."
safe_copy_dir "$SCRIPT_DIR/claude-code/commands" "$TARGET_DIR/.claude/commands"
info "Commands installed: .claude/commands/"

echo ""
echo "🤖 Step 4/6: Installing agents..."
safe_copy_dir "$SCRIPT_DIR/claude-code/agents" "$TARGET_DIR/.claude/agents"
info "Agents installed: .claude/agents/"

echo ""
echo "📝 Step 5/6: Merging CLAUDE.md / AGENTS.md..."
merge_with_markers "$SCRIPT_DIR/claude-code/CLAUDE.md.template" "$TARGET_DIR/CLAUDE.md"
merge_with_markers "$SCRIPT_DIR/claude-code/AGENTS.md.template" "$TARGET_DIR/AGENTS.md"

echo ""
echo "🧠 Step 6/6: Installing templates (skip if exists)..."
safe_copy_if_missing "$SCRIPT_DIR/templates/soul.md" "$TARGET_DIR/.claude/soul.md"
safe_copy_if_missing "$SCRIPT_DIR/templates/user.md" "$TARGET_DIR/.claude/user.md"
safe_copy_if_missing "$SCRIPT_DIR/templates/memory.md" "$TARGET_DIR/.claude/memory.md"
mkdir -p "$TARGET_DIR/.claude/wiki" 2>/dev/null || true
safe_copy_if_missing "$SCRIPT_DIR/templates/wiki/index.md" "$TARGET_DIR/.claude/wiki/index.md"
safe_copy_if_missing "$SCRIPT_DIR/templates/wiki/log.md" "$TARGET_DIR/.claude/wiki/log.md"

if [[ "$DRY_RUN" != true ]]; then
    cp "$SCRIPT_DIR/.ai-plc-version" "$TARGET_DIR/.ai-plc-version"
fi

echo ""
echo "✨ AI-PLC for Claude Code installed successfully!"
echo "   Version: $VERSION"
echo ""
echo "Next steps:"
echo "  1. Edit .claude/soul.md with your AI identity"
echo "  2. Edit .claude/user.md with your profile"
echo "  3. Run: /project:sense to start your first pipeline"
echo ""
