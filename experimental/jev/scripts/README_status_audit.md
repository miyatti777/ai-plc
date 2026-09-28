# AI-PLC ステータス監査（`aiplc_status_audit.py`）— 使い方

AI-PLC のステータスは、次の置き場所に分かれて記録されています。このツールはその食い違いを読み取り専用で洗い出し、**人が承認した行だけ**を反映します。

- **Layer ファイル:** `intent.yaml` の `status`、`backlog.yaml` の各タスクの status
- **Registry:** `.claude/db/ai_plc.db` の projects / tasks
- **todo.md** と **native memory:** 任意の参考入力（あれば読むだけ。無ければ読まない）
- **Registry の tasks.status の語彙:** 公開の `init_db.py` で作った DB は英語（`planned` / `active` / `completed` / `paused`）、日本語の語彙（`未着手` / `進行中` / `完了`）で作った DB もあります。tasks テーブルの `status` 列の `CHECK(status IN (...))` から自動で判定し、提案する値もその語彙に合わせます（判定できないときは日本語）。DB が英語か判定できないときに限り、Layer の intent.yaml の `sync_targets`（`type: sqlite`）に `status_map` があれば、それに従います

> 🧪 実験版パッケージ（experimental/jev）の一部です。`--with-jev` で入れたとき `.claude/ai-plc-jev/scripts/` に入り、`/04-operation-jev` の Phase 7「ステータス点検」から呼ばれます。

- **自動では何も閉じません。** 出すのは「候補」と「変更の提案」だけです。完了にするかどうかは人が決めます
- 既定の動きは読み取り専用です。書き込むのは `--apply <承認ファイル> --yes` を付けたときだけです
- `todo/todo.md` と native memory は書きません（todo.md の該当行は手で直してください）

必要なもの: Python 3.9 以上と `pyyaml`。`--jev` を使うときだけ、Jev の API キーが要ります（`.claude/ai-plc-jev/scripts/README_jev.md`）。

---

## 1. コマンド

リポジトリのルートで実行します。

| やりたいこと | コマンド | 書き込み |
| --- | --- | --- |
| 監査する（レポートを出す） | `python3 .claude/ai-plc-jev/scripts/aiplc_status_audit.py --quiet` | レポートだけ |
| 件数だけ短く見る（週1回ほど回すと便利） | `python3 .claude/ai-plc-jev/scripts/aiplc_status_audit.py --brief` | なし |
| 閉じる Layer 自身の食い違いだけ見る（`/04-operation-jev` Phase 7） | `python3 .claude/ai-plc-jev/scripts/aiplc_status_audit.py --brief --layer <Layerのパス>` | なし |
| 監査と承認ファイルの雛形をまとめて出す | `python3 .claude/ai-plc-jev/scripts/aiplc_status_audit.py --quiet --approval-template` | レポートと雛形 |
| 停滞 Layer に Jev の分類ヒントを付ける | `python3 .claude/ai-plc-jev/scripts/aiplc_status_audit.py --quiet --jev` | レポートと Jev の判断ログ `.claude/db/jev_decisions.jsonl`（外部送信あり。§5） |
| 反映の予定を確認する（dry-run） | `python3 .claude/ai-plc-jev/scripts/aiplc_status_audit.py --apply <承認ファイル>` | なし |
| 反映する | `python3 .claude/ai-plc-jev/scripts/aiplc_status_audit.py --apply <承認ファイル> --yes` | intent / backlog / Registry と、実行ログ |
| 一度反映した後に人が戻した値を、意図してもう一度反映する | 上のコマンドに `--allow-reapply` を足す | 同上 |

主なオプション:

| オプション | 意味 | 既定 |
| --- | --- | --- |
| `--quiet` | レポート本文を画面に出さない（書いた場所だけ出す） | 画面にも出す |
| `--stale-days N` | 停滞とみなす日数 | 30 |
| `--today YYYY-MM-DD` | 基準日（経過日数の計算とレポートの日付フォルダに使う） | 今日 |
| `--out DIR` | レポートの出力先を指定する（`DIR` にそのまま書く。同じ `DIR` を指定すると上書き） | 下の「置き場所」 |
| `--approval-template [PATH]` | 承認ファイルの雛形も出す | `<state-dir>/approvals/approval_template_YYYY-MM-DD.json` |
| `--state-dir DIR` | レポート・承認ファイル・実行ログの置き場所 | 環境変数 `AIPLC_STATUS_HYGIENE_DIR`、なければ `.claude/db/status_hygiene/` |
| `--db PATH` | 見る（書く）DB | 環境変数 `AIPLC_DB`、なければ `.claude/db/ai_plc.db` |
| `--scope SCOPE_ID` | 候補をその scope_id の行だけに絞る（複数回指定できる。`C-` のハッシュ ID でもよい）。レポート・雛形・参考欄も絞られる | 絞らない |
| `--layer PATH` | `PATH/intent.yaml` の scope_id を読んで `--scope` と同じに扱う（複数回指定できる。リポジトリからの相対パスか絶対パス） | 絞らない |
| `--brief` | 短い要約だけを画面に出す。ファイルは何も書かない（§1.1） | 出さない |

- `--apply` は `--jev` / `--approval-template` / `--brief` / `--scope` / `--layer` と同時に使えません（終了コード 2）
- `--brief` は `--jev` / `--approval-template` / `--out` と同時に使えません（終了コード 2）
- Registry にも Layer にも無い scope を `--scope` に渡すと終了コード 2（打ち間違いで「食い違いなし」にならないように。表示はハッシュ ID）。`--layer` の先に intent.yaml が無い・scope_id が無いときも 2
- `--yes` は `--apply` と一緒のときだけ使えます

### 1.1 短い要約（`--brief`）

- **読み取り専用です。** レポートも雛形も書かず、Jev も呼びません（外部送信なし）。作者の環境の実データで 1 秒未満（0.3〜0.4 秒）
- `--scope` / `--layer` と一緒に使うと、1候補1行で出します。候補が無ければ「ステータス点検: 食い違いなし」の1行だけです

```
C-1a2b3c4d:all_tasks_done_unclosed: 全タスク完了なのに未クローズ — intent を completed に（→Registry） — 反映するなら --approval-template → --apply
L-0000-2:stale: N日以上更新なし（停滞） — 停滞の中身を確認 — --apply の対象外（人が判断）
ステータス点検: 候補 2 件（2 scope）— うち --apply で反映できる 1 件・人が判断 1 件。詳細は --brief を外して実行
```

- 行の形は「candidate_id（機密は `C-` + ハッシュ）: 分類 — 推奨アクション — 反映のしかた」です。承認ファイルで反映できない行（停滞・フォルダ不明・行の追加が要るもの・食い違う写しがあるもの）は、最後が「--apply の対象外（人が判断）」になります
- `--scope` なしだと、分類ごとの件数の表と件数の1行だけを出します（行の詳細は出しません）。週1回の棚卸しの入口に使えます
- 反映するときは、`--brief` を外して同じ `--scope` / `--layer` を付け、`--quiet --approval-template` で雛形を出してから §3 の手順で `--apply` します

**Phase 7（`/04-operation-jev`）での使い方の例:** 完了する Layer を閉じた後に `python3 .claude/ai-plc-jev/scripts/aiplc_status_audit.py --brief --layer <Layerのパス>` を流し、終了コード 0 なら食い違いなし、10 なら出た行を確認します。`--layer` / `--scope` は scope_id の完全一致で絞るので、子の SubLayer（例 `L-XXXX-SG1`）の行は出ません。子も見るときは `--layer` を子の数だけ重ねて指定します。

---

## 2. 出力と置き場所（git 管理外にする）

既定の置き場所は `.claude/db/status_hygiene/` です。**installer は `.gitignore` に触らないので、`.claude/db/status_hygiene/` を自分で `.gitignore` に足してください**（出力には Layer 名・パス・承認ファイル・実行ログが入ります。**コミットしない**。足す行の一覧は `.claude/ai-plc-jev/scripts/README_jev.md` の「.gitignore に足す行」）。`--state-dir` や環境変数で別の場所にしたときは、リポジトリの外か、git 管理外の場所を選んでください。

```
.claude/db/status_hygiene/
├── reports/YYYY-MM-DD/HHMMSS/   # 実行ごとに新しいフォルダ。report.md と report.json
├── approvals/                   # 承認ファイルの雛形と、人が編集した承認ファイル
└── apply_log.jsonl              # --yes で反映したときだけ1変更1行で追記
```

- **レポートは実行ごとに別のフォルダに書きます**（`reports/<日付>/<時分秒>/`。同じ秒に2回動かすと `-2`, `-3` を付ける）。前の実行のレポートは上書きしません。`--out` を指定したときだけ、その場所に直接書きます
  - 注: 以前の版は `reports/<日付>/` に直接書いていました。その頃のファイルが日付フォルダ直下に残っていることがあります
- `report.md`: 人が読むレポート。冒頭に件数の要約、続いて分類ごとの表
- `report.json`: 同じ内容の機械向けデータ（`counts`・`candidates`・`info`・`jev_summary`）
- 承認ファイルの雛形は、同じ日に作り直すと**同じ名前で上書き**されます。編集するときは、先にコピーして別名にしてください（例: `approval_batch1_2026-09-28.json`）

### 分類（`kind`）

| # | kind | 意味 | 変更の提案 |
| --- | --- | --- | --- |
| 1 | `intent_done_registry_open` | Layer は完了なのに Registry が未完了 | Registry を完了に |
| 2 | `all_tasks_done_unclosed` | 全タスクが終わっているのに未クローズ | intent を完了に（→ Registry）。未完了の子 Layer がある行は雛形に `"warning": "未完了の子Layerあり"` が付く。フォルダの写しの中身が食い違う行は対象外 |
| 3 | `completed_project_open_tasks` | 完了した PJ に未完了のタスク行がある | Registry のタスク行を完了に |
| 4 | `folder_missing` | Registry の行に対応する Layer フォルダが見つからない | なし（人が判断） |
| 5 | `stale` | 最終更新から N 日（既定30日）以上たっている | なし（判断材料だけ） |
| 6 | `registry_closed_layer_open` | Registry は完了なのに intent が未完了 | intent を完了に。タスクが残っている行は「Layer を閉じる／Registry を戻す」から選ぶ |
| 7 | `task_status_mismatch` | タスクの status が backlog と Registry で違う | Registry を backlog に合わせる |
| 8 | `registry_task_missing` | backlog にあるタスクが Registry に無い | 対象外（行の追加が要る。§8） |
| 9 | `registry_missing` | Layer はあるのに Registry に PJ の行が無い | 対象外（行の追加が要る。§8） |

- Layer を探すときは、`Documents/`・隠しフォルダ（`.worktrees/` など）・`node_modules` などの依存フォルダの中は見ません（そこにある intent.yaml は Layer として扱わない）
- 停滞の「最終更新日」は、`backlog.yaml` の更新時刻と、タスクの `completed_at` の最大値のうち新しい方です（`backlog.yaml` が無い Layer は `intent.yaml` の更新時刻）。同じ scope のフォルダが複数あるときは、全フォルダのうち新しい方を採ります。Registry の `updated_at` は使いません（作業が続いていても更新されないため）
- 14 日以上・停滞の日数未満（既定では 14〜29 日）のものは停滞にせず、参考欄の `watch` に出します
- 参考欄（候補ではない）には、todo.md が完了済みの Layer を指している行（`todo_points_to_done`）なども出ます。todo.md の行は手で直してください

---

## 3. 承認ファイルの書き方

1. 雛形を作る: `python3 .claude/ai-plc-jev/scripts/aiplc_status_audit.py --quiet --approval-template`
2. 雛形を `approvals/` の中にコピーし、別名にする
3. 反映したい行だけ `"decision": "undecided"` を `"approve"` に変える。選択肢がある行（`alternatives_available` がある行）は `"alternative"` に選んだ名前を書く

```json
{
  "version": 1, "kind": "aiplc_status_audit.approval", "report_date": "2026-09-28",
  "approvals": [
    {"candidate_id": "L-0000-1:intent_done_registry_open", "decision": "approve", "alternative": null,
     "from": [{"target": "registry.projects", "field": "status", "from": "active", "to": "completed"}]},
    {"candidate_id": "C-1a2b3c4d:registry_closed_layer_open", "decision": "approve", "alternative": "registry_reopen",
     "alternatives_available": ["layer_close", "registry_reopen"], "from": {"layer_close": ["…雛形のまま…"], "registry_reopen": ["…雛形のまま…"]}},
    {"candidate_id": "L-0000-2:all_tasks_done_unclosed", "decision": "undecided", "alternative": null, "from": ["…雛形のまま…"]}
  ],
  "out_of_scope": [],
  "no_changes_rows": 32
}
```

（`from` の中身は雛形に入っているものをそのまま残します。上の例の `"…雛形のまま…"` は省略の印で、実際のファイルには書きません。`from` を空にすると `invalid` になります）

- **`undecided` のままの行は反映されません。** 雛形をそのまま `--yes` しても何も書かれません。要らない行は消してもかまいません
- `from` はレポートを作った時点の値です。反映の直前に読んだ値が `from` と違えば、その候補は何も書かずに `conflict` になります。すでに `to` になっていれば `noop` です
- `out_of_scope`（分類8・9 など）は承認しても反映されません
- 候補が再走査で出なくなった行は `not_current` になります。レポートを取り直して承認し直してください

反映の流れ:

```
python3 .claude/ai-plc-jev/scripts/aiplc_status_audit.py --apply .claude/db/status_hygiene/approvals/<承認ファイル>.json        # dry-run（予定だけ）
python3 .claude/ai-plc-jev/scripts/aiplc_status_audit.py --apply .claude/db/status_hygiene/approvals/<承認ファイル>.json --yes  # 反映
python3 .claude/ai-plc-jev/scripts/aiplc_status_audit.py --apply .claude/db/status_hygiene/approvals/<承認ファイル>.json        # もう一度流して全行 noop なら完了
```

- 書く順番は、1つの候補の中で ①`intent.yaml` の `status` → ②`backlog.yaml` の `summary.status`（キーがあるときだけ）→ ③Registry です
- intent / backlog は `status:` の1行だけを書き換えます（コメントや並びは保ちます）
- Registry への書き込みは `plc_query.py` を通ります
- 件数が多いときは、分類ごとに数回に分けて承認・反映すると確認しやすくなります

---

## 4. 機密の表示

- 機密と判定した行は、レポート・雛形・反映の出力・実行ログで、scope_id を `C-` + ハッシュ8桁（例 `C-1a2b3c4d`）で表示します。Layer のパスは `（機密）` や「（機密のため非表示）」になります
- 承認ファイルにはハッシュ ID のまま書けます（元の scope_id で書いても受け付けますが、出力には元の ID を出しません）
- **これは秘匿化ではありません。** ハッシュは scope_id から計算しただけのものです。scope_id は推測しやすい形式なので、Registry を持っている人なら逆引きできます。画面共有やログに平文で出さないための表示です。レポートを外部に渡すときは、別途中身を確認してください
- 機密かどうかは、`jev_client.redact()` の語リスト（コード側の汎用語＋ローカルの `.claude/db/jev_redact_extra.txt` など。`.claude/ai-plc-jev/scripts/README_jev.md`）・親 Layer からの継承・intent の宣言（`extensions: [privacy]` / `jev_monitor: false`）で判定します。迷うものは機密の側に倒します（一般の語が機密語に一致して、機密でない Layer が機密扱いになることがあります）

---

## 5. Jev の分類ヒント（`--jev`、任意）

- 停滞（分類5）の行のうち、**機密でなく、intent に `jev_monitor: true` がある Layer だけ**を Jev に1問ずつ送ります。答えは `done`（実質完了）/ `handed_off`（他の Layer に引き継ぎ済み）/ `stalled`（本当に停滞）/ `unknown`（判断できない）のどれかです
- 送るのは、ゴール1行・最後に完了したタスクの名前と結果・進捗・停滞日数だけです。送る直前にもう一度 `redact()` で検査します
- **ヒントだけです。** `done` と出ても閉じません。変更の提案は変わりません
- `--jev` なしでは何も外部に送りません。API キーが無い・通信に失敗したときは「スキップ」と表示して、レポートは最後まで出ます
- ヒントが妥当だったかを記録し、あとで集計できます

```
python3 .claude/ai-plc-jev/scripts/jev_bt_monitor.py --override <decision_id> accept    # 妥当だった（外れなら reject）
python3 .claude/ai-plc-jev/scripts/jev_bt_monitor.py --noise-report --use-case status_audit
```

- 集計の「ヒント」は、停滞とされた Layer に Jev が `done` / `handed_off` と答えたもの（＝コードの判定を疑う答え）です。`stalled` / `unknown` はヒントに数えません

---

## 6. 止め方・戻し方

**止め方**
- `--yes` を付けなければ何も書きません。まず dry-run で予定を確かめてください
- 反映は1変更ずつ確定します。途中で止めた（Ctrl-C など）場合は、止めるまでに書いた分だけが残ります。もう一度 dry-run を流して、現在の状態を確かめてください（書けた分は `noop`、途中で分類が変わった候補は `not_current`）
- 定期運用をやめるときは、呼び出している手順からこのコマンドを外すだけです。常駐するものはありません

**反映の前にバックアップを取る（推奨）**

DB は WAL モードのため、ファイルのコピーではなく SQLite のバックアップ機能を使います。

```
python3 -c "import sqlite3; s=sqlite3.connect('.claude/db/ai_plc.db'); d=sqlite3.connect('.claude/db/status_hygiene/backup_before_apply.db'); s.backup(d); d.close(); s.close()"
```

（保存先の名前は日時などを付けて毎回変えてください）

**戻し方**
- 何を書いたかは `apply_log.jsonl` の各行（`before` → `after`、結果）で分かります
- Registry を丸ごと戻す: 他のセッションが DB を使っていないことを確かめてから、バックアップを元の場所に戻します。**バックアップの後に他の作業で入った変更も消える**ので、1件だけ戻すときは次のほうが安全です
- Registry を1件だけ戻す: 値は必ず `apply_log.jsonl` のその行の `before` を使います
  - PJ 行: `python3 .claude/db/plc_query.py sql "UPDATE projects SET status='<before の値>' WHERE scope_id='<scope_id>'"`
  - タスク行: `python3 .claude/db/plc_query.py sql "UPDATE tasks SET status='<before の値>' WHERE scope_id='<scope_id>' AND task_id='<task_id>'"`
  - **タスク行は必ず scope_id と task_id の両方で絞ってください。** task_id（T001 など）は PJ をまたいで重複するため、task_id だけで絞るとほかの PJ の行まで書き換わります
  - タスクを「完了」にした反映では、`completed_at` が空だった行に日付も入れています（元から入っていた行は変えません）。この書き込み前の値はログに残りません。反映前に空だったと確かめられる場合だけ `completed_at=NULL` も戻し、分からなければバックアップと突き合わせてください
- intent / backlog を戻す: ログの `before` の値に `status:` の行を手で戻します
- 戻した後に同じ承認ファイルを流しても、ログに反映済みの記録があるため `conflict` になり、書きません（意図してもう一度反映するときだけ `--allow-reapply`）

---

## 7. 終了コード

| コード | 意味 |
| --- | --- |
| 0 | 問題なし（監査の完了、または反映・dry-run で書けなかった行がない） |
| 1 | 反映中の書き込み失敗がある（`failed` / `partial`。ログを確認） |
| 2 | 引数・承認ファイルの形式エラー、DB が見つからない、出力先が Layer フォルダ |
| 3 | 書かなかった行がある（`conflict` / `invalid` / `not_current` / `not_found`） |
| 10 | **`--brief` のときだけ:** 候補がある（候補が無ければ 0）。Phase 7 や定期実行で機械判定するため。`--brief` なしの監査は候補があっても 0 のまま |

---

## 8. 後続の扱い（このツールでは反映しないもの）

| 分類 | どうするか |
| --- | --- |
| 8 Registry にタスク行が無い | `python3 .claude/db/plc_query.py add-task <task_id> <scope_id> "<タスク名>" [type] [priority]` で1行ずつ追加し、status など残りの列は `plc_query.py sql` の UPDATE で入れる。**本番 DB への書き込みなので、人の承認とバックアップの後に行う**。行の追加は `add-project` / `add-task` を使う（列の整合のため） |
| 9 Registry に PJ 行が無い | `python3 .claude/db/plc_query.py add-project <scope_id> "<名前>" "<ゴール>"` で追加する（分類8のタスク行より先に）。同じく承認とバックアップの後 |
| 4 Layer フォルダが見つからない | Notion 等の外部 DB と同期している場合はそちらと突き合わせて、実体がどこにあるか、Registry を閉じるか残すかを人が決める。決めた結果は `plc_query.py` で反映する |
| 5 停滞 | 人が判断する（続ける／閉じる／他の Layer に引き継いだ）。閉じると決めたら、Layer 側を完了にしてから次の監査で分類1として反映する。Jev のヒントは材料の1つで、判断の後に `--override` で妥当／外れを記録する |
| 重複フォルダで中身が食い違う行 | どちらが正しいかを人が決めて、写しを整理してから監査をやり直す |

- 反映した後の Registry → Notion の同期（`ai-plc-db-sync`）は、このツールでは行いません。必要なら別に実行してください
- todo.md に完了済みの Layer が残っているときは、該当行を手で直してください（このツールは todo.md を書きません）
