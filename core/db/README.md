# AI-PLC ローカルDB（Project Registry / Tasks）

AI-PLC は、プロジェクト横断の台帳とタスクをローカル SQLite（`ai_plc.db`）で管理します。
インストール時に空のDBが作られます（個人データは含まれません）。

## 何に使うか

- **Project Registry（`projects` テーブル）** — Collection の Phase 3.5 で各プロジェクトを登録し、横断で状況を見る台帳
- **Tasks（`tasks` テーブル）** — 既定の External Sync 先。Operation の Phase 7 でタスクの完了状況を反映（`sync_targets` 未指定時のデフォルト）

> 核の4ステージループ（Collection→Operation）は DB が無くても動きます。DBは「横断管理」の追加レイヤーです。

## セットアップ

インストーラが自動で実行します。手動なら:

```bash
python3 .claude/db/init_db.py            # 空DBを作成（.claude/db/ai_plc.db）
python3 .claude/db/init_db.py --reset    # 作り直す
```

DBは **このスクリプトと同じディレクトリ**に作られます（Claude Code 既定: `.claude/db/ai_plc.db`）。

## 使い方

```bash
python3 .claude/db/plc_query.py projects        # プロジェクト一覧
python3 .claude/db/plc_query.py tasks           # タスク一覧
python3 .claude/db/plc_query.py tasks L-1234    # 特定Scopeのタスク
python3 .claude/db/plc_query.py dashboard       # ダッシュボード
python3 .claude/db/plc_query.py sql "SELECT ..."  # 任意SQL
```

## Notion 同期（任意・上級）

`sync.py` で、この SQLite を自分の Notion DB と双方向同期できます。使う場合のみ、環境変数で対象を指定:

```bash
export NOTION_API_TOKEN=<あなたのNotionトークン>
export AI_PLC_PROJECTS_DB_ID=<あなたの Projects DB のID>
export AI_PLC_TASKS_DB_ID=<あなたの Tasks DB のID>

python3 .claude/db/sync.py status       # 差分プレビュー
python3 .claude/db/sync.py sync         # 双方向同期
```

Notion側DBのプロパティ構成に依存します。使わない場合はローカルDBだけで完結します。

## スキーマ

- `projects`: scope_id / name / goal / owner / status(planned/active/completed/paused) / mode / depth / system / parent_scope / deadline …
- `tasks`: task_id / scope_id / name / status / type / priority / estimate_days / output_url / completed_at …
- `_metadata`: schema_version など
