---
name: ppm-update
description: ポートフォリオ層の日次の画面（その日の WillDo）を、終わった仕事に合わせて更新する。WillDo に載っている行と、今日の日記の「緊急」の行が終わっていれば `- [x]` にし、どちらにも載っていないが今日終わった仕事は振り返りの「DONE（WillDo外）」に書く。今日のリスト（5つの欄）に行は足さない。「〇〇終わった」「WillDo を更新して」「チェックを付けて」で使う。
---

# ppm-update（日次の画面の更新）

> 層: ポートフォリオ層 ／ 書くのはその日の WillDo、その日の日記の緊急の行の完了の印、First Task の印だけ。関連: `/ppm-plan`・`/ppm-capture`・`/ppm-close`・`/ppm-status`

- **何をするか:** 終わった仕事を、利用者が見る画面（その日の WillDo）に反映する。会話で「終わった」と聞いただけで済ませず、ファイルを保存する
- **考え方:**
  - 仕事の状態の正は、各 Layer の intent・backlog と利用者の言葉。WillDo はそれを映す画面
  - WillDo の5つの欄（First Task・差し込み・繰り越し・TODOから・Daily Task）は、前日に決めた閉じたリスト。当日は増やさない。終わったものはチェックを付け、載っていなかった仕事は振り返りの「DONE（WillDo外）」に残す
  - 新しいやることを足したくなったら、このスキルではなく `/ppm-capture`

## コアロジック（環境に依存しない）

### 手順

1. `date +%Y-%m-%d` を単独で実行して対象日を決める（引数に日付があればその日）
2. 対象日の WillDo（既定は `Flow/YYYYMM/YYYY-MM-DD/will_do.md`。置き場は設定 `.ai-plc/config.yaml` の `ppm:` で替えられる）を読む。**無ければ作らず**「この日の WillDo がまだありません。先に /ppm-plan」と伝えて止まる
3. 終わった仕事を集める（読めるものだけ。どれも読むだけ）
   - 利用者が「終わった」と言った仕事
   - WillDo に既に付いている `- [x]`
   - TODO の一覧（既定は `todo/todo.md`）の進行中の行の Layer の注記をたどり、`intent.yaml` の status が completed で `completed_at` が対象日のもの、`backlog.yaml` の Task で status が completed かつ `completed_at` が対象日のもの
     - `completed_at` は全部の Task に書かれるわけではない（`/04-operation` が書くのは、実行時期 `scheduled_for` のある Task などに限られる）。日付の無い完了はここでは拾えないので、利用者の言葉で足す。拾えたものだけで「今日の完了は全部」と言わない
4. 下の「当て方」で、WillDo の5つの欄の未完了の行と、対象日の日記（既定は `Flow/YYYYMM/YYYY-MM-DD/task_diary.md`）の「緊急」の未完了の行に当て、当たった行を `- [ ]` → `- [x]` にする（行の文は変えない）
5. どの行にも当たらない今日の完了は、振り返りの `### DONE（WillDo外）` の下に `- <題名>` の形で1行ずつ足す（既にある題名は足さない）。5つの欄には足さない
6. First Task のファイル（既定は `todo/first_task.md`）の「⭐ 現在のFirst Task」の行と同じ仕事を完了にしたなら、そのファイルの行も `- [x]` にする（任意。WillDo と食い違わないようにする）
7. **ファイルを保存する**（このターンのうちに）。チャットに書くだけで終えない
8. 何に印を付け、WillDo外に何を足したかを報告する

### 当て方

1. 題名が同じ（行の末尾の見積 `:30`、「（理由: …）」、終業の扱いの印 `→ 繰り越し` などは比べない。道具の `title` はこれらを外してある）
2. 案件の通称が同じで、その日の未完了の行がその案件に1行しかない（例: 「見積もりツール」→「見積もりツールの計算の部分を1つ通す」）
3. 利用者が行を指した

- 2つ以上の行に当たりそうで決められないときは、どの行かを利用者に1問だけ聞く
- Daily Task は、利用者が言ったときだけ完了にする（推測で付けない）
- 既に終わっている仕事が First Task に残っていた（Layer で completed）ときは、その行を `- [x]` にするだけ。題名の書き換えや新しい行の追加はしない

### 返す形

```
📝 WillDo を更新しました: <WillDo のパス>
  [x] にした: N件（<題名>、…）
  緊急の行を [x] にした: K件（<題名>、…）（無ければ省く）
  DONE（WillDo外）に足した: M件（<題名>、…）
  （First Task のファイルも [x] にした場合は1行）
```

## ストレージ操作（ファイル I/O）

| 用途 | 読み方・書き方 |
| --- | --- |
| 対象日の WillDo の場所 | `python3 .claude/skills/ppm/ppm_files.py paths --date <対象日>` の `will_do` |
| WillDo の今の行（行番号つき） | `python3 .claude/skills/ppm/ppm_files.py willdo --date <対象日>`（各行の `line` が行番号） |
| TODO の一覧の Layer の注記 | `python3 .claude/skills/ppm/ppm_files.py todo --json` の `inflight[].layer` |
| First Task | `python3 .claude/skills/ppm/ppm_files.py first`（`path` と、行の `line`） |
| 今日の日記の緊急 | `python3 .claude/skills/ppm/ppm_files.py diary --date <対象日>` の `urgent`（`path` と各行の `line`。日記が無ければ緊急は無い） |
| 書く: 完了の印 | WillDo のその行（`line`）、または日記の緊急のその行（`line`）の `- [ ]` を `- [x]` に Edit する。行のほかの文字は変えない |
| 書く: WillDo外 | 振り返り（`## 📈 振り返り`）の `### DONE（WillDo外）` の見出しの下に `- <題名>` を Edit で足す。見出しが無ければ `### DONE` の節の後（`### LEARN` の前）に `### DONE（WillDo外）` を足してから書く |
| 書く: First Task の印（任意） | First Task のファイルのその行の `- [ ]` を `- [x]` に Edit する |

- 置き場と見出しは、必ず共通の部品 `ppm_files` を通して読む。パスや見出しを決め打ちしない
- 書くときは Edit で、決めた行だけを変える。ファイル全体を書き直さない
- 外部のサービス（タスク管理・チャット・メール・予定表）には書かない
- Cursor だけの配置では `.claude/` を `.cursor/` に読み替える

## 注意

- WillDo の5つの欄に行を足さない（足したいものは `/ppm-capture`）。日記の緊急にも行を足さない（印を付けるだけ）
- Layer の intent・backlog・Registry は読むだけ。WillDo に付けた印を Layer へ書き戻さない（Layer の完了は `/04-operation` の手順で行う）
- チェックの状況をチャットに書くだけでファイルを触らないのは失敗

## 次のアクション

返答の最後に「次のアクション」と、コピーして送れる「次のプロンプト」を付ける（RUL_plc_session §7.4）。

| 状況 | 次の入口 |
| --- | --- |
| 続けて今日のリストを進める | `/ppm-status today`（残りを見る） |
| 新しいやることが出てきた | `/ppm-capture <やること>` |
| 1日を締める | `/ppm-close` |
| WillDo が無かった | `/ppm-plan today` |
