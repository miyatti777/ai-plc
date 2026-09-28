"""Claude Code UserPromptSubmit hook: per-utterance Jev check (experimental, ai-plc-jev only).

Asks Jev one question about the user's latest utterance (correction / missing item / scope change / concern,
even indirect) and, when p >= 0.5, adds ONE line of context for the main model. It never blocks a prompt:
every path exits 0, and on any doubt it stays silent.

Scope gate (the main privacy control):
- The hook is dormant unless THIS session activated it. A prompt that starts with /04-operation-jev or
  /01-collection-jev and names a Layer whose intent.yaml has `jev_monitor: true` binds that session to that
  Layer (marker file keyed by session_id). Other sessions, and this session before activation, send nothing.
- Bindings expire after ACTIVE_HOURS, or on `--deactivate [session_id]`, or when JEV_DISABLE=1.

Pre-filters (skip without sending): slash commands, short approvals (OK / A / accept / はい ...),
questions ending with ？/?, and pasted blocks (<pasted_content>…</pasted_content> is removed; only the user's
own text, up to MAX_CHARS, is sent). redact() in jev_client still applies.

Usage:
  (hook)  python3 .claude/ai-plc-jev/scripts/jev_prompt_hook.py            # reads the hook JSON from stdin
  python3 .claude/ai-plc-jev/scripts/jev_prompt_hook.py --status
  python3 .claude/ai-plc-jev/scripts/jev_prompt_hook.py --deactivate [SESSION_ID]
"""
import fcntl
import json
import os
import re
import signal
import sys

sys.dont_write_bytecode = True  # no __pycache__ next to the installed scripts (clean uninstall)
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jev_bt_monitor as mon  # noqa: E402

jev_client = mon.jev_client
MARKER_PATH = Path(os.environ.get("JEV_HOOK_MARKER_PATH",
                                  jev_client.REPO / ".claude" / "db" / "jev_prompt_hook_sessions.json"))
ACTIVE_HOURS = float(os.environ.get("JEV_HOOK_ACTIVE_HOURS", "12"))
MAX_CHARS = 400
TIMEOUT = 1.5           # Jev HTTP timeout
KEYCHAIN_TIMEOUT = "1.0"  # seconds for the macOS keychain lookup
TOTAL_BUDGET = 3        # hard wall-clock cap for the whole hook (seconds)
USE_CASE = "prompt_hook"

ACTIVATE_RE = re.compile(r"^\s*/(?:0[1-4]-(?:collection|inception|construction|operation)-jev)\b(.*)", re.S)
LAYER_RE = re.compile(r"Layer\s*[:：]\s*(\S+)")
PASTED_RE = re.compile(r"<pasted_content[^>]*>.*?</pasted_content[^>]*>", re.S)
APPROVAL_RE = re.compile(
    r"^\s*(ok|okay|a|b|c|d|e|accept|reject|yes|no|はい|いいえ|うん|了解|りょ|次|次へ|続けて|進めて|お願いします|"
    r"おねがいします|それで|それでお願いします|いいよ|大丈夫|go|lgtm)\s*[。!！.]*\s*$", re.I)


def _read_markers(f):
    try:
        f.seek(0)
        d = json.loads(f.read() or "{}")
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


def _load_markers():
    try:
        with open(MARKER_PATH, "r", encoding="utf-8") as f:
            return _read_markers(f)
    except OSError:
        return {}


def _update_markers(mutate):
    """Read-modify-write under an exclusive lock, replaced atomically (parallel sessions)."""
    try:
        MARKER_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(str(MARKER_PATH) + ".lock", "a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            d = mutate(_load_markers())
            tmp = MARKER_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, MARKER_PATH)
    except OSError:
        pass


def _opted_in(layer):
    intent = mon.load_yaml(Path(layer) / "intent.yaml")
    return intent.get("jev_monitor") is True


def try_activate(prompt, session_id, cwd):
    """Bind this session to the Layer named in a /04-operation-jev or /01-collection-jev prompt."""
    m = ACTIVATE_RE.match(PASTED_RE.sub(" ", prompt or ""))  # a pasted block never chooses the Layer
    if not m or not session_id:
        return None
    lm = LAYER_RE.search(m.group(1))
    if not lm:
        return None
    layer = Path(lm.group(1).rstrip("（(、,"))
    if not layer.is_absolute():
        layer = Path(cwd or os.getcwd()) / layer
    layer = layer.resolve()
    if not (layer / "intent.yaml").is_file() or not _opted_in(layer):
        return None
    rec = {"layer": str(layer), "since": time.time()}
    _update_markers(lambda d: {**d, session_id: rec})
    return str(layer)


def active_layer(session_id):
    if not session_id:
        return None
    rec = _load_markers().get(session_id)
    if not isinstance(rec, dict):
        return None
    if time.time() - float(rec.get("since") or 0) > ACTIVE_HOURS * 3600:
        return None
    layer = rec.get("layer")
    return layer if layer and _opted_in(layer) else None


def clean_utterance(prompt):
    """Return the user's own text to send, or None when it should be skipped."""
    text = PASTED_RE.sub(" ", prompt or "").strip()
    if not text or text.startswith("/"):
        return None
    if APPROVAL_RE.match(text):
        return None
    if re.search(r"[？?]\s*$", text):
        return None
    return " ".join(text.split())[:MAX_CHARS]


def judge(layer, utterance, ask=None):
    ask = ask or jev_client.ask
    layer = Path(layer)
    intent, backlog = mon.load_yaml(layer / "intent.yaml"), mon.load_yaml(layer / "backlog.yaml")
    st, _ = mon.count_conditions(backlog)
    state = mon.build_state(intent, backlog, st, report="（会話中）", utterance=utterance)
    rec = ask(state, {"user_signal": {"type": "noul", "instructions": mon.Q["user_signal"]}}, USE_CASE,
              scope_id=intent.get("scope_id"), task_id="prompt", timeout=TIMEOUT, retries=0)
    if rec.get("action") != "answered":
        return None
    p = (rec.get("answers") or {}).get("user_signal")
    if isinstance(p, (int, float)) and p >= jev_client.THRESHOLD:
        return (f"💡 Jev会話監視（実験版）: 直前の発話に、進捗の訂正・抜けの指摘・範囲の変更・懸念の可能性（p={p:.2f}）。"
                f"該当すればBacktrackの軽量提案を1行で検討（提案のみ・同一話題で再提案しない）。"
                f"判定を記録するなら decision_id={rec['decision_id']}")
    return None


def handle(payload, ask=None):
    """Returns the hook stdout (JSON string) or '' for silence."""
    if os.environ.get("JEV_DISABLE") == "1":
        return ""
    prompt = payload.get("prompt") if isinstance(payload, dict) else None
    prompt = prompt if isinstance(prompt, str) else ""
    sid = payload.get("session_id") if isinstance(payload, dict) else None
    sid = sid if isinstance(sid, str) else ""
    cwd = payload.get("cwd") if isinstance(payload, dict) else None
    if try_activate(prompt, sid, cwd if isinstance(cwd, str) else None):
        return ""  # the activation prompt itself is a command; nothing to judge
    layer = active_layer(sid)
    if not layer:
        return ""
    utt = clean_utterance(prompt)
    if not utt:
        return ""
    line = judge(layer, utt, ask=ask)
    if not line:
        return ""
    return json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": line}},
                      ensure_ascii=False)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv[:1] == ["--status"]:
            d = _load_markers()
            now = time.time()
            for sid, rec in d.items():
                age = (now - float(rec.get("since") or 0)) / 3600
                print(f"{sid[:8]}… layer={rec.get('layer')} age={age:.1f}h "
                      f"{'active' if age <= ACTIVE_HOURS else 'expired'}")
            print(f"{len(d)} binding(s)")
            return 0
        if argv[:1] == ["--deactivate"]:
            target = argv[1] if len(argv) > 1 else None
            _update_markers(lambda d: {k: v for k, v in d.items() if target is not None and k != target})
            print("deactivated")
            return 0
        os.environ["JEV_KEYCHAIN_TIMEOUT"] = KEYCHAIN_TIMEOUT
        if hasattr(signal, "SIGALRM"):
            signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError()))
            signal.alarm(TOTAL_BUDGET)
        raw = sys.stdin.read()
        out = handle(json.loads(raw) if raw.strip() else {})
        if out:
            print(out)
    except BaseException:  # never block the user's prompt (incl. the wall-clock alarm)
        pass
    finally:
        if hasattr(signal, "alarm"):
            signal.alarm(0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
