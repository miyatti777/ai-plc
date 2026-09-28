"""Success-criteria coverage hint for AI-PLC Inception (experimental, ai-plc-jev only).

Before the decomposition approval (02-inception Phase 4), ask Jev — in ONE request — for each success criterion
in intent.yaml: "which backlog task satisfies it?" with the task IDs plus NONE as choices. Criteria whose answer
is NONE (or whose NONE probability >= 0.5) are shown as a one-line hint. The main model decides whether a task
is really missing; nothing is changed automatically, and the script always exits 0.

Opt-in (intent.yaml jev_monitor: true), redact/sanitize and hash-only logging come from jev_client.

Usage: python3 .claude/ai-plc-jev/scripts/jev_coverage_check.py --layer <Layer path> [--backlog <path>]
"""
import argparse
import sys

sys.dont_write_bytecode = True  # no __pycache__ next to the installed scripts (clean uninstall)
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jev_bt_monitor as mon  # noqa: E402

jev_client = mon.jev_client
USE_CASE = "coverage"
NONE = "__NONE__"  # sentinel label; cannot collide with a task ID (tasks with this ID are excluded)
QUESTION = ("Which task in the backlog (the state) would, when completed, satisfy this success criterion? "
            "Criterion: {c} Choose NONE if no single task clearly covers it.")


def build(intent, backlog):
    crit = [str(c).strip() for c in ((intent.get("goal") or {}).get("success_criteria") or []) if str(c).strip()]
    tasks, seen, dup = [], set(), []
    for t in (backlog.get("tasks") or []):
        if not (isinstance(t, dict) and t.get("id")) or t.get("status") in mon.SKIP:
            continue
        tid = str(t["id"])
        if tid == NONE or tid in seen:
            dup.append(tid)
            continue
        seen.add(tid)
        tasks.append(t)
    build.duplicates = dup
    if not crit or not tasks:
        return None, None, crit
    lines = [f"ゴール: {' '.join(str((intent.get('goal') or {}).get('description', '')).split())[:200]}", "タスク一覧:"]
    choices = {}
    for t in tasks:
        tid = str(t["id"])
        desc = " ".join(str(t.get("description") or "").split())[:160]
        lines.append(f"- {tid}: {t.get('name', '')} — {desc}")
        choices[tid] = f"{tid}: {str(t.get('name', ''))[:60]}"
    choices[NONE] = "どのタスクもこの成功条件を満たさない"
    questions = {f"c{i + 1}": {"type": "choice", "instructions": QUESTION.format(c=c), "criteria": choices}
                 for i, c in enumerate(crit)}
    return "\n".join(lines), questions, crit


def check(layer, backlog_path=None, ask=jev_client.ask):
    layer = Path(layer)
    intent = mon.load_yaml(layer / "intent.yaml")
    backlog = mon.load_yaml(Path(backlog_path) if backlog_path else layer / "backlog.yaml")
    if intent.get("jev_monitor") is not True:
        return ["Jev成功条件カバー判定: 無効（intent.yaml に jev_monitor: true がないため送信しない）"], None
    state, questions, crit = build(intent, backlog)
    if not questions:
        return ["Jev成功条件カバー判定: スキップ（成功条件またはタスクがない）"], None
    rec = ask(state, questions, USE_CASE, scope_id=intent.get("scope_id"), task_id="inception", timeout=10, retries=1)
    if rec.get("action") != "answered":
        return [f"Jev成功条件カバー判定: スキップ（{rec.get('action')}）— 通常どおり続行"], rec
    ans = rec.get("answers") or {}
    missing, mapping = [], []
    for i, c in enumerate(crit):
        a = ans.get(f"c{i + 1}") or {}
        probs = a.get("probabilities") or {}
        choice = a.get("choice")
        p_none = probs.get(NONE, 1.0 if choice == NONE else 0.0)
        mapping.append(f"  ・{c[:40]}… → {'NONE' if choice == NONE else (choice or '?')}")
        if choice == NONE or p_none >= jev_client.THRESHOLD:
            missing.append(f"「{c[:50]}」(NONE p={p_none:.2f})")
    note = f"（重複・予約IDのため除外: {', '.join(build.duplicates)}）" if getattr(build, "duplicates", None) else ""
    head = (f"🧭 Jev成功条件カバー判定: {len(crit)}件中 {len(missing)}件がどのタスクにも対応しない可能性 — "
            + " / ".join(missing) if missing else f"Jev成功条件カバー判定: {len(crit)}件すべてに対応タスクあり")
    return [head + f"（decision_id={rec['decision_id']}）{note}"] + mapping, rec


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--layer")
    ap.add_argument("--backlog")
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        return 0
    try:
        if a.layer:
            print("\n".join(check(a.layer, a.backlog)[0]))
    except Exception as e:  # never block the pipeline
        print(f"Jev成功条件カバー判定: スキップ（内部エラー {type(e).__name__}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
