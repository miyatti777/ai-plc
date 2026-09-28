"""Jev (TypeSafe judgment model) shared client for AI-PLC.

Design notes:
- Jev only ranks or raises hints. It never gates, stops, or replaces a reviewer.
- Every call goes through redact() (do-not-send policy) and sanitize() (instruction-like lines).
- The decision log stores hashes only, never the state or question text.
- If Jev is unavailable (no key / HTTP error / timeout) the caller gets action=skipped(...) and continues.

Routes: TYPESAFE_API_KEY -> official API; else OPENROUTER_API_KEY (env or macOS keychain
service=OPENROUTER_API_KEY) -> OpenRouter. Key values are never printed or logged.

Do-not-send words: the generic list lives in REDACT_PATTERNS below. Words specific to your environment (project
names, people, private matters) go in a local file that you keep out of git yourself (add
.claude/db/jev_redact_extra.txt to your .gitignore): <repo>/.claude/db/jev_redact_extra.txt is always
read when it exists, and the file named by $JEV_REDACT_EXTRA is read as well (both when both exist). One regex per
line; blank lines and lines starting with # are ignored. See .claude/ai-plc-jev/scripts/jev_redact_extra.example.txt.
"""
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path



def _find_repo(start: Path) -> Path:
    """<repo>/.claude/ai-plc-jev/scripts/x.py -> <repo>; <repo>/scripts/x.py -> <repo> (unchanged).

    $AIPLC_REPO overrides (tests / unusual layouts). Otherwise walk up to the first directory named .claude whose
    parent carries the AI-PLC install marker (.ai-plc-version or .ai-plc-install-manifest); fall back to the
    grandparent of this file (the historical <repo>/scripts/ layout)."""
    env = os.environ.get("AIPLC_REPO")
    if env:
        return Path(env).resolve()
    for p in start.parents:
        if p.name == ".claude" and ((p.parent / ".ai-plc-version").is_file()
                                    or (p.parent / ".ai-plc-install-manifest").is_file()):
            return p.parent
    return start.parent.parent


REPO = _find_repo(Path(__file__).resolve())
LOG_PATH = Path(os.environ.get("JEV_LOG_PATH", REPO / ".claude" / "db" / "jev_decisions.jsonl"))
OVERRIDE_PATH = Path(os.environ.get("JEV_OVERRIDE_PATH", REPO / ".claude" / "db" / "jev_overrides.jsonl"))
MODEL_OPENROUTER = "typesafe/jev-1.13"
MODEL_OFFICIAL = "jev-1.13.0"  # same model; the official API names it without the provider prefix
THRESHOLD = 0.5  # fixed until re-registered on separate data

# Do-not-send policy. One place for all callers. When in doubt, do not send.
# Generic words only: anything that names a project, person or private matter belongs in the local extra file.
REDACT_PATTERNS = [
    # money / HR / management
    r"経費", r"finance", r"精算", r"給与", r"年収", r"勤怠", r"1on1", r"面談", r"評価面談", r"キャリア",
    r"\bOKR\b", r"役員会", r"経営会議", r"CxO",
    r"経費申請",                                           # paperwork (a bare 申請 would block ordinary docs)
    r"人事評価", r"査定",                                  # HR (a bare 評価 collides with 回帰評価 etc.)
    # private life
    r"趣味", r"私生活", r"家族",
    # personal identifiers
    r"[\w.+-]+@[\w-]+\.[\w.-]+", r"\b0\d{1,4}-\d{1,4}-\d{3,4}\b",
]
# Ordinary words (customer, user research, demo names ...) are intentionally NOT listed: the primary gate is the
# per-Layer opt-in (intent.yaml jev_monitor: true); this list is only the last gate.
BASE_REDACT_PATTERNS = tuple(REDACT_PATTERNS)
REDACT_LOCAL_PATH = REPO / ".claude" / "db" / "jev_redact_extra.txt"  # environment-specific; add it to your .gitignore
_UNSET = object()


def _read_pattern_file(path):
    """One regex per line; blank lines and # comments are skipped. Raises on unreadable files / bad regexes
    (ValueError names the line number, never the text)."""
    pats = []
    for no, line in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            re.compile(line)  # a broken line must not silently weaken the policy
        except re.error:
            raise ValueError(f"invalid regex on line {no}") from None
        if re.search(r"\\[1-9]|\(\?P=", line):  # back-references would point at another line's group once combined
            raise ValueError(f"back-reference not allowed on line {no}")
        pats.append(line)
    return pats


def load_redact_patterns(local_path=_UNSET, env_path=_UNSET):
    """Rebuild the do-not-send regex: BASE_REDACT_PATTERNS + local file (if it exists) + $JEV_REDACT_EXTRA file.

    local_path / env_path default to REDACT_LOCAL_PATH / $JEV_REDACT_EXTRA; pass None to skip one (tests use this
    so they never depend on the real local file). A missing default local file is skipped; a missing
    $JEV_REDACT_EXTRA file is an error. Fail-closed: when a path exists but is
    not a readable file (directory, dangling symlink, bad encoding) or a line / the combined pattern does not
    compile, redact() refuses everything until it is fixed. Returns the active pattern list."""
    global REDACT_PATTERNS, _REDACT_RE, _REDACT_ERROR, REDACT_SOURCES
    if local_path is _UNSET:
        local_path = REDACT_LOCAL_PATH
    if env_path is _UNSET:
        env_path = os.environ.get("JEV_REDACT_EXTRA") or None
    pats, errs, sources, seen = list(BASE_REDACT_PATTERNS), [], [], set()
    for label, src in (("local", local_path), ("JEV_REDACT_EXTRA", env_path)):
        if not src:
            continue
        src = Path(src)
        if not src.exists() and not src.is_symlink():
            if label == "local":
                sources.append((label, str(src), "missing"))
                continue  # the default local file is optional (public checkouts do not have it)
            errs.append(f"{label} {src.name}: file not found")  # an explicitly named file must exist (typo / moved)
            sources.append((label, str(src), "ERROR (file not found)"))
            continue
        key = str(src.resolve())
        if key in seen:
            sources.append((label, str(src), "same file as above"))
            continue  # the same file twice is read once
        seen.add(key)
        try:
            if not src.is_file():
                raise OSError("not a regular file")
            got = _read_pattern_file(src)
            pats += got
            sources.append((label, str(src), f"{len(got)} patterns"))
        except (OSError, UnicodeDecodeError, ValueError) as e:
            msg = str(e) if isinstance(e, ValueError) else type(e).__name__
            errs.append(f"{label} {src.name}: {msg}")
            sources.append((label, str(src), f"ERROR ({msg})"))
    try:
        rx = re.compile("|".join(f"(?:{p})" for p in pats), re.IGNORECASE)
    except re.error:  # each line compiles alone but not together (e.g. inline global flags, duplicate group names)
        errs.append("combined pattern does not compile")
        rx = re.compile("|".join(f"(?:{p})" for p in BASE_REDACT_PATTERNS), re.IGNORECASE)
    REDACT_PATTERNS, _REDACT_RE, REDACT_SOURCES = pats, rx, sources
    _REDACT_ERROR = "; ".join(errs) or None
    return pats


REDACT_SOURCES = []
_REDACT_ERROR = None
load_redact_patterns()

# Instruction-like lines embedded in data (prompt-injection countermeasure).
_INSTR_RE = re.compile(
    r"(と(判定|回答)(して|すること|せよ|しなさい)|と答え(ること|よ|てください|なさい)"
    r"|(監視|判定|採点|評価|回答)(する側|者)は"
    r"|ignore (all|any|the)? ?(previous|prior|above)|answer (yes|no)\b|must answer|respond with (yes|no)"
    r"|you (must|should) (answer|respond|output))",
    re.IGNORECASE)  # imperative aimed at the judge only; bare claims like 確認済み are content, not instructions
INSTR_PLACEHOLDER = "[指示文を除去]"


def _sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _flatten(state):
    return state if isinstance(state, str) else json.dumps(state, ensure_ascii=False, sort_keys=True)


def redact(state):
    """Return (ok_to_send, category_hint). Matched text is never returned or logged."""
    if _REDACT_ERROR:
        return False, "policy_file_error"  # fail-closed: a broken extra file never lets text through
    return (False, "policy") if _REDACT_RE.search(_flatten(state)) else (True, None)


def sanitize(text):
    """Replace instruction-like lines. Returns (clean_text, removed_lines)."""
    out, n = [], 0
    for line in text.splitlines():
        if _INSTR_RE.search(line):
            out.append(INSTR_PLACEHOLDER)
            n += 1
        else:
            out.append(line)
    return "\n".join(out), n


def _sanitize_questions(questions):
    """Apply sanitize() to every string inside the questions (instructions, criteria values/items)."""
    total = 0

    def clean(v):
        nonlocal total
        if isinstance(v, str):
            c, n = sanitize(v)
            total += n
            return c
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items()}  # keys are our own labels (task IDs etc.)
        if isinstance(v, list):
            return [clean(x) for x in v]
        return v
    return {q: clean(spec) for q, spec in questions.items()}, total


def get_key(name):
    """Env var first, then the macOS keychain (service=name, account=$USER). Never printed or logged."""
    return _get_key_with_source(name)[0]


def _get_key_with_source(name):
    v = os.environ.get(name)
    if v:
        return v, "env"
    try:
        r = subprocess.run(["security", "find-generic-password", "-a", os.environ.get("USER", ""), "-s", name, "-w"],
                           capture_output=True, text=True,
                           timeout=float(os.environ.get("JEV_KEYCHAIN_TIMEOUT", "5")))  # the hook lowers this
        return (r.stdout.strip() or None), ("keychain" if r.stdout.strip() else None)
    except Exception:  # not macOS / no keychain / timeout
        return None, None


OFFICIAL_URL = "https://api.typesafe.ai/v1/systemone"


def route(with_source=False):
    """Pick the Jev route. Returns (url, key, model, route_name[, key_source]) or None when no key is set.

    JEV_PROVIDER=typesafe|openrouter forces a route; otherwise TYPESAFE_API_KEY (official) wins over
    OPENROUTER_API_KEY. Each key is read from the env var or the macOS keychain. JEV_MODEL overrides the model,
    JEV_OFFICIAL_URL / JEV_BASE_URL override the endpoints."""
    if os.environ.get("JEV_DISABLE") == "1":
        return None
    forced = (os.environ.get("JEV_PROVIDER") or "").strip().lower()
    order = [forced] if forced in ("typesafe", "openrouter") else ["typesafe", "openrouter"]
    for name in order:
        if name == "typesafe":
            key, src = _get_key_with_source("TYPESAFE_API_KEY")
            if key:
                r = (os.environ.get("JEV_OFFICIAL_URL", OFFICIAL_URL), key,
                     os.environ.get("JEV_MODEL", MODEL_OFFICIAL), "official")
                return r + (src,) if with_source else r
        else:
            key, src = _get_key_with_source("OPENROUTER_API_KEY")
            if key:
                base = os.environ.get("JEV_BASE_URL", "https://openrouter.ai/api")
                r = (base + "/v1/systemone", key, os.environ.get("JEV_MODEL", MODEL_OPENROUTER), "openrouter")
                return r + (src,) if with_source else r
    return None


def _post(url, key, body, timeout, retries):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    err = None
    for i in range(retries + 1):
        req = urllib.request.Request(url, data=data, method="POST",
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8")), (time.perf_counter() - t0) * 1000, None
        except urllib.error.HTTPError as e:
            err = f"http_{e.code}"
            if e.code not in (429, 500, 502, 503, 529):
                break
        except Exception as e:  # timeout / network
            err = type(e).__name__
        if i < retries:
            time.sleep(0.5 * (2 ** i))
    return None, None, err


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _numeric_answer(a):
    """Keep only numbers from the API answer, so an unexpected response can never put text into the log."""
    if not isinstance(a, dict):
        return a if _num(a) else None
    if _num(a.get("noul")):
        return a["noul"]
    nums = {k: v for k, v in a.items() if _num(v)}
    return nums or None


def _choice_answer(a, criteria):
    """Keep only labels we sent (criteria keys) and numeric probabilities — never free text from the API."""
    if not isinstance(a, dict):
        return None
    labels = set(criteria)
    probs = a.get("probabilities") if isinstance(a.get("probabilities"), dict) else {}
    kept = {k: v for k, v in probs.items() if k in labels and _num(v)}
    choice = a.get("choice") if a.get("choice") in labels else None
    if choice is None and not kept:
        return None
    return {"choice": choice, "probabilities": kept}


def log_decision(rec):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def ask(state, questions, use_case, scope_id=None, task_id=None, timeout=2.0, retries=0, log=True):
    """Ask Jev one or more questions about `state`.

    questions: {qid: {"type": "noul"|"choice"|"score", "instructions": str, "criteria": {...}?}}
    Returns dict: {"decision_id", "action", "answers" (qid -> noul prob or raw answer) or None, ...}.
    Never raises on API problems; action is "answered" or "skipped(<reason>)".
    """
    flat = _flatten(state)
    rec = {"decision_id": uuid.uuid4().hex[:12],
           "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
           "use_case": use_case, "scope_id": scope_id, "task_id": task_id,
           "input_sha256": _sha(flat), "input_chars": len(flat),
           "questions": {q: _sha(json.dumps(v, ensure_ascii=False, sort_keys=True)) for q, v in questions.items()},
           "threshold": THRESHOLD, "answers": None, "model": None, "provider": None, "route": None,
           "latency_ms": None, "cost": None, "sanitized": {"removed_lines": 0}, "action": None,
           "human_override": None}
    # Policy check covers everything that leaves the machine: state AND question text (criteria may embed data).
    ok, _ = redact(flat + "\n" + json.dumps(questions, ensure_ascii=False))
    if not ok:
        rec["action"] = "skipped(redacted)"
    else:
        clean, n = sanitize(flat)
        questions, nq = _sanitize_questions(questions)  # question text may embed user-authored strings
        rec["sanitized"]["removed_lines"] = n + nq
        r = route()
        if r is None:
            rec["action"] = "skipped(unavailable:no_key)"
        else:
            url, key, model, rname = r
            rec["route"] = rname
            out, ms, err = _post(url, key, {"model": model, "state": clean, "questions": questions}, timeout, retries)
            if err or not isinstance(out, dict) or "answers" not in out:
                rec["action"] = f"skipped(unavailable:{err or 'bad_response'})"
            else:
                ans = {}
                for q, spec in questions.items():
                    raw = (out.get("answers") or {}).get(q)
                    if spec.get("type") == "choice":
                        ans[q] = _choice_answer(raw, spec.get("criteria") or {})
                    else:
                        ans[q] = _numeric_answer(raw)
                rec.update(answers=ans, model=out.get("model"), provider=out.get("provider"),
                           latency_ms=round(ms, 1), cost=(out.get("usage") or {}).get("cost"), action="answered")
    if log:
        log_decision(rec)
    return rec


def redact_status():
    """One line about the do-not-send list: base size and each extra file (path + count or error). Never the words."""
    parts = [f"汎用 {len(BASE_REDACT_PATTERNS)} 件"] + [f"{label} {path}: {st}" for label, path, st in REDACT_SOURCES]
    head = "送信禁止パターン: " + " / ".join(parts)
    return head + (f" — エラーのため何も送りません: {_REDACT_ERROR}" if _REDACT_ERROR else "")


def check():
    """One cheap connectivity call. Prints route/model/key source (never the key) and the result."""
    r = route(with_source=True)
    if r is None:
        print("Jev: キーが見つかりません。TYPESAFE_API_KEY か OPENROUTER_API_KEY を環境変数かキーチェーンに設定してください"
              "（JEV_DISABLE=1 の場合も無効）。手順: .claude/ai-plc-jev/scripts/README_jev.md")
        return 1
    url, key, model, rname, src = r
    print(f"経路: {rname} / モデル指定: {model} / キーの読み込み元: {src} / 接続先: {url}")
    print(redact_status())
    out, ms, err = _post(url, key, {"model": model, "state": "接続確認のためのテスト文です。",
                                    "questions": {"ok": {"type": "noul",
                                                         "instructions": "Is this text a connection test message?"}}},
                         10, 1)
    if err or not isinstance(out, dict) or "answers" not in out:
        print(f"失敗: {err or 'bad_response'}（401=キーが無効 / 402=残高不足 / 404=モデル名違い / 429・529=混雑）")
        return 1
    p = _numeric_answer((out.get("answers") or {}).get("ok"))
    cost = (out.get("usage") or {}).get("cost")
    print(f"成功: 応答 p={p} / 所要 {ms:.0f}ms / 応答モデル {out.get('model')}" + (f" / 費用 ${cost}" if cost else ""))
    return 0


def record_override(decision_id, verdict, note=None):
    """Record a human accept/reject for a past decision (separate file; the decision log stays append-only)."""
    if verdict not in ("accept", "reject"):
        raise ValueError("verdict must be accept or reject")
    OVERRIDE_PATH.parent.mkdir(parents=True, exist_ok=True)
    rec = {"decision_id": decision_id, "human_override": verdict,
           "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")}
    if note:
        rec["note_sha256"] = _sha(note)  # keep the log free of free text
    with OVERRIDE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


if __name__ == "__main__":
    import sys as _sys
    if _sys.argv[1:2] == ["--check"]:
        _sys.exit(check())
    if _sys.argv[1:2] == ["--redact-status"]:  # offline: which extra files are loaded (no words are printed)
        print(redact_status())
        _sys.exit(1 if _REDACT_ERROR else 0)
    print("usage: python3 .claude/ai-plc-jev/scripts/jev_client.py --check | --redact-status")
