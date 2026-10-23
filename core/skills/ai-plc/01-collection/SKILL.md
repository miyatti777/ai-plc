---
name: 01-collection
description: ai_plc_collection - AI-PLC Stage 1。Execution Contextを確立し、外部・内部情報源からコンテキストを収集・構造化する。
---

# AI-PLC Stage 1: Collection

パイプライン（Collection → Inception → Construction → Operation）の初期化ステージ。Goal と Mode を受け取り、Execution Context（Scope）を確立し、Context を収集・構造化する。

**共通規約:** 命名は RUL_plc_system §6 / 完了報告は RUL_plc_session §7（4パート・説明の詳しさは §7.0）/ Phase遷移通知は §8 / Mob CP出力と質問UIは §9・§9.1 に従う。

**ライブ表示:** 公開版にはライブ表示（BacklogLive）は無い。手元に `tools/BacklogLive/server.py` があるときだけ使える（無ければ何もしない）。

**自動完走モード:** セッション中に RUL_plc_session §10 を指す /goal があるときは §10 に従い、Phase 7 も待たずに進める（無ければ本 SKILL のとおり止まる）。Phase 1 で RUL_plc_adaptive §0 の①に当たった場合と、complex・platform_builder と判定した場合は停止する。明示 force は §10.1。

**選択した方式だけ読む（発動条件は3つ）:** 同梱の PM アドオン（目録 [addon-catalog.yaml](../references/addon-catalog.yaml) の aipm。旧い欄 `work_style: aipm` も同じ）が選ばれた Layer は [aipm-guided](../../aipm-guided/SKILL.md)、`dev_style: <your_style>`（開発方式）を選んだ Layer は完成ゲートでその開発方式の規約（チェックポイント・PR の作り方・レビュー）を使い、持ち込みのアドオン（`intent.addons` の case の件）がある Layer は [addon-seam.md](../references/addon-seam.md) を該当 Phase で読む。どれが選ばれているかは、intent の `work_style` が null 以外か `addons` が空でないときだけ、判定関数 `python3 -B .claude/skills/ai-plc/scripts/plc_addon_select.py --layer <Layer>`（目録を読む・書き込まない。持ち込みの件があるときは `--read-root <実許可root>`、scope: common なら `--common-root <root>` も付ける。plc_addon.py と同じ）で確かめる（`route` が `held` なら `hold_reasons` を出して止める。同梱は `selected[].addon_id`、持ち込みは `has_case_addons`）。どれも無い Layer（既定＝MVP）は判定関数も呼ばず、本 SKILL と rules だけで進め、契約・binding・予算の文書を読まない。

## 入力

| 入力 | 必須 | 説明 |
| --- | --- | --- |
| goal | ✅ | 達成すべき目標の自然言語記述 |
| mode | ⭕ | direct / platform_builder（デフォルト: direct） |
| owner / deadline | ⭕ | デフォルト: 現在のユーザー / +30d |
| parent_scope | ⭕ | 親ScopeのURL/パス。Sub-Agent Scope作成時に指定 |
| scope_name | ⭕ | デフォルト: Goalから自動生成 |
| explanation | ⭕ | brief / reasoned / guided（RUL_plc_session §7.0） |

## 実行フロー

### Phase 0: Scope判定

- parent_scope なし & 既存Scope指定なし → `pipeline_init`（新規パイプライン）
- parent_scope あり → `sub_agent_scope`（親配下のsublayers/に作成、親Context継承）
- 既存Scope指定あり → `scope_reinit`（構造・成果物を保持してIntent/Manifestを更新）。intent.status が cancelled なら RUL_plc_system §21 の再開手順（plc-project-status）へ案内して止まる

### Phase 1: Adaptive Workflow深度判定

RUL_plc_adaptive §1 に従い simple / standard / complex を判定し（§0 の表の深度の目安と食い違えば、その理由も `workflow_depth_reason` の同じ行に書く）、結果と根拠をユーザーに報告する（変更指示があれば従う。停止はしない。§0 の①〔Layer を作らない〕に当たれば、その旨を報告し、続けるかをユーザーに聞く）。深度と理由を intent.yaml に記録する: `workflow_depth_reason`（1行）と、参考として `depth_axes`（R 受け手・U やり直し・V 確かめ方・C 固有の文脈を S/H で。判定の条件にはまだ使わない）。

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

本人の原要求の原文と出典を `request_provenance` に保ち、後続の明示変更は `explicit_changes` に足す（Goal の要約で原文を置き換えない。既存の原文が無い Layer では捏造せず未取得のままにする）。

scope_id は Phase 3.5 の add-project が `[OK]` を返してから intent に書く（番号を決めたら、intent・context を書く前に Phase 3.5 の登録を先に行う）。

```yaml
scope_id: "L-MMDD"            # 自動採番（重複時は L-MMDD-2 等。Sub: L-MMDD-SG1）
scope_name: "[Scope名]"
display_name: "[人向けの短い表示名。未設定なら scope_name]"
status: active
workflow_depth: standard      # Phase 1の判定結果
workflow_depth_reason: "[1行。§1 の判定理由。§0 の当たった行（例: ②③）]"
depth_axes: {R: S, U: S, V: S, C: S}
goal:
  description: "[Goal]"
  success_criteria: []        # Context収集後に設定
mode: direct                  # direct / platform_builder
explanation: {level: reasoned} # 任意。入力/本人希望優先。未回答時の既定であって本人の選択ではない
owner: "[Owner]"
deadline: "YYYY-MM-DD"
parent_scope: null
sub_agent_scopes: []          # Stage 2で生成
sync_targets: []              # Phase 6.5で設定（スキーマ: RUL_plc_system §9）
jev_monitor: false            # Phase 6.5で判定。trueのLayerのみ04-operationがJev監視を呼ぶ（opt-in）
classification:               # Registry の分類（書き方は .claude/db/README_classification.md）
  affiliation: <語彙のキー>    # 所属。`python3 .claude/db/classify.py vocab` の一覧から選ぶ。決められない・classify.py が無い環境ではこの行を書かない（スキップ）
  kind: <語彙のキー>           # 種類。同上
  executor: claude-code        # この Collection を実行している環境: claude-code / codex / cursor
request_provenance:
  original_request: {text: "[原文]", source: "[出典]"}
  explicit_changes: []
# 本人が選んだときだけ書く: addons の同梱の1件（PM アドオン。{addon_id: aipm, source: bundled, addon_version, selection_ref}。references/aipm-recommendation.md の手順で書き、work_style は書かない）/ dev_style: <your_style>（開発方式） / addons の持ち込みの件
```

### Phase 3.5: Project Registry登録

`.claude/db/ai_plc.db` の `projects` テーブルに登録（scope_id/name/goal/owner/status=active/mode/depth/system=AI-PLC/parent_scope/top_page_url/start_date/deadline）し、「📊 Project Registryに登録しました」と通知する。scope_reinit時はスキップ。登録は `python3 .claude/db/plc_query.py add-project <scope_id> "<name>" "<goal>"` で行い、残りの列は `plc_query.py sql "UPDATE projects SET ... WHERE scope_id='<scope_id>'"` で更新する（SQLで直接INSERTしない。Identity v2 schemaではIdentityが付かず同期対象外になる）。

add-project が `SCOPE_ALREADY_EXISTS`（終了コード2）を返したら次の番号（-2・-3 …）で取り直す（3回まで。取れなければ止まって報告）。ほかの `[BLOCKED]` では止まる。add-project の直後に、top_page_url を自分の Layer のパス（リポジトリ相対）にする UPDATE を最初に行う。UPDATE の列名は intent のキーと違うものがある：`workflow_depth`→`depth`、Layer のパス→`top_page_url`（ほかは同じ名前）。`sql` は失敗しても終了コード0なので、出力に `Error:` が無いことを確かめる。Cloud では add-project がキューに積まれるだけですぐ確定しないので、この手順は Mac のもの（Cloud の番号の扱いは未確定）。

### Phase 4: Context Collection

RUL_plc_system §16 の優先順位で収集する。**内部・既存資産を最優先**し、利用可能なものだけ使う（未接続MCP・未導入ツールは黙ってスキップ）。各収集は §17 に従い件数を絞る（LIMIT必須）。

1. **ワークスペース横断検索** — Flow日付フォルダ・Stock/programs を起点に、Grep/Glob で全域を串刺し検索。`serena` 等のセマンティック検索が使えれば意味的に近い過去成果物も拾う
2. **Project Registry照会** — `.claude/db/plc_query.py` で `projects` を Goalキーワード検索し、関連PJ・親PJ・同ドメインの過去PJ（scope_id/goal/status）を引く
3. **wiki検索** — `.claude/wiki/index.md` を読み、Goalに関連する概念ページ（設計知見・学び・バグパターン・矛盾フラグ）を拾う
4. **native memory参照** — ユーザーモデル・好み・参照を踏まえる（§7準拠）。関連 PJ の経緯は 1・2（横断検索・Registry）で Layer から引く
5. **接続済みMCP/検索ツールの動的活用** — 環境に接続された検索系（Notion / Drive / Gmail / serena 等のMCP）を検出して使う。無ければスキップ。GitHubは `gh` CLI が確実
6. Standard/Complex で内部が不足する場合のみ **外部Web検索**で補う
7. sub_agent_scope では親のContext Storeを読み込み、Context Cascade 3分類（RUL_plc_system §2）で継承
8. `Context/` にカテゴリ別ドキュメントとして格納（例: 01_関連PJ・既存知見.md / 02_技術・制約.md / 03_関連リンク集.md）。各Context冒頭に**収集元**（Registry/wiki/横断/MCP/Web）を明記する。**wiki と native memory は、見たものを名前つきで1行ずつ書く:** `wiki: [slug]（[節名 or 日付]）→ 使った: [何に] / 該当なし` ・ `memory: [ファイル名] → 使った: [何に] / 該当なし`（見なかったら「wiki: 見ていない」）

**Goal の明確化と Inception との役割分担:** Context 収集後も Goal・成功条件・根本的な範囲が曖昧で、その違いが仕事を変える場合だけ RUL_plc_session §9 に従って確認する（自動完走中は §10 の仮定・停止規約を優先）。Goal 内のタスクの粒度・優先・範囲外・受け手に関する分解の未決定は Context に残して Inception Phase 1.5 へ渡す。資料から答えが出ることや、既に確定した Goal は聞き直さない。


### Phase 4.5: 方式の推薦（同梱の PM も work_method を宣言した持ち込みのアドオンも未選択のときだけ・任意）

Goal が「利用者を探索して課題→仮説→ストーリーに落とす」性質で、本人がまだ方式を選んでいない（同梱の PM も、排他の組 work_method を宣言した持ち込みのアドオンも選ばれていない）ときだけ、[aipm-recommendation.md](references/aipm-recommendation.md) に従って Phase 7 の確認表示で AIPM 方式（同梱の PM アドオン）を1行で勧める。推薦は選択ではない。既選択・辞退済み・自動完走中は出さない。

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

intent.yamlのsync_targetsを設定する: ユーザー指定の同期先があればそれを、なければデフォルト（`.claude/db/ai_plc.db` の projects テーブル、push — RUL_plc_system §9。タスクは同期しない）を自動設定し、「📊 External Sync設定: [設定内容]」とログ出力する。「同期不要」と明言された場合のみ `[]` のまま。Notion 同期はこの Layer のページを root にした専用 nsync ワークスペースで（広域に相乗りしない。機密 Context は `exclude_paths` へ）。

**Jev監視（opt-in）の判定:** 既定は `jev_monitor: false`。Goal・Contextが外部送信禁止の区分（機密PJ・経費/finance・人事/キャリア・顧客名/人名・趣味/私生活）に当たらない場合だけ、Phase 7の確認表示で「Jev監視（Backtrackの異常ヒント、外部API送信あり）を有効にするか」を1行で示し、承認されたら `true` にする（自動完走中もこの承認は自動で出さない）。該当する場合は提示せず `false` のまま（理由を1行ログ）。仕組みはRUL_plc_adaptive §5 実行ルール6。

### Phase 7: Mob Checkpoint（停止）

ここで必ず停止し、ユーザーの応答を待つ（§9.1 の質問UIを呼び、同文を会話にも残す）:

1. 作成した構造と深度判定結果を確認表示。説明の詳しさ（§7.0）の3候補と現在値を添える（選択済みなら再質問しない）
2. RUL_plc_session §7 の4パート（📍現在位置 / ✅完了サマリ / 📊進捗 / 🔜Next Action Protocol）を出力
3. Next Action: A=/02-inception 実行（⭐推奨） / B=Context追加修正（+コピペ用プロンプト。表記は RUL_plc_session §7.4「実行形式は環境の正」）
4. **自動で進める案内:** 完了報告の最後に「自動で進めるなら:」として RUL_plc_session §10 の短い版 /goal を、Layer パスと開始列を埋めて1行出し、「ターン上限で止まったら同じ /goal を貼り直す」と添える。complex か platform_builder の Layer では出さず「自動完走の対象外（理由）」を1行出す。simple で Collection が backlog を作るときは、[成果単位の分解](../references/outcome-delivery.md)の要点（小さい単発は1Task、複数の意味ある増分があればスライス）に従い、RUL_plc_adaptive §6 の①〜⑤を判定して `construction`（required・reason・tasks）を書く
5. **分類（`classification`）:** 確認表示に所属・種類（`classify.py vocab` の表示名。機密の所属は画面にキーだけを出す）と実行環境を出し、`python3 .claude/db/classify.py sync --layer <Layer> --require-owner --yes` で Registry に写す。終了コード1（Registry の行が別の Layer を指す・行が無い）なら書かずに理由を出し、本人に伝える。修正指示で分類を直したら intent.yaml を直してから sync をやり直す。自動完走中は affiliation・kind を語彙の keywords で1つに決まるときだけ書き、executor は常に書く。classify.py が無い環境（終了コード 2）では「分類: スキップ（理由）」を1行出して進む

### Phase 7.5: 初期化の段（宣言があるときだけ・停止）

選んだ方式の参照先（「選択した方式だけ読む」の3つ）が**初期化が要る**とする宣言を、この Layer の intent・アドオンの manifest・同梱のアドオンは目録の `init`（記録先 `record`。aipm は `mode_init`）から見つけたときだけ行う。宣言が無ければ何も出さず、Phase 7 で終わる（モード名はこの SKILL に書かず、何を作るかは各参照先が決める）。

1. 宣言を見つけたら intent に `mode_init: {state: pending}` を書く（Phase 7 の確認表示と同時でよい）
2. Phase 7 の OK の後、作るもの（パスと中身の概要）を示して**別の OK** を待つ（§9.1。自動完走中は §10 の書き込み範囲に当たれば⭐で進め、当たらなければ保留）
3. OK の後に参照先の手順で初期化を実行し、intent に `mode_init: {state: done, done_at: <ISO 日時>, outputs: [{path, sha256}]}` を書く。既にあるもの（既存の Project など）は上書きしない
4. 失敗・保留なら `state: pending` のまま理由を1行残し、Inception・Operation へ進めない（02-inception と 04-operation が Hold する）。pending の間は Phase 7 の自動完走の /goal を出さない

`mode_init` の無い旧い Layer は今までどおり扱い、一括で書き足さない。

## Re-Collection（Backtrack対応）

BT-B（ゴールドリフト）/ BT-C（全完了GAP分析）/ 本人の明示指示から scope_reinit で呼び出される再実行モード（RUL_plc_adaptive §5）:

1. 既存intent.yamlを読み込み、Backlog完了実績 vs 元ゴールの到達度を分析
2. GAP分析（達成済み / 未達成 / 新規発見）を表形式で出力
3. 判定: GAPなし→完了推奨 / GAPあり→Intent.goal更新+Re-Inception推奨 / ドリフト→ゴール再定義+追加Context収集
4. ゴール変更時はContext Store追加収集 + Manifest更新。原文と変更履歴（request_provenance・goal_history）は保つ

## 出力

intent.yaml / context.yaml / Context/（常に） / backlog.yaml（空で初期生成） / variables.yaml（platform_builder時のみ）→ Stage 2: /02-inception へ。

---
**作成日:** 2026-04-06 ｜ **更新日:** 2026-10-22 ｜ **バージョン:** 3.0（PM の選択は addons の同梱の1件で書く（雛形）／方式の判定を目録と判定関数へ（読み方は同じ）／軽量化: 10/1 版（v2.7）を土台に、AIPM/DevStyle/アドオンの契約本文を外し、発動条件3つ（work_style / dev_style / addons）と1行参照だけを残す。request_provenance・explanation・cancelled の再開案内・Phase 7 の質問UIは要点だけ保持。以前の版履歴は git）
