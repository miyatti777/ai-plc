---
name: plc-db-sync
description: SKL_plc_db_sync（旧 ai-plc-db-sync）- AI-PLCのローカルDBとNotion DBをpull、push、sync、statusで双方向同期する。タスク同期の凍結（tasks-sync）も扱う。
---

# AI-PLC DB Sync

`.claude/db/ai_plc.db` をローカルの正本として扱い、`projects` / `tasks` テーブルを Notion と双方向同期する。人向けのリファレンスは `.claude/db/README.md`。

## When to Use

- 「DBを同期して」「NotionのDBをPullして」→ pull
- 「タスクをNotionに反映して」「Push」→ push
- 「DB同期状態を確認して」「syncステータス」→ status
- 「DB同期」→ sync（双方向）
- 「タスク同期は凍結されている？」→ `tasks-sync --status`
- プロジェクトやタスクをローカルで追加・更新した後にNotionへ反映したいとき
- Notion側の最新データをローカルに取り込みたいとき

## Commands

```bash
python3 .claude/db/sync.py pull              # Notion → ローカル
python3 .claude/db/sync.py push              # ローカル → Notion
python3 .claude/db/sync.py sync              # 双方向 (pull → push)
python3 .claude/db/sync.py status            # 差分プレビュー
python3 .claude/db/sync.py pull --dry-run    # dry-run (変更なし)
python3 .claude/db/sync.py push --dry-run    # dry-run (変更なし)
python3 .claude/db/sync.py tasks-sync --status                                  # タスク同期の凍結を確認
python3 .claude/db/sync.py tasks-sync --freeze --approved-by NAME [--reason TEXT] # タスク同期を凍結
python3 .claude/db/sync.py tasks-sync --unfreeze --approved-by NAME               # 凍結を解除
```

## Prerequisites

- `NOTION_API_TOKEN` 環境変数が設定済みであること（pull / push / sync / status。`tasks-sync` は Notion を呼ばない）
- 同期先の Notion DB ID を `AI_PLC_PROJECTS_DB_ID`（タスク同期が凍結されていなければ `AI_PLC_TASKS_DB_ID` も）で指定すること
- `.claude/db/ai_plc.db` が存在すること（なければ `python3 .claude/db/init_db.py` で作成）

## Agent Rules

- 読み取り確認として実行してよいのは `status`、`pull` / `push` の `--dry-run`、`tasks-sync --status`。
- `pull` / `push` / `sync` / `tasks-sync --freeze` / `tasks-sync --unfreeze` は状態を変更する。ユーザーが求めた範囲だけ実行し、`--approved-by` はユーザーの判断なしに埋めない。
- タスク同期の凍結中（`tasks-sync --status` が FROZEN。新しく作った DB は凍結済み）は、タスクの正は各 Layer の backlog.yaml だけ。`plc_query.py add-task` は書き込まずに `[SKIP]` を出す（RUL_plc_system §9）。

## Sync Logic

- **Pull**: Notion 側を query → `notion_last_edited` で差分検出 → `.claude/db/ai_plc.db` を更新
- **Push**: `updated_at > last_sync_at` の行を検出 → Notion API で PATCH/POST
- **Conflict**: Pull時にローカルも変更されている行は CONFLICT としてスキップ（安全側）
- **タスク同期の凍結中**: pull / push / sync / status は Projects だけを扱い、tasks テーブルにも Notion の Tasks DB にも触れない。凍結の記録が壊れていると pull / push / sync / status は止まる（exit 3）。記録は手で直さず報告する
- **Project の cancelled**: 中止の metadata（理由・判断）の Notion への同期は未対応（RUL_plc_system §21）。中止・再開は `plc-project-status` で扱う

## Data Model

| テーブル | ローカルDB | 同期先Notion DB | 用途 |
| --- | --- | --- | --- |
| projects | `.claude/db/ai_plc.db` | Notion: Projects DB（`AI_PLC_PROJECTS_DB_ID` で指定） | プロジェクト管理 |
| tasks | `.claude/db/ai_plc.db` | Notion: Tasks DB（`AI_PLC_TASKS_DB_ID` で指定） | タスク管理（凍結中は同期しない） |

## Typical Workflow

1. `status` で差分を確認
2. `pull` でNotion側の最新を取得
3. ローカルで `plc_query.py` を使って編集
4. `push` でNotionに反映

## Related Files

- `.claude/db/ai_plc.db` — SQLite DB本体
- `.claude/db/init_db.py` — スキーマ作成（新しい DB はタスク同期を凍結済みで作る）
- `.claude/db/plc_query.py` — ローカルクエリヘルパー
- `.claude/db/sync.py` — 同期エンジン
- `.claude/db/README.md` — ドキュメント
