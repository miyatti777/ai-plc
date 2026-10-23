#!/usr/bin/env python3
"""plc_auto.py — Claude Code 用の AI-PLC 自動完走（/plc-auto の Claude Code 版）の状態管理と Stop hook。

CC の組み込み /goal はスキルから設定できないため、CC の /plc-auto は次の2つで同じ動きを作る:
  1. スキルが `start` で状態ファイル（.claude/db/plc_auto_state.json）を active にする
  2. Stop hook（`hook`）が、ターン終了のたびに停止・達成を判定し、未達なら
     {"decision": "block", "reason": ...} を返して次のターンへ進ませる

判定（すべてコードで決める。モデル判定はしない）:
  - 最後の応答に行頭の「⛔ 自動完走を停止」がある → stopped（止める）
  - 全タスクが終端で「Phase 7」表示 → done / partial / stopped（達成を区別）
  - 未完了の通常タスクが全部、実行時期（scheduled_for）が今日より後で in_progress が無い → stopped（最も早い日を残す）
  - ターン数が上限（既定 60）に達した → expired（止める）
  - それ以外 → 続ける

使い方:
  python3 .claude/skills/plc-auto/scripts/plc_auto.py start [--layer <Layerパス>] [--goal <Goal文>] [--session <id>] [--max-turns 60]
  python3 .claude/skills/plc-auto/scripts/plc_auto.py set-layer <Layerパス>
  python3 .claude/skills/plc-auto/scripts/plc_auto.py status
  python3 .claude/skills/plc-auto/scripts/plc_auto.py clear
  python3 .claude/skills/plc-auto/scripts/plc_auto.py hook        # Stop hook から stdin の JSON を受けて呼ぶ
"""
import argparse
import contextlib
import datetime
import fcntl
import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or next((p for p in Path(__file__).resolve().parents if (p / ".claude").is_dir()), Path.cwd()))   # <repo>/.claude/skills/plc-auto/scripts/plc_auto.py
STATE = ROOT / ".claude" / "db" / "plc_auto_state.json"
STOP_MARK = "⛔ 自動完走を停止"
TERMINAL = {"completed", "deferred", "blocked"}
DEFAULT_MAX_TURNS = 60


@contextlib.contextmanager
def state_lock():
    """Serialize load/check/save; an active state can never be raced into replacement."""
    STATE.parent.mkdir(parents=True, exist_ok=True)
    with STATE.with_suffix(".lock").open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def execution_decision(layer, action, runtime, *, require_bound=False):
    """Only records explicitly opting into the shared gate use it; legacy stays legacy."""
    if not layer:
        return None
    import yaml
    try:
        data = yaml.safe_load((layer_dir(layer) / "backlog.yaml").read_text()) if (layer_dir(layer) / "backlog.yaml").exists() else {}
        if (data.get("execution_contract") or {}).get("record_version") != 2:
            return {"decision": "hold", "reason": "束縛済み実行のv2記録がない", "requires_user_input": False} if require_bound else None
    except (OSError, ValueError, TypeError, AttributeError, yaml.YAMLError):
        return {"decision": "hold", "reason": "現在のLayer実行記録を読めない", "requires_user_input": False}
    script_dir = str(Path(__file__).resolve().parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    from plc_execution import evaluate
    return evaluate(layer_dir(layer), action, runtime)


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def load():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def layer_dir(layer):
    if not layer:
        return None
    p = Path(layer)
    return p if p.is_absolute() else ROOT / p


def backlog_progress(layer):
    """(終端タスク数, 全タスク数) を返す。backlog が読めなければ None。"""
    d = layer_dir(layer)
    if d is None:
        return None
    path = d / "backlog.yaml"
    if not path.exists():
        return None
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    try:
        tasks = execution_tasks(data)
    except (ValueError, TypeError):
        return None
    if not isinstance(tasks, list):
        return None
    tasks = [t for t in tasks if not (isinstance(t, dict) and t.get("recurrence"))]  # recurring operation tasks never complete
    done = sum(1 for t in tasks if isinstance(t, dict) and str(t.get("status", "")).strip() in TERMINAL)
    return done, len(tasks)


def _scheduled_date(value):
    """scheduled_for: YYYY-MM-DD か YYYY-Www（その週の月曜。w は大文字小文字を問わない）。引用符つきの日時は先頭10文字。
    空・読めなければ None（ステータス点検と同じ決まり）。"""
    import re
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    v = str(value if value is not None else "").strip().strip("'\"").strip()
    m = re.match(r"^(\d{4})-[Ww](\d{2})$", v)
    try:
        if m:
            return datetime.date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
        if re.match(r"^\d{4}-\d{2}-\d{2}$", v[:10]):
            return datetime.date.fromisoformat(v[:10])
    except ValueError:
        return None
    return None


def schedule_waiting_only(layer, today=None):
    """未完了の通常タスク（recurrence の無いもの）が全部、実行時期が今日より後で in_progress が無いとき、その最も早い日を
    返す。それ以外（時期の無い・今日以前・読めない時期のタスクがある、backlog を読めない）は None。
    blocked は TERMINAL（終わったと数える）なので対象外。"""
    d = layer_dir(layer)
    if d is None or not (d / "backlog.yaml").exists():
        return None
    try:
        import yaml
        data = yaml.safe_load((d / "backlog.yaml").read_text(encoding="utf-8")) or {}
        tasks = execution_tasks(data)
    except Exception:
        return None
    if not isinstance(tasks, list):
        return None
    today = today or datetime.date.today()
    open_tasks = [t for t in tasks if isinstance(t, dict) and not t.get("recurrence")
                  and str(t.get("status", "")).strip() not in TERMINAL | {"cancelled", "dropped"}]
    if not open_tasks or any(str(t.get("status", "")).strip() == "in_progress" for t in open_tasks):
        return None
    dates = [_scheduled_date(t.get("scheduled_for")) for t in open_tasks]
    if not all(x and x > today for x in dates):
        return None
    return min(dates)


def recurring_only_count(layer):
    """通常タスク（recurrence の無いもの）が0件で、retired_at の無い運用タスクがあるときその件数を返す。それ以外は 0
    （運用タスクだけの Layer は達成と数えず、§10 の停止理由「運用タスクだけが残った」へつなぐ）。"""
    d = layer_dir(layer)
    if d is None or not (d / "backlog.yaml").exists():
        return 0
    try:
        import yaml
        tasks = execution_tasks(yaml.safe_load((d / "backlog.yaml").read_text(encoding="utf-8")) or {})
    except Exception:
        return 0
    if not isinstance(tasks, list):
        return 0
    tasks = [t for t in tasks if isinstance(t, dict)]
    if any(not t.get("recurrence") for t in tasks):
        return 0
    return sum(1 for t in tasks if t.get("recurrence") and not t.get("retired_at"))


RECURRING_GAP_DAYS = {"daily": 1, "weekly": 7}


def due_recurring(layer, today=None):
    """回す日（04-operation Phase 1）に当たる運用タスクの ID。自動完走では回さないので、停止・終了の文に添えるだけ
    daily は前回から1日・weekly は7日。per_meeting は会議の後に本人が呼ぶので添えない。
    scheduled_for（回し始める日）が今日より後なら当たらない。retired_at のある運用タスクは除く"""
    d = layer_dir(layer)
    if d is None or not (d / "backlog.yaml").exists():
        return []
    try:
        import yaml
        tasks = execution_tasks(yaml.safe_load((d / "backlog.yaml").read_text(encoding="utf-8")) or {})
    except Exception:
        return []
    today = today or datetime.date.today()
    out = []
    for t in tasks if isinstance(tasks, list) else []:
        if not isinstance(t, dict) or not t.get("recurrence") or t.get("retired_at"):
            continue
        start = _scheduled_date(t.get("scheduled_for"))
        if start and start > today:
            continue
        kind = str(t.get("recurrence")).strip().lower()
        if kind == "per_meeting":   # 会議の後に本人が呼ぶもので、日では決まらないので添えない
            continue
        gap = RECURRING_GAP_DAYS.get(kind)
        if gap is None:
            continue
        runs = [_scheduled_date((x or {}).get("date")) for x in (t.get("runs") or []) if isinstance(x, dict)]
        runs = [x for x in runs if x and x <= today]
        if not runs or (today - max(runs)).days >= gap:
            out.append(str(t.get("id")))
    return out


def recurring_suffix(layer):
    due = due_recurring(layer)
    return f"（回す日の運用タスク: {'・'.join(due)}。自動完走では回さない — /04-operation で Task を指定して回す）" if due else ""


def execution_tasks(data, *, approved_scope=None, approved_versions=None):
    tasks = data.get("tasks") or []
    contract = data.get("execution_contract") or {}
    if contract.get("record_version") == 2:
        scope = contract.get("scope_tasks") or []
        if approved_scope is not None and scope != approved_scope:
            raise ValueError("開始時の承認Task範囲と現在範囲が不一致")
        if approved_versions is not None and contract.get("task_versions") != approved_versions:
            raise ValueError("開始時の承認Task版と現在版が不一致")
        selected = [t for t in tasks if t.get("id") in scope]
        if not scope or len(selected) != len(scope):
            raise ValueError("承認済みTask範囲を確認できない")
        if approved_versions is not None and any(t.get("task_version") != approved_versions.get(t.get("id")) for t in selected):
            raise ValueError("承認一式内に未承認のTask版がある")
        return selected
    return tasks


def last_assistant_text(payload):
    text = payload.get("last_assistant_message")
    if isinstance(text, str) and text:
        return text
    tp = payload.get("transcript_path")
    if not tp:
        return ""
    try:
        lines = Path(tp).read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("type") != "assistant":
            continue
        content = (entry.get("message") or {}).get("content")
        if isinstance(content, str):
            return content
        texts = [c.get("text", "") for c in content or [] if isinstance(c, dict) and c.get("type") == "text"]
        if texts:
            return "\n".join(texts)
    return ""


def has_stop_mark(text):
    return any(line.lstrip().startswith(STOP_MARK) for line in text.splitlines())


def completion_result(state, text):
    """終了と達成を分ける。forceの存在検査は意味的AC検証の代替ではない。"""
    import yaml
    directory = layer_dir(state.get("layer"))
    data = yaml.safe_load((directory / "backlog.yaml").read_text(encoding="utf-8"))
    bounded = (data.get("execution_contract") or {}).get("record_version") == 2
    if bounded and not state.get("approved_scope_tasks"):
        return "stopped", "開始時の承認範囲が未確認"
    tasks = execution_tasks(data, approved_scope=state.get("approved_scope_tasks"),
                            approved_versions=state.get("approved_task_versions"))
    remaining = [t.get("id", "?") for t in tasks if t.get("status") != "completed" and not t.get("recurrence")]
    if remaining:
        return "partial", "保留タスクあり: " + ", ".join(remaining)
    if tasks and all(t.get("recurrence") for t in tasks):  # 運用タスクだけの Layer は達成ではない
        return "stopped", "運用タスクだけが残った（自動完走では回さない。達成とは数えない。閉じるのは本人の判断）"
    tasks = [t for t in tasks if not t.get("recurrence")]  # recurring operation tasks are judged by their runs, not output
    if state.get("mode") != "workflow-force" and (data.get("execution_contract") or {}).get("record_version") != 2:
        return "done", "全タスクcompleted・Phase 7表示（AC/成果物はStageで検証）"
    if "AI-PLC result: partial" in text.splitlines():
        return "partial", "保留/未確認/未達をpartialとして報告（詳細はLayerログ）"
    if "AI-PLC result: complete" not in text.splitlines():
        return "stopped", "forceのcomplete報告が未確認"
    if not any("[auto-approved]" in str(entry) for entry in data.get("refactoring_log", [])):
        return "stopped", "forceの判断ログが未確認"
    for task in tasks:
        output = task.get("output")
        paths = output if isinstance(output, list) else output.split(",") if isinstance(output, str) else []
        if not paths or not any(str(p).strip() for p in paths):
            return "stopped", f"{task.get('id')} のoutput未設定"
        for raw in paths:
            path = Path(str(raw).strip())
            candidates = [path] if path.is_absolute() else [directory / path, ROOT / path]
            if not any(p.is_file() for p in candidates):
                return "stopped", f"{task.get('id')} のoutputが実在しない: {raw}"
    if (data.get("execution_contract") or {}).get("record_version") == 2:
        verified = data["execution_contract"].get("final_verification") or {}
        if verified.get("all_acceptance_criteria") is not True or verified.get("unresolved_p0_p2") != 0:
            return "stopped", "承認一式の最終AC/品質が未検証"
        artifacts = verified.get("reviewed_artifacts") or {}
        if not artifacts:
            return "stopped", "最終レビュー対象版の証拠がない"
        import hashlib
        actual = {}
        for name, fingerprint in artifacts.items():
            artifact = Path(name)
            if not artifact.is_absolute():
                artifact = directory / artifact
            if not artifact.is_file() or hashlib.sha256(artifact.read_bytes()).hexdigest() != fingerprint:
                return "stopped", "最終成果とレビュー対象版が不一致"
            actual[str(artifact.resolve())] = fingerprint
        for task in tasks:
            output = task.get("review_outputs", task.get("output"))
            names = output if isinstance(output, list) else output.split(",")
            for name in names:
                artifact = Path(name.strip())
                candidates = [artifact] if artifact.is_absolute() else [directory / artifact, ROOT / artifact]
                if not any(str(p.resolve()) in actual for p in candidates):
                    return "stopped", "最終成果が独立レビューの対象に含まれない"
        return "done", "承認された実行一式completed・成果/最終AC/対象版確認（Project全Goal完了とは別）"
    return "done", "全completed・output存在・Phase 7/complete表示（意味的ACはStage検証）"


def continue_reason(state, progress):
    layer = state.get("layer") or "（未確定 — Layer を作ったら `python3 .claude/skills/plc-auto/scripts/plc_auto.py set-layer <パス>` を実行）"
    prog = f"{progress[0]}/{progress[1]} タスク終了" if progress else "backlog 未作成"
    mode = state.get("mode", "auto")
    recurring = recurring_only_count(state.get("layer")) if progress and progress[1] == 0 else 0
    recurring_note = (f"通常タスクは無く運用タスク {recurring} 件だけ（達成とは数えない）。自動完走では運用タスクを回さないので、"
                      "行頭に「⛔ 自動完走を停止: 運用タスクだけが残った（自動完走では回さない）」を出し、次に回す日を示す（RUL_plc_session §10）。"
                      if recurring else "")
    contract = ("明示 workflow-force v1。§10.1のforce-contractを読み、固定write_set内だけ。"
                "本人回答/ツール承認を偽装せず、保留はpartial、停止後は再指定まで続けない。"
                if mode == "workflow-force" else "")
    return (
        f"AI-PLC 自動完走（/plc-auto）継続中 — ターン {state['turns']}/{state['max_turns']}。"
        f"Layer: {layer}（{prog}）。"
        f"{contract}"
        "RUL_plc_session §10 の自動完走として次の手順へ進む（Mob Checkpoint は⭐を選ぶ・Next Action は⭐を実行・保留に当たる操作は保留してログ）。"
        "実行時期（scheduled_for）が今日より後の Task は選ばない。"
        f"{recurring_note}"
        "達成したら Phase 7 チェックリストと自動承認ログを表示する。止まるべきときは行頭に単独で「⛔ 自動完走を停止: <理由>」を出す。"
    )


def finish(state, status, note):
    state["active"] = False
    state["status"] = status
    state["ended_at"] = now()
    state["end_note"] = note
    save(state)


def _cmd_hook():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    state = load()
    if not state or not state.get("active"):
        return 0
    sid = payload.get("session_id")
    bound = state.get("session_id")
    if state.get("mode") == "workflow-force" and (not sid or not bound):
        return 0  # 身元不明のhookでは自動選択を再開しない
    if state.get("approved_task_versions") and (not sid or not bound or sid != bound):
        return 0
    if bound and sid and bound != sid:
        return 0  # 別セッションの自動完走には触らない
    if not bound and sid:
        state["session_id"] = sid

    text = last_assistant_text(payload)
    progress = backlog_progress(state.get("layer"))

    if has_stop_mark(text):
        finish(state, "stopped", "応答に停止の印")
        return 0
    if state.get("mode") == "workflow-force" and "AI-PLC result: partial" in text.splitlines():
        finish(state, "partial", "部分終了を明示。未完了/保留の詳細と再開条件はLayerログ")
        return 0
    waiting = schedule_waiting_only(state.get("layer"))
    if waiting:  # 実行時期の来ていないタスクだけが残った（§10 の停止理由。status の値は増やさない）
        suffix = recurring_suffix(state.get("layer"))
        finish(state, "stopped", f"実行時期の来ていないタスクだけが残った（最も早い {waiting.isoformat()}）{suffix}")
        print(json.dumps({"systemMessage": f"/plc-auto: 実行時期の来ていないタスクだけが残ったため自動完走を止めました。"
                                           f"{waiting.isoformat()} 以降に /plc-auto を打ち直すと続きから再開できます。{suffix}"},
                         ensure_ascii=False))
        return 0
    finishing = progress and progress[1] > 0 and progress[0] == progress[1] and "Phase 7" in text
    runtime = dict(state.get("execution_runtime") or {})
    if state.get("approved_task_versions") and state.get("layer"):
        import yaml
        contract = (yaml.safe_load((layer_dir(state["layer"]) / "backlog.yaml").read_text()) or {}).get("execution_contract") or {}
        runtime["task_version"] = state["approved_task_versions"].get(contract.get("current_task"))
    shared = execution_decision(state.get("layer"), "management_record" if finishing else "resume",
                                runtime, require_bound=bool(state.get("approved_task_versions")))
    if shared and shared["decision"] == "busy":
        return 0  # existing operation is running; no new turn/start and no forced cancellation
    if shared and shared["decision"] != "continue_internal":
        finish(state, "stopped", shared["reason"])
        return 0
    if finishing:
        try:
            status, note = completion_result(state, text)
        except (OSError, ValueError, KeyError, TypeError):
            status, note = "stopped", "終了判定中にbacklogを確認できない"
        finish(state, status, note + recurring_suffix(state.get("layer")))
        return 0
    if state["turns"] >= state["max_turns"]:
        finish(state, "expired", f"ターン上限 {state['max_turns']} に到達")
        print(json.dumps({"systemMessage": f"/plc-auto: ターン上限 {state['max_turns']} に達したため自動完走を止めました。続けるなら /plc-auto を打ち直してください。"}, ensure_ascii=False))
        return 0

    state["turns"] += 1
    state["last_turn_at"] = now()
    save(state)
    print(json.dumps({"decision": "block", "reason": continue_reason(state, progress)}, ensure_ascii=False))
    return 0


def _cmd_start(args):
    cur = load()
    if STATE.exists() and not isinstance(cur, dict):
        print("[NG] 既存状態を確認できません。壊れた状態を新規開始で上書きしません")
        return 1
    if cur and cur.get("active"):
        print(f"[NG] 自動完走が既に active です（Layer: {cur.get('layer')}・開始 {cur.get('started_at')}）。"
              "対象/モードを確認し、本人の指示で clear してから再開してください。forceで置き換えません。")
        return 1
    mode = "workflow-force" if args.force else args.mode
    if not 1 <= args.max_turns <= DEFAULT_MAX_TURNS:
        print("[NG] --max-turns は1〜60です")
        return 1
    if args.layer and not (layer_dir(args.layer) / "intent.yaml").exists():
        print(f"[NG] Layer に intent.yaml がありません: {args.layer}")
        return 1
    session = args.session if args.session and not args.session.startswith("${") else None
    if mode == "workflow-force" and not session:
        print("[NG] workflow-force は有効な --session が必要です。未束縛状態は開始しません")
        return 1
    runtime = {}
    if getattr(args, "execution_request", None):
        if not args.layer:
            print("[NG] 現在実行JSONを使う開始には照合対象Layerが必要です")
            return 1
        runtime = json.loads(Path(args.execution_request).read_text())
    if args.layer:
        import yaml
        intent = yaml.safe_load((layer_dir(args.layer) / "intent.yaml").read_text()) or {}
        if intent.get("status") in {"cancelled", "paused", "blocked"}:
            print("[NG] 停止/取消済みProjectを開始しません")
            return 1
        shared = execution_decision(args.layer, "resume", runtime, require_bound=bool(runtime))
        if shared and shared["decision"] != "continue_internal":
            print("[NG] " + shared["reason"])
            return 1
    state = {
        "active": True,
        "status": "running",
        "mode": mode,
        "contract_version": 1 if mode == "workflow-force" else None,
        "write_set": [str(Path(p).resolve()) for p in args.write_path],
        "layer": str(layer_dir(args.layer).resolve()) if args.layer and mode == "workflow-force" else args.layer,
        "goal": args.goal,
        "session_id": session,
        "turns": 0,
        "max_turns": args.max_turns,
        "started_at": now(),
    }
    if runtime:
        state["execution_runtime"] = runtime
        import yaml
        contract = (yaml.safe_load((layer_dir(args.layer) / "backlog.yaml").read_text()) or {}).get("execution_contract") or {}
        if contract.get("record_version") == 2:
            state["approved_task_versions"] = contract.get("task_versions") or {}
            state["approved_scope_tasks"] = contract.get("scope_tasks") or []
    save(state)
    print(f"[OK] /plc-auto を開始しました（Layer: {args.layer or '未確定'}・上限 {args.max_turns} ターン・"
          f"セッション: {session or '最初の Stop で確定'}）")
    return 0


def _cmd_set_layer(args):
    state = load()
    if not state or not state.get("active"):
        print("[NG] active な自動完走がありません")
        return 1
    if not (layer_dir(args.layer) / "intent.yaml").exists():
        print(f"[NG] Layer に intent.yaml がありません: {args.layer}")
        return 1
    if (state.get("mode") == "workflow-force" and state.get("layer")
            and layer_dir(state["layer"]).resolve() != layer_dir(args.layer).resolve()):
        print("[NG] workflow-force の対象Layerは変更できません。停止し本人の再指定が必要です")
        return 1
    state["layer"] = str(layer_dir(args.layer).resolve()) if state.get("mode") == "workflow-force" else args.layer
    save(state)
    print(f"[OK] Layer を設定しました: {args.layer}")
    return 0


def cmd_status():
    state = load()
    if not state:
        print("自動完走の記録はありません")
        return 0
    progress = backlog_progress(state.get("layer"))
    print(json.dumps(state, ensure_ascii=False, indent=2))
    print(f"backlog: {f'{progress[0]}/{progress[1]} タスク終了' if progress else '未作成または読めない'}")
    return 0


def _cmd_clear():
    state = load()
    if not state or not state.get("active"):
        print("active な自動完走はありません")
        return 0
    finish(state, "cleared", "利用者が clear")
    print("[OK] 自動完走を止めました（状態ファイルは履歴として残します）")
    return 0


def serialized(function, *args, hook=False):
    try:
        with state_lock():
            return function(*args)
    except BlockingIOError:
        if not hook:
            print("[NG] 自動完走の状態writerが稼働中。二重起動しません")
        return 0 if hook else 1


def cmd_start(args):
    return serialized(_cmd_start, args)


def cmd_hook():
    return serialized(_cmd_hook, hook=True)


def cmd_clear():
    return serialized(_cmd_clear)


def cmd_set_layer(args):
    return serialized(_cmd_set_layer, args)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--layer")
    s.add_argument("--goal")
    s.add_argument("--session")
    s.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS)
    s.add_argument("--force", action="store_true", help="workflow-forceモード。active状態を置換しない")
    s.add_argument("--mode", choices=["auto", "workflow-force"], default="auto")
    s.add_argument("--write-path", action="append", default=[])
    s.add_argument("--execution-request", help="現在の呼出元が照合した実行情報JSON。認証や権限付与は行わない")
    sl = sub.add_parser("set-layer")
    sl.add_argument("layer")
    sub.add_parser("status")
    sub.add_parser("clear")
    sub.add_parser("hook")
    args = p.parse_args()
    if args.cmd == "hook":
        return cmd_hook()
    if args.cmd == "start":
        return cmd_start(args)
    if args.cmd == "set-layer":
        return cmd_set_layer(args)
    if args.cmd == "status":
        return cmd_status()
    return cmd_clear()


if __name__ == "__main__":
    sys.exit(main())
