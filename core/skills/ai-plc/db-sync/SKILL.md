# AI-PLC DB Sync

`.claude/db/ai_plc.db` をローカルの正本として扱い、`projects` / `tasks` テーブルを Notion と双方向同期する。

## When to Use

- 「DBを同期して」「NotionのDBをPullして」→ pull
- 「タスクをNotionに反映して」「Push」→ push
- 「DB同期状態を確認して」「syncステータス」→ status
- 「DB同期」→ sync (双方向)
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
```

## Prerequisites

- `NOTION_API_TOKEN` 環境変数が設定済みであること
- `.claude/db/ai_plc.db` が存在すること（なければ `python3 .claude/db/init_db.py --import` で作成）

## Sync Logic

- **Pull**: Notion 側を query → `notion_last_edited` で差分検出 → `.claude/db/ai_plc.db` を更新
- **Push**: `updated_at > last_sync_at` の行を検出 → Notion API で PATCH/POST
- **Conflict**: Pull時にローカルも変更されている行は CONFLICT としてスキップ（安全側）

## Data Model

| テーブル | ローカルDB | 同期先Notion DB | 用途 |
| --- | --- | --- | --- |
| projects | `.claude/db/ai_plc.db` | AI-PLC Projects (`8f5680ac-...`) | プロジェクト管理 |
| tasks | `.claude/db/ai_plc.db` | AI-PLC Tasks (`a4df4cf0-...`) | タスク管理 |

## Typical Workflow

1. `status` で差分を確認
2. `pull` でNotion側の最新を取得
3. ローカルで `plc_query.py` を使って編集
4. `push` でNotionに反映

## Related Files

- `.claude/db/ai_plc.db` — SQLite DB本体
- `.claude/db/init_db.py` — スキーマ作成 + マイグレーション
- `.claude/db/plc_query.py` — ローカルクエリヘルパー
- `.claude/db/sync.py` — 同期エンジン
- `.claude/db/README.md` — ドキュメント
