# AI-PLC ローカルDB（Project Registry / Tasks）

AI-PLC は、プロジェクト横断の台帳とタスクをローカル SQLite（`ai_plc.db`）で管理します。
インストール時に空のDBが作られます（個人データは含まれません）。

## 何に使うか

- **Project Registry（`projects` テーブル）** — Collection の Phase 3.5 で各プロジェクトを登録し、横断で状況を見る台帳
- **Tasks（`tasks` テーブル）** — **凍結して使わない**（v1.12.0〜）。タスクの正は各 Layer の `backlog.yaml` で、External Sync の既定は `projects` テーブル（RUL_plc_system §9）。新しく作った DB は最初から凍結され（`_metadata` の `task_sync_frozen`）、凍結中は `plc_query.py add-task` が書き込まずに `[SKIP]` を出し、`plc_query.py tasks` / `dashboard` は backlog.yaml を見る

> 核の4ステージループ（Collection→Operation）は DB が無くても動きます。DBは「横断管理」の追加レイヤーです。

## このフォルダの道具

| ファイル | 役割 |
| --- | --- |
| `init_db.py` | DB を作る・スキーマを保証する（下の「セットアップ」） |
| `plc_query.py` | 一覧・照会・`add-project` などの日常の操作 |
| `sync.py` | Notion との同期と、Identity v2.0 への移行（任意） |
| `aiplc_paths.py` | DB の場所を決める共通の関数（下の「DB の場所」）。`python3 .claude/db/aiplc_paths.py` で、決まった場所と理由を表示する |
| `project_lifecycle.py` | Project の中止（`cancelled`）と再開。`plc-lifecycle` スキルから使う |
| `plc_explain.py` | 案件ごとの説明の詳しさ（`intent.explanation.level`）の表示と保存 |
| `business_registry.py` | 業務Project の表（Program・業務Project・所属・AI-PLC 案件とのつながり）を作り、行を足す。AIPM の箱の保存先を決めるのに使う。前提は Identity v2.0（下の「Identity v2.0 への移行」） |
| `shared_stock.py` | 共有 Stock の書き込みの手順（試験用の一時の置き場と、発行ファイルで1組に絞った本番の置き場）。業務Project の表は読むだけで書かない |

## セットアップ

インストーラが自動で実行します。手動なら:

```bash
python3 .claude/db/init_db.py --allow-production            # 空DBを作成（新しく作るときだけタスク同期を凍結）
python3 .claude/db/init_db.py --allow-production --reset    # 作り直す
python3 .claude/db/init_db.py --db /tmp/try.db               # 別の DB で試す
```

- 既定の DB（下の「DB の場所」で決まる本番の DB）への書き込みは、まだ無いときも含めて `--allow-production` が無いと、DB を開く前に終了コード 3（`INIT_DB_PRODUCTION_WRITE_FORBIDDEN`）で止まります。`--db PATH` で別の DB を指したときは要りません
- 既存の DB に `init_db.py` を流しても、スキーマを保証するだけで凍結の印は足しません
- 業務Project の表（`business_projects`・`business_project_links`）がある DB には、`init_db.py` は何も書かず、`--reset` も含めて終了コード 3（`INIT_DB_BUSINESS_TABLES_PRESENT`）で止まります（業務Project の関係を消さないため）

## DB の場所

`plc_query.py`・`sync.py`・`init_db.py`・`business_registry.py`・Registry ビューア・`ppm-collection` は、`aiplc_paths.py` で同じ DB を選びます。上から順に、最初に当たったものを使います。

1. 環境変数 `AIPLC_DB`（試験・一時の DB 用。`init_db.py` の既定の対象と本番の守りの基準には使わない。`init_db.py` で別の DB を作るときは `--db PATH`）
2. `.ai-plc/config.yaml` の `id_allocation.db_path`（相対パスは作業ツリーから）
3. `id_allocation.mode` が `local-db` か `git-ref` のとき: git の共通ディレクトリから求めた本体の作業ツリーの `.claude/db/ai_plc.db`（あるとき）
4. どれも無いとき（既定）: スクリプトの隣の `ai_plc.db`（Claude Code は `.claude/db/ai_plc.db`、Cursor は `.cursor/db/ai_plc.db`）

設定も環境変数も無ければ、今までどおり隣の `ai_plc.db` を使います。`aiplc_paths.py` が無い単体のコピーでも隣の DB を使います。

書き込むコマンドは、決まった DB が git の worktree の中の写しなら `DB_NOT_MAIN`（終了コード 3）で止まり、何も書きません（`AIPLC_DB` で同じパスを明示したときは通します）。読むだけのコマンドは警告を出して続けます。`plc_query.py sql` は、`SELECT`・`WITH`・`EXPLAIN` で始まる文を読むだけの接続で実行し、書き込みを含んでいれば書き込みとして扱い直します。

## 使い方

```bash
python3 .claude/db/plc_query.py projects        # プロジェクト一覧
python3 .claude/db/plc_query.py tasks           # タスク一覧（凍結中は backlog.yaml を表示）
python3 .claude/db/plc_query.py tasks L-1234    # 特定Scopeのタスク
python3 .claude/db/plc_query.py dashboard       # ダッシュボード
python3 .claude/db/plc_query.py sql "SELECT ..."  # 任意SQL
python3 .claude/db/plc_query.py add-project L-1234 "名前" "Goal"   # プロジェクトを登録
```

Project の中止（`cancelled`）への出入りは `project_lifecycle.py`（`plc-lifecycle` スキル）だけで行います。`plc_query.py sql` で `cancelled` に変える・戻す文は、終了コード 3（`PROJECT_LIFECYCLE_COMMAND_REQUIRED`）で取り消されます。

## タスク同期の凍結（`tasks-sync`）

```bash
python3 .claude/db/sync.py tasks-sync --status                                   # 凍結しているか
python3 .claude/db/sync.py tasks-sync --freeze --approved-by <名前> [--reason "<理由>"]   # 凍結する
python3 .claude/db/sync.py tasks-sync --unfreeze --approved-by <名前>             # 戻す
```

- v1.11.0 以前から使っている DB は、installer が書き換えないので凍結されていません。更新の後に `--freeze` を1回実行してください
- 凍結しても tasks テーブルの行は消えません（古い写しとして残るだけ）。凍結中、`sync.py` の pull / push / sync / status は Projects だけを扱い、Notion の Tasks DB には問い合わせません（`AI_PLC_TASKS_DB_ID` も不要）
- Notion の設定が無くても `tasks-sync` は使えます
- 凍結の印が壊れていると、`tasks-sync --status` は `MALFORMED` と出して終了コード 3、`sync.py` の pull / push / sync / status も止まります（`plc_query.py` は凍結として扱い、警告を1行出します）。`tasks-sync --unfreeze --approved-by <名前>` で壊れた印を履歴（`task_sync_unfrozen:<日時>`）に退避して消し、必要なら `--freeze` し直します
- 凍結中の `plc_query.py tasks` は、プロジェクトのルートから intent.yaml を探して backlog.yaml を読みます。隠しフォルダ・`node_modules`・`Documents` などは見ず、シンボリックリンクはたどりません。同じ scope_id の Layer が複数あるときは最初に見つかった1つだけを表示します

## Notion 同期（任意・上級）

`sync.py` で、この SQLite を自分の Notion DB と双方向同期できます。使う場合のみ、環境変数で対象を指定:

```bash
export NOTION_API_TOKEN=<あなたのNotionトークン>
export AI_PLC_PROJECTS_DB_ID=<あなたの Projects DB のID>
export AI_PLC_TASKS_DB_ID=<あなたの Tasks DB のID>   # タスク同期を凍結していれば不要

python3 .claude/db/sync.py preflight    # Notion の DB の列と、保存済みのページのつながりを読むだけで確かめる
python3 .claude/db/sync.py status       # 差分プレビュー
python3 .claude/db/sync.py sync         # 双方向同期
```

使わない場合はローカルDBだけで完結します。コマンドの一覧は `sync.py` の冒頭の Usage にあります。

### Notion の DB に要る列

`sync.py preflight` は、Notion の DB に次の列が**この名前と型で全部**あるかを調べ、足りない・型が違う列があれば `SCHEMA_MISMATCH` で止まります（終了コード 3）。古い版から使っている Notion の DB には、Identity の列（Sync UID など）を Notion の画面で足してください。タスク同期を凍結しているときは Tasks DB を調べません。

| Projects DB の列 | 型 | Tasks DB の列 | 型 |
| --- | --- | --- | --- |
| PJ名 | title | タスク名 | title |
| Goal | rich_text | Task ID | rich_text |
| Scope ID | rich_text | Scope ID | rich_text |
| Owner | people | ステータス | status |
| ステータス | status | タイプ | select |
| モード | select | 優先度 | select |
| 深度 | select | 見積(日) | number |
| システム | select | 成果物 | url |
| 親Scope | rich_text | 完了日 | date |
| トップページ | url | Project Sync UID | rich_text |
| 開始日 | date | Workspace ID | rich_text |
| 期限 | date | Project Ownership Epoch | number |
| Sync UID | rich_text | Identity Version | number |
| Workspace ID | rich_text | | |
| Ownership Epoch | number | | |
| Identity Version | number | | |

### Identity v2.0 への移行（`adopt-existing`）

Identity v2.0 は、各 Project に変わらない ID（`sync_uid`）と、その DB の持ち主を表す `workspace_id` を付ける形です。業務Project の表（`business_registry.py`）はこの形を前提にします。まだ移していない DB（今までの `init_db.py` で作った DB を含む）は、次の手順で移します。Notion を使っていなくても移せます（この手順は Notion に書き込みません）。

> この移行は合成の DB を使った試験で確かめたもので、実際の Notion のワークスペースでの確認はしていません。始める前に `ai_plc.db` の写しを取ってください。

1. Notion と同期している人は、上の列を足してから `python3 .claude/db/sync.py preflight` が `PASS` になることを確かめます
2. 親の Project が無いタスクの行（孤児）を一覧します。この行ごとに扱いを決める必要があります

   ```bash
   python3 .claude/db/plc_query.py sql "SELECT t.scope_id || '/' || t.task_id AS routing_key FROM tasks t LEFT JOIN projects p ON p.scope_id = t.scope_id WHERE p.id IS NULL"
   ```

3. 決めたことを JSON ファイル（`--decisions`）に書きます。孤児が無ければ次の最小の形です

   ```json
   {"adopt_decisions_version": 1, "decisions": []}
   ```

   孤児があるときは、その全部（`routing_key` は 2 の出力の `<scope_id>/<task_id>`）を1件ずつ書きます。足りない・余分・重複があると止まります（`ADOPT_ADJUDICATION_INCOMPLETE`・`ADOPT_DECISION_NOT_ORPHAN`・`ADOPT_DUPLICATE_DECISION`）。同じ Scope の孤児には同じ扱いを書きます（`ADOPT_DECISION_CONFLICT`）。
   - 移さない（`legacy_excluded`）: キーはこの3つだけ。`evidence_digest` は `sha256:` と16進64桁の形かだけを確かめます

     ```json
     {"routing_key": "L-9001/T001", "decision": "legacy_excluded", "evidence_digest": "sha256:<16進64桁>"}
     ```

   - 親の Project を新しく作って移す（`fixed_mapping`）: キーはこの6つだけ。`intent_path` はその Scope の intent.yaml（相対パスは decisions のファイルのあるフォルダから）で、最上位の `scope_id` が孤児の Scope と同じでなければなりません。`evidence_digest` はそのファイルの中身の sha256（`sha256:<16進64桁>`。macOS なら `shasum -a 256 <ファイル>`）、`project_status` は `planned`・`active`・`completed`・`paused` のどれか

     ```json
     {"routing_key": "L-9001/T001", "decision": "fixed_mapping", "evidence_digest": "sha256:<intent.yaml の sha256>",
      "intent_path": "path/to/intent.yaml", "project_name": "<名前>", "project_status": "active"}
     ```

   ファイルの形が違うと `ADOPT_DECISIONS_INVALID`（最上位のキーは `adopt_decisions_version` と `decisions` の2つだけ）、1件の形が違うと `ADOPT_DECISION_INVALID` で止まります（どちらも終了コード 2）。
4. 計画を作ります（DB は書き換えません）。`--writer-id` はこの DB に書く人・端末の名前で、英数字で始まり、英数字と `.`・`_`・`-` だけの64文字以内（例 `writer-main`）

   ```bash
   python3 .claude/db/sync.py adopt-existing --dry-run --decisions decisions.json --writer-id writer-main --plan-out adopt-plan.json
   ```

   出力の `plan_id`（`sha256:` で始まる値）を控えます。同じ `--plan-out` で dry-run をやり直すと、作り直さずに同じ計画を確かめ直します。
5. 計画を実行し、結果を確かめます

   ```bash
   python3 .claude/db/sync.py adopt-existing --plan adopt-plan.json --plan-id <plan_id>
   python3 .claude/db/sync.py adopt-existing --status --plan adopt-plan.json   # state が verified なら完了
   ```

   スクリプトの隣（`.claude/db/`）に `workspace_identity.json` が作られます。途中で止まったときは、同じコマンドで続きから実行します。
6. Notion のページとつながっている行があるときは、Notion のページに Identity の列の値を書き込みます

   ```bash
   python3 .claude/db/sync.py backfill-remote-identity --dry-run --plan-out backfill-plan.json
   python3 .claude/db/sync.py backfill-remote-identity --plan backfill-plan.json --plan-id <plan_id>
   python3 .claude/db/sync.py backfill-remote-identity --status --plan backfill-plan.json
   ```

## スキーマ

- `projects`: scope_id / name / goal / owner / status（planned・active・completed・paused・cancelled。`cancelled` は Goal 未達のまま意図して中止した Project） / mode / depth / system / parent_scope / deadline …。Identity v2.0 の後は workspace_id・sync_uid・ownership_epoch・identity_version も
- `tasks`: task_id / scope_id / name / status / type / priority / estimate_days / output_url / completed_at …。新しく作った DB の status は Notion と同じ日本語（未着手・進行中・完了）。v1.14.0 までの公開版で作った DB の英語の status も `plc_query.py` はそのまま数えます
- `_metadata`: schema_version・タスク同期の凍結の印（`task_sync_frozen`）など
