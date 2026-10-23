---
name: 02-inception
description: ai_plc_inception - AI-PLC Stage 2。Goalを分析し、BacklogとSub-Agent Registryを生成する。
---

# AI-PLC Stage 2: Inception

Goalを分析し、Sub-Agent Scope（SubLayer）とTask（実行単位）に再帰的に分解するステージ。Sub-Agent Scopeが生成されると、そのスコープ内でStage 1から再びパイプライン全体が展開される（Fractal Decomposition）。

**共通規約:** 命名は RUL_plc_system §6 / 完了報告は RUL_plc_session §7（説明の詳しさは §7.0）/ Phase遷移通知は §8 / Mob CP出力と質問UIは §9・§9.1 に従う。

**ライブ表示:** 公開版にはライブ表示（BacklogLive）は無い。手元に `tools/BacklogLive/server.py` があるときだけ使える（無ければ何もしない）。

**自動完走モード:** セッション中に RUL_plc_session §10 を指す /goal があるときは §10 に従い、Mob Checkpoint・Next Action・タスク選択で待たずに進める（無ければ本 SKILL のとおり止まる）。明示 force は §10.1。

**選択した方式だけ読む（発動条件は3つ）:** 同梱の PM アドオン（目録 [addon-catalog.yaml](../references/addon-catalog.yaml) の aipm。旧い欄 `work_style: aipm` も同じ）が選ばれた Layer は [aipm-guided](../../aipm-guided/SKILL.md) の「Stageとの接続 2」（必須文書・工程順・`aipm.registers: true` のときの論点の表の条件と wbs_id・issue_id）を分解の制約にする。`dev_style: <your_style>`（本人が選んだ開発方式）の Layer は開発 Task の完成ゲートに「その開発方式の規約（チェックポイント・PR の作り方・レビュー）を通す」を AC に1行書く（binding・予算・版照合は書かない）。持ち込みのアドオン（`intent.addons` の case の件）がある Layer は [addon-seam.md](../references/addon-seam.md) の型を使う Task に `addon_refs` を付ける。アドオンの binding が指す案内（guide）に運用タスクの雛形の宣言（`recurring_templates`）があれば、`plc_addon.py --stage inception_recurring` の案を分解表に入れて承認を取り、承認の後に backlog に書く（雛形の name は変えずに書く。出どころは description に書く。同じ雛形を名前で見分けて重ねて出さないため）。どれが選ばれているかは、intent の `work_style` が null 以外か `addons` が空でないときだけ、判定関数 `python3 -B .claude/skills/ai-plc/scripts/plc_addon_select.py --layer <Layer>`（目録を読む・書き込まない。持ち込みの件があるときは `--read-root <実許可root>`、scope: common なら `--common-root <root>` も付ける。plc_addon.py と同じ）で確かめる（`route` が `held` なら `hold_reasons` を出して止める。同梱は `selected[].addon_id`、持ち込みは `has_case_addons`）。どれも無い Layer（既定）は判定関数も呼ばず、本 SKILL と rules だけで分解する。

## 入力

| 入力 | 必須 | 説明 |
| --- | --- | --- |
| Intent + Context Manifest + Context Store | ✅ | Stage 1の生成物 |
| decomposition_strategy | ⭕ | product_manager / system_architect / content_strategist / tech_lead / generic。デフォルト: AI自動判定 |

## 実行フロー

### Phase 1: 既存成果と未達の確認

intent.yaml / context.yaml / backlog.yaml / 必要な Context Store を読む。intent.status が cancelled なら RUL_plc_system §21 の再開手順へ案内して止まる。intent に `mode_init` があり state が done でなければ Hold し、/01-collection の Phase 7.5（初期化の段）へ案内する（`mode_init` の無い Layer は今までどおり）。既存の原要求・明示変更、成立済み成果、Goal/SC の未達を先に照合し、追加収集は今回の分解判断を変える不足だけに限る（新セッションを理由に調査をやり直さない。実装詳細の調査は原則その成果 Task の中に置く）。

### Phase 1.5: 分解前インタビュー（必要なときだけ）

Goal・成功条件・根本的な範囲が曖昧なら、新しいGoalを仮定して分解せず Collection の補完／Re-Collection を提案して止まる。Goal が確定している場合だけ、回答でタスクの粒度・優先・依存・AC・範囲外・受け手への説明が変わる未決定を確認する。コード・規約・Context で答えが出る事項は読むだけとし、不明点が無ければ質問を省略して Phase 2 へ進む。

- 通常セッション: RUL_plc_session §9 の Material Ambiguity に当たるものだけ、影響の大きい順に**1問ずつ、合計最大3問**。選択肢は現実的なもの最大3つ、各選択肢に結果＋作業量、推奨理由は選択肢の後。§9.1 の質問UIで聞き、回答を待ってから進む
- 自動完走中: 質問をせず最も妥当な仮定を置き、`refactoring_log` に `[auto-approved] S2/P1.5: …` と1行残す。データ・権限・受け手に見える挙動は保守的に
- 3問で残った不明点は、Goal内の戻せる小さな案で分解できる場合だけ仮定し、残件を Phase 4 に示す。安全な案が作れなければ Collection に戻る案を出して止まる。質問への回答は Phase 4 の分解承認ではない

### Phase 2: Decomposition Strategy選択

Goalの性質から最適な戦略を判定する（ユーザー指定があれば優先。判定結果を報告して続行）:

| 戦略 | 適用 | 分解の特徴 |
| --- | --- | --- |
| product_manager | プロダクト開発・改善 | 一つの利用者成果が成立する小さい単位。Discovery 等は Task 内手順 |
| system_architect | システム構築・基盤整備 | 一つの利用経路が実動する単位。設計/モジュールは内部手順 |
| content_strategist | コンテンツ制作・発信 | 受け手/用途に使える一つの完成成果。配信は依頼/許可範囲のみ |
| tech_lead | コーディングPJ（複数実装タスク） | Adaptive Skip判定 + SubLayer分割 |
| generic | その他 | Contextから動的判断 |

### Phase 3: Goal分解

**成果スライスの原則（[outcome-delivery.md](../references/outcome-delivery.md) の要点）:** 最終 Goal → 段階ごとの利用/判断状態の増分 → Task の順に切る。大きい依頼は「各段階で利用者の状態が変わり証拠が残る」複数スライスに分け、短い単発は理由付きで1Task にする。必要な調査は各成果スライスの中に含め、独立の調査 Task は「調査自体が依頼成果」か「結果で方式/可否が変わる重大な未知」に限る（後者は判断・終了条件・結果別の後続先を書く）。Role の典型フェーズや技術スタックだけで分割しない。description・AC・guardrails に、対象／前段からの増分／証拠／次段階／許可境界を含める。

Goalを2種に分類する:

- **SubLayer化:** 複数Taskで構成 / 独自Contextが必要 / 他者に委譲可能 / 独立スケジュール → 再帰展開（詳細タスクは親で作らない。親のmodeを継承）
- **Task化:** 1-2日で完結 / これ以上分解不要 / 管理・調整系

### Phase 4: Mob Checkpoint — 分解承認（停止）

ここで必ず停止し、承認を待つ（タスク数が少なくても省略しない。§9.1 の質問UIを呼ぶ）:

1. SubLayer/Task分解テーブル（ID・名称・type・priority・依存・見積・繰り返す運用タスクなら recurrence・実行時期があれば scheduled_for・成立する成果と AC の要点・Agent 定義の要否〔要なら理由＝RUL_plc_adaptive §6 の①〜⑤〕）を提示。各スライスの前→後の状態、1Task なら分割不要の理由、選択方式があれば必須工程への対応を添える
2. セッション分割判定（SubLayer≥3 or Task≥10 → RUL_plc_session §1に従い分割推奨を明記）
3. 承認後フロー1行 + 🙋承認待ちブロック（OK / 修正: [指示] / 差し戻し）。**この OK が開始ゲート**＝承認された Task は実装・検証まで一括で許可され、工程ごとの再承認は要らない（RUL_plc_adaptive §0 ⑤の操作だけは実行前に個別確認）

### Phase 5: Backlog + Sub-Agent Registry生成

承認後、backlog.yaml を生成する:

- **全タスク必須フィールド:** `id` / `name` / `description` / `type` / `priority` / `status` / `owner` / `estimated_hours` / `command` / `origin`（commandはmanagement系タスクのみnull可）、standard 以上は `acceptance_criteria`（検証できる形のリスト）。任意: `guardrails`（タスク固有の禁止事項・途中で人に確認する点）/ `delegable`（既定 false。true は途中で人の確認が要らないタスクだけ）/ `command_template_ref`（Construction が書く）/ `output`（成果物のパス）/ `recurrence`（繰り返す運用タスク：`daily`・`weekly`・`per_meeting`。Operation で実行しても completed にせず `runs`〔date・summary・output・checked_ac〕に1行ずつ足し、Layer を閉じるときに `retired_at`・`retired_reason` を付ける。status の値は増やさず運用中は `in_progress`。運用タスクを他の Task の依存先にしない（運用の結果を使う Task は、初回の run の output を input に書く）。context.yaml には運用タスクの output の置き場を初回に1行だけ書き、run ごとには足さない）/ `scheduled_for`（実行時期：いつ着手するか。`YYYY-MM-DD` か、週なら `YYYY-Www`＝その週の月曜）/ `due`（期限。実行時期とは別の欄で、期限から実行時期を推測しない）/ `schedule_history`（実行時期を変えたときに date・from・to・reason を1行）
- **既定の上限:** `description`＋`command` は合計 500 字以内（長い指示や JSON はファイルに置き参照だけ書く）。計画は backlog の AC そのもので、別の計画書を版管理しない。分単位の予算・時計の締切・版 hash・同版承認の表は書かない（回数の上限と branch 運用は 04-operation の既定）
- **トップレベル必須:** `focus_strategy` / `focus_strategy_reason` / `focus_strategy_confirmed_by` / `decomposition_pattern` / `sublayers` / `tasks` / `summary`（task_count / p0_tasks / p1_tasks / p2_tasks / next_action）/ `construction`（required / reason / tasks — RUL_plc_adaptive §6）。任意: `decisions`（Layer 共通の決めごと・禁止事項）
- 再分解があった場合は `refactoring_log` も記録
- SubLayerがあれば `sublayers/` にフォルダを作成し、各SubLayerに「次のステップ」（Collection起動プロンプト）を含める

### Phase 5.5: 外部実行タスク判定

各タスクを判定する: ✅PJ内実行→そのまま / 📤外部委譲（別の実行者がやるべき）→ Self-Describing Task構造（RUL_plc_system §9）でチケット化し「外部DBに書き出しますか？」と確認→承認後push / ⏳先送り→`deferred`ステータスで残す。

### Phase 6: Mob Checkpoint — 次ステージ提案（停止）

ここで必ず停止し、RUL_plc_session §7 の4パートを出力する。Next Action: SubLayerあり→各SubLayerの /01-collection 起動案内 / Tasksのみ→ `construction.required` が true なら /03-construction、false なら /04-operation を案内（表記は §7.4「実行形式は環境の正」）。Tasksのみのときは、完了報告の最後に「自動で進めるなら:」として RUL_plc_session §10 の短い版 /goal（Layer パスと開始列を埋めたもの）を1行出す（complex か platform_builder の Layer では出さず「自動完走の対象外（理由）」を1行出す）。

## Re-Inception（Backtrack対応）

BT-A（ブロッカー）/ BT-B（節目再評価）/ 本人の明示指示から呼び出される差分再分解モード（RUL_plc_adaptive §5）:

1. 既存backlog.yamlを読み込む（completedタスクは保持）。再計画の reviewer/checker には本人原文（intent.request_provenance）と現在 Goal の照合（[requirement-review.md](../references/requirement-review.md) の要点）を含める。Phase 3 と同じ成果スライスの原則を差分に適用し、再利用できる調査/途中成果と未達の終点から残 Task を作る（完了部品を作り直さない。調査 Task の完了を利用者成果の完了に読み替えない）。本人が `review_profile: gobold` を Task に明示したときだけ [gobold-review.md](../references/gobold-review.md) を reviewer 入力に使う
2. トリガー原因を分析し、差分のみ実施: タスク追加（新ID採番）/ 修正（description・priority・dependencies更新）/ 削除（statusを`cancelled`に。物理削除しない）
3. refactoring_log に date / trigger / reason / changes を記録。タスクを足した・変えたときは `construction` を判定し直す（足したタスクが条件に当たれば `construction.tasks` に加え、Next Action は /03-construction）
4. 差分テーブル（操作/タスクID/内容/理由）を提示して承認を待ち（§9.1）、承認後にbacklog.yamlを更新。本人が今回の Re-Inception を具体的に許可済み、または有効な自動完走/force の範囲内なら表示・記録後に続行する
5. 目的の意味のある変更で表示名を変えるべきかは [plc-registry の命名判断](../../plc-registry/SKILL.md#命名の判断と表示名の限定更新) に従う（単なる Task 追加は改名の節目にしない）

## 出力

backlog.yaml（常に） / sublayers/（SubLayer生成時） → Stage 3（要るときだけ）または Stage 4 へ。

---
**作成日:** 2026-04-07 ｜ **更新日:** 2026-10-22 ｜ **バージョン:** 3.0（方式の判定を目録と判定関数へ（読み方は同じ）／軽量化: 10/1 版（v2.3）を土台に、DevStyle binding・AIPM-FIRST・アドオン A2・命名確認の本文を外し、発動条件3つと1行参照・成果スライスの要点・Phase 5 の既定上限・Phase 4 の「OK が開始ゲート」を残す。命名確認の正本は plc-registry。以前の版履歴は git）
