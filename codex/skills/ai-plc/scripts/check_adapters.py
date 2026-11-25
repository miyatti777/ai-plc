"""Read-only parity audit of AI-PLC canonical skills and Codex entrypoints.

Works in two layouts:
- installed: <repo>/.agents/skills/ai-plc/scripts/check_adapters.py, canonical skills in <repo>/.claude/
- distribution: <ai-plc checkout>/codex/skills/ai-plc/scripts/check_adapters.py, canonical skills in core/

Usage:
  python3 .agents/skills/ai-plc/scripts/check_adapters.py [--root <repo>] [--json]
Exit code: 0 = no errors, 1 = errors found.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True

import yaml


# pm-* adapters (bundled PM add-on) point at the aipm-guided operation documents, not a SKILL.md.
PM_OPS = {
    "pm-init": "init", "pm-persona": "persona", "pm-story": "story", "pm-issue": "issue",
    "pm-hypothesis": "hypothesis", "pm-todo": "todo", "pm-today": "today", "pm-suggest": "capture",
}


def metadata(path):
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if not text.startswith("---\n") or len(parts) < 3:
        raise ValueError(f"Missing frontmatter: {path}")
    meta = yaml.safe_load(parts[1])
    if not isinstance(meta, dict) or not meta.get("name") or not meta.get("description"):
        raise ValueError(f"Missing name/description: {path}")
    return meta, text


def layout(root):
    """Return (adapter_root, skills_root, rules_root). Canonical paths in adapters are always `.claude/...`."""
    if (root / "codex/skills/ai-plc").is_dir() and (root / "core/skills").is_dir():
        return root / "codex/skills/ai-plc", root / "core/skills", root / "core/rules"
    return root / ".agents/skills/ai-plc", root / ".claude/skills", root / ".claude/rules"


def audit(root):
    root = Path(root).resolve()
    adapter_root, skills_root, rules_root = layout(root)
    sources = sorted((skills_root / "ai-plc").glob("*/SKILL.md"))
    sources += sorted(skills_root.glob("plc-*/SKILL.md"))
    sources += sorted(skills_root.glob("ppm-*/SKILL.md"))
    errors, rows = [], []
    if not sources:
        errors.append("No canonical AI-PLC skills found")
    names = set()

    def check_adapter(name, canonical):
        rel_source = ".claude/skills/" + canonical.relative_to(skills_root).as_posix()
        adapter = adapter_root / name / "SKILL.md"
        if not adapter.is_file():
            errors.append(f"Missing adapter: {name}")
            return
        entry, text = metadata(adapter)
        if entry["name"] != name:
            errors.append(f"Name mismatch: {name}")
        if rel_source not in text:
            errors.append(f"Canonical reference missing: {name}")
        if "../references/codex-runtime.md" not in text:
            errors.append(f"Codex runtime reference missing: {name}")
        rows.append({"name": name, "canonical": rel_source,
                     "adapter": adapter.relative_to(root).as_posix(),
                     "canonical_sha256": hashlib.sha256(canonical.read_bytes()).hexdigest()})

    for canonical in sources:
        meta, _ = metadata(canonical)
        name = meta["name"]
        if name in names:
            errors.append(f"Duplicate canonical name: {name}")
        names.add(name)
        check_adapter(name, canonical)
    pm_count = 0
    for name, op in sorted(PM_OPS.items()):
        canonical = skills_root / "aipm-guided/ops" / f"{op}.md"
        if not canonical.is_file():
            errors.append(f"Missing canonical: .claude/skills/aipm-guided/ops/{op}.md")
            continue
        pm_count += 1
        names.add(name)
        check_adapter(name, canonical)
    for path in adapter_root.glob("*/SKILL.md"):
        entry, _ = metadata(path)
        if entry["name"] not in names:
            errors.append(f"Adapter without canonical skill: {path.relative_to(root)}")
    resources = [adapter_root / "references/codex-runtime.md",
                 rules_root / "ai-plc-system.md", rules_root / "ai-plc-session.md",
                 rules_root / "ai-plc-adaptive.md",
                 skills_root / "ai-plc/04-operation/knowledge-lint.md",
                 skills_root / "ai-plc/04-operation/platform-builder.md"]
    for path in resources:
        if not path.is_file():
            errors.append(f"Missing runtime resource: {path.relative_to(root).as_posix()}")
    return {"canonical_count": len(sources) + pm_count, "adapter_count": len(rows),
            "errors": errors, "skills": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = audit(args.root)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"AI-PLC parity: {result['adapter_count']}/{result['canonical_count']} adapters; "
              f"{len(result['errors'])} errors")
        for error in result["errors"]:
            print(error)
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
