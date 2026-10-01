---
name: 01-collection-jev
description: 【実験版・Jev監視つき】ai_plc_collection - AI-PLC Stage 1。Execution Contextを確立し、外部・内部情報源からコンテキストを収集・構造化する。
---

# AI-PLC Stage 1: Collection（Jev実験版）

> 🧪 **実験版（ai-plc-jev 1.12.0-exp.2）:** 公開 core の `.claude/skills/ai-plc/01-collection/SKILL.md`（v2.2）の代わりに `/01-collection-jev` で使う試行用のスキル。**本体の SKILL・rules は書き換えない。** 公開 core 2.2 との違いは Jev 監視（opt-in）に関わる箇所だけ（intent.yaml の `jev_monitor` 欄のコメント、Phase 6.5 の opt-in 判定〔自動完走中も自動で承認しない〕、Phase 7 の Next Action と 4. の /goal 1行を `-jev` に）。詳細は `.claude/skills/ai-plc-jev/README.md`。

パイプライン（Collection → Inception → Construction → Operation）の初期化ステージ。Goal と Mode を受け取り、Execution Context（Scope）を確立し、Context を収集・構造化する。

**共通規約:** 命名は RUL_plc_system §6 / 完了報告は RUL_plc_session §7（4パート）/ Phase遷移通知は §8 / Mob CP出力は §9 に従う。

**自動完走モード:** セッション中に RUL_plc_session §10 を指す /goal があるときは §10 に従い、Phase 7 も待たずに進める（無ければ本 SKILL のとおり止まる）。Phase 1 で RUL_plc_adaptive §0 の①に当たった場合と、complex・platform_builder と判定した場合は停止する（§10 の停止）。

## 入力

| 入力 | 必須 | 説明 |
| --- | --- | --- |
| goal | ✅ | 達成すべき目標の自然言語記述 |
| mode | ⭕ | direct / platform_builder（デフォルト: direct） |
| owner / deadline | ⭕ | デフォルト: 現在のユーザー / +30d |
| parent_scope | ⭕ | 親ScopeのURL/パス。Sub-Agent Scope作成時に指定 |
| scope_name | ⭕ | デフォルト: Goalから自動生成 |

## 実行フロー

### Phase 0: Scope判定

- parent_scope なし & 既存Scope指定なし → `pipeline_init`（新規パイプライン）
- parent_scope あり → `sub_agent_scope`（親配下のsublayers/に作成、親Context継承）
- 既存Scope指定あり → `scope_reinit`（構造・成果物を保持してIntent/Manifestを更新）

### Phase 1: Adaptive Workflow深度判定

RUL_plc_adaptive §1 に従い simple / standard / complex を判定し（§0 の表の深度の目安と食い違えば、その理由も `workflow_depth_reason` の同じ行に書く）、結果と根拠をユーザーに報告する（変更指示があれば従う。停止はしない。§0 の①〔Layer を作らない〕に当たれば、その旨を報告し、続けるかをユーザーに聞く）。深度と、その理由を intent.yaml に記録する: `workflow_depth_reason`（1行）と、参考として `depth_axes`（判定の条件にはまだ使わない。各軸を S〔軽い〕か H〔重い＝問いに「はい」。V だけは「いいえ」が H〕で書く）— R 受け手「成果物を自分以外が読んで何かを決めるか」／U やり直し「AI 自身が行う操作で、間違えたとき元に戻すのに他人や外部が絡むか（公開・送信・本体のルールやスキル・外部 DB・削除・お金）」／V 確かめ方「完了の条件を人の判断なしに ○/× できるか（できなければ H）」／C 固有の文脈「このリポジトリや組織の資料を読まないと書けないか」。

### Phase 2: ディレクトリ構造生成

`Flow/[YYYYMM]/[YYYY-MM-DD]/[Scope名]/` に作成（既存Flowを使用。日付フォルダは当日分を使用、なければ作成）:

```
[Scope名]/
├── intent.yaml / context.yaml / backlog.yaml（空で初期生成）
├── Context/      （Context Store）
├── Agents/       （Stage 3 を通したときだけ生成）
├── sublayers/    （Stage 2で生成）
└── Documents/    （Stage 4で生成）
```

sub_agent_scope時は親の `sublayers/` 配下に同構造。scope_reinit時は既存構造を維持。

### Phase 3: Intent生成（intent.yaml）

```yaml
scope_id: "L-MMDD"            # 自動採番（重複時は L-MMDD-2 等。Sub: L-MMDD-SG1）
scope_name: "[Scope名]"
status: active
workflow_depth: standard      # Phase 1の判定結果
workflow_depth_reason: "[1行。§1 の判定理由。§0 の当たった行（例: ②③）]"
depth_axes: {R: S, U: S, V: S, C: S}   # 参考。R 受け手・U やり直し・V 確かめ方・C 固有の文脈
goal:
  description: "[Goal]"
  success_criteria: []        # Context収集後に設定
mode: direct                  # direct / platform_builder
owner: "[Owner]"
deadline: "YYYY-MM-DD"
parent_scope: null
sub_agent_scopes: []          # Stage 2で生成
sync_targets: []              # Phase 6.5で設定（スキーマ: RUL_plc_system §9）
jev_monitor: false            # Phase 6.5で判定。trueのLayerのみ04-operation-jevがJev監視を呼ぶ（opt-in）
```

### Phase 3.5: Project Registry登録

`.claude/db/ai_plc.db` の `projects` テーブルに登録（scope_id/name/goal/owner/status=active/mode/depth/system=AI-PLC/parent_scope/top_page_url/start_date/deadline）し、「📊 Project Registryに登録しました」と通知する。scope_reinit時はスキップ。登録は `python3 .claude/db/plc_query.py add-project <scope_id> "<name>" "<goal>"` で行い、残りの列は `plc_query.py sql "UPDATE projects SET ... WHERE scope_id='<scope_id>'"` で更新する（SQLで直接INSERTしない）。

### Phase 4: Context Collection

RUL_plc_system §16 の優先順位で収集する。**内部・既存資産を最優先**し、利用可能なものだけ使う（未接続MCP・未導入ツールは黙ってスキップ）。各収集は §17 に従い件数を絞る（LIMIT必須）。

1. **ワークスペース横断検索** — Flow日付フォルダ・Stock/programs を起点に、Grep/Glob で全域を串刺し検索。`serena` 等のセマンティック検索が使えれば意味的に近い過去成果物も拾う
2. **Project Registry照会** — `.claude/db/plc_query.py` で `projects` を Goalキーワード検索し、関連PJ・親PJ・同ドメインの過去PJ（scope_id/goal/status）を引く
3. **wiki検索** — `.claude/wiki/index.md` を読み、Goalに関連する概念ページ（設計知見・学び・バグパターン・矛盾フラグ）を拾う
4. **native memory参照** — ユーザーモデル・好み・進行中PJの状態を踏まえる（§7準拠）
5. **接続済みMCP/検索ツールの動的活用** — 環境に接続された検索系（Notion / Drive / Gmail / serena 等のMCP）を検出して使う。無ければスキップ。GitHubは `gh` CLI（`gh search ...`）が確実（MCPは環境依存でトークン伝播に失敗しうる）
6. Standard/Complex で内部が不足する場合のみ **外部Web検索**で補う
7. sub_agent_scope では親のContext Storeを読み込み、Context Cascade 3分類（RUL_plc_system §2）で継承
8. `Context/` にカテゴリ別ドキュメントとして格納（例: 01_関連PJ・既存知見.md / 02_技術・制約.md / 03_関連リンク集.md — Goalに応じて調整）。各Context冒頭に**収集元**（Registry/wiki/横断/MCP/Web）を明記する

### Phase 5: Context Manifest生成（context.yaml）

```yaml
version: "1.0"
scope_id: "L-MMDD"
generated_at: "YYYY-MM-DD"
parent_context_store: null      # sub_agent_scope時は親Context/のパス
context_documents:
  - name: "[カテゴリ名]"
    url: "@Context/01_[カテゴリ].md"
    summary: "[3-5行の要約]"
inheritance_rules:
  global_immutable: ["vision", "tech_stack"]
  overridable: ["deadline", "budget"]
  local_only: ["team", "tools"]
```

### Phase 6: Parameter Store生成 [platform_builder時のみ]

変数化可能なポイントを特定し `variables.yaml`（variables: 型/説明/必須/デフォルト + variable_mappings: task_id→変数）を生成する。direct時は作成しない。

### Phase 6.5: External Sync設定

intent.yamlのsync_targetsを設定する: ユーザー指定の同期先があればそれを、なければデフォルト（`.claude/db/ai_plc.db` の projects テーブル、push — RUL_plc_system §9。タスクは同期しない: tasks テーブルは凍結）を自動設定し、「📊 External Sync設定: [設定内容]」とログ出力する。ユーザーが「同期不要」と明言した場合のみ `[]` のまま。

> ⚠️ **Layer成果物をNotion同期する場合のスコープ注意（nsync）:** このLayerの成果物ページをNotionと双方向同期したいなら、**このLayer自身のNotionページをrootにした専用nsyncワークスペースを `nsync init <LayerページURL>` で切り出す**こと。既存の広域ワークスペース（例: プログラム全体をrootにした `.nsync.yaml`）の**サブフォルダとして相乗りしない** — nsyncの `sync` はroot配下全体が対象で、Layer単位に絞れず、無関係な変更や機密ファイルまで巻き込んでPushする。機密Context（会計実数・個人情報等）は同期ツリーの外に置くか `exclude_paths` に登録する。

**Jev監視（opt-in）の判定:** 既定は `jev_monitor: false`。Goal・Contextが外部送信禁止の区分（機密PJ・経費/finance・人事/キャリア・顧客名/人名・趣味/私生活）に当たらない場合だけ、Phase 7の確認表示で「Jev監視（Backtrackの異常ヒント、外部API送信あり）を有効にするか」を1行で示し、承認されたら `true` にする（自動完走中もこの承認は自動で出さない — `04-operation-jev` の「Jev監視ルール」）。該当する場合は提示せず `false` のまま（理由を1行ログ）。仕組みは `04-operation-jev` の「Jev監視ルール」。**Jev版で始めたLayerは intent.yaml に `pipeline_variant: jev` を記録し、以降も `/02-inception-jev` → `/03-construction-jev`（要るときだけ — RUL_plc_adaptive §6）→ `/04-operation-jev` で実行する**（02・03は本体スキルを読む薄いラッパー）。

### Phase 7: Mob Checkpoint（停止）

ここで必ず停止し、ユーザーの応答を待つ:

1. 作成した構造と深度判定結果を確認表示
2. RUL_plc_session §7 の4パート（📍現在位置 / ✅完了サマリ / 📊進捗 / 🔜Next Action Protocol）を出力
3. Next Action: A=/02-inception-jev 実行（⭐推奨） / B=Context追加修正（+コピペ用プロンプト。表記は RUL_plc_session §7.4「実行形式は環境の正」。即実行禁止）
4. **自動で進める案内:** 完了報告の最後に「自動で進めるなら:」として RUL_plc_session §10 の短い版 /goal を、Layer パスと開始列（§10 の開始列）を埋めて1行出し（`pipeline_variant: jev` の Layer は各コマンドを -jev 版に）、直後に「ターン上限で止まったら同じ /goal を貼り直す」と添える（止まる挙動は変えない。/goal はユーザーが貼る）。workflow_depth が complex か mode が platform_builder の Layer では /goal を出さず、「自動完走の対象外（理由）」を1行出す。workflow_depth が simple で Collection が backlog を作るときは、RUL_plc_adaptive §6 の①〜⑤を判定して `construction`（required・reason・tasks）を書く。自動完走中（§10）は、この Phase 7 も⭐（/02-inception-jev。simple で backlog が空なら §10 の表の「simple で backlog が空」）で進む。Jev 監視の opt-in の確認は自動承認せず false のままにする

## Re-Collection（Backtrack対応）

BT-B（ゴールドリフト）/ BT-C（全完了GAP分析）から scope_reinit で呼び出される再実行モード（RUL_plc_adaptive §5）:

1. 既存intent.yamlを読み込み、Backlog完了実績 vs 元ゴールの到達度を分析
2. GAP分析（達成済み / 未達成 / 新規発見）を表形式で出力
3. 判定: GAPなし→完了推奨 / GAPあり→Intent.goal更新+Re-Inception推奨 / ドリフト→ゴール再定義+追加Context収集
4. ゴール変更時はContext Store追加収集 + Manifest更新

## 出力

intent.yaml / context.yaml / Context/（常に） / backlog.yaml（空で初期生成） / variables.yaml（platform_builder時のみ）→ Stage 2: SKL_plc_02_inception へ。

---
**作成日:** 2026-04-06 ｜ **更新日:** 2026-10-01 ｜ **バージョン:** 2.2-jev（公開実験版 1.12.0-exp.2。公開 core 01-collection 2.2 に Jev 監視の opt-in を足したもの。Phase 6.5 の External Sync の既定を projects に〔タスクは同期しない — RUL_plc_system §9〕も core 2.2 と同じ）｜ 2.1-jev（公開実験版 1.8.1-exp.1）
