---
name: ppm
description: ポートフォリオ層の入口。依頼の目的から、日次の入口（状況確認・翌日の計画・差し込み・完了の反映・終業・TODO の見直し）や他の PPM スキル・AI-PLC の Stage のどれを使うかを1つ選び、既存の案件の再開も判定する。「いまの状況」「明日の計画を作って」「TODO を見直して」「この案件を続けたい」で使う。
---

# ppm（ポートフォリオ層の入口）

> 層: ポートフォリオ層 ／ この入口は振り分けるだけ。保存・外の収集・承認は、選んだ先のスキルの手順で行う

- **何をするか:** 依頼の目的から下の表の行き先を1つ選び、その SKILL.md を読んで実行する。利用者にスキルの名前を選ばせない。指定された対象・日付・範囲・許可はそのまま渡す
- **考え方（日次の入口）:** 前日に翌日の予定（WillDo）を決め、当日はそのリストだけをこなす。差し込みは「今日やらないと実害が出るか」で分け、そうでなければ翌日以降に回す。進行中の案件は TODO の一覧に1件1行で置き、今日やる到達点は WillDo に書く
- **使わなくてもよい:** 日次の入口を使わなくても、AI-PLC の Stage（`/01-collection`〜`/04-operation`）の動きは変わらない
- 設定（置き場・見出しの名前・1日の容量など）と、ファイルの書式は [README.md](README.md)

## コアロジック（環境に依存しない）

### 行き先を選ぶ

| 依頼の例・目的 | 行き先 | 選んだ後 |
| --- | --- | --- |
| 「いまどうなってる？」「今日の残りは？」 | [/ppm-status](../ppm-status/SKILL.md) | TODO の一覧の進行中と今日の WillDo を見る。読むだけ |
| 「明日の計画を作って」 | [/ppm-plan](../ppm-plan/SKILL.md) | 翌日の WillDo の案を出し、本人の確認の後に保存 |
| 「差し込みを記録して」「これ今日やるべき？」 | [/ppm-capture](../ppm-capture/SKILL.md) | 今日やるか、翌日以降に回すかを分けて記録 |
| 「終わった分を反映して」 | [/ppm-update](../ppm-update/SKILL.md) | WillDo の既存の行に済みの印を付ける。本人の報告と確かめた事実を分ける |
| 「今日を締める」 | [/ppm-close](../ppm-close/SKILL.md) | 振り返り・残りの扱い・翌日の準備 |
| 「TODO を見直して」「TODO と Layer のずれを見て」 | [/ppm-todo](../ppm-todo/SKILL.md) | 差分と待ちの見直しの案 → 本人が承認した行だけ一覧に書く |
| 「Layer の候補だけ見せて」 | [/ppm-inflight](../ppm-inflight/SKILL.md) | 候補だけ。反映を頼まれたら /ppm-todo へ |
| 「これ似た案件ある？」「この依頼、どこでやる？」 | [/ppm-collection](../ppm-collection/SKILL.md) | 既存の案件を最大3件と行き先を勧める。読むだけ |
| 「外のツールから仕事を拾って」 | [/ppm-scan](../ppm-scan/SKILL.md) | 指定した範囲だけで1回集める。保存したメモは /ppm-todo に渡せる |
| 「いつかやりたい」「ストックから始めたい」 | [/ppm-someday](../ppm-someday/SKILL.md) | ストックに貯める／1件を正式に始める |
| 「状態の食い違い・閉じ忘れを点検して」 | [/ppm-audit](../ppm-audit/SKILL.md) | 点検は読むだけ。直すのは承認の後 |
| 「案件の一覧を見せて」「Registry に登録して」 | [/ppm-registry](../ppm-registry/SKILL.md) | Registry を見る・足す |
| 「複数の案件をまとめて週次で見て」 | [/ppm-pmo](../ppm-pmo/SKILL.md) | 案件をまたぐ状況・依存・資源をまとめる |
| 「この案件を新しく始める」 | [/01-collection](../ai-plc/01-collection/SKILL.md) | 先に /ppm-collection で同じ目的の既存の案件を照らす。あれば下の再開へ |
| 「この案件を続ける」「Layer を再開して」 | 下の「案件の再開」 | 同じ Layer の続き。状態から Stage と次のタスクを決める |

- 表の `/名前` は Claude Code での呼び方。コマンドのファイル（`.claude/commands/<名前>.md`）が無いもの（/ppm-inflight・/ppm-someday・/ppm-audit・/ppm-registry・/ppm-pmo）は、同じ名前のスキルとして呼ぶ。Codex は `$<名前>`
- 「状況を見る」だけの依頼では、外の収集・一覧の書き換え・案件の開始をつなげない
- 「TODO を見直して、その案件を再開」のような依頼は順に扱い、一覧の反映の承認と案件の実行の指示を混ぜない
- 解釈によって書き込みや収集の範囲が変わるときだけ目的を聞く。読むだけで確かめられる所は先に確かめる
- 振り分けの手がかりを道具で出すこともできる（`ppm_route.py`。下の「ストレージ操作」）。道具の答えは候補で、Stage の承認を代わりにしない

### TODO の一覧が無いとき

日次の入口は TODO の一覧（既定は `todo/todo.md`）を使う。無い環境では、勝手に作らず本人に聞く。

1. `python3 .claude/skills/ppm/ppm_files.py paths` で、一覧の置き場（設定で替えられる）と、使われる雛形の場所を確かめる
2. 「TODO の一覧がまだ無い。同梱の雛形（区分の節〔主軸・支援課題・進行中の私生活〕と待ちの節が入っている。例の行は全部架空）から `<置き場>` に作るか」を聞く。選択肢は「作る」「作らずに続ける」の2つ
3. 「作る」なら、雛形をそのまま置き場に写す（親のフォルダが無ければ作る）。例の行を消すかも聞き、消すと言われたら見出しと説明を残して例の行だけ消す。First Task・決まった日のタスク（Daily）の雛形も要るかを、同じ問いに添えてよい
4. 「作らずに続ける」なら、一覧が無いまま動く行き先（状況確認など）は「一覧はまだ無い」と書いて続ける

### 案件の再開

1. Layer が指定されていればそれを使う。無ければ TODO の一覧の進行中の行の `<!-- layer: … -->` の注記と目的を照らす。見つからなければ /ppm-collection で Registry と各 Layer の intent・context を照らす（読むだけ）。名前が似ているだけでまとめない。候補が複数なら本人に選んでもらう。同じ目的の続きなのに新しい Layer を作らない
2. その Layer の intent・context・backlog と、最後の Stage の報告を読む。読むだけの手がかりは `python3 .claude/skills/ppm/ppm_route.py resume --layer <Layer のパス>`（Layer の置き場として認めるのは `Flow/` と `.ai-plc/projects/` の下だけ。`Flow` 自体を別の場所へのリンクにしていてもよいが、Layer の中のファイルがリンクで Layer の外を指すものは断る）。道具が出す Stage は候補で、本人の確認待ちの Mob Checkpoint・guardrails・Backtrack を越える承認にはならない
3. 道具の判定:
   - まず intent の status を見る:
     - `completed` → 完了済み。この Layer は再開しない。続きの仕事は新しい案件にする（`ppm_route.py new`）。食い違いがありそうなら `/ppm-audit` で点検する
     - `cancelled` → 中止済み。再開するなら `/plc-lifecycle` の再開の手順（再計画と本人の再開の指示が要る）
     - `paused`・`deferred`（`paused` と同じ扱い）→ 止めている。再開してよいかを本人に確かめる。再開するなら status を `active` に戻してから、もう一度判定する
     - `blocked` → 止まって原因と再開の許可を確かめる
     - `planned` → まだ始めていない。始めてよいかを本人に確かめてから、下の判定の手順へ（Goal から見直すなら `/01-collection`）。下の判定が「止まる」なら、始める確認に替えずに止まったまま理由を示す
     - `active` → 下の判定
   - backlog が空 → standard 以上は `/02-inception`、simple は `/04-operation`（Stage 2 を省く手順は RUL_plc_adaptive §1）
   - Agent の定義が要るタスク（backlog の `construction.tasks`）に定義が無い → `/03-construction`
   - 依存が済んだ未完了のタスクがある → `/04-operation`。並びは、実行時期（`scheduled_for`）のあるタスク（今日以前）を時期の早い順に先に、その後に時期の無いタスク。同じ時期の中と時期の無いタスクの中は優先度→ID の順で、先頭のタスクを選ぶ。実行時期（`scheduled_for`）が今日より後のタスクと、運用タスク（`recurrence` のあるタスク）は候補にしない（`/04-operation` の Phase 2 と同じ選び方）
   - blocked・deferred・依存が済んでいない・実行時期が来ていない・子の Layer が終わっていない → 止まって理由を示す。運用タスクは回すときだけ `/04-operation` で Task を指定する
   - backlog の通常のタスクが全部済み（運用タスクは数えない）→ `/ppm-audit` で点検して、次にしたいことを本人に確かめる。勝手に Re-Collection や完了の宣言をしない
4. `pipeline_variant: jev` の Layer も本体版として進める（書き換えない）。分類や `jev_monitor` を勝手に変えない。道具が「データがおかしい」と言ったら、元のファイルを確かめて直す案を示す
5. 利用者が実行を頼んでいれば、選んだ Stage の SKILL.md を読み、Layer と Task を渡して進める。「次は何？」と聞かれただけなら、開始の一文を示すまで。Stage 自身の承認の手順は省かない。`/goal` で自動完走（RUL_plc_session §10）が明示されているときだけ、その範囲で続けて進める

## ストレージ操作（ローカル実装）

- 置き場の役割: TODO の一覧は本人の案件の一覧（1件1行）、`backlog.yaml` は選んだ案件のタスクの正本、WillDo はその日の行動。WillDo に Layer のタスクを全部写さない
- AIPM を選んだ案件の論点・ToDo は、その案件の箱の一覧が正本。TODO の一覧には案件1行だけを置き、論点・ToDo は写さない。会議で出たやることは、AIPM を選んだ案件なら `/pm-suggest` で候補を拾って `/pm-todo`・`/pm-issue` で箱に入れ、それ以外は `/ppm-capture` に回す
- 日次の作業と Layer の完了をつなぐときは、先に AI-PLC の検証と Propagation（`/04-operation` の Phase 5.5〜7）を通し、日次の画面への反映は `/ppm-update` で行う。案件の完了から、本人の日々の行動や満足度の完了を推し量らない
- この入口と `ppm_route.py` は、保存・外の収集・同期をしない。一覧の反映は /ppm-todo の承認の手順、外の範囲は /ppm-scan の決まり、送信・git の操作は個別の依頼に従う

```bash
python3 .claude/skills/ppm/ppm_route.py <行き先>                 # status・plan・capture・update・close・todo・inflight・collection・scan・someday・audit・registry・pmo
python3 .claude/skills/ppm/ppm_route.py new --goal "<Goal>"      # 新しい案件（先に同じ目的の案件を探す印つき）
python3 .claude/skills/ppm/ppm_route.py resume --layer <Layer>   # 既存の Layer の続きを判定（--today YYYY-MM-DD で今日を替えられる）
python3 .claude/skills/ppm/ppm_files.py paths                    # 置き場と雛形の場所（読むだけ）
```

- 出力は JSON（`skill_path`・`prompt`・`advisory_only` など）。`prompt` は読ませる一文で、シェルで実行しない
- エラーは `{"error": …}` と終了コード 2（知らない行き先・知らないオプション・`--today` の形の誤りも同じ）
- Claude Code は `/ppm <依頼>`、Codex は `$ppm <依頼>` でこの入口を使う
