#!/usr/bin/env python3
"""/ppm の振り分けの手がかり（読むだけ）。スキルを実行せず、DB にもファイルにも書かない。

- `<行き先>`: その入口の SKILL.md の場所と、読ませる一文を返す
- `new --goal <Goal>`: 新しい案件の入口（/01-collection）。先に同じ目的の既存の案件を探す印を付ける
- `resume --layer <Layer>`: 既存の Layer の続きを、intent・context・backlog だけから判定する
  （Layer の置き場として認めるのは、リポジトリの `Flow/` と `.ai-plc/projects/` の下だけ。
  `Flow` 自体を別の場所へのリンクで置いてもよい。Layer の中のファイルがリンクで外を指すものは断る）

返す値はどれも「候補」（advisory_only）。Stage の承認・Mob Checkpoint・Backtrack を越える承認にはならない。

使い方（導入先のリポジトリのルートで）:
  python3 .claude/skills/ppm/ppm_route.py status
  python3 .claude/skills/ppm/ppm_route.py new --goal "<Goal>"
  python3 .claude/skills/ppm/ppm_route.py resume --layer <Layer のパス> [--today YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

sys.dont_write_bytecode = True

try:
    import yaml
except ImportError:  # pragma: no cover
    print(json.dumps({"error": "PyYAML が要ります（pip install pyyaml）", "advisory_only": True}, ensure_ascii=False))
    raise SystemExit(2)

HERE = Path(__file__).resolve().parent

# 行き先 → スキルのフォルダ（skills の下）。この版にある入口だけ
SKILLS = {
    "status": "ppm-status", "todo": "ppm-todo", "inflight": "ppm-inflight",
    "plan": "ppm-plan", "capture": "ppm-capture", "update": "ppm-update", "close": "ppm-close",
    "collection": "ppm-collection", "scan": "ppm-scan", "someday": "ppm-someday",
    "audit": "ppm-audit", "registry": "ppm-registry", "pmo": "ppm-pmo",
}
LAYER_BASES = ("Flow", ".ai-plc/projects")
DONE = {"completed", "done", "cancelled", "dropped"}
DEPENDENCY_COMPLETE = {"completed", "done"}
OPEN = {"pending", "in_progress", "blocked", "deferred", "active"}
# intent の status の扱い（Project の状態は planned・active・paused・completed・cancelled。
# deferred は paused と同じ。blocked は外の都合で止まっている active）
INTENT_FINISHED = {"completed", "done"}
INTENT_CANCELLED = {"cancelled", "dropped"}
INTENT_PAUSED = {"paused", "deferred"}
WEEK_RE = re.compile(r"^(\d{4})-[Ww](\d{2})$")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class RouteError(ValueError):
    pass


def default_root() -> Path:
    """導入先（<repo>/.claude/skills/ppm/ または .cursor/...）ならそのリポジトリ、そうでなければ今のフォルダ。"""
    if HERE.parents[0].name == "skills" and HERE.parents[1].name in (".claude", ".cursor"):
        return HERE.parents[2]
    return Path.cwd()


def read_mapping(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise RouteError(f"{path.name}: 読めません（{type(exc).__name__}）") from exc
    if not isinstance(data, dict):
        raise RouteError(f"{path.name}: YAML の mapping が要ります")
    return data


def skill_path(relative: str, root: Path) -> Path:
    """スキルの SKILL.md。導入先の .claude/skills・.cursor/skills を先に、無ければこの部品の隣の skills を見る。"""
    for base in (root / ".claude" / "skills", root / ".cursor" / "skills", HERE.parent):
        p = base / relative / "SKILL.md"
        if p.is_file():
            return p
    raise RouteError(f"入口がありません: .claude/skills/{relative}/SKILL.md")


def skill_hint(action: str, relative: str, root: Path, **fields) -> dict:
    path = skill_path(relative, root)
    try:
        shown = path.relative_to(root).as_posix()
    except ValueError:
        shown = str(path)
    return {"action": action, "skill_path": shown, "prompt": f"{shown} を読んで実行してください",
            "advisory_only": True, "checkpoint_review_required": True, **fields}


def resolve_layer(value: str, root: Path) -> Path:
    """Layer のフォルダ（root からの見かけのパス。リンクは解かない）。

    置き場は root の下の `Flow/`・`.ai-plc/projects/`。置き場そのものはリンクでもよい（解いた先を置き場とみなす）。
    置き場より下でリンクを使って置き場の外へ出るものと、Layer の中のファイルが Layer の外を指すものは断る。"""
    raw = Path(value).expanduser()
    lexical = Path(os.path.normpath(raw if raw.is_absolute() else root / raw))
    layer = None
    for b in LAYER_BASES:
        base = root / b
        real_base = base.resolve()
        # 見かけのパスで置き場の下か、解いたパスで置き場の実体の下か（後者は見かけのパスに直す）
        for top, given, mapped in ((base, lexical, False), (real_base, lexical.resolve(), True)):
            if given != top and given.is_relative_to(top):
                cand = base / given.relative_to(top) if mapped else given
                if cand.resolve().is_relative_to(real_base) and cand.resolve() != real_base:
                    layer = cand
                    break
        if layer is not None:
            break
    if layer is None:
        raise RouteError("Layer は、このリポジトリの Flow/ か .ai-plc/projects/ の下を指定してください")
    if not layer.is_dir():
        raise RouteError("Layer のフォルダがありません")
    real = layer.resolve()
    for name in ("intent.yaml", "context.yaml", "backlog.yaml"):
        path = layer / name
        if not path.is_file() or not path.resolve().is_relative_to(real):
            raise RouteError(f"{name}: Layer の中の実在のファイルが要ります")
    return layer


def scheduled_date(value) -> date | None:
    """実行時期 scheduled_for（YYYY-MM-DD か YYYY-Www＝その週の月曜）。読めなければ None（時期なし）。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    v = str(value if value is not None else "").strip().strip("'\"").strip()
    m = WEEK_RE.match(v)
    try:
        if m:
            return date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
        if DAY_RE.match(v[:10]):
            return date.fromisoformat(v[:10])
    except ValueError:
        return None
    return None


def tasks_from(backlog: dict) -> list[dict]:
    tasks = backlog.get("tasks", []) or []
    if not isinstance(tasks, list):
        raise RouteError("backlog の tasks は一覧が要ります")
    ids = set()
    for task in tasks:
        if not isinstance(task, dict) or not isinstance(task.get("id"), str):
            raise RouteError("タスクは id 付きの mapping が要ります")
        if task["id"] in ids:
            raise RouteError("タスクの id が重複しています")
        ids.add(task["id"])
        if not isinstance(task.get("status"), str) or task["status"] not in DONE | OPEN:
            raise RouteError(f"{task['id']}: 知らない status")
        deps = task.get("dependencies", []) or []
        if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
            raise RouteError(f"{task['id']}: dependencies は文字列の一覧が要ります")
        priority = task.get("priority", "P1")
        if not isinstance(priority, str) or priority not in {"P0", "P1", "P2"}:
            raise RouteError(f"{task['id']}: priority は P0/P1/P2 が要ります")
        if task.get("command") is not None and not isinstance(task["command"], str):
            raise RouteError(f"{task['id']}: command は文字列か null が要ります")
    for task in tasks:
        if any(dep not in ids or dep == task["id"] for dep in task.get("dependencies", []) or []):
            raise RouteError(f"{task['id']}: 知らない依存か、自分への依存")
    return tasks


def agent_exists(task: dict, layer: Path, root: Path) -> bool:
    ref = task.get("command_template_ref")
    if ref is not None and not isinstance(ref, str):
        raise RouteError(f"{task['id']}: Agent の参照は文字列が要ります")
    agents = layer / "Agents"
    if ref:
        raw = Path(ref)
        cands = [raw] if raw.is_absolute() else [layer / raw, root / raw]
        return any(p.is_file() and p.resolve().is_relative_to(agents.resolve()) for p in cands)
    token = re.compile(rf"(^|_){re.escape(task['id'])}($|_)")  # 参照の無い古い Agent は ID の語で当てる
    return any(p.is_file() and token.search(p.stem) and p.resolve().is_relative_to(agents.resolve())
               for p in agents.glob("*.md"))


def resume_hint(value: str, root: Path, today: date | None = None) -> dict:
    today = today or date.today()
    layer = resolve_layer(value, root)
    intent = read_mapping(layer / "intent.yaml")
    context = read_mapping(layer / "context.yaml")
    backlog = read_mapping(layer / "backlog.yaml")
    scope = intent.get("scope_id")
    if not isinstance(scope, str) or not scope or any(d.get("scope_id") != scope for d in (context, backlog)):
        raise RouteError("intent・context・backlog の scope_id がそろっていません")
    variant = intent.get("pipeline_variant")
    if variant not in (None, "standard", "jev"):
        raise RouteError("知らない pipeline_variant")
    depth = intent.get("workflow_depth")
    if not isinstance(depth, str) or depth not in {"simple", "standard", "complex"}:
        raise RouteError("workflow_depth は simple/standard/complex が要ります")
    rel = layer.relative_to(root).as_posix()
    # 実験版（jev）は凍結中。pipeline_variant: jev は書き換えず、本体版として読む
    fields = {"layer": rel, "scope_id": scope, "pipeline_variant": variant or "standard",
              "variant_read_as": "standard",
              "auto_run_eligible": depth != "complex" and intent.get("mode") != "platform_builder"}
    tasks = tasks_from(backlog)

    def stage(name: str, reason: str, task_id: str | None = None) -> dict:
        r = skill_hint("resume", f"ai-plc/{name}", root, stage=name, reason=reason, task_id=task_id, **fields)
        r["prompt"] += f" / Layer: {rel}" + (f" / Task: {task_id}" if task_id else "")
        return r

    def audit(reason: str) -> dict:
        r = skill_hint("audit", "ppm-audit", root, reason=reason, **fields)
        r["prompt"] += f" / Layer: {rel}"
        return r

    status = intent.get("status")
    if not isinstance(status, str):
        raise RouteError("intent の status は文字列が要ります")
    if status in INTENT_FINISHED:
        r = skill_hint("completed", "ppm-audit", root, **fields,
                       reason=f"完了済み（{status}）。この Layer は再開しない。続きの仕事は新しい案件にする"
                              "（/ppm new）。状態の食い違いがありそうなら点検する")
        r["prompt"] += f" / Layer: {rel}"
        return r
    if status in INTENT_CANCELLED:
        r = skill_hint("reopen", "plc-lifecycle", root, **fields,
                       reason=f"中止済み（{status}）。再開するなら /plc-lifecycle の再開の手順"
                              "（再計画と本人の再開の指示が要る）。再開しないならこのまま")
        r["prompt"] += f" / Layer: {rel}"
        return r
    if status in INTENT_PAUSED:
        return {"action": "hold", "advisory_only": True, "owner_confirmation_required": True, **fields,
                "reason": f"止めている（{status}）。再開してよいかを本人に確かめる。再開するなら intent の status を "
                          "active に戻してから、もう一度続きを判定する"}
    if status == "blocked":
        return {"action": "hold", "reason": "Layer が blocked。原因と再開の許可を確かめる", "advisory_only": True, **fields}
    if status not in ("active", "planned"):
        raise RouteError("intent の status が分かりません（planned・active・blocked・paused・deferred・"
                         "completed・cancelled のどれかが要ります）")
    if status == "planned":
        r = next_step(tasks, backlog, intent, depth, layer, root, today, stage, audit, fields)
        r["owner_confirmation_required"] = True
        if r["action"] == "hold":  # 止まる理由があるときは止まったまま（始める確認に替えない）
            r["reason"] = "まだ始めていない（planned）。" + r["reason"]
            return r
        r["action"] = "confirm_start"
        r["reason"] = ("まだ始めていない（planned）。始めてよいかを本人に確かめてから、次の手順へ"
                       "（Goal から見直すなら /01-collection）: " + r["reason"])
        return r
    return next_step(tasks, backlog, intent, depth, layer, root, today, stage, audit, fields)


def next_step(tasks, backlog, intent, depth, layer, root, today, stage, audit, fields) -> dict:
    """active（と planned）の Layer の次の手順。"""
    if not tasks:
        return stage("04-operation" if depth == "simple" else "02-inception",
                     "backlog が空。準備（simple）か分解（standard 以上）の手順を使う")
    unfinished = [t for t in tasks if t["status"] not in DONE]
    normal = [t for t in unfinished if not t.get("recurrence")]
    # 運用タスク（recurrence）は、全部済みの判定に数えない。止めた（retired_at）ものは回さない
    recurring = [t for t in tasks if t.get("recurrence") and not t.get("retired_at") and t["status"] not in DONE]
    if not normal:
        children = backlog.get("sublayers", []) or []
        scopes = intent.get("sub_agent_scopes", []) or []
        if not isinstance(children, list) or not isinstance(scopes, list):
            raise RouteError("子の Layer の一覧は list が要ります")
        for child in children + scopes:
            if not isinstance(child, dict) or not isinstance(child.get("status"), str):
                raise RouteError("子の Layer は文字列の status 付きの mapping が要ります")
        if any(c["status"] not in DONE for c in children + scopes):
            return {"action": "hold", "reason": "子の Layer が終わっていないか状態が分からない。親を閉じずに確かめる",
                    "advisory_only": True, **fields}
        reason = "backlog が全部済み。点検して、次にしたいことを確かめる"
        if recurring:
            reason += f"（運用タスク {len(recurring)}件は数えていない。回すなら /04-operation で Task を指定する）"
        r = audit(reason)
        if recurring:
            r["recurring_task_ids"] = [t["id"] for t in recurring]
        return r
    construction = backlog.get("construction", {}) or {}
    if not isinstance(construction, dict):
        raise RouteError("construction は mapping が要ります")
    required = construction.get("tasks", []) or []
    ids = {t["id"] for t in tasks}
    if not isinstance(required, list) or not all(isinstance(x, str) and x in ids for x in required):
        raise RouteError("construction.tasks は実在のタスク id の一覧が要ります")
    missing = [t["id"] for t in normal if t["status"] in {"pending", "in_progress", "active"}
               and t["id"] in required and t.get("command") and not agent_exists(t, layer, root)]
    if missing:
        return stage("03-construction", "Agent の定義が要るタスクに定義が無い", missing[0])
    done = {t["id"] for t in tasks if t["status"] in DEPENDENCY_COMPLETE}
    ready, later = [], []
    for t in normal:
        if t["status"] not in {"pending", "in_progress", "active"} or not set(t.get("dependencies", []) or []) <= done:
            continue
        when = scheduled_date(t.get("scheduled_for"))
        (later if when and when > today else ready).append((t, when))
    # /04-operation の Phase 2 と同じ順: 実行時期のあるタスク（今日以前）を時期の早い順に先に、
    # その後に時期の無いタスク。同じ時期・時期なしの中は優先度→ID
    ready.sort(key=lambda x: (x[1] is None, x[1] or date.max, x[0].get("priority", "P1"), x[0]["id"]))
    if ready:
        first, when = ready[0]
        why = (f"依存が済んだ未完了のタスク（実行時期 {when.isoformat()} のものを先に）" if when
               else "依存が済んだ未完了のタスク")
        return stage("04-operation", why, first["id"])
    extra = {}
    reason = "blocked・deferred か依存が済んでいない。理由を確かめる"
    if later:
        first = min(w for _, w in later)
        reason = f"実行時期がまだ来ていないタスクだけが動かせる（いちばん早いのは {first.isoformat()}）。待つか、本人が Task を指定して前倒しする"
        extra["scheduled_task_ids"] = [t["id"] for t, _ in later]
    if recurring:
        extra["recurring_task_ids"] = [t["id"] for t in recurring]
        reason += "。運用タスクは回すときだけ /04-operation で Task を指定する"
    return {"action": "hold", "reason": reason, "task_ids": [t["id"] for t in normal],
            "advisory_only": True, **extra, **fields}


def route(action: str = "status", *, layer: str | None = None, goal: str | None = None,
          root: Path | None = None, today: date | None = None) -> dict:
    root = Path(root or default_root()).resolve()
    if action == "resume":
        if goal:
            raise RouteError("--goal は new のときだけ使う")
        if not layer:
            raise RouteError("resume には --layer が要ります")
        return resume_hint(layer, root, today)
    if layer:
        raise RouteError("--layer は resume のときだけ使う（黙って無視しない）")
    if action == "new":
        if not goal or not goal.strip():
            raise RouteError("new には --goal が要ります。先に同じ目的の既存の案件を探してください")
        r = skill_hint("new", "ai-plc/01-collection", root, goal=goal, existing_layer_search_required=True)
        r["prompt"] += f" / Goal: {goal}"
        return r
    if goal:
        raise RouteError("--goal は new のときだけ使う")
    if action not in SKILLS:
        raise RouteError("知らない行き先")
    return skill_hint(action, SKILLS[action], root)


class JsonArgumentParser(argparse.ArgumentParser):
    """引数の誤りも、ほかの誤りと同じ形（stdout に {"error": …}、終了コード 2）で返す。"""

    def error(self, message):  # noqa: D401
        print(json.dumps({"error": f"引数が違います: {message}", "advisory_only": True}, ensure_ascii=False))
        raise SystemExit(2)


def parse_today(value: str | None) -> date | None:
    if not value:
        return None
    try:
        if not DAY_RE.match(value):
            raise ValueError
        return date.fromisoformat(value)
    except ValueError:
        raise RouteError(f"--today は YYYY-MM-DD で指定してください（今の値: {value!r}）") from None


def main(argv=None) -> int:
    ap = JsonArgumentParser(description="/ppm の振り分けの手がかり（読むだけ）")
    ap.add_argument("action", nargs="?", default="status", choices=[*SKILLS, "new", "resume"])
    ap.add_argument("--layer")
    ap.add_argument("--goal")
    ap.add_argument("--root", default=None)
    ap.add_argument("--today", default=None, help="YYYY-MM-DD（試験用。実行時期の判定に使う）")
    try:
        a = ap.parse_args(argv)
    except SystemExit as exc:  # -h は 0、誤りは error() が JSON を出して 2
        return int(exc.code or 0)
    try:
        today = parse_today(a.today)
        result = route(a.action, layer=a.layer, goal=a.goal, root=Path(a.root) if a.root else None, today=today)
    except (ValueError, OSError) as exc:  # RouteError も ValueError の仲間
        msg = str(exc) if isinstance(exc, RouteError) else f"読めません（{type(exc).__name__}）"
        print(json.dumps({"error": msg, "advisory_only": True}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
