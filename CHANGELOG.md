# Changelog

AI-PLC の変更履歴です。版は2種類あり、別々に数えます。

| 版 | どこに出るか | 対象 |
| --- | --- | --- |
| **core の版**（例: `1.8.0`） | インストール先の `.ai-plc-version`、installer の `--help` | installer と、4ステージのスキル・rules・DB スクリプトなどの本体 |
| **実験版パッケージの版**（例: `1.8.0-exp.1`） | `experimental/jev/VERSION`、台帳の `package_version` | `--with-jev` を付けたときだけ入る Jev 監視（`experimental/jev/`） |

実験版の番号は core の版と連動しません。たとえば v1.8.0-exp.1 を入れた環境の `.ai-plc-version` は `1.7.1`（その時点の core の版）です。

この版より前の変更は、GitHub のリリースとタグを見てください。

## [Unreleased]

## [2.3.2] - 2026-11-26

実験版パッケージ（`experimental/jev/`）は **1.12.0-exp.2 のまま**です。機能の追加はありません。

### 修正

- **`plc_query.py` が、`sync.py`・`init_db.py`・Registry ビューアと同じ決め方で DB を選ぶようになりました。** 順は、環境変数 `AIPLC_DB` → `.ai-plc/config.yaml` の `id_allocation.db_path` → （`id_allocation.mode` が `local-db` か `git-ref` のときだけ）git の作業ツリーから求めた本体の DB → 隣の DB です。今までは、`AIPLC_DB` や設定を使っていても、`plc_query.py` の全部のコマンドが隣の DB を使っていました。**環境変数も設定も無いときの動き（隣の DB に読み書きする）は変わりません**（git の worktree の中で使っている場合も同じです）
- `id_allocation.mode` を `local-db` か `git-ref` にしている場合に限り、決まった DB が git の worktree の中の写しだったとき、`plc_query.py` の書き込みのコマンド（add-project・someday-add など）は `DB_NOT_MAIN`（終了コード 3）で止まります（`sync.py` と同じ動き）。その DB に書きたいときは `AIPLC_DB` で明示します
- `plc_query.py sql` の `SELECT`・`WITH`・`EXPLAIN` で始まる文は、読むだけの接続で実行します（書き込みを含んでいれば、書き込みとして扱い直します）
- `plc_query.py` の、DB が無いときの案内を今の `init_db.py --allow-production` に合わせました
- `core/db/README.md` を今の内容に書き直しました。道具ごとの役割、DB の場所の決め方、Notion の DB に要る列の一覧（名前と型）、v1.14.0 までの DB を新しい識別子の形に移す手順（`sync.py preflight` → 決定ファイル → `adopt-existing` → `backfill-remote-identity`）と、決定ファイル（`--decisions`）の書式を載せています。この移行は合成の DB で確かめたもので、実際の Notion のワークスペースでの確認はしていません
- コードとテストのコメント・説明文・メッセージから、開発時の内部向けの番号の記述を除きました。`sync.py import-legacy` が DB の除外の記録に書く理由の文字列も `legacy triage` になります（古い値のままの DB もそのまま使えます）。`tests/db/` のファイル名6本を、内容を表す名前に変えました

## [2.3.1] - 2026-11-26

実験版パッケージ（`experimental/jev/`）は **1.12.0-exp.2 のまま**です。機能の追加はありません。

### 修正

- `sync.py adopt-existing` の完了後の案内を直しました。Notion のページと既につながっている Project があるときの次の手順は `sync.py backfill-remote-identity --dry-run --plan-out <ファイル>` です（これを通す前に push すると `REMOTE_IDENTITY_BACKFILL_REQUIRED` で止まります）。v2.0.0 の節の Notion 利用者向けの手順にも、この手順が要ります
- `sync.py` の同期前の検査は、v2.0.0 で足した識別子の列だけでなく、Notion の DB の既存の列の有無と型も見ます。結果は `sync.py preflight` で確かめられます
- `core/db/business_registry.py` の冒頭の説明を実際の動きに合わせました（リポジトリに `Stock/programs/` があれば、設定が無くても箱の保存先を業務プロジェクトの表から決めます。読ませないときは `.ai-plc/config.yaml` に `aipm_archive: {business: none}` を書きます）
- README の更新手順を v2.3 までの内容にし、同梱の方式（AIPM・AIPM ライトモード）の説明を今の仕様に合わせました
- テストとコメントに残っていた、開発時の内部向けの名前や出典の記述を、合成の名前と一般の説明に替えました（動きは変わりません）

## [2.3.0] - 2026-11-26

実験版パッケージ（`experimental/jev/`）は **1.12.0-exp.2 のまま**です。既存のスキルの動きは変わりません。

### 追加: AI-PLC の PPM スキルを3つ（ポートフォリオ層は4つから7つに）

- **`/ppm-collection` — 依頼に似た既存の案件を照らす（読み取り専用）:** 依頼の言葉から、Registry のすべての状態の案件と Layer の intent・context を照らし、似た案件を最大3件出して、行き先を1つ勧めます（続きを進める・新しい Layer を作る・中止した案件を再開する・いつかやるに入れる など）。`/01-collection` の前に呼ぶと、同じ目的の Layer を重ねて作るのを防げます（Collection から自動では呼びません）。業務プロジェクトの表（`business_registry.py`）がある DB では、Program の公開範囲で仕事と私生活を分けます。表が無い DB では、仕事の依頼なら案件の中身まで照らし、私生活の依頼には intent に `membership.read_domain: private` と書いた Layer だけを出します。**表が無い DB で私的な Layer を仕事の依頼から外したいときは、その Layer の `intent.yaml` に `membership: {read_domain: private}` を書いてください**（書かないと、仕事の依頼の結果に目的や成功条件が出ます）。Layer の無い「いつかやる」の行は分けられず、仕事の依頼に名前と目的が出ます
- **`/ppm-scan` — 外から案件の候補を集める（外のサービスと案件は読むだけ。書くのは収集メモ1つ）:** 指定した範囲の Notion と、自分の公開 Slack 発言・関連する返信から、まだ一覧に無い案件・判断・相手待ちを根拠つきで1回だけ集め、収集メモ（既定は `Flow/YYYYMM/YYYY-MM-DD/ppm-scan/`）にします。Notion・Slack の接続が無ければ「未取得」と返して止まります。TODO への反映は行いません
- **`ppm-pmo` — 複数案件の PMO:** 複数の案件の資料から、案件間の依存の遅れ、共有する人や資源の上限超過、共通の課題、時点の古い資料を洗い出します（`scripts/portfolio.py`）。責任者向けの判断メモの型と、決定を案件別の要求に分ける型があり、反映されたかを `scripts/readback.py` で照合します。Python 3 の標準ライブラリだけで動きます
- 3層の定義（`three-tiers.md`）と rules §6・session §7.4 の一覧を7つに直しました。日次の計画や振り返りの入口は、引き続き公開版には含みません
- Codex の入口は 25 から 28 になりました（`$ppm-collection`・`$ppm-scan`・`$ppm-pmo`）

## [2.2.0] - 2026-11-26

実験版パッケージ（`experimental/jev/`）は **1.12.0-exp.2 のまま**です。installer が配るファイルのうち変わるのは `ppm-viewer` の説明だけです。

### 変更: Registry ビューア 0.3.0-alpha（`experimental/registry-viewer/`。installer の対象外）

- **破壊的な変更: 閲覧専用になりました。** 画面から Project と Task の status を変える機能と、そのための API を外しました（GET・HEAD 以外は 405）。status は `/plc-lifecycle`（中止・再開）や各 Stage の実行で変えます。0.2.x までの変更の記録（`viewer_log.jsonl`）は使わなくなりました。0.2.x では、中止した Project が一覧に出ず、status を変えられる構成では中止した Project を画面から進行中に戻せたため、閲覧専用にそろえました
- **中止した Project の表示:** cancelled を絞り込みと件数に足し、詳細に中止の記録を出します。中止した Project には起動プロンプトを出しません
- **進捗の数え方:** 運用タスク（`recurrence`）を進捗と未完了の数から外します。タスクの表に実行時期（`scheduled_for`）と期限（`due`）を出します。起動プロンプトは本体版のコマンド（`-jev` なし）です
- **並び順:** 一覧を作業記録（backlog・context）の更新が新しい順に並べられます（更新順・開始日順・ID 順の3つ）。ID は数として比べます（`-12` が `-2` より前に来ていたのを直しました）
- **Program・業務プロジェクトごとの表示:** 業務プロジェクトの表（`core/db/business_registry.py`）があり、移行済みの DB（`sync.py adopt-existing` で新しい識別子の形にしたもの）では、案件を Program・業務プロジェクトごとにまとめて見られます。画面共有モードでは private の Program の名前を伏せます。表が無い DB では今までどおりの一覧です
- **起動まわり:** 起動確認用の `/api/health`、一覧の 15 秒キャッシュ、切断時のエラーの無視、Mac のメニューバーアプリの起動確認とログ表示。DB の場所は `aiplc_paths.py` があればそれで決め、無ければ隣の DB を使います
- 更新するときは、古い `<プロジェクト>/.claude/db/registry_viewer` を消してから `experimental/registry-viewer` をコピーし直してください

### 変更: `ppm-viewer` の説明

- `core/skills/ppm-viewer/SKILL.md` と Codex の入口を、閲覧専用の説明に直しました

## [2.1.0] - 2026-11-26

実験版パッケージ（`experimental/jev/`）は **1.12.0-exp.2 のまま**です。

### 追加: ビューア2つ（アルファ版・installer の対象外）

- **`experimental/backlog-live/`（BacklogLive 0.1.0-alpha）:** Layer の `backlog.yaml` を読んで、タスク全体と「いまどこをやっているか」を図で表示します。backlog を保存すると数秒で表示が変わります。依存の流れの図、運用タスクと予定のタブ、タスクの詳細を見られます
- **`experimental/yaml-viewer/`（YamlViewer 0.1.0-alpha）:** AIPM の箱の一覧（仮説・論点・WBS・節目・ToDo）と、Layer の intent・context・backlog を、表と札で読めます。箱の新しい形（`Sheets/`）と古い形（`Documents/aipm_project/registers/`）の両方を読めます
- どちらも閲覧専用で、127.0.0.1 でだけ待ち受け、外部への送信はありません。`install.sh` では入らないので、各フォルダの README の手順でプロジェクトの `tools/` にコピーして使います。必要なのは Python 3.9 以上と pyyaml です

### 変更: Stage の本文のライブ表示の扱い

- `/01-collection`〜`/04-operation` と Codex の共通の参照で、「公開版にはライブ表示は無い」としていた1行を、「`tools/BacklogLive/server.py` があるときだけ、対象 Layer の画面を開く。無ければ何もしない」に変えました。BacklogLive を入れていないプロジェクトの動きは変わりません

### この版に入れていないもの

- Registry ビューア（`experimental/registry-viewer/`）は 0.2.1-alpha のままです。YamlViewer の Mac アプリ（Finder から `.yaml` を開く形）は入れていません

## [2.0.0] - 2026-11-26

名前が変わり、旧名では呼べなくなるので、版を 2.0.0 に上げました。実験版パッケージ（`experimental/jev/`）は **1.12.0-exp.2 のまま**です。

### 破壊的な変更: 名前替え（旧名は残りません）

| 旧名（v1.14.0 まで） | 新しい名前 | 層 |
| --- | --- | --- |
| `plc-registry` | `ppm-registry` | ポートフォリオ層 |
| `plc-status-audit` | `ppm-audit` | ポートフォリオ層 |
| `plc-viewer` | `ppm-viewer` | ポートフォリオ層 |
| `plc-someday` | `ppm-someday` | ポートフォリオ層 |
| `plc-project-status` | `plc-lifecycle` | プロジェクト層 |
| `pm-capture` | `pm-suggest` | ワークパッケージ層 |

- 案件をまたいで全体を見るスキルを `ppm-<機能>`（AI-PLC の PPM スキル。PPM はプロジェクトポートフォリオマネジメント）、1つの案件の中を見る・直すスキルを `plc-<機能>`、AIPM の箱の操作を `pm-<機能>` にそろえました。`ppm-` と `pm-` は1文字違いです
- installer で更新すると、旧名のファイルは消え、新しい名前のファイルが入ります（`--dry-run` に `DELETE:` が出ます）。旧名のファイルを自分で編集していた場合は `[CONFLICT]` で止まるので、`--backup-modified` で退避してください
- Codex の入口も同じ名前に変わります（`$ppm-registry`・`$plc-lifecycle`・`$pm-suggest` など）。入口の数は 25 のままです

### 破壊的な変更: 進め方（方式）の記録が必須に

- Layer ごとに進め方（方式）を1つ記録するようにしました。選べるのは同梱の2つ、**AIPM**（19文書を作る）と **AIPM ライトモード**（`aipm-light`。WBS と ToDo の表だけ）です。Collection で答えが無ければ、既定の `aipm-light` を記録します
- 方式が記録されていない Layer は、Inception・Construction・Operation・plc-backfill の最初で止まります。**v1.14.0 までに作った Layer は、続きを実行する前に次を1回実行してください**（既にある方式は変えません）

  ```bash
  python3 .claude/skills/ai-plc/01-collection/recommendation.py default --layer <Layer のパス> --apply
  ```

- `aipm-light` を記録した Layer では、Inception が人の ToDo を backlog の Task ではなく `Sheets/todo.yaml` に入れるようになります。既存の Layer でこの表を使うなら、続けて `python3 .claude/skills/aipm-guided/package.py init --layer <Layer のパス> --light` で箱（`Sheets/todo.yaml`・`Sheets/wbs.yaml`）を作ってください
- 記録されたかは `python3 .claude/skills/ai-plc/scripts/plc_addon_select.py --layer <Layer のパス> --require-method` で確かめられます
- 継ぎ目の契約は v0.6（`core/skills/ai-plc/references/addon-seam-contract_v0.6.yaml`）、目録（`addon-catalog.yaml`）は `aipm` と `aipm-light` の2行になりました

### 追加: 3層の定義

- `core/skills/ai-plc/references/three-tiers.md` を足しました。ポートフォリオ層（`ppm-`）・プロジェクト層（AI-PLC の Stage と `plc-`）・ワークパッケージ層（`pm-`。AIPM の箱）の役割、正本の置き場、層の間の受け渡し、語の書き分けを定義しています
- rules（system・session・model-routing）をこの定義に合わせました。公開版のポートフォリオ層のスキルは上の4つで、日次の計画や振り返りの入口は含みません

### 変更: AIPM の箱の作り直し

- **箱の形:** 箱の一覧（論点・仮説・ToDo・WBS など）を Layer の `Sheets/` の直下に置く形（sheets_v1）を既定にしました。v1.14.0 の形（`Documents/aipm_project/registers/`）の箱もそのまま読めます。移すときは `package.py migrate-layout`・`migrate-sheets` を使います（`core/skills/aipm-guided/SKILL.md` の「古い形の箱を移す」）
- **AIPM ライトモード:** `package.py init --layer <Layer> --light` で、`Sheets/todo.yaml`・`Sheets/wbs.yaml` だけの軽い箱を作ります
- **保存先の設定:** 完成した箱の保存先を `.ai-plc/config.yaml` の `aipm_archive`（`where: auto | stock | layer`、`business: registry | none`）で決められます。設定が無く `Stock/programs/` も無いリポジトリでは、Layer の中（`Documents/aipm_archive/`）に保存します
- **箱の版と改訂:** 保存した箱を次の版として取り出し、変更を1件ずつ判定して反映する操作（`register`・`clone`・`change`・`judge-change`・`apply`・`snapshot-sources`）を足しました
- **一覧の契約:** v2〜v4（ToDo の行に、ほかの表の行との結びつきと確認日の列）。v1.14.0 で作った箱は v2 の契約のまま読めます
- **業務プロジェクトの表と共有 Stock（任意・既定では使いません）:** 複数の案件を業務プロジェクトの下に束ねて保存先を決める表（`core/db/business_registry.py`）と、案件どうしで共有する保存先（`core/db/shared_stock.py`、`core/skills/aipm-guided/shared-stock.md`）を入れました。検証済みの範囲と未検証の範囲は shared-stock.md に書いてあります
- 操作は 11 種から 28 種に増えました

### 変更: DB の道具

- `core/db/` の `sync.py`・`init_db.py` を新しい版にし、`aiplc_paths.py`・`business_registry.py`・`shared_stock.py` を配るようにしました
- **`init_db.py` は、既定の DB（`.claude/db/ai_plc.db`）に書くとき `--allow-production` が要ります**（付けないと DB を開く前に終了コード 3 で止まります）。試すときは `--db <パス>` で別の DB を指定します。installer が最初に DB を作る動きは変わりません
- v1.14.0 の DB は、ローカルの Registry（`plc_query.py` の projects・dashboard・someday、`tasks-sync --status`）としてそのまま使えます
- **破壊的な変更（Notion と同期している人だけ）:** `sync.py` の `pull`・`push`・`sync` は、実行の前に Notion の DB の列を検査するようになり、次の列が無いと `SCHEMA_MISMATCH`（終了コード 3）で止まります。Projects の DB に `Sync UID`（テキスト）・`Workspace ID`（テキスト）・`Ownership Epoch`（数値）・`Identity Version`（数値）、Tasks の DB（タスク同期を凍結していなければ）に `Project Sync UID`（テキスト）・`Workspace ID`（テキスト）・`Project Ownership Epoch`（数値）・`Identity Version`（数値）を足してください。ローカルの DB は `python3 .claude/db/sync.py adopt-existing --dry-run …` → `--plan …` で新しい識別子の形に移します（使い方は `sync.py` の冒頭と `python3 .claude/db/sync.py preflight`）。この移行は合成の DB の試験で確かめたもので、実際の Notion のワークスペースでの確認はしていません。Notion と同期している人は、先に `--dry-run` と `preflight` で確かめてください
- 新しく作る DB では、`tasks.status` の値が英語（planned など）から日本語（未着手・進行中・完了）に変わりました（タスク同期は v1.12.0 から凍結されているので、通常は使いません）。既存の DB の値は変わらず、`plc_query.py dashboard` はどちらも数えます。既存の DB に `init_db.py --allow-production` を流すと、行はそのままで、分類の表（`project_classification`・`task_execution`）が足されます

### 追加: 汎用の改善

- plc-auto: 重い工程の作業量の上限（`work_budget_v1`）を `references/execution-record.md` に足しました
- Codex: 入口が正本を指しているかを確かめる `codex/skills/ai-plc/scripts/check_adapters.py`

### この版に入れていないもの

- 日次の計画・振り返りなどポートフォリオ層の日常運用の入口、会議の取り込み、軽い頼みごとの置き場（quick）、Project の分類と ID の自動採番。ステータス点検のスクリプトは今までどおり実験版（`--with-jev`）にだけ入ります
- Cursor の rules（`cursor/rules/*.mdc`）は v1.14.0 のままです

## [1.14.0] - 2026-10-23

実験版パッケージ（`experimental/jev/`）は **1.12.0-exp.2 のまま**です（この版では変えていません）。

### 変更: rules を v3.0 に軽量化

- `core/rules/` の system・session・adaptive を v3.0 にしました。細かい手順（自動完走の予算・`/plc-auto force` の契約・自己完結版 /goal・質問UIの細則・アドオンの前置き）は各スキルの `references/` に移し、rules には要点だけを残しています。挙動の変更ではなく、置き場所の整理です
- `core/rules/ai-plc-model-routing.md` を足しました（タスクの曖昧さ・複雑さ・影響から担当モデルと Advisor 相談を選ぶ共通の決まり。本人が頼んだとき、または Layer/Task に `model_routing: true` を書いたときだけ使います）
- 説明の詳しさ（session §7.0）: Layer の `intent.explanation.level` に `brief` / `reasoned`（既定）/ `guided` を保存できます（`python3 .claude/db/plc_explain.py show|set`）。ID はその応答で最初に出すときに名前を添えます
- Project の終了状態（system §21）: `planned / active / paused / completed / cancelled`。`completed` は元の Goal の全 AC を検証で確かめたときだけで、Goal 未達の意図的な終了は `cancelled` として別に数えます（入口は `/plc-project-status`）

### 追加: 繰り返す運用タスクと実行時期

- **運用タスク:** backlog の Task に `recurrence`（毎日・毎週など）を書くと、一度きりのタスクとは分けて「次に回す運用タスク」として示します。1回ごとの実行は `runs` に追記し、完了率や全完了の判定（BT-B・BT-C）には数えません。Layer を閉じるときは `retired_at`・`retired_reason` を付けます（status の値は増やしていません）
- **実行時期:** 通常の Task に `scheduled_for`（`YYYY-MM-DD` か `YYYY-Www`）を書くと、その日より前は実行可能な一覧から外し「待ち（実行時期 ○月○日）」と示します
- 自動完走（session §10）では、運用タスクは回さず、実行時期の来ていないタスクは選びません。それだけが残ったら停止の理由として報告します

### 追加: 同梱アドオン AIPM（`aipm-guided`）と `pm-` コマンド8本

- PM の進め方を Layer ごとに選べる「アドオン」の受け口を足しました（目録 `core/skills/ai-plc/references/addon-catalog.yaml`・継ぎ目の契約 `addon-seam-contract_v0.5.yaml`・判定スクリプト `core/skills/ai-plc/scripts/plc_addon_select.py` ほか）。選んでいない Layer の動きは変わりません
- 同梱のアドオン **AIPM**（`core/skills/aipm-guided/`）: 1人の利用者について、ペルソナ → 課題 → 仮説検証 → 解決策 → ストーリーまでの19文書を決まった形式で作り、検証します。コースは3つ（質問から・解決策から・既存の文書から）。Collection で「AIPM で進めたい」と選んだ Layer だけで動き、`intent.yaml` の `addons` に1件を書きます（旧い欄 `work_style: aipm` も同じに読みます）
- 元にした公開の原文（コマンド5件・雛形19件）は再配布の許可を得て同梱し、例の人名・社名・製品名などを一般の語に置き換えた適応版です。出典の commit と、元の hash・公開版の hash を分けて `source/source_manifest.json` に記録しています
- 箱の中の操作 `pm-` 8本（Claude Code は `/pm-…`、Codex は `$pm-…`）: `pm-issue`（論点）・`pm-hypothesis`（仮説）・`pm-todo`（ToDo と WBS）・`pm-capture`（会議・インタビューのメモから候補を拾う。書かない）・`pm-today`（今日動かす1件）・`pm-persona`・`pm-story`（文書の改訂の範囲の案。書かない）・`pm-init`（途中から AIPM にするときの案内）
- 開発方式（`dev_style: <your_style>`）を併用する Layer では、完成の判定をその開発方式の規約（チェックポイント・PR・レビュー）に委ねます
- 公開版に無いもの: 社内の Registry と共有する Stock（`aipm.storage: registry_stock_v1`）。選ぶと分かりやすいエラーで止まり、既定の Layer 内の保存（`Documents/aipm_project`）で動きます

### 追加: ユーティリティ（`plc-<機能>`）

- `/plc-next` — 欠けた Next Action（選択肢・おすすめ・開始文）を、直前の結果と案件の正本から補う（読み取りのみ）
- `/plc-decision` — 承認・選択の質問1件を、決めること・変わる範囲・負担・推奨の根拠・返信の案まで短く説明する（読み取りのみ。承認は代行しない）
- `/plc-brief` — Project が何のためで、何ができ、どう使うかを成果物から平易に説明する（読み取りのみ。テキストの説明だけ）
- `/plc-project-status` — Goal 未達のまま意図的に中止（cancelled）し理由を残す。再計画の後の再開も扱う
- `/plc-model-routing` — タスクに合う担当モデルと Advisor 相談を選び、実行環境のモデル指定へ渡す
- `/plc-someday` — 「いつかやる」Project を Registry に貯め、1件選んで Collection の起動プロンプトにする。`plc_query.py` に `someday-add` / `someday` / `someday-start` / `someday-revert` を足しました（`-` で始まる引数は使い方を出して書きません）
- `/plc-db-sync` に、タスク同期の凍結（`sync.py tasks-sync --status|--freeze|--unfreeze`）と、読み取り確認として実行してよい範囲・状態を変えるコマンドの区別を書きました

### 変更: Codex の入口

- 新しい plc- 6本と pm- 8本の入口を `codex/skills/ai-plc/` に足しました（入口は 11 → 25）
- 各入口の「前提確認（4ファイル）」の節と、読み取り専用の診断モード（`AI-PLC prerequisite diagnostics`）を廃止しました。各入口は共通の `references/codex-runtime.md` を先に読み、正本や必要な参照が欠けていれば、欠けたパスを報告して止まります。診断モードを使っていた人は、この欠落の報告で代えてください
- plc-registry・plc-someday・plc-status-audit・plc-viewer の入口の参照パスを、実在の場所に直しました（Registry は `.claude/db/`、ステータス点検は実験版の `.claude/ai-plc-jev/scripts/`、ビューアは `experimental/registry-viewer` を手でコピーしたときの `.claude/db/registry_viewer`）

### この版に入れていないもの

- **ステータス点検（`plc-status-audit`）** は今までどおり実験版（`--with-jev`）にだけ入ります。core の本文は「無ければスキップ」のままです
- ライブの進捗表示・`plc-brief` の HTML モード・Project の分類（`classify.py`。`experimental/registry-viewer` には同梱）・社内向けの共有 Stock と、Program・業務 Project への割り当ては、この版には入れていません。本文には「公開版には無い（あれば使う）」と書いてあり、無くても Stage は止まりません。業務 Project への割り当ては後の版で検討します
- 本人専用の情報の保存先（プロフィール・好み）は公開版にはありません。共有の Context・wiki・memory に写さない、という決まりだけを rules に残しています

### 既存の利用者へ

- 既存の Layer の `intent.yaml`・`backlog.yaml` は書き換えずにそのまま読めます（`construction` 欄の無い backlog は従来どおりのみなし、`work_style: aipm` は同梱の AIPM として、`recurrence`・`scheduled_for` の無い Task は今までどおり）
- installer が配らなくなったファイルはありません（`--dry-run` に `DELETE:` は出ません）。上げ方は README の「v1.13.x から v1.14.0 へ」
- 凍結の契約ファイル（`registers_contract.v1.yaml` など）は、コメントを公開向けに直したため、ほかで配られている版と hash が違います（公開版の中では一貫しています）
- テスト: 01-collection と extensions のテストは、ソース（`core/skills`）と導入先（`.claude/skills`）のどちらでも動くようにしました。受け入れテストの Codex の入口の数を 25 にしました。`test_with_jev.py` の「`--with-jev` なしの挙動は前と同じ」の比較は、この版で配り始めた3ファイルを比べる元の installer にも足してから比べます

### 版

- rules: `ai-plc-system.md`・`ai-plc-session.md`・`ai-plc-adaptive.md` 3.0、`ai-plc-model-routing.md` 新規

## [1.13.0] - 2026-10-02

### 追加: `plc-auto`（固定Goalで自動完走）

- 正本 `core/skills/plc-auto/`（固定Goalを含む）とCodex adapter・UI metadataを同梱。Codexの表示名は `plc-auto`
- `$plc-auto` の明示実行で、利用可能なnative Goal機能へ固定本文を設定し、成功とactiveを確認して通常版AI-PLCを続行。通常Stageの承認待ちは変えません
- 別Goalや停止中のGoalを上書きしません。Goal機能が無ければ未設定で停止し、コピペ用 `/goal` を案内。公開・外部送信・git操作等の保留とBacktrack停止を維持
- 60ターンはモデルへの指示で、nativeの機械的上限やトークン予算ではありません。Jev Layerも通常版を使い、監視opt-inを自動で承認しません
- `core/rules/ai-plc-session.md` §10（v2.2）に専用入口の適用条件を追加。詳細・実測範囲は [docs/plc-auto.md](docs/plc-auto.md)
- installerの処理・DB・実験版パッケージ（1.12.0-exp.2）は変更しません

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
