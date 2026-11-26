# 日次の入口の土台（ppm）

ポートフォリオ層の日次の入口（`/ppm`・`/ppm-plan`・`/ppm-status`・`/ppm-todo`・`/ppm-inflight`・`/ppm-capture`・`/ppm-update`・`/ppm-close`）が共通で使う、設定を読む部品と雛形です。
使わなくても AI-PLC の Stage の動きは変わりません。

考え方は「前日に翌日の予定を決め、当日はそのリスト（閉じたリスト）だけをこなす。差し込みは基本、翌日に回す」です。

| ファイル | 役割 |
| --- | --- |
| `ppm_files.py` | 設定（`.ai-plc/config.yaml` の `ppm:`）を読み、TODO の一覧・First・Daily・WillDo・日記を読む。読むだけで、ファイルは書かない |
| `templates/todo_template.md` | 進行中の案件の一覧（1件1行） |
| `templates/first_task_template.md` | その日の最重要の1件 |
| `templates/daily_task_template.md` | 決まった日に繰り返すタスク |
| `templates/will_do_template.md` | その日にやるリスト（前夜に作る） |
| `templates/task_diary_template.md` | 差し込みの受け皿（日ごと） |

## 雛形の使い方

設定を書かない場合の置き場（リポジトリのルートから）:

| 雛形 | コピー先 |
| --- | --- |
| `todo_template.md` | `todo/todo.md` |
| `first_task_template.md` | `todo/first_task.md` |
| `daily_task_template.md` | `todo/daily_task.md` |
| `will_do_template.md` | `Flow/YYYYMM/YYYY-MM-DD/will_do.md`（ふつうは `/ppm-plan` が作る） |
| `task_diary_template.md` | `Flow/YYYYMM/YYYY-MM-DD/task_diary.md`（ふつうは `/ppm-capture` が作る） |

- TODO・First・Daily の例は全部架空です。コピーしたら例の行を消してください
- WillDo と日記の雛形の `{{YYYY-MM-DD}}` は、作るときにその日の日付に置き換わります
- 雛形を自分用に直したいときは、`todo/templates/<名前>_template.md` に置くと、同梱の雛形より先に使われます（WillDo と日記は `ppm.will_do.template`・`ppm.task_diary.template` で場所を指定することもできます）
- 雛形は読むだけなので、雛形の場所（`templates_dir`・`will_do.template`・`task_diary.template`）はリポジトリの外を指してもかまいません（`~` も展開します。複数のリポジトリで雛形を共有するため）

## 設定（`.ai-plc/config.yaml` の `ppm:`）

どのキーも、書かなければ既定値で動きます。型が違う値（一覧のはずの所に文字列など）はエラーで止まります。知らないキーは警告を出して無視します。

スキルが書き込むパス（`todo.path`・`first_task.path`・`daily_task.path`・`day_dir`）は、リポジトリのルートからの相対パスだけです。絶対パス・`~` で始まるもの・ルートの外に出るもの（`../todo.md` など）はエラーで止まります（`lists/../todo/todo.md` のように途中に `..` があっても、中に収まれば通ります）。`.git`・`.claude`・`.ai-plc` のフォルダの中を指すもの（例: `.claude/todo.md`）も止まります。判定は字面で行い、シンボリックリンクはたどりません。`will_do.file`・`task_diary.file` はファイル名だけです（`/` を含められません）。

| キー | 既定値 | 意味 |
| --- | --- | --- |
| `todo.path` | `todo/todo.md` | TODO の一覧 |
| `todo.inflight_sections` | `[進行中の仕事, 進行中の私生活]` | 進行中として読む節（`##`）。1つ以上 |
| `todo.work_subgroups` | `[主軸, 支援課題]` | 仕事の小区分（`###`）。空でもよい（区分なし） |
| `todo.private_sections` | `[進行中の私生活]` | 私生活として扱う節。空でもよい |
| `todo.waiting_section` | `待ち／要確認` | 待ちの節。`null` で使わない |
| `todo.misc_section` | `いつでもいい雑務` | 期限の無い小さなタスクの節。`null` で使わない |
| `todo.end_marker` | `未再計画` | この語で始まる `##` の見出しより後は進行中として読まない。`null` で使わない |
| `first_task.path` | `todo/first_task.md` | First のファイル |
| `first_task.heading` | `⭐ 現在のFirst Task` | First を読む見出し |
| `daily_task.path` | `todo/daily_task.md` | Daily のファイル |
| `day_dir` | `Flow/{YYYYMM}/{YYYY-MM-DD}` | 日のフォルダ。`{YYYYMM}`・`{YYYY-MM-DD}`・`{YYYY}`・`{MM}`・`{DD}` が使える |
| `templates_dir` | `todo/templates` | 自分用の雛形を探すフォルダ（無ければ同梱の雛形） |
| `will_do.file` / `will_do.template` | `will_do.md` / `null` | WillDo のファイル名と雛形の場所 |
| `task_diary.file` / `task_diary.template` | `task_diary.md` / `null` | 日記のファイル名と雛形の場所 |
| `plan.capacity_hours` | `6` | 1日に入れる見積の合計（時間） |
| `plan.max_items` | `10` | WillDo の上限（Daily を除く） |
| `plan.overflow_rule` | `tomorrow_diary` | 溢れた分を翌日の日記へ送る（今はこの値だけ） |
| `plan.lookback_days` | `14` | 翌日の WillDo を組むとき、前の WillDo と日記をさかのぼって探す日数 |
| `capture.urgent_criteria` | `今日やらないと実害（他者ブロック・締切超過・信頼毀損）が出るか` | 差し込みを今日に入れる基準 |
| `owner_words` | `[本人, user, human]` | 自分が担当のタスクを見分ける語 |
| `sources.calendar` | `auto` | 予定を読む（`auto`＝接続があれば読む／`off`） |
| `sources.mail` | `off` | メールを読む（既定は読まない） |
| `inflight.recent_days` | `21` | 進行中の候補を洗い出すときに見る日数 |

例（見出しを英語にして、待ちの節を使わない）:

```yaml
ppm:
  todo:
    path: lists/todo.md
    inflight_sections: [Doing, Home]
    work_subgroups: []
    private_sections: [Home]
    waiting_section: null
  sources:
    calendar: off
```

`python3 .claude/skills/ppm/ppm_files.py config` で、既定値で埋めた後の設定を確かめられます。

## 道具が読む形

### TODO の一覧

- 節は `## 名前`、小区分は `### 名前`。名前は設定の名前と同じか、名前の後に「（…）」などが続く見出しに当たります（例: `## 未再計画（旧案件）`）
- 案件の行は、行の頭から `- [ ] 題名`（終わったら `- [x]`）
- 案件の行のすぐ下に字下げした行は、その案件に付きます
  - `<!-- layer: <Layer のパス> scope: <Scope ID> -->`（scope は省けます）
  - `<!-- source: <出どころのパス> candidate: <候補の名前> -->`
  - `YYYY-MM-DD: …` で始まる行は日付つきのメモ、それ以外の字下げした文もメモ
  - 空行では切れません。字下げの無い文・見出しで切れます
- 待ちの節は1行1件の `- 〜`（字下げした続きの行は同じ件）
- 雑務の節は案件の行と同じ形。行の末尾の `:15` は見積の分
- HTML コメントの中（行の頭から始まるもの）とコードブロックの中は読みません

### First

- `## ⭐ 現在のFirst Task` の下（次の `##` の見出しまで）の、最初の未完了の `- [ ] …` を1件。`:60` は見積の分

### Daily

- `- [ ] 題名 :15 [daily]` のように、行の末尾のタグで日を決めます
  - `[daily]` 毎日／`[weekly:月水金]` 書いた曜日／`[monthly:1]` 毎月その日（その日が無い月は入らない）
- タグの無い行は入りません。見出しの名前は自由です

### WillDo

- 5つの欄 `## 1. First Task`・`## 2. 差し込み…`・`## 3. 繰り越し…`・`## 4. TODOから…`・`## 5. Daily Task` の `- [ ]`・`- [x]` の行
- 振り返りは `## 📈 振り返り…` と、その下の `### FUN`・`### DONE`・`### DONE（WillDo外）`・`### LEARN`
- 行の書き方は `- [ ] 題名 :見積分`。緊急の行は `（理由: …）` を付けます
- 終業（`/ppm-close`）で未完了の行の扱いを決めると、行の末尾に印が付きます。チェックは `[ ]` のまま（完了ではない）で、実行率（完了 ÷ 全体）の数え方は変わりません

  | 印 | 意味 | 翌日の WillDo を組むとき |
  | --- | --- | --- |
  | `→ 繰り越し` | 明日もやる | 3（繰り越し）の欄の候補 |
  | `→ 繰り越し: <書き直した行 :30>` | 明日もやる（書き直した行で） | 書き直した行で 3 の欄の候補 |
  | `→ TODO へ` | 急がないので TODO の一覧へ戻した | 入れない |
  | `→ やめた` | もうやらない | 入れない |
  | （印なし） | 締めなかった日の未完了 | 3 の欄の候補（Daily Task の欄の行は除く） |

### 日記

- `## 予定タスク…` と `## 緊急…` の下の `- [ ]`・`- [x]` の行
- 緊急の行にも、終業で WillDo と同じ印が付きます
- 翌日の WillDo を組むときは、`carry_candidates`（`ppm_files.py carry --date <対象日>`）が、対象日より前で WillDo がある最も新しい日（最大 `plan.lookback_days` 日さかのぼる）の未完了と、その日から対象日までの日記の予定タスク、その日から対象日の前の日までの日記の緊急の未完了を集めます（同じ題名は1回だけ）。WillDo がある最も新しい日の日記の行は、その日の WillDo に同じ題名の行が無いもの（WillDo を組んだ後に足された行）だけを拾います

## 部品の主な関数（スキルを作る人向け）

すべて読むだけです。ファイルが無いときは `None` を返します。

| 関数 | 返すもの |
| --- | --- |
| `context(root=None)` | `(ルート, 設定)` |
| `load_config(root)` | 既定値で埋めた設定の dict（型が違えば `PpmConfigError`） |
| `todo_path`・`first_task_path`・`daily_task_path(root, cfg)` | パス |
| `day_dir`・`will_do_path`・`task_diary_path(root, cfg, day)` | 日のパス（day は `date` か `YYYY-MM-DD`） |
| `template_path(root, cfg, name)`・`load_template(root, cfg, name, day=None)` | 雛形の場所・本文 |
| `read_todo(root, cfg)` / `parse_todo(text, cfg)` | 節・進行中・待ち・雑務 |
| `inflight_items(todo, include_done=False, group=None)` | 進行中の案件の行 |
| `inflight_layers(todo, include_done=False, group=None)` | `{layer のパス: scope}`（group は work / private） |
| `read_first_task(root, cfg)` | First の1件 |
| `read_daily_tasks(root, cfg, day=None)`・`daily_applies(tag, day)` | Daily の行と当てはまり |
| `read_will_do(root, cfg, day)`・`will_do_counts(willdo)` | WillDo の欄と振り返り、件数と見積の合計 |
| `read_task_diary(root, cfg, day)` | 日記の予定と緊急 |
| `split_estimate(text)` | `(題名, 見積の分)` |
| `split_disposition(text)` | `(印を外した文, 扱い, 書き直した行)`。扱いは `carryover`・`to_todo`・`dropped`・`None`。WillDo と日記の行には `disposition`・`carry_title`・`carry_estimate_min` のキーが付きます |
| `find_last_will_do(root, cfg, before, lookback_days=None)` | `before` より前で WillDo がある最も新しい日（無ければ `None`） |
| `carry_candidates(root, cfg, target, lookback_days=None, include_target_urgent=False)` | 翌日の WillDo の 2・3 の欄の候補（`carryover`・`urgent`・`scheduled`・入れない `set_aside`） |
| `check_inside_path(rel, key)` | 書き込みに使うパスがルートの中で、`.git`・`.claude`・`.ai-plc` の中でないか（違えば `PpmConfigError`） |

CLI（どれも読むだけ）: `config`・`paths`・`todo`・`first`・`daily`・`willdo`・`diary`・`carry`。`todo` の JSON でない出力は、私生活の節の行の Layer のパスを出しません（出すときは `--show-private`）。

テスト: `python3 -m unittest discover -s .claude/skills/ppm/tests`

## 日次の入口どうしの依存

どれも installer が一緒に入れます。手で一部だけを写すときは、次の組を一緒に写してください。

| スキル | 一緒に要るもの | 無いとどうなるか |
| --- | --- | --- |
| 全部 | `ppm/`（この部品と雛形） | 動かない |
| `ppm-plan` | `ppm-status/owner_open_count.py` | 自分が関わる Task の件数の行が出ない |
| `ppm-plan` | `aipm-guided/ops.py` | AIPM の箱の期限が迫った項目が候補に上がらない |
| `ppm-todo` | `ppm-inflight/list_inflight.py` | Layer と TODO の一覧の差分が出ない |
| `ppm-close` | `ppm-plan` | 翌日の WillDo を組めない |
