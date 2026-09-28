"""Backtrack anomaly hint for AI-PLC 04-operation (use case: Backtrack monitoring).

Division of labor (RUL_plc_adaptive §5):
- Counting conditions (50% done, >5 done, ad-hoc >= 2, all done) are decided HERE IN CODE, never by Jev.
- Jev answers one question only: is there an anomaly? (5.5b: blocker / 6b: drift / prompt: user_signal)
- The main model decides the Backtrack type and writes the proposal. Execution needs user approval.
- This script never stops anything: it prints one hint line and always exits 0.
- Opt-in: only Layers whose intent.yaml has `jev_monitor: true` send anything to Jev.

Usage:
  python3 .claude/ai-plc-jev/scripts/jev_bt_monitor.py --layer <Layer path> --phase 5.5b [--task T003] [--report "<completion report>"]
  python3 .claude/ai-plc-jev/scripts/jev_bt_monitor.py --layer <Layer path> --phase 6b
  python3 .claude/ai-plc-jev/scripts/jev_bt_monitor.py --override <decision_id> accept|reject   # accept = the judgment was right (hint or not)
  python3 .claude/ai-plc-jev/scripts/jev_bt_monitor.py --noise-report [--use-case bt_monitor|prompt_hook|coverage|status_audit]
"""
import argparse
import fcntl
import json
import os
import re
import sys

sys.dont_write_bytecode = True  # no __pycache__ next to the installed scripts (clean uninstall)
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jev_client  # noqa: E402

Q = {
    "blocker": ("Does the latest report show a blocker that should stop work and revise the plan: a critical failure, "
                "an unresolved external dependency, a contradiction with a design assumption, or insufficient verification "
                "coverage? Minor issues already resolved inside the task do not count."),
    "drift": ("Is there a sign that the plan or goal no longer fits: new goals or scope changes, earlier deliverables now "
              "inconsistent, or tasks needed for the goal missing from the backlog? Reaching a progress percentage alone "
              "does not count."),
    "user_signal": ("Does the latest user utterance correct the progress, point out something missing, add a new requirement, "
                    "or bring a new fact that changes assumptions? Simple approvals or small cosmetic edits do not count. "
                    "If there is no user utterance, answer no."),
}
PHASE_Q = {"5.5b": "blocker", "6b": "drift", "prompt": "user_signal"}
DONE = ("completed", "done")
SKIP = ("cancelled", "deferred")


def load_yaml(p):
    try:
        d = yaml.safe_load(Path(p).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return d if isinstance(d, dict) else {}


_ADHOC_RE = re.compile(r"re[-_ ]?(inception|collection)|backtrack|ad[-_ ]?hoc|\bbt-?[abc]\b", re.IGNORECASE)


def is_adhoc(task):
    """origin is free text in real backlogs (inception / decomposition / user_goal / Stage 2 Inception /
    'Re-Inception: …' / re_inception_v3 / backtrack …). Count as ad-hoc only when it carries an explicit
    "added later" marker; anything else is a planned task (unknown -> planned avoids false BT-B hints).
    Design note: checked against the origin values found in real backlogs."""
    return bool(_ADHOC_RE.search(str(task.get("origin") or "")))


LABELS = {"all_done": "BT-C: 全タスク完了 → GAP分析", "ratio50": "BT-B: 完了率50%到達", "done_gt5": "BT-B: 完了5件超"}
COUNTS_STATE_PATH = Path(os.environ.get("JEV_COUNTS_STATE_PATH",
                                        jev_client.REPO / ".claude" / "db" / "jev_counts_state.json"))


def count_conditions(backlog):
    """Deterministic §5 counting conditions. Returns (stats, {condition_key: label})."""
    tasks = [t for t in (backlog.get("tasks") or []) if isinstance(t, dict) and t.get("status") not in SKIP]
    done = [t for t in tasks if t.get("status") in DONE]
    adhoc = [t for t in tasks if is_adhoc(t)]
    n, d = len(tasks), len(done)
    st = {"total": n, "done": d, "adhoc": len(adhoc), "ratio": (d / n) if n else 0.0}
    cond = {}
    if n and d == n:
        cond["all_done"] = LABELS["all_done"]
    else:
        if n and st["ratio"] >= 0.5:
            cond["ratio50"] = LABELS["ratio50"]
        if d > 5:
            cond["done_gt5"] = LABELS["done_gt5"]
        if len(adhoc) >= 2:
            cond["adhoc"] = f"BT-B: ad-hoc {len(adhoc)}件"
    return st, cond


def counts(backlog):
    """Backward-compatible view: (stats, list of all currently true condition labels)."""
    st, cond = count_conditions(backlog)
    return st, list(cond.values())


def _read_state(f):
    try:
        f.seek(0)
        d = json.loads(f.read() or "{}")
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


def new_conditions(key, st, cond, save=True):
    """Only conditions that newly hold since the previous 6b of this Layer (hide re-shown BT-B noise).
    A condition that stops holding is forgotten, so it can fire again later. ad-hoc re-fires when the count grows;
    all_done re-fires when the task total changed. State holds counts and condition keys only (no text).
    The shared state file is updated under an exclusive lock and replaced atomically (concurrent Layers)."""
    try:
        COUNTS_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        lock = open(str(COUNTS_STATE_PATH) + ".lock", "a+", encoding="utf-8")
    except OSError:
        lock = None
    try:
        if lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            with open(COUNTS_STATE_PATH, "r", encoding="utf-8") as f:
                state = _read_state(f)
        except OSError:
            state = {}
        prev = state.get(key) if isinstance(state.get(key), dict) else {}
        fired = set(prev.get("fired") or [])
        out = []
        for k, label in cond.items():
            if k not in fired:
                out.append(label)
            elif k == "adhoc" and st["adhoc"] > int(prev.get("adhoc") or 0):
                out.append(label)
            elif k == "all_done" and st["total"] != int(prev.get("total") or 0):
                out.append(label)
        if save:
            state[key] = {"fired": sorted(cond), "adhoc": st["adhoc"], "total": st["total"], "done": st["done"]}
            try:
                fd, tmp = tempfile.mkstemp(dir=str(COUNTS_STATE_PATH.parent), prefix=".jev_counts_", suffix=".tmp")
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True))
                os.replace(tmp, COUNTS_STATE_PATH)
            except OSError:
                pass  # never block the pipeline
        return out
    finally:
        if lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_UN)
            finally:
                lock.close()


def build_state(intent, backlog, st, report=None, task=None, utterance=None):
    goal = " ".join(str((intent.get("goal") or {}).get("description", "")).split())[:200]
    if report is None:
        tasks = backlog.get("tasks") or []
        pick = [t for t in tasks if t.get("id") == task] if task else [t for t in tasks if t.get("status") in DONE]
        report = str((pick[-1].get("result") or pick[-1].get("description") or "")) if pick else ""
    lines = [f"ゴール: {goal}", f"進捗: {st['done']}/{st['total']}完了（ad-hoc {st['adhoc']}件）",
             f"直近のタスク完了報告: {report.strip()[:1200]}"]
    if utterance:
        lines.append(f"直近のユーザー発話: {utterance.strip()[:400]}")
    return "\n".join(lines)


def hint_line(rec, qid):
    if rec is None:
        return "Jev監視: 無効（intent.yaml に jev_monitor: true がないため送信しない）"
    if rec["action"] != "answered":
        return f"Jev監視: スキップ（{rec['action']}）— 通常どおり続行"
    p = rec["answers"][qid]
    if isinstance(p, (int, float)) and p >= jev_client.THRESHOLD:
        return (f"💡 Jev監視: 異常の可能性（{qid} p={p:.2f}）— 種類と提案はメインモデルが判断し、提案のみ行う"
                f"（decision_id={rec['decision_id']}）")
    return f"Jev監視: 異常なし（{qid} p={p:.2f}）（decision_id={rec['decision_id']}）"


def monitor(layer, phase, task=None, report=None, utterance=None, ask=jev_client.ask):
    layer = Path(layer)
    intent, backlog = load_yaml(layer / "intent.yaml"), load_yaml(layer / "backlog.yaml")
    st, cond = count_conditions(backlog)
    out = []
    if phase == "6b":
        key = f"{intent.get('scope_id') or '-'}|{layer.resolve()}"  # same scope_id in two dirs stays separate
        fresh = new_conditions(key, st, cond)
        if fresh:
            out.append("📏 数え上げ判定（コード）: " + " / ".join(fresh))
    qid = PHASE_Q[phase]
    rec = None
    if intent.get("jev_monitor") is True:
        state = build_state(intent, backlog, st, report, task, utterance)
        rec = ask(state, {qid: {"type": "noul", "instructions": Q[qid]}}, "bt_monitor",
                  scope_id=intent.get("scope_id"), task_id=task)
    out.append(hint_line(rec, qid))
    return out, rec


STATUS_AUDIT_HINT_CHOICES = ("done", "handed_off")


def _status_audit_hint(vals):
    """status_audit (--jev) asks one choice question per stale Layer: done / handed_off / stalled / unknown.
    The code already says "stale", so a *hint* is an answer that doubts it: done (実質完了) or handed_off (引き継ぎ済み).
    stalled / unknown agree with the code (no hint). Uses `choice`, or the most probable label when choice is missing."""
    for v in vals:
        if not isinstance(v, dict):
            continue
        choice = v.get("choice")
        probs = v.get("probabilities") or {}
        if choice is None and isinstance(probs, dict) and probs:
            choice = max(probs, key=lambda k: probs[k] if isinstance(probs[k], (int, float)) else -1)
        if choice in STATUS_AUDIT_HINT_CHOICES:
            return True
    return False


def noise_report(use_case="bt_monitor"):
    """Two views over the real log (the given use_case, answered; bt_monitor by default):
    - all judgments: human verdict per decision (accept = the judgment was right, hint or not; reject = wrong)
    - shown hints only: rejection rate = noise rate"""
    decs = {}
    if jev_client.LOG_PATH.exists():
        with jev_client.LOG_PATH.open(encoding="utf-8") as f:
            rows = [json.loads(l) for l in f if l.strip()]
        for r in rows:
            if r.get("use_case") == use_case and r.get("action") == "answered":
                vals = list((r.get("answers") or {}).values())
                if use_case == "coverage":  # hint shown when any criterion maps to NONE
                    decs[r["decision_id"]] = any(isinstance(v, dict) and (
                        v.get("choice") == "__NONE__" or (v.get("probabilities") or {}).get("__NONE__", 0) >= jev_client.THRESHOLD)
                        for v in vals)
                elif use_case == "status_audit":  # choice; hint = Jev doubts the code's "stale" (see _status_audit_hint)
                    decs[r["decision_id"]] = _status_audit_hint(vals)
                elif vals and isinstance(vals[0], (int, float)):
                    decs[r["decision_id"]] = vals[0] >= jev_client.THRESHOLD
    ov = {}
    if jev_client.OVERRIDE_PATH.exists():
        with jev_client.OVERRIDE_PATH.open(encoding="utf-8") as f:
            rows = [json.loads(l) for l in f if l.strip()]
        for r in rows:
            ov[r["decision_id"]] = r["human_override"]  # last write wins
    judged = [d for d in decs if d in ov]
    wrong = [d for d in judged if ov[d] == "reject"]
    hints = [d for d, shown in decs.items() if shown]
    h_judged = [d for d in hints if d in ov]
    h_rej = [d for d in h_judged if ov[d] == "reject"]
    rate = f"{len(wrong) / len(judged):.1%}" if judged else "n/a"
    hrate = f"{len(h_rej) / len(h_judged):.1%}" if h_judged else "n/a"
    title = "Jev監視の判定" if use_case == "bt_monitor" else f"Jev監視の判定（{use_case}）"
    out = (f"{title}: 総数 {len(decs)}件 / 人が確認 {len(judged)}件 / 外れ {len(wrong)}件 / 外れ率 {rate}"
           f"（参考: 実験版README の「試す人向けの確認観点」）\n"
           f"うちヒント: 出した {len(hints)}件 / 人が判定 {len(h_judged)}件 / 却下 {len(h_rej)}件 / 却下率 {hrate}")
    if use_case == "status_audit":
        out += "\n（status_audit のヒント＝停滞とされた Layer に Jev が done / handed_off と答えたもの。stalled / unknown はヒントに数えない）"
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--layer")
    ap.add_argument("--phase", choices=sorted(PHASE_Q))
    ap.add_argument("--task")
    ap.add_argument("--report")
    ap.add_argument("--utterance")
    ap.add_argument("--override", nargs=2, metavar=("DECISION_ID", "VERDICT"))
    ap.add_argument("--noise-report", action="store_true")
    ap.add_argument("--use-case", default="bt_monitor", choices=["bt_monitor", "prompt_hook", "coverage", "status_audit"])
    try:
        a = ap.parse_args(argv)
    except SystemExit:  # bad invocation must not block the pipeline either
        return 0
    try:
        if a.override:
            jev_client.record_override(a.override[0], a.override[1])
            print(f"human_override を記録: {a.override[0]} = {a.override[1]}")
        elif a.noise_report:
            print(noise_report(a.use_case))
        elif a.layer and a.phase:
            print("\n".join(monitor(a.layer, a.phase, a.task, a.report, a.utterance)[0]))
        else:
            ap.print_usage()
    except Exception as e:  # never block the pipeline
        print(f"Jev監視: スキップ（内部エラー {type(e).__name__}）— 通常どおり続行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
