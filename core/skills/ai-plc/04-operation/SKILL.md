---
name: 04-operation
description: ai_plc_operation - AI-PLC Stage 4。Agent定義に従ってタスクを実行し、成果物をArtifact Storeに格納する。
---

# AI-PLC Stage 4: Operation

Agent定義に従い各タスクを実行する最終ステージ。Context Storeからコンテキストを注入し、成果物をArtifact Store（Documents/）に格納する。実行中に発見したコンテキストはContext Storeに追加する（Hierarchical Context Propagation）。

**共通規約:** 命名は RUL_plc_system §6 / 完了報告は RUL_plc_session §7 / Phase遷移通知は §8 / Mob CP出力は §9 に従う。

## 入力

| 入力 | 必須 | 説明 |
| --- | --- | --- |
| Backlog + Agents + Context Store | ✅ | Stage 1-3の生成物 |
| target_task | ⭕ | 未指定時は実行可能タスク一覧を提示 |

## 実行フロー

### Phase 1: Auto-Research

backlog.yamlを読み込み、依存関係を解決し、実行可能タスク（依存解決済み・未着手）を特定する。

### Phase 2: Mob Checkpoint — タスク選択（停止）

実行可能タスク一覧を提示し、ユーザーの選択を待つ。タスクIDが入力で指定されていても、後続のAgent定義内Mob Checkpointは省略しない。実行可能タスクが複数あり並列委譲条件（Phase 4）を満たす組があれば、「並列委譲候補: TXXX+TYYY / 逐次: TZZZ」も併せて提示する。

### Phase 3: Context Ingestion

タスク実行に必要な追加情報を収集（優先順位: RUL_plc_system §16）→ Context Storeに追加 → context.yamlを更新する。

### Phase 4: Skill Execution

タスクのAgent定義を読み込み、そのPhase構造に従って実行する: Autonomous PhaseはAIが自動処理し、Mob Checkpoint Phaseでは必ず停止して人間の判断を待つ。Agent定義の指示に忠実に従い、実装系タスクは実体（DB・ページ・コード等）を作る（設計書だけで終わらない）。

**並列委譲（Subagent実行）:** 実行可能タスクが複数あり、①`delegable: true`（Autonomous-only）②依存独立（dependencies全completed・同時実行タスク間に依存なし）③出力パス非競合 の3条件を満たす場合、承認を得たうえでAgent toolに並列委譲できる（初期は2-3並列まで）。委譲時はAGT本文+絶対パス補足をpromptに渡し、変更禁止ファイル（backlog.yaml / context.yaml / intent.yaml / sqlite / rules / SKILL）を明示する。ステータス更新・Phase 5.5検証・Propagationは親が実施し、Subagentの自己申告は必ず親のL1検証で裏取りする（例外: Phase 5.5の独立reviewer検証で代替可）。失敗・品質不足時はメインループで逐次再実行する。

### Phase 5: Artifact Generation

成果物をArtifact Store（Documents/）に格納する。成果物は具体的に記録する（「〇〇を作成」「△△を更新」）。

### Phase 5.5: Verification（省略禁止）

intent.yamlのworkflow_depthに応じて3層検証（RUL_plc_system §18）を実行し、結果をチェックリスト形式で必ず出力する。出力しない限りPhase 6に進めない:

```
🔍 Phase 5.5: Verification（[workflow_depth]）
- [x] L1: [チェック内容と結果]（全タスク必須）
- [x] L2: [チェック内容と結果]（standard以上）
- [x] L3 + NFR: [チェック内容と結果]（complexのみ。NFRはRUL_plc_system §19）
```

P0-P1相当の問題はPhase 4に戻って必ず修正する（同格・例外なし）。P2は原則その場で対応し、影響が限定的なら後続タスクへの持ち越しをMaker判断で選べる（持ち越し先タスクのdescriptionに反映）。P3は差し戻し対象外（語彙: RUL_plc_system §18）。タスク内で修正できない前提崩壊・外部依存・設計矛盾は Phase 5.5b のBT-A判定に委ねる。

**独立検証（maker≠checker・全タスク既定動作）:** Phase 5.5の自己検証チェックリストを出力した直後、「する/しない」を質問せず原則毎回、作成文脈から独立したreviewerによる検証を実施（または提示）する — maker≠checkerの原則はコードに限らない（企画書・記事・設計書も作った本人は自分の欠陥に盲目）。検証は作成した文脈から分離する — CC / Cursor=Subagent reviewer（Agent tool・delegableなreviewer AGT、`TPL_review_agent`）/ Codex=sub-agent / Notion AI等サブエージェント機能のない環境=`@SKL_plc_checker`を別チャットで起動（成果物のみを入力にした別会話）。共通規定: reviewerには成果物と検証に必要な定義（Goal/Output・受け入れ基準・検証Level・該当typeのレンズ・snapshot）のみ渡し、作成文脈・会話履歴は渡さない / 出力は P0-P3 のフラットリスト or「No findings」（語彙: RUL_plc_system §18）/ 対象スナップショット（commit / ファイル更新時刻）を1行記録する（版ズレ重複指摘の防止）。reviewer結果はチェックリストの該当Level欄に転記する（例: `- [x] L1: 独立reviewer検証（snapshot: …）— No findings`）。reviewer出力が得られない場合はセルフ検証（L1/L2）にフォールバックし、その旨を1行記録して進む（silent skip禁止）。並列委譲（Phase 4）されたタスクでは、独立reviewer検証をもって親のL1裏取りに代えてよい（reviewerは実行Subagentと別文脈のため）。

**発動強度（上から順に判定。レンズ表で対象外のtypeは常に対象外）:** 必須=complexのL3検証／受け手に渡る最終成果物（外部向け資料・公開コンテンツ・意思決定文書）→ reviewer結果を得るまで完了しない。既定=workflow_depth standard以上 → 毎回実施（または提示）し、reviewer出力が返らなければセルフ検証にフォールバック。省略可=simple・内部メモ・中間生成物・management/coordination・レビュー対象のない意思決定オンリー → セルフ検証L1でよい（省略時は「独立レビュー省略（基準: …）」と1行出力）。

**type別検証レンズ（reviewerへの指示に使う。§18/§19の具体化）:**

| タスクtype | レンズ |
| --- | --- |
| implementation / coding | 動作・回帰・エッジケース・セキュリティ |
| content（記事・資料） | 事実確認・引用の裏取り / 読者視点で最後まで読めるか（L3）/ トーン一貫性 / 専門外への可読性（NFR） |
| planning / design（企画・設計書） | 論理の飛躍・根拠 / 実現可能性・工数妥当性 / 意思決定者が判断できるか（L3）/ 矛盾検出（L2） |
| research | ソースの信頼性・反証可能性 / 主張とエビデンスの対応 / 欠落した対立見解 |
| management / coordination | 対象外（独立レビュー不要・セルフチェックで可） |

backlog.yamlの`type`値が表にない場合は最近縁の行を適用する（例: validation→implementation行 / operation→実行対象成果物のtype行）。

### Phase 5.5b: Backtrack判定（タスク単位）

検証結果からBT-A（ブロッカー: critical NG / 外部依存未解決 / 設計矛盾 — RUL_plc_adaptive §5）を判定する。該当時のみNext ActionにD/E選択肢を追加し、該当なしなら何も出力しない。

### Phase 6: Status Update

backlog.yamlを更新（status → completed + 成果物リンク）し、context.yamlに成果物エントリを追加し、進捗ダッシュボードと次の実行可能タスクを表示する。SubLayer内のTaskが親ScopeBacklogのTaskに対応する場合、親側のステータスも連動更新する。

### Phase 6b: Backtrack判定（パイプライン単位）

BT-B（節目再評価: 完了率50% / ゴールドリフト）と BT-C（全完了GAP分析）を判定する（RUL_plc_adaptive §5）。該当時のみNext ActionにD/E選択肢を統合する。

### Phase 7: Propagation（省略禁止）

RUL_plc_system §8 のチェックリスト7項目（backlog / context / native memory / External Sync / Wiki波及 / log / Registry DB）を全て「確認→判断→結果出力」で処理し、チェックリストを必ず出力する。Wiki波及はここが唯一の発動ポイント（RUL_plc_system §11）。

### Phase 8: Knowledge Lint [月次/手動]

通常のタスク実行フローには含めない。月次または「Knowledge Lintを実行して」の指示で [knowledge-lint.md](knowledge-lint.md) に従い実行する。

### Phase 9-11: Platform Builder [mode=platform_builder 全タスク完了時のみ]

[platform-builder.md](platform-builder.md) に従い、Production Skill生成 → 量産実行 → Eval Feedbackを実行する。direct modeでは発動しない。

## タスク完了時の出力

RUL_plc_session §7 の4パート（📍現在位置 / ✅完了サマリ / 📊進捗 / 🔜Next Action Protocol）を必ず出力する。Next Actionの標準選択肢: A=次タスク実行（⭐推奨） / B=親Layerに戻る / C=セッション終了。全タスク完了時: A=親Backlog更新→次Sub-Layerへ / B=パイプライン完了（+BT-C該当時はGAP分析提案）。

## 出力

Documents/（成果物） / Context Store・context.yaml（更新） / backlog.yaml（更新） / Production Skills（platform_builder時のみ）。

---
**作成日:** 2026-04-07 ｜ **更新日:** 2026-07-08 ｜ **バージョン:** 2.3（独立検証をNotion v2.3-Nとハイブリッド統合: 全タスク既定動作〔常時提示+セルフフォールバック・silent skip禁止〕+ type別レンズ表 + 発動強度、P0-P1差し戻し/P2持ち越し可に整合、reviewer実現手段を追記。2.2: 独立検証の全type化。2.1: AGT-Subagent並列委譲。2.0: Fable観点軽量化・Lint/PB分離・BT 3種統合）
