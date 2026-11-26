---
name: ppm-status
description: ポートフォリオ層の状況確認。進行中の案件を TODO の一覧（既定は todo/todo.md）から、今日やることをその日の WillDo と日記の緊急から読み、First Task と自分が関わる未完了 Task の件数を添えて短く見せる。Layer のパスを渡したときだけ、その Layer の状態と次の数件を見る。読み取り専用で、どのファイルにも行を足さない。「今どうなってる？」「今日の残りは？」「進行中の一覧を見せて」で使う。
---

# ppm-status（状況確認）

> 層: ポートフォリオ層 ／ 読み取り専用。日次の入口（`/ppm-plan`・`/ppm-update`・`/ppm-capture`・`/ppm-close`）の「今どこにいるか」を見る窓

- **何をするか:** 進行中の案件（TODO の一覧）と、今日やること（その日の WillDo）を並べて見せる。差し込みを見つけても書かず、行き先を案内するだけ
- **考え方:**
  - 進行中の仕事の定位置は TODO の一覧の1件1行。いつ開いても同じ場所にある
  - 今日やることは、前日に組んだ WillDo だけ（当日は増やさない閉じたリスト）。ここでは増やさない
  - Task の ID（T001 など）や Layer の中身は、Layer のパスを渡されたときだけ見る
- **使わなくてもよい:** TODO の一覧や WillDo が無い環境でも止まらない。無いものは「無い」と書いて続ける

## コアロジック（環境に依存しない）

### 入力

| 引数 | 見る範囲 |
| --- | --- |
| なし・`summary` | TODO の一覧の進行中＋今日の WillDo と緊急＋First Task（既定） |
| `inflight` | TODO の一覧の進行中だけ |
| `today` | 今日の WillDo と、今日の日記の緊急の未完了と、WillDo に無い予定タスクの未完了だけ |
| `detail` | 既定の範囲に加え、進行中の仕事の各行の Layer の注記を開き、未完了の次の一手を1行ずつ（ID は出さない）。私生活の節の行の Layer は開かない（利用者がその案件を名指ししたときだけ開く） |
| `Flow/` で始まる Layer のパス | その Layer の intent.yaml の status と、backlog.yaml の未完了の上位3件の名前だけ（SubLayer があれば status だけ） |

### 手順

1. `date +%Y-%m-%d` を単独で実行して基準日を決める
2. TODO の一覧（既定は `todo/todo.md`。置き場と節の名前は設定 `.ai-plc/config.yaml` の `ppm:` で替えられる）の進行中の未完了の行と、雑務の節の未完了の件数を読む。待ちの節があれば件数を添える
   - TODO の一覧が無ければ「TODO の一覧がまだありません」と書いて続ける。このスキルは作らない。同梱の雛形から作るには `/ppm-plan` か `/ppm-capture`（どちらも作る前に利用者に聞く）を案内する
3. 基準日の WillDo（既定は `Flow/YYYYMM/YYYY-MM-DD/will_do.md`）を読み、5つの欄（First Task・差し込み・繰り越し・TODOから・Daily Task）の完了と未完了の数を出す。無ければ「まだ組んでいない（/ppm-plan）」と書いて続ける
   - 今日の日記（既定は `Flow/YYYYMM/YYYY-MM-DD/task_diary.md`）の「緊急」の未完了も、題名と件数を出す（`/ppm-capture` が今日に入れた差し込み。WillDo の件数には足さない）
   - 今日の日記の「予定タスク」の未完了のうち、今日の WillDo に同じ題名の行が無いものも、題名と件数を出す（WillDo を組んだ後に `/ppm-capture` が足した行。比べるときは空白と「（理由: …）」を無視する。WillDo の件数には足さない。次に `/ppm-plan` で組むときに拾われる）
4. First Task（既定は `todo/first_task.md` の「⭐ 現在のFirst Task」の下の最初の未完了の行）を1行添える
5. 自分が関わる未完了 Task の**件数**を添える（TODO の一覧の進行中の案件の backlog だけを数える。Task は列挙しない。スキップと出たら行を省く）
6. 既定（summary）は、上を日本語で短く出す。Task の ID や SubLayer の名前を題名に出さない
7. `detail` か Layer のパスのときだけ、注記の Layer の `intent.yaml`・`backlog.yaml` を読む。`detail` でも私生活の節の行の Layer は読まない（利用者が名指ししたときだけ）。TODO の一覧・WillDo には書かない
8. 差し込みに気づいたら `/ppm-capture` へ、完了の反映は `/ppm-update` へ案内するだけ。ファイルは書かない

### 返す形

```
📋 状況（{基準日}）

⭐ First: <First Task の1行。無ければ「未設定」>
進行中（TODO の一覧）: N件
- <題名>（<小区分があれば 主軸 など>）
自分が関わる未完了 Task: X件（Y案件。中身は Layer のパスを渡すと見られます）
今日の WillDo: 完了 a / 未完了 b（無ければ「まだ組んでいない」）
今日の緊急: 未完了 c件（<題名>、…）（無ければ省く）
今日の日記に後から入った予定: 未完了 d件（<題名>、…）（WillDo に無いもの。無ければ省く）
待ち: W件 ／ 雑務: M件

次: <下の「次のアクション」>
```

- 進行中の私生活の節（既定は「進行中の私生活」）の行は、題名だけにする（注記の Layer やメモを出さない）。道具も既定では私生活の行の Layer のパスと ID を出さない（`ppm_files.py todo` と `owner_open_count.py` の `--show-private` は、利用者が求めたときだけ付ける）

## ストレージ操作（ファイル I/O）

| 読むもの | コマンド |
| --- | --- |
| 置き場の一覧（あるかどうかも） | `python3 .claude/skills/ppm/ppm_files.py paths --date <基準日>` |
| TODO の一覧 | `python3 .claude/skills/ppm/ppm_files.py todo`（中身まで要るときは `--json`） |
| First Task | `python3 .claude/skills/ppm/ppm_files.py first` |
| 今日の WillDo（件数つき） | `python3 .claude/skills/ppm/ppm_files.py willdo --date <基準日>` |
| 今日の緊急・後から入った予定 | `python3 .claude/skills/ppm/ppm_files.py diary --date <基準日>` の `urgent` と `scheduled`（`done` が false の行。`scheduled` は WillDo の5つの欄の `title` と比べて、同じ題名の無い行だけ。日記が無ければどちらも無い） |
| 自分が関わる未完了 Task の件数 | `python3 .claude/skills/ppm-status/owner_open_count.py`（担当の見分け方は設定 `ppm.owner_words`。既定は 本人・user・human） |
| Layer の詳細（指定時だけ） | その Layer の `intent.yaml`・`backlog.yaml` を Read |

- 置き場と見出しは、必ず上の道具（共通の部品 `ppm_files`）を通して読む。パスや見出しを決め打ちしない
- 道具が `[ERROR]` で止まったら、その文をそのまま伝える。続けて、文に「PyYAML」とあれば環境に PyYAML が無いだけなので `pip install pyyaml` を案内する（設定は直さなくてよい）。それ以外（型が違う・置き場がおかしいなど）は、文に出たキー（`ppm.` で始まる名前）の設定を直すよう案内する
- Cursor だけの配置では `.claude/` を `.cursor/` に読み替える

## 注意

- **読み取り専用。** TODO の一覧・First・WillDo・日記・Layer・Registry を変えない。WillDo の5つの欄に行を足さない
- Registry の `plc_query.py active` を、進行中の一覧の代わりに使わない（進行中の定位置は TODO の一覧）
- 題名に Task の ID・SubLayer の名前を出さない

## 次のアクション

返答の最後に、状況に合うものを選んで「次のアクション」と、コピーして送れる「次のプロンプト」を付ける（RUL_plc_session §7.4）。

| 状況 | 次の入口 |
| --- | --- |
| 今日の WillDo がまだ無い | `/ppm-plan today`（今日の分を組む） |
| 終わった仕事がある | `/ppm-update`（WillDo にチェックを付ける） |
| 新しいやることが出てきた | `/ppm-capture <やること>`（今日か明日以降かを振り分ける） |
| 1日を締める | `/ppm-close`（振り返りと明日の WillDo） |
| 1つの案件の中を続けたい | `/04-operation <Layer のパス>`、説明だけなら `/plc-brief <Layer のパス>` |
| Layer と TODO の一覧のずれを見たい | `/ppm-todo`・`/ppm-inflight`、食い違いの点検は `/ppm-audit` |
