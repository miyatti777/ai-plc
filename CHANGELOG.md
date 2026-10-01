# Changelog

AI-PLC の変更履歴です。版は2種類あり、別々に数えます。

| 版 | どこに出るか | 対象 |
| --- | --- | --- |
| **core の版**（例: `1.8.0`） | インストール先の `.ai-plc-version`、installer の `--help` | installer と、4ステージのスキル・rules・DB スクリプトなどの本体 |
| **実験版パッケージの版**（例: `1.8.0-exp.1`） | `experimental/jev/VERSION`、台帳の `package_version` | `--with-jev` を付けたときだけ入る Jev 監視（`experimental/jev/`） |

実験版の番号は core の版と連動しません。たとえば v1.8.0-exp.1 を入れた環境の `.ai-plc-version` は `1.7.1`（その時点の core の版）です。

この版より前の変更は、GitHub のリリースとタグを見てください。

## [Unreleased]

## [実験版 1.12.0-exp.2] - 2026-10-01

実験版パッケージ（`experimental/jev/`、`--with-jev` のときだけ入る）の新しい版です。前の実験版 1.12.0-exp.1 の次の版で、**core の版は 1.12.0 のまま**です。

- **会話監視 hook と成功条件カバー判定を凍結しました。** 作者の試行で、会話監視は人が判定したヒント15件のうち10件が外れ（却下率約67%。継続の基準は30%以下）、成功条件カバー判定は出したヒントに役に立ったものがありませんでした。`/02-inception-jev` はカバー判定を呼ばなくなり（`jev_monitor: true` でも）、会話監視は「新しく登録しない（登録している場合は外してよい）」と案内します。スクリプト（`jev_coverage_check.py`・`jev_prompt_hook.py`）は残しますが、更新しません
- Backtrack の異常ヒント（`/04-operation-jev` の 5.5b・6b）とステータス点検は変わりません（Backtrack の異常ヒントは、判定135件で外れ率3.4%）
- `KNOWN_RELEASES.sha256` に 1.12.0-exp.1 の配布物のハッシュを足しました
- Python のコードと installer の処理は変えていません

上げ方: `./install.sh --target <プロジェクト> cc --with-jev`（先に `--dry-run` で確認できます）。

## [1.12.0] - 2026-10-01

実験版パッケージは **1.12.0-exp.1** に上がります（下の節）。

### 追加: 自動完走モード（/goal で RUL_plc_session §10 を指すとき）

- Claude Code の `/goal` で、Layer を承認待ちで止まらずに最後まで進められるようにしました。ルールは `core/rules/ai-plc-session.md` §10（v2.1）。切り替えは「そのセッションで貼った /goal が §10 を指しているか、『AI-PLC 自動完走（自己完結版）』を含むとき」だけで、口頭の指示や `intent.yaml` の欄では切り替わりません。止めるのは `/goal clear`
- 自動で進めるもの: Mob Checkpoint は承認ブロックを出したうえで⭐を選ぶ／Next Action は A（⭐）をその場で実行（Layer の全タスク完了後の Next Action は実行しない）／Stage 4 のタスクは P0→P1→P2・依存順／明確化の質問はせずに仮定を置く（データ・権限・受け手に見える挙動は最も保守的な案）
- 緩めないもの: Phase 5.5 の独立検証（未解決 P0〜P2 ゼロ。修正→再検証は2回まで）、Backtrack の承認（要る判定なら停止）
- 保留するもの（実行せずログに残して先へ進む）: git の commit・push・PR・merge・タグ、外部公開（リポジトリ・パッケージへの反映）、Notion・Slack・メールへの書き込み・送信、ローカル sqlite 以外の外部 DB への書き込み、承認後の決まりがある反映（ステータス点検の反映など）、決まった書き込み先以外の Layer 外のファイル、削除・移動・既存成果物の上書き、上記以外の操作（お金・外部 API への送信・ツールの導入など）
- 停止: 行頭に `⛔ 自動完走を停止: <理由>`（complex・platform_builder の Layer、SubLayer、BT-A、Backtrack が要る、2回の修正後も P0〜P2 が残る、など）。自動で選んだ判断は backlog の `refactoring_log` に `[auto-approved]` で1行ずつ残し、完了・停止のときに表で示す
- `/01-collection`・`/02-inception` の完了報告の最後に、Layer パスと開始列を埋めた /goal 1行（短い版）を出します（止まる挙動は変えない。complex・platform_builder では出さない）。新しい Goal から1本で走らせる「Goal から版」と、§10 の無い環境でも貼るだけで動く「自己完結版」は README の「自動完走（/goal）」の節にあります
- 01〜04 の SKILL の冒頭に自動完走モードの1行、04 の Phase 2 に自動完走中のタスク選択、`ai-plc-session.md` §7.4・§8・§9 に例外の参照、`ai-plc-adaptive.md` §5 ルール1 に「自動完走中も Backtrack は停止」を追加
- Codex は開始列のコマンドを `$02-inception` 等に読み替えて使えます（`codex/skills/ai-plc/01-collection` の手順4）。Cursor には /goal が無いため対象外で、`cursor/rules/ai-plc-session.mdc` にその旨を1行足しました

### 変更: Construction（Stage 3）を既定で省く

- Stage 3（Agent 定義の生成）は、次のどれかに当たるときだけ通すようにしました: ①workflow_depth が complex ②mode が platform_builder ③intent.yaml の `construction_mode: always`（慎重モード・opt-in）④`delegable: true` のタスクがある ⑤type が implementation / coding で手順が5つを超えるタスクがある。①〜③は全タスク、④⑤は当たるタスクだけ Agent 定義を作ります（`ai-plc-adaptive.md` §1・§3・§6、v2.5）
- 要否は backlog を作る者（standard 以上は Inception、simple は Collection）が backlog のトップレベル `construction`（required・reason・tasks）に書き、Stage 2 の後の Next Action はそれで決まります（`ai-plc-session.md` §7.4）。`construction` 欄の無い既存の backlog は「required: false」とみなし、進行中の Layer は止まりません（Agents/ に定義のあるタスクはそれに従います）
- Construction を通さないとき、Operation は backlog の description・acceptance_criteria・guardrails・decisions と Context から実行します。standard 以上は `acceptance_criteria` が必須になり、Phase 5.5 の L1 で1項目ずつ ○/× を確かめます。`delegable: true` は途中で人の確認が要らないタスクにだけ付け、Agent 定義の frontmatter には backlog の値を写します
- 独立レビューの契約は 04-operation Phase 5.5 に一本化し、Agent 定義の Guardrails には参照の1行だけを書きます（テンプレート `templates/agents/TPL_*`・ロール `TPL_role_*` も合わせて更新）
- `plc-consult`: Re-Inception で `/03-construction` を添えるのは、足したタスクが §6 の条件に当たるときだけにしました
- 02〜04 の SKILL・`claude/commands/03-construction.md` の説明・Codex アダプターの説明・Cursor の `ai-plc-adaptive.mdc`・`CLAUDE.md` / `AGENTS.md` のテンプレートを合わせて更新

### 変更: Registry の tasks を凍結（タスクの正は backlog.yaml）

- タスクの正を各 Layer の `backlog.yaml` だけにしました。Registry（`.claude/db/ai_plc.db`）の `tasks` テーブルは古い写しとして凍結し、External Sync の既定を `tasks` テーブルから **`projects` テーブル**に変えました（`ai-plc-system.md` §8・§9、v2.5）。既存 Layer の `sync_targets` に `.claude/db/ai_plc.db#tasks` が書かれていても、書き換えずに読む側で無視します
- `sync.py tasks-sync --status | --freeze --approved-by <名前> [--reason <理由>] | --unfreeze --approved-by <名前>` を追加。凍結の印が壊れていれば `--status` は `MALFORMED`（終了コード 3）と出し、`--unfreeze` で壊れた印を履歴に退避して消せます。凍結の印は `_metadata` の `task_sync_frozen`（承認者・理由・日時の JSON）で、解除すると `task_sync_unfrozen:<日時>` に履歴が残ります。`tasks-sync` は Notion の設定なしで使えます
- 凍結中は、`plc_query.py add-task` が書き込まずに `[SKIP]` を出して終了コード 0（古い手順から呼ばれても止めない）、`plc_query.py tasks` は各 Layer の backlog.yaml を表示、`dashboard` はタスクの集計を出しません。`sync.py` の pull / push / sync / status は Projects だけを扱い、Notion の Tasks DB には問い合わせません（`AI_PLC_TASKS_DB_ID` も不要）
- **新しくインストールした DB は最初から凍結**されます（`init_db.py` が新しい DB を作るときだけ、`approved_by: "installer"` の印を入れる）。**既存の DB は installer から書き換えません。** v1.11.0 以前から使っている環境は、更新の後に `python3 .claude/db/sync.py tasks-sync --freeze --approved-by <名前>` を1回実行してください。凍結しても tasks テーブルの行は消えません
- `/plc-registry`・`/plc-backfill`（Phase 7 で add-task をしない）・`/01-collection`（Phase 6.5 の既定）・`core/db/README.md` を合わせて更新。自動完走（§10）の書き込み範囲も「ローカル sqlite は projects の追加・更新だけで、tasks 行は書かない」にしました
- 実験版のステータス点検（`aiplc_status_audit.py`）は、凍結中は Registry のタスク行を読まず、分類 3・7・8 を出しません
- テスト `tests/db/test_task_freeze.py` を追加しました（新しい DB は凍結・既存 DB は凍結しない・凍結中の add-task は SKIP・backlog の表示・tasks-sync の3モード・installer が作る DB）

### 追加: 使い分け（記録は広く、手順は絞る）と深度の理由の記録

- `ai-plc-adaptive.md` に §0 を新設しました。仕事ごとに、記録（Layer）が要るかと、どの守り（完了条件の ○/×・Collection での資料集め・独立レビュー・取り返しにくい操作の前の承認）が要るかを分けて決める表です。①（その場限り・汎用・自分用）は Layer を作りません
- `/01-collection` の Phase 1 で、深度の判定理由を `workflow_depth_reason`（1行。§0 の表の目安と食い違えばその理由も）に、参考として4軸 `depth_axes`（R 受け手・U やり直し・V 確かめ方・C 固有の文脈。判定の条件にはまだ使わない）を intent.yaml に書きます。§0 の①に当たれば、その旨を報告して続けるかを聞きます

### 版

- rules: `ai-plc-session.md` 2.1・`ai-plc-adaptive.md` 2.5・`ai-plc-system.md` 2.5
- 同じリリースの中で後から足した変更（tasks の凍結など）は、版を重ねて上げず、この版で上げた番号（session 2.1・01-collection 2.2 など）の説明に追記しています
- スキル: `01-collection` 2.2・`02-inception` 2.1・`03-construction` 2.3・`04-operation` 2.8

### 同梱: Registry ビューア 0.2.1-alpha（installer 対象外）

- 0.2.1-alpha: タスク同期の凍結（上の「Registry の tasks を凍結」）に対応。凍結中は Registry の tasks 行を読まず（一覧・詳細・進捗）、Project を閉じるときの未完了チェックにも数えず、Task の status の変更でも tasks に UPDATE しません（backlog.yaml だけ）。テストを追加
- 0.2.0-alpha（1.11.0 の後に main に入っていたもの）: `experimental/registry-viewer/` に **分類（所属・種類・実行環境）** を追加。intent.yaml の `classification` とタスクの `executed_by` を正本に、Registry の別表（`project_classification` / `task_execution`。projects / tasks の列は変えない）へ写し、ビューアの一覧のバッジと絞り込みで見分けられるようにした。`classify.py`（語彙の検査・表の作成・写し・既存 Project の候補提案と承認反映）と語彙のサンプルを同梱。core のスキルは変えていないので、分類は手で書くか `classify.py suggest` → `apply` で付ける

## [実験版 1.12.0-exp.1] - 2026-10-01

実験版パッケージ（`experimental/jev/`、`--with-jev` のときだけ入る）の新しい版です。前の実験版 1.8.1-exp.1 の次の版で、core 1.12.0 に合わせて出しました。

- スキル（`/01-collection-jev`〜`/04-operation-jev`）を core 1.12.0 のスキル（`01-collection` 2.2・`04-operation` 2.8）に揃えました。Construction を既定で省く変更（`/03-construction-jev` は要るときだけ、`/02-inception-jev` の Next Action は `construction.required` で選ぶ）、深度の理由の記録、自動完走モードの1行が入ります。core のスキルとの違いは Jev 部分だけです
- 自動完走中（RUL_plc_session §10 を指す /goal があるセッション）の Jev の扱いを、`04-operation-jev` の「Jev監視ルール」の例外として書きました: opt-in した Layer の Jev の判定は行い、判定ごとの採否の記録とコピペ用プロンプトへの貼り付けはせず、完了報告の冒頭に「🧭 未確認の Jev 判定: N件」と貼り付け用1行をまとめて出します（回収は `jev_bt_monitor.py --pending --layer <Layer>`）。Jev 監視の opt-in は自動では承認しません（`01-collection-jev` Phase 6.5）。`01-collection-jev` の最後に出す /goal 1行は `-jev` 版のコマンドで書きます
- `KNOWN_RELEASES.sha256` に 1.8.1-exp.1 の配布物のハッシュを追加しました
- ステータス点検（`aiplc_status_audit.py`）: Registry のタスク同期が凍結されている（core 1.12.0 で新しく作った DB は最初から凍結）ときは、Registry のタスク行を読まず、分類 3・7・8（完了 PJ の未完了タスク行・status の食い違い・タスク行が無い）を出しません
- installer の処理は変えていません

## [1.11.0] - 2026-09-29

実験版パッケージは **1.8.1-exp.1 のまま**です。

### 追加: `plc-backfill`（スキル外作業の事後記録）

- 急いでいるときなどに `/04-operation` などのスキルを通さずに頼んで**済んだ**作業を、あとから Layer の記録に載せるユーティリティです。`/plc-backfill [Layer] [メモ]` か「Propagationして」「さっきの作業を記録して」のような言葉で呼べます
- 流れ: 会話から済んだ作業を棚卸し → 対象 Layer を決める（会話からの推定も可・承認で確定）→ **何をどこに書くかを見せて承認を待つ** → 会話にしか無い中間生成物を `Documents/` に書き起こし（冒頭に「事後に書き起こしたもの」と明記）、backlog に `origin: "ad-hoc …"` のタスクを `in_progress` で追加 → 04-operation の Phase 5.5〜7 を**定義のまま**通して `completed` にする
- 足したタスクは origin の `ad-hoc` の印で、Phase 6b の BT-B「ad-hoc 2件以上」に数えられます（スキル外作業が続いた合図）
- 記録するのは済んだ作業だけです。作業のやり直し・続きの実装・git 操作はしません。検証で既存の成果物に問題が見つかったときは、済んだ部分だけを記録して `/plc-consult` に回します
- 当てはまる Layer が無い作業は、続きがあれば `/01-collection`、それ以外はメモに残す1行の文案を返して止まります（何も書き込みません）
- Codex アダプター `codex/skills/ai-plc/plc-backfill/` 付き。rules は `ai-plc-system.md` §6（v2.4）の一覧と、`ai-plc-adaptive.md` §5（v2.4）の会話中監視に記録の提案1文を追加
- 既知の制限: 実験版（`/0N-*-jev`）で進めている Layer でも、参照する Phase と出すコマンドは本体版です。ステータス点検は実験版を入れていないと使えないため、その場合は intent・backlog を目視で確かめます

## [1.10.0] - 2026-09-29

実験版パッケージは **1.8.1-exp.1 のまま**です。

### 追加: `plc-consult`（アイデア相談）

- スキル実行の合間（例: Operation で成果物が出た後）に、「ここをこうしたい」を命令ではなく相談として持ち込めるユーティリティです。`/plc-consult <アイデア>` か「どう思う？」「どのコマンドを打てばいい？」のような言葉で呼べます
- 今の Layer の `intent.yaml`（goal・success_criteria）と `backlog.yaml` を読み、**却下／今のタスク内で修正／Re-Inception／Re-Collection／いつかやる** のどれかに振り分けて、所感（賛成・条件つき賛成・反対）・理由・次に打つコマンドを返します
- **読み取り専用**です。ファイルも Registry も書き換えず、コマンドも実行しません（貼って実行するのは人）
- 判定は3ステップ（goal との関係 → 手当ての大きさ → 却下チェック）。完了済みタスクの修正は Re-Inception（修正タスクを1件足す）に回します
- Codex アダプター `codex/skills/ai-plc/plc-consult/` 付き。rules は `ai-plc-system.md` §6（v2.3）の一覧と、`ai-plc-adaptive.md` §5（v2.3）の会話中監視に案内1文を追加
- 既知の制限: 実験版（`/0N-*-jev`）で進めている Layer でも、出すコマンドは本体版（`/0N-*`）です。「いつかやる」はコマンドを出さず、メモに残す1行の文案を示します

## [1.9.0] - 2026-09-29

実験版パッケージは **1.8.1-exp.1 のまま**です（中身も変えていません。そのため実験版の `README_status_audit.md` には旧名 `ai-plc-db-sync` の記述が残っています。読み替えてください）。

### 追加: AI-PLC ユーティリティスキル（`plc-<機能>`）

- ユーティリティのスキル名を **`plc-<機能>`** にそろえ、`.claude/skills/` の直下に置くようにしました（Claude Code は `.claude/skills/` の1階層だけをスキルとして読みます）。名前の決まりは `core/rules/ai-plc-system.md` §6（v2.2）の「呼び出し名」の表にあります
- 新しく入るスキル: `plc-registry`（Registry の照会と追加）、`plc-status-audit`（ステータス点検。実験版を入れたときだけ使える）、`plc-viewer`（Registry ビューア。`experimental/registry-viewer` を手でコピーしたときだけ使える）。Codex 用のアダプター（`.agents/skills/ai-plc/plc-*`）も入ります

### 変更: DB 同期スキルの改名

- `ai-plc-db-sync` → **`plc-db-sync`**。置き場所は `.claude/skills/ai-plc/db-sync/` → `.claude/skills/plc-db-sync/`（Cursor は `.cursor/skills/plc-db-sync/`、Codex は `.agents/skills/ai-plc/plc-db-sync/`）。更新すると古いファイルは自動で消えます（編集していた場合は止まります）。手順は README の「アップデート手順」

### 修正

- `spec-story-starter` と `wire-aa-authoring` は `.claude/skills/utility/` の下に入るだけで、Claude Code から呼べませんでした。`.claude/commands/` にラッパーを同梱し、`/spec-story-starter`・`/wire-aa-authoring` で呼べるようにしました

## [実験版 1.8.1-exp.1] - 2026-09-29

実験版パッケージ（`experimental/jev/`、`--with-jev` のときだけ入る）の新しい版です。前の実験版 1.8.0-exp.1 の次の版で、**core の版は 1.8.1 のまま**です（installer の `--help` の表示も `v1.8.1`）。`1.8.1-exp.1` は core 1.8.1 に合わせて出した版で、末尾の `exp.1` はその版での通し番号です（前の実験版 1.8.0-exp.1 は core 1.7.1 の上に作ったもので、頭の数字が core の版と一致するとは限りません）。1.8.0 の「未対応・既知の点」に書いた実験版の古い版表記と、README の実験版の節の「既知の制約」に書いていた uninstall の後片付けの制約は、この版で直しました。

### 実験版パッケージ

- スキル（`/01-collection-jev`〜`/04-operation-jev`）を core 1.8.1 のスキル（`01-collection` 2.1・`04-operation` 2.7）に揃えました。core のスキルとの違いは Jev 部分だけです。説明文の古い版表記（「core の版は 1.7.1」など）も直しました
- `jev_bt_monitor.py --override-pending`: `--only` / `--except` の指定で記録対象が0件になったとき、「未確認の Jev 判定なし」ではなく「記録対象なし（未確認は N件残っています・…）」と出します。`--layer` に Layer パスでも scope_id の形でもない値を渡すと「Layer の scope_id が読めません」と出します
- `/02-inception-jev`: カバー判定の採否の記録を、タスクの実行より先に行うことを明記しました
- ステータス点検（`aiplc_status_audit.py`）: Registry のタスク ID が `<scope_id>-T001` の形でも、backlog の `T001` と同じタスクとして突き合わせます（前は「タスク行なし」と誤って出ていました）
- `KNOWN_RELEASES.sha256` に 1.8.0-exp.1 の配布物のハッシュを追加しました。1.8.0-exp.1 から上げたときや、中断した後処理の残り物を掃除するときの照合に使います

### installer（`lib/ai_plc_multi_env.py`）

- 実験版の uninstall の後処理（`.bak` と空ディレクトリの掃除）の最中にプロセスが落ち、次が codex 経路（`install.sh codex` / `install-codex.sh`）だった場合に、実験版の `.bak` とディレクトリが残っていました。cc を含む uninstall（`cc` / `both` / `all`）のときに、中身が既知の版か今の配布物と一致する `.bak` と、それで空になった実験版のディレクトリを掃除します。一致しないものは残して `[WARN]` に件数を出します。台帳が無くて uninstall がエラーで止まる環境でも、残り物だけ掃除してから同じエラーで止まります
- 後処理の再開中にもう一度落ちると、再開の情報が失われていました。再開の情報を先に保存してから後処理するようにしました（次の `install.sh`（codex 以外）/ `uninstall.sh` で再開します。`install-codex.sh` を挟んだなどで再開の情報が失われた場合も、cc を含む uninstall で掃除します）
- **実験版の残り物が無い環境では、動きは今までと同じです**（`--with-jev` を付けない install・uninstall の出力・終了コードも同じ）。残り物がある環境で cc を含む uninstall のときに掃除することは、意図した変更です。install・`--dry-run`・`--plan-only`・cursor / codex だけの uninstall では掃除しません
- `tests/installers/README.md`: `test_with_jev.py` は git の履歴を読むため、完全な clone が必要なことを書きました

### 上げ方

`./install.sh --target <プロジェクト> cc --with-jev`（先に `--dry-run` で確認できます）。core も 1.8.1 に上がります。`--with-jev` を付けずに更新すると、実験版は 1.8.0-exp.1 のまま残ります。手順の詳細は README の実験版の節にあります。

## [1.8.1] - 2026-09-29

### 修正

- `plc_query.py dashboard` のタスク集計が、日本語の状態（`未着手`・`進行中`・`完了`）で数えていたため、完了したタスクがあっても `0 done` と表示されていました。DB のタスクの状態は `planned` / `active` / `completed` / `paused` しか受け付けないので、todo = `planned`、WIP = `active`、done = `completed` で数えるように直しました（v1.2.0 からの不具合。DB の中身は変わりません）

## [1.8.0] - 2026-09-29

実験版パッケージは **1.8.0-exp.1 のまま**です（中身も変えていません）。

### 追加: 旧版からのアップデート

- **旧版（v1.1.0〜v1.6.0）の自動判別と移行。** 台帳（`.ai-plc-install-manifest`）のない旧版は、どれも `.ai-plc-version` が `1.1.0` と出るため、版番号では本当の版が分かりませんでした。installer が、入っているファイルの中身を旧版ごとの一覧（`migration/legacy-releases/`）と照らし合わせて版を判別し、フラグなしで更新できるようになりました。中身が同じ版（例: v1.2.1〜v1.4.1）はまとめて扱います。判別の結果は `[INFO] legacy release detected: …` と、`--dry-run` の `legacy_release` に出ます
- **`--backup-modified`（新しいオプション）。** 自分で編集したファイルがあると、installer は今までどおり何も書き換えずに止まります。このオプションを付けると、編集したファイルを `<path>.bak.<UTC>.<n>` に退避してから更新します。退避したファイルは `[BACKUP]` 行と、台帳の `user_backups` に記録されます。`cc` / `cursor` / `both` / `all` で使えます。**Codex だけの指定（`codex`）では使えません**（終了コード 2）。Codex 対応は v1.7.0 からで、Codex だけの環境には台帳のない旧版が無いためです
- 手順は README の「アップデート手順」にあります

### 変更: core（スキル・rules）

- rules: `ai-plc-system` 2.1（Phase 7 のチェックリストに8項目目「ステータス点検」を追加）、`ai-plc-adaptive` 2.2（Jev 監視は実験版の `/0x-*-jev` だけで、core からは呼ばないことを明記）
- skills: `01-collection` 2.1（Registry への登録を `plc_query.py` 経由に。intent.yaml の `jev_monitor` 欄は core では常に false）、`03-construction` 2.2（すべての Agent 定義に独立レビューの約束を入れる）、`04-operation` 2.7（独立 reviewer の起動を明示し、未解決の P0/P1/P2 を完了の条件に。Phase 7 にステータス点検）
- **core は Jev を呼びません（外部送信なし）。** ステータス点検は、実験版（`--with-jev`）を入れた環境でだけ動き、ローカルで読むだけです。実験版が無い環境では「点検ツールなし — スキップ」と出して進みます
- Cursor の `ai-plc-system.mdc` にも、Propagation の項目としてステータス点検を追加しました（点検ツールは Claude Code 用の実験版にしか入らないため、Cursor だけの環境では常にスキップになります）

### 同梱: Registry ビューア（アルファ版・installer 対象外）

- `experimental/registry-viewer/` を **0.1.1-alpha** に更新（db8c136 で 0.1.0-alpha を追加、fbfce4c で更新）。空のプロジェクトに入れた試用の結果を README に反映（ポート使用中の対処・`.gitignore` が無いとき・バックアップ名・フル機能にする手順・止め方）、変更記録の時刻にタイムゾーン、simple 深度で backlog が空の Layer の起動プロンプトを `/04-operation` に

### 修正

- 旧版を引き取るとき、`.ai-plc-version` を台帳の管理ファイルに入れないようにしました。途中で失敗したときに、元に戻す処理と次回の再開が失敗することがありました（`.ai-plc-version` は版の目印として別に扱います）
- `core/skills/ai-plc/README.md` に残っていた、特定の組織の作業場所の名前や内部ページの ID を、中立的な説明に置き換えました

### 未対応・既知の点

- **Codex 用のスキル（`codex/skills/ai-plc/`）は、今回の core の変更をまだ取り込んでいません。** Codex 用は core とは別に管理しているコピーで、次の版以降で同期します
- 実験版パッケージ（`experimental/jev/`）の中の説明文には、「core の版は 1.7.1」「公開 core 2.4」などの古い版表記が残っています。インストール済みの実験版の中身を変えると、同じ版番号（1.8.0-exp.1）のまま中身が違うとして、実験版を入れた環境の更新が止まるため、次の実験版で直します。新しい版の関係はこのファイルと README を見てください
