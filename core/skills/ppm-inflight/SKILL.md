---
name: ppm-inflight
description: ポートフォリオ層・進行中の候補の洗い出し。Layer の intent.yaml から「進行中の仕事」の候補を集め、TODO の一覧（既定は todo/todo.md）との差分（一覧にある・足す候補・外す候補・期限を過ぎたか止まっている）を示す。読み取り専用で、反映は /ppm-todo。「進行中の候補を出して」「TODO の一覧と Layer のずれを見て」で使う。
---

# ppm-inflight（進行中の候補を洗い出す）

> 層: ポートフォリオ層 ／ 読み取り専用。TODO の一覧・Layer・Registry のどれにも書かない

- **何をするか:** リポジトリの Layer（`Flow/` と `.ai-plc/projects/` の下の `intent.yaml`）から進行中の案件を集め、TODO の一覧と比べて「足す候補」「外す候補」などを示す
- **考え方:** 案件の状態の正本は Layer の intent と backlog。TODO の一覧は、その中から本人が今かかえている案件を1件1行に写したもの。写しがずれていないかを、ここで見る
- **反映はしない:** 一覧に足す・外すと言われたら `/ppm-todo` に渡す（本人が承認した行だけを書く）

## コアロジック（環境に依存しない）

### 見る範囲

- 親の Layer だけを見る。`sublayers/` の下、`parent_scope` のある Layer、Layer の中の `Documents/`・`Context/` に置いた写しは数えない
- 進行中とみなすのは、intent の status が `active` か `blocked` で、backlog の通常のタスクが全部は終わっていないもの。全部終わっていても、子の Layer が進行中なら進行中に入れる。運用タスク（recurrence のあるタスク）は `retired_at` が付くまで終わっていないとみなす
- 題名は intent の `display_name`（無ければ `scope_name`、無ければフォルダ名）。ID は intent の `scope_id` をそのまま使う
- 「足す候補」に出すのは最近の Layer だけ（設定 `ppm.inflight.recent_days`、既定 21 日）。古い Layer は件数だけを出す。Layer の日付は、フォルダの名前の `YYYY-MM-DD` → intent の `start_date`・`created_at` → `intent.yaml` の更新日の順で決める
- TODO の一覧の置き場と節の名前は、設定 `.ai-plc/config.yaml` の `ppm:`（[ppm の README](../ppm/README.md)）。一覧の進行中の節の行の下にある `<!-- layer: … scope: … -->` の注記で、案件と行を結ぶ
- 進行中の節の外（止めている案件の節など）に注記がある案件は、候補に出さない（件数だけ）
- 注記の layer は `./`・`a/../b` を畳んでから照らす。絶対パスでも（途中に `..` があっても）、リポジトリの中を指していれば相対パスに直して結ぶ。リポジトリの外を指す注記（外の絶対パスと、畳むと外に出る相対パス）は「外す候補」にせず、件数と題名を別に出す（注記を直すか、そのまま残すかは本人が決める）
- TODO の一覧はあるのに、進行中の節の見出し（設定 `ppm.todo.inflight_sections`）が1つも見つからないときは、1行の注意を出す（一覧の行を読めていないので、足す候補が多めに出る）
- リンクで置き場（`Flow/`・`.ai-plc/projects/`）の外を指す `intent.yaml`・`backlog.yaml` は読まない（件数だけ出す）。置き場の `Flow` 自体を別の場所へのリンクにしているのはかまわない

### 手順

1. リポジトリのルートで道具を実行する（下の「ストレージ操作」）
2. 出力の区分ごとに、要点を日本語で伝える:
   - TODO の一覧にある（一覧では済みの印なのに、案件がまだ進行中なら添える）
   - 足す候補（最近の進行中の案件で、一覧に無いもの）
   - 外す候補（一覧にあるが、案件が閉じた・タスクが全部終わった・Layer が見つからない）
   - 期限を過ぎたか止まっている（閉じる・延ばす・待つを決める材料）
   - そのほか（古い案件の件数、リポジトリの外を指す注記、リンクで外を指すので読まなかった `intent.yaml`、読めなかった `intent.yaml`、同じ `scope_id` の重なり）
3. 反映したいと言われたら `/ppm-todo` に渡して止まる

### しないこと

- TODO の一覧・intent・backlog・Registry を書き換えない
- Registry の「進行中」の一覧（`plc_query.py active`）を、この候補の代わりにしない（閉じ忘れの行が混ざるため）
- いつかやるストック（`/ppm-someday`）は Layer を持たないので、ここには出ない。見るなら `/ppm-someday`

## ストレージ操作（ローカル実装）

```bash
python3 .claude/skills/ppm-inflight/list_inflight.py          # 本人向けの文
python3 .claude/skills/ppm-inflight/list_inflight.py --json   # 機械向け（keep・add・parked・elsewhere・remove・stale・outside_notes・outside_links・inflight_sections_missing）
```

- 読むもの: `Flow/`・`.ai-plc/projects/` の下の `intent.yaml`・`backlog.yaml`、TODO の一覧（置き場は `.claude/skills/ppm/ppm_files.py` が設定から決める）
- 書くもの: なし
- PyYAML が要る。TODO の一覧が無い環境でも止まらない（全部を「一覧に無い」として出し、一覧はまだ無いと書く）
- 業務プロジェクトごとのまとめは `/ppm-todo` の `inflight_programs.py` が、この道具の結果を使って作る
