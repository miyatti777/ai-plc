# AI-PLC ローカルDB（Project Registry / Tasks）

AI-PLC は、プロジェクト横断の台帳とタスクをローカル SQLite（`ai_plc.db`）で管理します。
インストール時に空のDBが作られます（個人データは含まれません）。

## 何に使うか

- **Project Registry（`projects` テーブル）** — Collection の Phase 3.5 で各プロジェクトを登録し、横断で状況を見る台帳
- **Tasks（`tasks` テーブル）** — **凍結して使わない**（v1.12.0〜）。タスクの正は各 Layer の `backlog.yaml` で、External Sync の既定は `projects` テーブル（RUL_plc_system §9）。新しく作った DB は最初から凍結され（`_metadata` の `task_sync_frozen`）、凍結中は `plc_query.py add-task` が書き込まずに `[SKIP]` を出し、`plc_query.py tasks` / `dashboard` は backlog.yaml を見る

> 核の4ステージループ（Collection→Operation）は DB が無くても動きます。DBは「横断管理」の追加レイヤーです。

## セットアップ

インストーラが自動で実行します。手動なら:

```bash
python3 .claude/db/init_db.py            # 空DBを作成（.claude/db/ai_plc.db。新しく作るときだけタスク同期を凍結）
python3 .claude/db/init_db.py --reset    # 作り直す
```

既存の DB に `init_db.py` を流しても、スキーマを保証するだけで凍結の印は足しません。

DBは **このスクリプトと同じディレクトリ**に作られます（Claude Code 既定: `.claude/db/ai_plc.db`）。

## 使い方

```bash
python3 .claude/db/plc_query.py projects        # プロジェクト一覧
python3 .claude/db/plc_query.py tasks           # タスク一覧（凍結中は backlog.yaml を表示）
python3 .claude/db/plc_query.py tasks L-1234    # 特定Scopeのタスク
python3 .claude/db/plc_query.py dashboard       # ダッシュボード
python3 .claude/db/plc_query.py sql "SELECT ..."  # 任意SQL
```

## タスク同期の凍結（`tasks-sync`）

```bash
python3 .claude/db/sync.py tasks-sync --status                                   # 凍結しているか
python3 .claude/db/sync.py tasks-sync --freeze --approved-by <名前> [--reason "<理由>"]   # 凍結する
python3 .claude/db/sync.py tasks-sync --unfreeze --approved-by <名前>             # 戻す
```

- v1.11.0 以前から使っている DB は、installer が書き換えないので凍結されていません。更新の後に `--freeze` を1回実行してください
- 凍結しても tasks テーブルの行は消えません（古い写しとして残るだけ）。凍結中、`sync.py` の pull / push / sync / status は Projects だけを扱い、Notion の Tasks DB には問い合わせません（`AI_PLC_TASKS_DB_ID` も不要）
- Notion の設定が無くても `tasks-sync` は使えます
- 凍結の印が壊れていると、`tasks-sync --status` は `MALFORMED` と出して終了コード 3、`sync.py` の pull / push / sync / status も止まります（`plc_query.py` は凍結として扱い、警告を1行出します）。`tasks-sync --unfreeze --approved-by <名前>` で壊れた印を履歴（`task_sync_unfrozen:<日時>`）に退避して消し、必要なら `--freeze` し直します
- 凍結中の `plc_query.py tasks` は、プロジェクトのルートから intent.yaml を探して backlog.yaml を読みます。隠しフォルダ・`node_modules`・`Documents` などは見ず、シンボリックリンクはたどりません。同じ scope_id の Layer が複数あるときは最初に見つかった1つだけを表示します

## Notion 同期（任意・上級）

`sync.py` で、この SQLite を自分の Notion DB と双方向同期できます。使う場合のみ、環境変数で対象を指定:

```bash
export NOTION_API_TOKEN=<あなたのNotionトークン>
export AI_PLC_PROJECTS_DB_ID=<あなたの Projects DB のID>
export AI_PLC_TASKS_DB_ID=<あなたの Tasks DB のID>   # タスク同期を凍結していれば不要

python3 .claude/db/sync.py status       # 差分プレビュー
python3 .claude/db/sync.py sync         # 双方向同期
```

Notion側DBのプロパティ構成に依存します。使わない場合はローカルDBだけで完結します。

## スキーマ

- `projects`: scope_id / name / goal / owner / status(planned/active/completed/paused) / mode / depth / system / parent_scope / deadline …
- `tasks`: task_id / scope_id / name / status / type / priority / estimate_days / output_url / completed_at …
- `_metadata`: schema_version・タスク同期の凍結の印（`task_sync_frozen`）など
