---
name: plc-registry
description: AI-PLCの Project Registry（.claude/db/ai_plc.db の projects / tasks）を照会・追加する。「Registry見せて」「AI-PLCのダッシュボード」「プロジェクト一覧」「L-xxxx のタスク状況」「Registryに登録して」で使う。
---

# plc-registry（Project Registry の照会と追加）

> 論理名: SKL_plc_registry ／ 包むもの: `.claude/db/plc_query.py`（挙動は変えない）

## 使い方

| やりたいこと | コマンド | 書き込み |
| --- | --- | --- |
| 全体の概況 | `python3 .claude/db/plc_query.py dashboard` | なし |
| 全プロジェクト | `python3 .claude/db/plc_query.py projects` | なし |
| active のプロジェクト | `python3 .claude/db/plc_query.py active` | なし |
| 特定PJのタスク | `python3 .claude/db/plc_query.py tasks <scope_id>`（Task 同期の凍結中は backlog.yaml を表示する） | なし |
| 任意の照会 | `python3 .claude/db/plc_query.py sql "SELECT ... LIMIT 20"` | SELECT ならなし |
| プロジェクトを追加 | `python3 .claude/db/plc_query.py add-project <scope_id> "<名前>" "<goal>"` | あり |
| タスクを追加 | `python3 .claude/db/plc_query.py add-task <task_id> <scope_id> "<名前>" [type] [priority]`（**Task 同期の凍結中は書き込まず `[SKIP]` を出す**。タスクの正は backlog.yaml） | あり（凍結中はなし） |
| いつかやるPJをストック | `python3 .claude/db/plc_query.py someday-add "<タイトル>" ["<メモ>"]` | あり |
| ストック一覧 | `python3 .claude/db/plc_query.py someday` | なし |
| ストック着手 | `python3 .claude/db/plc_query.py someday-start <S-ID>` | あり |
| 着手の取消 | `python3 .claude/db/plc_query.py someday-revert <S-ID>` | あり |
| 列の更新 | `python3 .claude/db/plc_query.py sql "UPDATE projects SET ... WHERE scope_id='<scope_id>'"` | あり |

リポジトリのルートで実行する。結果の表はそのまま見せ、長ければ要点（件数・該当行）だけを抜き出す。

## 命名の判断と表示名の限定更新

Inception の Re-Inception と Operation の節目（Phase 5.5 を通した成果が案件の目的の説明を変えるとき）で、表示名を変えるべきかを判断する。単なる Task の追加・軽い状態の変化は改名の節目にしない。

- 現在の名前で目的を説明できるなら維持する。意味のある目的の差分があるときだけ、対象と何をする案件かが分かる短い新しい表示名を最大1案出す。未確認の成果・推測・管理番号だけを名前にしない
- 案（旧名→新名と理由）を本人に見せ、明確な OK があったときだけ反映する。Goal の承認や分解の承認を、改名の承認に流用しない
- 反映するのは `intent.yaml` の `display_name` と Registry の `projects.name` だけ（`python3 .claude/db/plc_query.py sql "UPDATE projects SET name='<新名>' WHERE scope_id='<ID>'"`。出力に `Error:` が無いことを確かめる）。`scope_name`・Scope ID・パス・Goal は変えない
- 判断と結果を backlog の `refactoring_log` に1行残す。変更しなかったときは通知を増やさない
- cancelled・paused の案件、Layer が見つからない・重複している案件では改名しない

## 注意

- Project中止/再開は `/plc-project-status` の正式手順（RUL_plc_system §21）。`cancelled`はGoal未達の終了で、SQL status変更では判断記録が欠けるため拒否する。completedと別集計する。

- **進行中の一覧の正本ではない。** 進行中の仕事はあなたの TODO 管理で見る（AI-PLC の範囲外）。`active` には閉じ忘れが混ざる（点検は `/plc-status-audit`）
- **Task は凍結中（2026-10-01〜）。** ローカルの tasks テーブルは backlog.yaml の古い写しで、読まない・書かない（`python3 .claude/db/sync.py tasks-sync --status` で確認できる）。タスクの状況は backlog.yaml を見る
- **行の追加は add-project / add-task だけ。** SQL で直接 INSERT しない（追加の入口を1つにそろえる）。追加した後の列（mode・depth・top_page_url・start_date・deadline 等）は UPDATE で埋める
- **task_id は `T001` の形。** scope_id は第2引数で渡すので、task_id に `L-xxxx-` を付けない
- **type の許可値:** research / design / implementation / content / verification / coordination（documentation などは不可 → content）。priority は P0〜P3
- 書き込み（add・UPDATE）はユーザーが頼んだ範囲だけ行う。`init_db.py` を本番に対して実行しない
- いつかやるPJのストックは `/plc-someday`、Notion との同期は `/plc-db-sync`
- 詳細: `.claude/db/README.md`
