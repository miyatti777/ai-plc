---
name: plc-registry
description: AI-PLCの Project Registry（.claude/db/ai_plc.db の projects / tasks）を照会・追加する。「Registry見せて」「AI-PLCのダッシュボード」「プロジェクト一覧」「このLayerのタスク状況」「Registryに登録して」で使う。
---

# plc-registry（Project Registry の照会と追加）

> 論理名: SKL_plc_registry ／ 包むもの: `.claude/db/plc_query.py`（挙動は変えない）／ 詳細: `.claude/db/README.md`

## 使い方

| やりたいこと | コマンド | 書き込み |
| --- | --- | --- |
| 全体の概況 | `python3 .claude/db/plc_query.py dashboard` | なし |
| 全プロジェクト | `python3 .claude/db/plc_query.py projects` | なし |
| active のプロジェクト | `python3 .claude/db/plc_query.py active` | なし |
| 特定PJのタスク | `python3 .claude/db/plc_query.py tasks <scope_id>`（タスク同期の凍結中は backlog.yaml を表示する） | なし |
| 任意の照会 | `python3 .claude/db/plc_query.py sql "SELECT ... LIMIT 20"` | SELECT ならなし |
| プロジェクトを追加 | `python3 .claude/db/plc_query.py add-project <scope_id> "<名前>" "<goal>"` | あり |
| タスクを追加 | `python3 .claude/db/plc_query.py add-task <task_id> <scope_id> "<名前>" [type] [priority]`（**タスク同期の凍結中は書き込まず `[SKIP]` を出す**。タスクの正は backlog.yaml） | あり（凍結中はなし） |
| 列の更新 | `python3 .claude/db/plc_query.py sql "UPDATE projects SET ... WHERE scope_id='<scope_id>'"` | あり |

プロジェクトのルートで実行する（Cursor だけの配置では `.claude/` を `.cursor/` に読み替える）。結果の表はそのまま見せ、長ければ要点（件数・該当行）だけを抜き出す。

## 注意

- **状態の値:** projects も tasks も `planned` / `active` / `completed` / `paused` だけを受け付ける。priority は P0〜P3
- **task_id は `T001` の形。** scope_id は第2引数で渡すので、task_id に scope_id を付けない
- **タスクは凍結中なら読まない・書かない。** tasks テーブルは backlog.yaml の古い写し（新しい DB は最初から凍結。確認は `python3 .claude/db/sync.py tasks-sync --status`）。タスクの状況は backlog.yaml を見る — RUL_plc_system §9
- 追加した後の列（mode・depth・top_page_url・start_date・deadline 等）は UPDATE で埋める。行は add-project（凍結していない DB では add-task も）で追加する
- 書き込み（add・UPDATE）はユーザーが頼んだ範囲だけ行う。`init_db.py` を既存の DB に対して実行しない
- `active` には閉じ忘れが混ざることがある（点検は `/plc-status-audit`）。Notion との同期は `/plc-db-sync`
