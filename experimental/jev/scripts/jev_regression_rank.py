"""Rank artifacts by how likely they are to violate their acceptance criteria (use case: regression review ordering).

Use after changing an AI-PLC rule/skill: re-score past artifacts + criteria and review the most
suspicious ones first. This is ORDERING ONLY. It never outputs pass/fail and never replaces the
LLM reviewer. Items Jev could not score are listed last, in input order.

Input JSONL: one object per (artifact, criterion) with keys
  id, state (artifact text), criterion  [optional: label = pass|fail for --eval]

Usage:
  python3 .claude/ai-plc-jev/scripts/jev_regression_rank.py items.jsonl --out ranked.md [--csv ranked.csv] [--eval]
"""
import argparse
import csv
import json
import sys

sys.dont_write_bytecode = True  # no __pycache__ next to the installed scripts (clean uninstall)
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jev_client  # noqa: E402

QUESTION = ("Does the artifact in the state fully satisfy this acceptance criterion? Criterion: {c} "
            "Judge only from the artifact text; do not trust the artifact's own self-check section.")


def auroc(scores, ys):
    pos = [s for s, y in zip(scores, ys) if y]
    neg = [s for s, y in zip(scores, ys) if not y]
    if not pos or not neg:
        return None
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def pctl(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))] if xs else None


def rank(rows, scope_id=None, timeout=5.0, retries=2):
    scored = []
    for r in rows:
        q = {"satisfies": {"type": "noul", "instructions": QUESTION.format(c=r["criterion"])}}
        rec = jev_client.ask(r["state"], q, "regression_rank", scope_id=scope_id, task_id=r.get("id"),
                             timeout=timeout, retries=retries)
        p = rec["answers"]["satisfies"] if rec["action"] == "answered" else None
        p = p if isinstance(p, (int, float)) else None  # non-numeric answer -> treat as unscored
        scored.append({"id": r["id"], "suspicion": None if p is None else round(1 - p, 4),
                       "action": rec["action"], "decision_id": rec["decision_id"],
                       "latency_ms": rec["latency_ms"], "cost": rec["cost"], "label": r.get("label")})
    ok = sorted([s for s in scored if s["suspicion"] is not None], key=lambda s: -s["suspicion"])
    return ok + [s for s in scored if s["suspicion"] is None]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("items")
    ap.add_argument("--out", required=True)
    ap.add_argument("--csv")
    ap.add_argument("--scope-id")
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--retries", type=int, default=2, help="retries on 429/5xx/timeout (batch use; the monitor uses 0)")
    ap.add_argument("--eval", action="store_true", help="compute AUROC from label (pass/fail) — evaluation only")
    a = ap.parse_args()
    rows = [json.loads(l) for l in Path(a.items).open(encoding="utf-8") if l.strip()]
    if a.eval:
        rows = [r for r in rows if r.get("label") in ("pass", "fail")]
    res = rank(rows, a.scope_id, a.timeout, a.retries)
    lat = [s["latency_ms"] for s in res if s["latency_ms"] is not None]
    cost = sum(s["cost"] or 0 for s in res)
    skipped = [s for s in res if s["suspicion"] is None]
    lines = ["# Jev 回帰評価の順位付け（順位のみ・合否ではない）", "",
             f"- 件数: {len(res)} / 採点済み: {len(res) - len(skipped)} / スキップ: {len(skipped)}",
             f"- p95: {pctl(lat, 0.95) and round(pctl(lat, 0.95))} ms / 費用: ${cost:.6f}",
             "- 使い方: 上から順にreviewerが確認する。下位＝問題なし、ではない（設計メモ: 試行ではしきい値0.5で recall 約0.68）", ""]
    if a.eval:
        sc = [s for s in res if s["suspicion"] is not None]
        au = auroc([s["suspicion"] for s in sc], [s["label"] == "fail" for s in sc])
        lines.insert(4, f"- 評価用 AUROC（fail=陽性）: {au and round(au, 4)}")
    lines += ["| 順位 | id | 疑わしさ | 状態 |", "| --- | --- | --- | --- |"]
    for i, s in enumerate(res, 1):
        lines.append(f"| {i} | {s['id']} | {'' if s['suspicion'] is None else s['suspicion']} | {s['action']} |")
    Path(a.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["rank", "id", "suspicion", "action", "decision_id", "latency_ms", "cost"]
                               + (["label"] if a.eval else []))
            w.writeheader()
            for i, s in enumerate(res, 1):
                row = {k: s[k] for k in w.fieldnames if k in s}
                row["rank"] = i
                w.writerow(row)
    print("\n".join(lines[:6]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
