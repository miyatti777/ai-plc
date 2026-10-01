---
name: 04-operation
description: ai_plc_operation - AI-PLC Stage 4。backlog（Agent定義があればそれ）に従ってタスクを実行し、成果物をArtifact Storeに格納する。
---

# AI-PLC Stage 4: Operation

backlog（Agent定義があればそれ）に従い各タスクを実行する最終ステージ。Context Storeからコンテキストを注入し、成果物をArtifact Store（Documents/）に格納する。実行中に発見したコンテキストはContext Storeに追加する（Hierarchical Context Propagation）。

**共通規約:** 命名は RUL_plc_system §6 / 完了報告は RUL_plc_session §7 / Phase遷移通知は §8 / Mob CP出力は §9 に従う。

**自動完走モード:** セッション中に RUL_plc_session §10 を指す /goal があるときは §10 に従い、Mob Checkpoint・Next Action・タスク選択で待たずに進める（無ければ本 SKILL のとおり止まる）。

## 入力

| 入力 | 必須 | 説明 |
| --- | --- | --- |
| Backlog + Context Store | ✅ | Stage 1-2の生成物（Agents/ は Stage 3 を通したときだけ） |
| target_task | ⭕ | 未指定時は実行可能タスク一覧を提示 |

## 実行フロー

### Phase 1: Auto-Research

backlog.yamlを読み込み、依存関係を解決し、実行可能タスク（依存解決済み・未着手）を特定する。`construction.tasks` に入っていて command があるのに Agents/ に定義が無いタスクは、実行可能タスクに含めず /03-construction（そのタスク指定）を案内する（command の無いタスクは外さない）（`construction` 欄の無い既存 backlog は RUL_plc_adaptive §6 のみなし規定に従う）。

### Phase 2: Mob Checkpoint — タスク選択（停止）

実行可能タスク一覧を提示し、ユーザーの選択を待つ（自動完走中〔RUL_plc_session §10〕は待たずに P0→P1→P2・依存順で選ぶ — RUL_plc_session §10）。タスクIDが入力で指定されていても、Agent 定義または backlog の guardrails にある途中の確認点は省略しない。実行可能タスクが複数あり並列委譲条件（Phase 4）を満たす組があれば、「並列委譲候補: TXXX+TYYY / 逐次: TZZZ」も併せて提示する。

### Phase 3: Context Ingestion

タスク実行に必要な追加情報を収集（優先順位: RUL_plc_system §16）→ Context Storeに追加 → context.yamlを更新する。先行タスク（dependencies）の output と Context/ は既定で読む。

### Phase 4: Skill Execution

タスクに Agent 定義があれば読み込み、その Phase 構造に従って実行する。無ければ backlog の description・acceptance_criteria・guardrails・decisions と Context から実行する（RUL_plc_adaptive §6）。どちらでも Autonomous Phase は AI が自動処理し、確認点では止まって人の判断を待つ（自動完走中は RUL_plc_session §10）。Agent定義の指示に忠実に従い、実装系タスクは実体（DB・ページ・コード等）を作る（設計書だけで終わらない）。

**並列委譲（Subagent実行）:** 実行可能タスクが複数あり、①backlog の `delegable: true`（Agent 定義を作ってあること）②依存独立（dependencies全completed・同時実行タスク間に依存なし）③出力パス非競合 の3条件を満たす場合、承認を得たうえでAgent toolに並列委譲できる（初期は2-3並列まで）。委譲時はAGT本文+絶対パス補足をpromptに渡し、変更禁止ファイル（backlog.yaml / context.yaml / intent.yaml / sqlite / rules / SKILL）を明示する。ステータス更新・Phase 5.5検証・Propagationは親が実施し、Subagentの自己申告は必ず親のL1検証で裏取りする（例外: Phase 5.5の独立reviewer検証で代替可）。失敗・品質不足時はメインループで逐次再実行する。委譲先には、最終メッセージで成果物パスと実測値を返すよう指示する。`delegable: true` でも Agent 定義が無いタスクは（Phase 1 で除外されなかった場合＝backlog を後から手で直したときなど）委譲せず逐次で実行する（委譲したいなら /03-construction でそのタスクだけ作る）。

**スコープ外タスク:** 実行中にスコープ外の作業（別チームの前提・別システムでの実装・スコープ外の改善）を見つけたら、Self-Describing Task 構造（RUL_plc_system §9）でチケット化し、外部に書き出すかを確認する（承認後に push）。

### Phase 5: Artifact Generation

成果物をArtifact Store（Documents/）に格納する。成果物は具体的に記録する（「〇〇を作成」「△△を更新」）。

### Phase 5.5: Verification（省略禁止）

intent.yamlのworkflow_depthに応じて3層検証（RUL_plc_system §18）を実行し、結果をチェックリスト形式で必ず出力する。出力しない限りPhase 6に進めない:

```
🔍 Phase 5.5: Verification（[workflow_depth]）
- [x] L1: [チェック内容と結果]（全タスク必須）
- [x] L1: acceptance_criteria を1項目ずつ ○/× で書く（backlog の acceptance_criteria。無ければ description の完了条件）。× が1つでもあれば Phase 4 に戻る
- [x] L2: [チェック内容と結果]（standard以上）
- [x] L3 + NFR: [チェック内容と結果]（complexのみ。NFRはRUL_plc_system §19）
```

P0-P2相当の問題はPhase 4に戻って必ず修正する（同格・例外なし）。未解決P0/P1/P2が0件になるまでPhase 6へ進めない。P3は差し戻し対象外（語彙: RUL_plc_system §18）。タスク内で修正できない前提崩壊・外部依存・設計矛盾は Phase 5.5b のBT-A判定に委ねる。

**独立検証（maker≠checker・全タスク既定動作）:** Phase 5.5の自己検証チェックリストを出力した直後、「する/しない」を質問せず原則毎回、作成文脈から独立したreviewerを起動して結果を取得する — maker≠checkerの原則はコードに限らない（企画書・記事・設計書も作った本人は自分の欠陥に盲目）。この段落は、CC / Cursor / Codexでsub-agent reviewerを起動する明示的な実行要求である。backlog（または Agent 定義）の `delegable: false` はPhase 4の成果物作成委譲だけに適用し、Phase 5.5のreviewer起動には適用しない。検証は作成した文脈から分離する — CC / Cursor=Subagent reviewer（Agent tool・Autonomous-onlyなreviewer AGT、`TPL_review_agent`）/ Codex=sub-agent / Notion AI等サブエージェント機能のない環境=別チャットで独立reviewerを起動し、結果をこのTaskへ戻す（成果物のみを入力にした別会話）。共通規定: reviewerには成果物と検証に必要な定義（Goal/Output・受け入れ基準・検証Level・該当typeのレンズ・snapshot）のみ渡し、作成文脈・会話履歴は渡さない。受け入れ基準は backlog の acceptance_criteria（無ければ description）から取る。reviewer は read-only（書き込み権限を渡さない） / 出力は P0-P3 のフラットリスト or「No findings」（語彙: RUL_plc_system §18）/ 対象スナップショット（commit / ファイル更新時刻）を1行記録する（版ズレ重複指摘の防止）。reviewer結果はチェックリストの該当Level欄に転記する（例: `- [x] L1: 独立reviewer検証（snapshot: …）— No findings`）。未解決P0/P1/P2があればPhase 6へ進まない。reviewer出力が得られない場合はセルフ検証（L1/L2）にフォールバックし、利用不能・起動失敗・出力未取得のいずれかの理由を1行記録して進む（silent skip禁止）。並列委譲（Phase 4）されたタスクでは、独立reviewer検証をもって親のL1裏取りに代えてよい（reviewerは実行Subagentと別文脈のため）。

**発動強度（上から順に判定。レンズ表で対象外のtypeは常に対象外）:** 必須=complexのL3検証／受け手に渡る最終成果物（外部向け資料・公開コンテンツ・意思決定文書）→ reviewer結果を得るまで完了しない。既定=workflow_depth standard以上 → 毎回sub-agent reviewerを起動して結果を取得し、reviewer出力が返らない場合だけ理由を記録してセルフ検証にフォールバック。省略可=simple・内部メモ・中間生成物・management/coordination・レビュー対象のない意思決定オンリー → セルフ検証L1でよい（省略時は「独立レビュー省略（基準: …）」と1行出力）。

**type別検証レンズ（reviewerへの指示に使う。§18/§19の具体化）:**

| タスクtype | レンズ |
| --- | --- |
| implementation / coding | 動作・回帰・エッジケース・セキュリティ |
| content（記事・資料） | 事実確認・引用の裏取り / 読者視点で最後まで読めるか（L3）/ トーン一貫性 / 専門外への可読性（NFR） |
| planning / design（企画・設計書） | 論理の飛躍・根拠 / 実現可能性・工数妥当性 / 意思決定者が判断できるか（L3）/ 矛盾検出（L2） |
| research | ソースの信頼性・反証可能性 / 主張とエビデンスの対応 / 欠落した対立見解 |
| goal / plan（Re-Collection GAP分析・Re-Inception残タスク再評価） | 元goal+success_criteriaとの充足・未達 / スコープ逸脱（ドリフト） / 見落とされた前提・欠落タスク / 完了宣言の妥当性 |
| management / coordination | 対象外（独立レビュー不要・セルフチェックで可） |
| validation / review | 対象外（自身がcheckerのため再帰reviewerを起動しない） |

backlog.yamlの`type`値が表にない場合は最近縁の行を適用する。complexは実際の成果物typeへ、operationは各量産成果物のtypeへ解決する。validation / reviewは最近縁フォールバックの対象外とする。

### Phase 5.5b: Backtrack判定（タスク単位）

検証結果からBT-A（ブロッカー: critical NG / 外部依存未解決 / 設計矛盾 — RUL_plc_adaptive §5）を判定する。該当時のみNext ActionにD/E選択肢を追加し、該当なしなら何も出力しない。

**Jev監視:** core のコマンド（`/01-collection`〜`/04-operation`）は Jev を**呼ばない**（外部API送信なし）。Jev 監視は実験版パッケージ experimental/jev（`--with-jev`）の `/01〜04-*-jev` コマンドで実行したときだけ動く。仕様は `.claude/ai-plc-jev/` 配下の実験版スキルと `scripts/README_jev.md` を参照。

### Phase 6: Status Update

backlog.yamlを更新（status → completed + 成果物リンク）し、context.yamlに成果物エントリを追加し、進捗ダッシュボードと次の実行可能タスクを表示する。SubLayer内のTaskが親ScopeBacklogのTaskに対応する場合、親側のステータスも連動更新する。

### Phase 6b: Backtrack判定（パイプライン単位）

BT-B（節目再評価: 完了率50% / ゴールドリフト）と BT-C（全完了GAP分析）を判定する（RUL_plc_adaptive §5）。**この判定は独立checkerに通すのが既定**（maker≠checker。実行してきた本人はドリフト・未達に最も盲目）: 作成文脈から独立したreviewer（CC=Subagent / Notion AI等サブエージェント機能のない環境=別スレッド）に、元intent.yamlのgoal+success_criteria+成果物リストを渡し（実行ナラティブは剥ぐが元ゴールは渡す）、上表の`goal/plan`レンズで「達成/未達/スコープ逸脱/見落とし前提」を判定させる。checker出力が返らなければmaker自己判定にフォールバックし1行記録。該当時のみNext ActionにD/E選択肢を統合する。

**Jev監視:** 5.5b と同じく core からは呼ばない（実験版の `/04-operation-jev` のときだけ）。

### Phase 7: Propagation（省略禁止）

RUL_plc_system §8 のチェックリスト8項目（backlog / context / native memory / External Sync / Wiki波及 / log / Registry DB / ステータス点検）を全て「確認→判断→結果出力」で処理し、チェックリストを必ず出力する。**ステータス点検**は Registry DB 更新の後に、完了するLayer自身の食い違い（intent・backlog・Registry）を判定器で確かめる項目。判定器 `aiplc_status_audit.py` は実験版パッケージ experimental/jev に同梱されており（`--with-jev` で `.claude/ai-plc-jev/scripts/` に入る）、**core だけの環境ではスクリプトが無いため「点検ツールなし — スキップ」と出力して次へ進む**。導入済みなら `python3 .claude/ai-plc-jev/scripts/aiplc_status_audit.py --brief --layer <Layer>` を実行し（読み取り専用・外部送信なし・終了コード0=食い違いなし／10=あり）、候補があれば1行ずつ提示して承認を求める。SubLayerを持つLayerを閉じるときは子も `--layer` を重ねて指定する（子は自動では含まれない）。反映は承認後に ①`python3 .claude/ai-plc-jev/scripts/aiplc_status_audit.py --quiet --approval-template --layer <Layer>` で雛形を作る ②コピーして承認する行だけ `approve` にする ③`--apply <承認ファイル>`（dry-run）→ `--apply <承認ファイル> --yes` の順。`--brief` が終了コード2（DBが無い・scope_idが無い等）や終了コード1（pyyaml が無いなどの起動失敗）で終わったときは要点を1行出してスキップする。`--apply <承認ファイル> --yes` が終了コード1（書き込み失敗）・3（書かなかった行がある）で終わったときはスキップせず、結果とログを提示して人の判断を待つ。詳細は `.claude/ai-plc-jev/scripts/README_status_audit.md`。Wiki波及はここが唯一の発動ポイント（RUL_plc_system §11）。

### Phase 8: Knowledge Lint [月次/手動]

通常のタスク実行フローには含めない。月次または「Knowledge Lintを実行して」の指示で [knowledge-lint.md](knowledge-lint.md) に従い実行する。

### Phase 9-11: Platform Builder [mode=platform_builder 全タスク完了時のみ]

[platform-builder.md](platform-builder.md) に従い、Production Skill生成 → 量産実行 → Eval Feedbackを実行する。direct modeでは発動しない。

## タスク完了時の出力

RUL_plc_session §7 の4パート（📍現在位置 / ✅完了サマリ / 📊進捗 / 🔜Next Action Protocol）を必ず出力する。Next Actionの標準選択肢: A=次タスク実行（⭐推奨） / B=親Layerに戻る / C=セッション終了。全タスク完了時: A=親Backlog更新→次Sub-Layerへ / B=パイプライン完了（+BT-C該当時はGAP分析提案）。

## 出力

Documents/（成果物） / Context Store・context.yaml（更新） / backlog.yaml（更新） / Production Skills（platform_builder時のみ）。

---
**作成日:** 2026-04-07 ｜ **更新日:** 2026-10-01 ｜ **バージョン:** 2.8（冒頭に自動完走モードの1行・Phase 2 は自動完走中に P0→P1→P2・依存順で選ぶ〔RUL_plc_session §10〕／Construction を既定で省く対応: Agent 定義が無ければ backlog の description・acceptance_criteria・guardrails・decisions から実行・L1 で acceptance_criteria を ○/×・delegable は backlog の値〔RUL_plc_adaptive §6〕）｜ 2.7（Phase 7にステータス点検を追加〔点検ツールは experimental/jev 同梱。未導入ならスキップ〕。2.6: Phase 5.5b/6bのJev監視は実験版 /04-operation-jev のみと明記〔core からは呼ばない〕。2.5: Codexを含むsub-agent reviewer起動を明示要求化し、`delegable: false`との適用範囲を分離。未解決P0/P1/P2を完了ゲート化。validation / reviewをレンズ対象外に。2.4: Phase 6b BT-B/BT-C判定に独立checker既定化 + goal/planレンズ追加 — Re-Collection/Re-Inceptionにもmaker≠checkerを適用。2.3: 独立検証を全タスク既定動作化〔常時提示+セルフフォールバック・silent skip禁止〕+ type別レンズ表 + 発動強度、P0-P1差し戻し/P2持ち越し可。2.2: 独立検証の全type化。2.1: AGT-Subagent並列委譲。2.0: Fable観点軽量化・Lint/PB分離・BT 3種統合）
