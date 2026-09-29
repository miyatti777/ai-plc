---
name: 04-operation-jev
description: 【実験版・Jev監視つき】ai_plc_operation - AI-PLC Stage 4。Agent定義に従ってタスクを実行し、成果物をArtifact Storeに格納する。
---

# AI-PLC Stage 4: Operation（Jev実験版）

> 🧪 **実験版（ai-plc-jev 1.8.0-exp.1）:** 公開 core の `.claude/skills/ai-plc/04-operation/SKILL.md`（v2.4）の代わりに `/04-operation-jev` で使う試行用のスキル。**本体の SKILL・rules は書き換えない。** 公開 core 2.4 との違いは次の4点だけ: ①Jev監視（Phase 5.5b / 6b。opt-in）②Phase 7 のステータス点検（8項目目）③Phase 5.5 の独立reviewer起動を明示的な実行要求にし、未解決 P0/P1/P2 を完了ゲートにした（公開 RUL_plc_system §18 の停止条件に沿ったもの）④type別レンズ表の「validation / review は対象外」の行と、最近縁フォールバック規則の書き方。このほかは、Phase 8 / 9-11 の参照先を本体側のパス（`.claude/skills/ai-plc/04-operation/`）に変えただけ。詳細は `.claude/skills/ai-plc-jev/README.md`。

**Jev監視ルール（公開 core の rules にはこの規定が無いため、本スキルの中でだけ有効）:** intent.yamlで `jev_monitor: true` のLayerでは、Phase 5.5b（BT-A）/ 6b（BT-B/C）で `.claude/ai-plc-jev/scripts/jev_bt_monitor.py` を呼び、判断専用モデルJevに「異常ありか」の1問だけを聞く。数え上げ条件（完了率50%・完了5件超・ad-hoc 2件以上・全完了）はスクリプトがコードで判定する。Jevの出力は**1行ヒントのみ**で止める権限を持たず、Backtrackの種類判断と提案文はメインモデルが行い、実行はRUL_plc_adaptive §5 実行ルール1（承認後に実行）に従う。ヒントは独立checker（同 実行ルール5）の代わりにしない。Jevが使えない・送信禁止に当たる場合はスキップして通常どおり続行する。**ヒントの有無にかかわらず、各判定のあとにユーザーの確認（妥当=accept／外れ=reject）を `--override <decision_id> accept|reject` で記録する**（試行の評価に使う。decision_id は判定の出力行に出る）。**未確認の判定の回収:** 記録漏れはコードで拾う。進捗ダッシュボードに `python3 .claude/ai-plc-jev/scripts/jev_bt_monitor.py --pending --layer <Layer>` の件数を「🧭 未確認の Jev 判定: N件」として出す（`jev_monitor: true` の Layer だけ。0件なら 0件と出す）。Next Actionのコピペ用プロンプトは**すべての選択肢**に、そのコマンドの出力の「貼り付け用」1行（`Jev判定 X・Y・Z は accept`）を含める（記憶で書かず毎回コマンドの出力から写す。0件なら書かない）。利用者の返答に「Jev判定 X・Y・Z は accept」「全部accept」等があれば、利用者に示した貼り付け用1行の ID だけを `--only` に渡して `python3 .claude/ai-plc-jev/scripts/jev_bt_monitor.py --override-pending accept|reject --layer <Layer> --only X・Y・Z [--except <ID> ...]` でまとめて記録する（示した後にできた判定は記録しない＝`--only` を省かない。個別に違う判定は先に `--override <ID> reject` 等で記録し、`--except` で除く。記録済みは二重に書かれない）。記録はタスクの実行より先に行う。会話中の監視は、実験版だけの機能として `.claude/ai-plc-jev/scripts/jev_prompt_hook.py`（UserPromptSubmit hook）が担う。**hook を settings に登録している場合だけ**、このコマンドを打ったセッションで有効になる（登録手順は `.claude/ai-plc-jev/scripts/README_jev.md`）。hook が「💡 Jev会話監視」の行を追加したら、該当するかをメインモデルが判断し、該当すれば軽量Re-Inception / Re-Collectionを1行で提案する（提案のみ・同一話題で再提案しない）。Next Actionのコピペ用プロンプトは `/04-operation-jev` 形式で書き、Re-Inceptionは `/02-inception-jev`、Re-Collectionは `/01-collection-jev` で案内する。

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

P0-P2相当の問題はPhase 4に戻って必ず修正する（同格・例外なし）。未解決P0/P1/P2が0件になるまでPhase 6へ進めない。P3は差し戻し対象外（語彙: RUL_plc_system §18）。タスク内で修正できない前提崩壊・外部依存・設計矛盾は Phase 5.5b のBT-A判定に委ねる。

**独立検証（maker≠checker・全タスク既定動作）:** Phase 5.5の自己検証チェックリストを出力した直後、「する/しない」を質問せず原則毎回、作成文脈から独立したreviewerを起動して結果を取得する — maker≠checkerの原則はコードに限らない（企画書・記事・設計書も作った本人は自分の欠陥に盲目）。この段落は、CC / Cursor / Codexでsub-agent reviewerを起動する明示的な実行要求である。Agent定義の`delegable: false`はPhase 4の成果物作成委譲だけに適用し、Phase 5.5のreviewer起動には適用しない。検証は作成した文脈から分離する — CC / Cursor=Subagent reviewer（Agent tool・Autonomous-onlyなreviewer AGT、`TPL_review_agent`）/ Codex=sub-agent / Notion AI等サブエージェント機能のない環境=成果物だけを渡した別の会話で独立レビューを行い、結果をこのTaskへ戻す。共通規定: reviewerには成果物と検証に必要な定義（Goal/Output・受け入れ基準・検証Level・該当typeのレンズ・snapshot）のみ渡し、作成文脈・会話履歴は渡さない / 出力は P0-P3 のフラットリスト or「No findings」（語彙: RUL_plc_system §18）/ 対象スナップショット（commit / ファイル更新時刻）を1行記録する（版ズレ重複指摘の防止）。reviewer結果はチェックリストの該当Level欄に転記する（例: `- [x] L1: 独立reviewer検証（snapshot: …）— No findings`）。未解決P0/P1/P2があればPhase 6へ進まない。reviewer出力が得られない場合はセルフ検証（L1/L2）にフォールバックし、利用不能・起動失敗・出力未取得のいずれかの理由を1行記録して進む（silent skip禁止）。並列委譲（Phase 4）されたタスクでは、独立reviewer検証をもって親のL1裏取りに代えてよい（reviewerは実行Subagentと別文脈のため）。

**発動強度（上から順に判定。レンズ表で対象外のtypeは常に対象外）:** 必須=complexのL3検証／受け手に渡る最終成果物（外部向け資料・公開コンテンツ・意思決定文書）→ reviewer結果を得るまで完了しない。既定=workflow_depth standard以上 → 毎回sub-agent reviewerを起動して結果を取得し、reviewer出力が返らない場合だけ理由を記録してセルフ検証にフォールバック。省略可=simple・内部メモ・中間生成物・management/coordination・レビュー対象のない意思決定オンリー → セルフ検証L1でよい（省略時は「独立レビュー省略（基準: …）」と1行出力）。

**type別検証レンズ（reviewerへの指示に使う。§18/§19の具体化）:**

| タスクtype | レンズ |
| --- | --- |
| implementation / coding | 動作・回帰・エッジケース・セキュリティ |
| content（記事・資料） | 事実確認・引用の裏取り / 読者視点で最後まで読めるか（L3）/ トーン一貫性 / 専門外への可読性（NFR） |
| planning / design（企画・設計書） | 論理の飛躍・根拠 / 実現可能性・工数妥当性 / 意思決定者が判断できるか（L3）/ 矛盾検出（L2） |
| research | ソースの信頼性・反証可能性 / 主張とエビデンスの対応 / 欠落した対立見解 |
| goal / plan（Re-Collection GAP分析・Re-Inception残タスク再評価） | 元goal+success_criteriaとの充足・未達 / スコープ逸脱（ドリフト） / 見落とされた前提・欠落タスク / 完了宣言の妥当性 |
| validation / review | 対象外（自身がcheckerのため再帰reviewerを起動しない） |
| management / coordination | 対象外（独立レビュー不要・セルフチェックで可） |

backlog.yamlの`type`値が表にない場合は最近縁の行を適用する。complexは実際の成果物typeへ、operationは各量産成果物のtypeへ解決する。validation / reviewは最近縁フォールバックの対象外とする。

### Phase 5.5b: Backtrack判定（タスク単位）

検証結果からBT-A（ブロッカー: critical NG / 外部依存未解決 / 設計矛盾 — RUL_plc_adaptive §5）を判定する。該当時のみNext ActionにD/E選択肢を追加し、該当なしなら何も出力しない。
**Jev監視（opt-in）:** intent.yamlに `jev_monitor: true` があるLayerのみ `python3 .claude/ai-plc-jev/scripts/jev_bt_monitor.py --layer <Layer> --phase 5.5b --task <ID>` を実行する。「💡異常の可能性」が出たら種類と提案文はメインモデルが判断し提案のみ行う（ヒントは止める権限を持たない・スキップ時は通常どおり続行）。

### Phase 6: Status Update

backlog.yamlを更新（status → completed + 成果物リンク）し、context.yamlに成果物エントリを追加し、進捗ダッシュボードと次の実行可能タスクを表示する。SubLayer内のTaskが親ScopeBacklogのTaskに対応する場合、親側のステータスも連動更新する。

### Phase 6b: Backtrack判定（パイプライン単位）

BT-B（節目再評価: 完了率50% / ゴールドリフト）と BT-C（全完了GAP分析）を判定する（RUL_plc_adaptive §5）。**この判定は独立checkerに通すのが既定**（maker≠checker。実行してきた本人はドリフト・未達に最も盲目）: 作成文脈から独立したreviewer（CC=Subagent / Notion AI等サブエージェント機能のない環境=別スレッド）に、元intent.yamlのgoal+success_criteria+成果物リストを渡し（実行ナラティブは剥ぐが元ゴールは渡す）、上表の`goal/plan`レンズで「達成/未達/スコープ逸脱/見落とし前提」を判定させる。checker出力が返らなければmaker自己判定にフォールバックし1行記録。該当時のみNext ActionにD/E選択肢を統合する。
**Jev監視（opt-in）:** `jev_monitor: true` のLayerのみ `python3 .claude/ai-plc-jev/scripts/jev_bt_monitor.py --layer <Layer> --phase 6b` を実行する。数え上げ条件（完了率50%・完了5件超・ad-hoc 2件以上・全完了）はスクリプトがコードで判定し、Jevはdriftの1問のみ。ヒントは独立checkerの代わりにしない。ユーザーがヒントを採否したら `--override <decision_id> accept|reject` で記録する。

### Phase 7: Propagation（省略禁止）

RUL_plc_system §8 のチェックリスト**7項目**（backlog / context / native memory / External Sync / Wiki波及 / log / Registry DB）に、本スキル固有の**8項目目「ステータス点検」**を足した8項目を全て「確認→判断→結果出力」で処理し、チェックリストを必ず出力する（ステータス点検は公開 core の rules には無い項目で、本スキルの中でだけ有効）。Wiki波及はここ（Phase 7）が唯一の発動ポイント（RUL_plc_system §11）。8項目目のチェックリスト行は次のとおり:

```
- [x] ステータス点検 — [`python3 .claude/ai-plc-jev/scripts/aiplc_status_audit.py --brief --layer <Layer>` の結果: 「食い違いなし」 or 「N件→承認後に `--quiet --approval-template --layer <Layer>` → `--apply <承認ファイル>` で反映」 or 「点検ツールなし／終了コード1・2 — スキップ」]（読み取り専用。検出と提示まで・反映は承認後）
```

**ステータス点検**は Registry DB 更新の後に、完了するLayer自身の食い違い（intent・backlog・Registry）を判定器で確かめる項目。`python3 .claude/ai-plc-jev/scripts/aiplc_status_audit.py --brief --layer <Layer>` を実行し（読み取り専用・外部送信なし・終了コード0=食い違いなし／10=あり）、候補があれば1行ずつ提示して承認を求める。SubLayerを持つLayerを閉じるときは子も `--layer` を重ねて指定する（子は自動では含まれない）。反映は承認後に ①`python3 .claude/ai-plc-jev/scripts/aiplc_status_audit.py --quiet --approval-template --layer <Layer>` で雛形を作る ②コピーして承認する行だけ `approve` にする ③`--apply <承認ファイル>`（dry-run）→ `--apply <承認ファイル> --yes` の順。スクリプトが無い環境では「点検ツールなし — スキップ」、終了コード2（DBが無い・scope_idが無い等）なら要点を1行出してスキップする。pyyaml が無いなどで起動に失敗した（終了コード1）ときも要点を1行出してスキップする。詳細は `.claude/ai-plc-jev/scripts/README_status_audit.md`。

### Phase 8: Knowledge Lint [月次/手動]

通常のタスク実行フローには含めない。月次または「Knowledge Lintを実行して」の指示で `.claude/skills/ai-plc/04-operation/knowledge-lint.md` に従い実行する。

### Phase 9-11: Platform Builder [mode=platform_builder 全タスク完了時のみ]

`.claude/skills/ai-plc/04-operation/platform-builder.md` に従い、Production Skill生成 → 量産実行 → Eval Feedbackを実行する。direct modeでは発動しない。

## タスク完了時の出力

RUL_plc_session §7 の4パート（📍現在位置 / ✅完了サマリ / 📊進捗 / 🔜Next Action Protocol）を必ず出力する。Next Actionの標準選択肢: A=次タスク実行（⭐推奨） / B=親Layerに戻る / C=セッション終了。全タスク完了時: A=親Backlog更新→次Sub-Layerへ / B=パイプライン完了（+BT-C該当時はGAP分析提案）。

## 出力

Documents/（成果物） / Context Store・context.yaml（更新） / backlog.yaml（更新） / Production Skills（platform_builder時のみ）。

---
**作成日:** 2026-04-07 ｜ **更新日:** 2026-09-28 ｜ **バージョン:** 2.7-jev（公開実験版 1.8.0-exp.1。公開 core 04-operation 2.4 をベースにした実験版の版番号。2.4 との差分は冒頭の callout と `.claude/skills/ai-plc-jev/README.md` を参照）
