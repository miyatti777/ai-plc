> 🏷️ **Project:** \[YOUR_PROJECT\]
> **Type:** rule
> **Context:** AI-PLC ルートシステムルール。全SKLが暗黙参照する共通実行ルール・成果物構造・Context Cascade定義。

## 1. AI-PLCの目的

AI-PLCの目的は「実際に動く成果物」を作ること。

- ガイド/設計書「だけ」では完了にならない。実装系タスクは実体（Database・Form・ページ・コード）を作る
- タスク完了前に「成果物は作成されたか？」を確認する
- セッション終了時に作成した成果物の数を報告する

## 2. Context Cascade（CC）伝播ルール

親Layer→子Layerへのコンテキスト伝播は3分類で管理する。

| カテゴリ | 伝播ルール | 例 |
| --- | --- | --- |
| global_immutable | 親→子に不変伝播。子は変更不可 | vision, tech_stack, core_principles |
| overridable | 親→子に伝播。子がオーバーライド可能 | deadline, scope, priority |
| local_only | そのLayerのみ。子には伝播しない | implementation_details |

実装ルール: intent.yamlに3分類を明記 / Sub-Layer作成時にglobal_immutableを自動継承 / overridableは子の明示上書きのみ / local_onlyは子に伝播させない。

## 3. 成果物構造標準

各Layerの必須ファイル: `intent.yaml` / `context.yaml` / `backlog.yaml` / `Context/`（Context Store）。任意: `variables.yaml`（Platform Builder時） / `Agents/` / `sublayers/` / `Documents/`。

Layerトップページは「成果物セクション（上部）+ AI-PLC管理セクション（下部・折りたたみ）」の2層構造。管理セクションの見出しは `### 🔧 AI-PLC管理（[Scope ID]）`。

## 4. Mob Checkpoint 共通ルール

1. 各Mob Checkpointでは必ず人間のアクションを待つ。返答があるまで次のPhaseに進まない
2. 承認パターン: `OK` / `修正指示` / `スキップ`
3. 出力形式は RUL_plc_session §9 に従う

## 5. スキル参照チェーン

RUL_plc_system（本ファイル）→ 全SKL_plc_* が参照。補助ルール: RUL_plc_session（セッション・出力規約）/ RUL_plc_adaptive（深度判定・Backtrack）。スキルはロール（templates/roles/）とAgentテンプレート（templates/agents/）を参照する。

## 6. 命名規則

| 種別 | プレフィックス | 例 |
| --- | --- | --- |
| スキル | `SKL_plc_` | SKL_plc_01_collection |
| ルール | `RUL_plc_` | RUL_plc_system |
| ロール | `ROL_plc_` | ROL_plc_product_manager |
| サブエージェント | `AGT_plc_` | AGT_plc_research |

旧AIPO名称は使用禁止（本表がプロジェクト唯一の定義。各スキルはここを参照する）:

| 旧AIPO（❌禁止） | AI-PLC（✅正） |
| --- | --- |
| layer.yaml | intent.yaml |
| tasks.yaml | backlog.yaml |
| Commands/ | Agents/ |
| 「aipo管理」 | 「AI-PLC管理」 |
| CMD_ / CTX_ | SKL_ / RUL_ |

## 7. 🧠 Persistent Memory ルール

セッション横断の記憶は**2系統**で管理する（旧memory.md/user.mdは2026-07-07に廃止・移行済み）:

- **wiki（.claude/wiki/）** = プロジェクト横断・共有可能な知見。バグパターン・設計判断・環境固有制約はここ（運用は§11、月次Lintは§10）
- **CC native memory（~/.claude/projects/&lt;repo&gt;/memory/）** = ユーザーモデル・好み・進行中PJの状態。**概念ページ原則（LLM Wiki準拠）:** 1ファイル=独立して参照される1概念。frontmatterのtype（user/feedback/project/reference）がSchema、MEMORY.mdがindex、`[[名前]]`で相互リンク。時点情報（現在のフォーカス等）は概念ページに置かず、PJメモリ/logに置く

振り分け: バグ・技術知見・PJ横断パターン→wiki / ユーザーの判断パターン・好み→native memory（feedback）。両方に重複させない。native memoryのユーザーモデルに基づいて対応を調整する。

## 8. 🔄 Post-Deliver Propagation ルール

SKL_plc_04_operation Phase 7として必ず実行する（省略禁止）。各項目は「確認→判断→結果出力」の3ステップを踏む。確認せずにスキップすることは禁止（確認の結果「該当なし」でのスキップは可）。

Phase 7では以下のチェックリストを必ず出力する:

```
📋 Phase 7: Propagation チェックリスト
- [x] backlog.yaml更新 — [タスクID] status → completed + Output: [成果物パス]
- [x] context.yaml更新 — 成果物エントリ [ファイル名] を追加
- [x] native memory — [概念ページ追記/新規/PJメモリ更新 or 「変更なし — スキップ」]（§7の2系統振り分けに従う）
- [x] External Sync — [sync_targets確認: 「未定義→スキップ」 or 「push実行: N件」]
- [x] Wiki波及更新 — [更新内容 or 「新規性なし — スキップ」]
- [x] log.md — [エントリ追加 or 「Wiki更新なしのためスキップ」]
- [x] Project Registry DB — [「未完了タスクあり→スキップ」 or 「全完了→completed更新」]
```

順序: Phase 5.5 Verification（§18）→ Phase 6 Status Update → Phase 7 Propagation。検証未完了の成果物をPropagationしない。

## 9. 🔗 External Sync 仕様

PJ内で発見したが今実行しないタスクを、独立実行できる形で外部に書き出す機構。intent.yamlの`sync_targets`で同期先を宣言する。

**2つの役割:** 📤 タスク委譲（コンテキスト付きで外部に書き出す） / 🔄 ステータス同期（backlogの変更を外部DBに反映）。

**Self-Describing Task構造（委譲チケットの必須フィールド）:** そのチケットだけで実行できる状態にする。

```yaml
title: "[タスク名]"
description: "[概要]"
context: {source_project, source_layer, source_task, decision_ref}
related_docs: ["読むべきドキュメント"]
constraints: ["制約・前提"]
acceptance_criteria: ["完了基準"]
priority: high
due_date: null  # 任意
```

**sync_targetsスキーマ:**

```yaml
sync_targets:
  - type: notion_db | linear | github_issues | sqlite
    target_url: "[URL/ID/パス]"
    mapping: {title: "...", status: "...", output: "..."}
    status_map: {pending: "...", in_progress: "...", completed: "...", blocked: "..."}
    auto_create: false   # true=新タスクを外部にも自動作成
    sync_direction: push # push / pull / bidirectional
```

**実行手順:** ①intent.yamlのsync_targetsを読む ②空→デフォルト（`.claude/db/ai_plc.db` の tasks テーブル、auto_create: true, push）を自動適用 ③mapping/status_mapで変換しsync_directionに従い同期 ④結果をログ出力「✅ External Sync: [type] [target] — [タスクID] を [ステータス] に更新」。ユーザーが「同期不要」と明言した場合のみ `sync_targets: []` のまま。

## 10. 🧹 Knowledge Lint ルール

wiki配下の知識ベース健全性を月次で検証する（SKL_plc_04_operationから手動/定期発動。実行手順詳細は `.claude/skills/ai-plc/04-operation/knowledge-lint.md`）。

チェック5項目: 🔴矛盾検出（CONTRADICTIONフラグ） / 🟡孤立ページ（バックリンクなし） / 🟡引用なし主張（Source未記載） / 🔵未説明概念 / 🔵欠落相互参照。
レポートは `wiki/lint-report-YYYY-MM.md` に Errors/Warnings/Info/Summary + 推奨アクション3件 + 読むべき3記事の形式で出力する。

## 11. 🌊 Wiki波及更新ルール（Ingest Ripple — LLM Wiki準拠）

新しい知見を得たら、LLM Wikiのページタイプ型（概念ページ=wiki直下 / sources/ / queries/ — Schema定義はwiki.md）で波及更新する。**発動タイミング: SKL_plc_04_operation Phase 7 Propagation時**（Collection段階では発動しない）。

**Ingest手順:**
①外部1次ソース由来の知見は、まず `sources/YYYY-MM-DD_[slug].md` にサマリーページを作成（1ソース=1ページ。テンプレはsources/README）。作業中の内部知見はサマリー不要で③へ
②index.mdを読み、関連する概念ページを特定
③概念ページに追記 `- [YYYY-MM-DD] [Source: [[ソース名]] or 実測] [内容]`
④`[[wikilink]]`で相互リンク（A→Bを足したらB→Aも確認。新規ページは関連既存ページ全てに）
⑤必要なら新規概念ページ作成 + index.md更新（タイプ別カタログの該当表へ）
⑥log.mdに `| YYYY-MM-DD | ingest | [ソース] | [影響数] |`
⑦frontmatterのlast_updated/source_count更新

**Query結果の還元:** Deliver中のQuery結果のうち 🔴比較分析 / 🟡新見解 / 🔵接続発見 に該当するものは `queries/YYYY-MM-DD_[slug].md` にQ&Aをファイリングし、概念ページへ還元する（log種別: `query-return`）。単純な事実確認・既存知見の範囲内・PJ固有ローカル情報はスキップ。

**スキップ条件:** 既存wiki知見の範囲内で新規性がない場合（その旨を出力する）。

## 12. ⚠️ 矛盾検出・フラグ機構（CONTRADICTION)

新情報が既存知見と矛盾したら、削除せず両方を保持してフラグを立てる:

```markdown
> ⚠️ CONTRADICTION: [既存主張] vs [新情報]
> Source: [出典] / Date: YYYY-MM-DD / Status: open | resolved | superseded
```

フロー: 既存主張の直下に挿入（Status: open）→ log.mdに`contradiction`エントリ → index.mdの該当行に⚠️。解決時: Statusを更新し `> Resolution: [内容] (日付)`、廃止主張は取り消し線（削除しない）、⚠️を除去。

## 13. 🔄 Query知識還元ループ

§11に統合（判定基準・スキップ条件は§11参照）。

## 14. 📝 ページ作成デフォルトルール

- 指定がなければ `Flow/[YYYYMM]/[YYYY-MM-DD]/` 配下に作成（フォルダがなければ作成）
- 全ページ先頭にフロントマターコールアウト: `> 🏷️ **Project:** [@mention] / **Type:** memo|meeting|decision|draft / **Context:** [1行]`（Project不明なら`TBD`）
- 顧客名・PJ文脈はprojects配下のProjectページを@mentionで参照。外部URLは貼らない

## 15. 🤖 自律的動作フロー

1. 明確な指示がある場合 → 最優先で従う
2. 不明確な場合 → 意図とGOALを推測 → Context収集（§16） → 該当スキルを探索 → あれば実行、なければ柔軟に対応
3. GOAL達成後、繰り返しそうなタスクはスキルへの型化を検討

## 16. 🔍 コンテキスト収集優先順位

🔴 Flow日付フォルダ → 🔴 Stock/programs → 🟡 チームスペース → 🟡 Slack → 🔵 GitHub → 🔵 Web検索。内部情報を最優先し、外部は不足時のみ。

## 17. ⚠️ 実行エラー回避原則

①一括処理をしない（取得も更新も5〜10件ずつ） ②範囲を絞ってから取得（LIMIT必須） ③一覧取得が不安定なら既知URL起点に切替 ④並列更新は控えめに（少数件で成功パターン確立後に拡大） ⑤再実行可能性を担保（移行済み判定を持ち重複・破壊を避ける）。

## 18. ✅ 汎用検証ステップ（Universal Verification）

全タスク共通の3層検証。workflow_depthと連動: Simple=L1のみ / Standard=L1+L2 / Complex=L1+L2+L3+NFR(§19)。

| Level | 名称 | 内容 | 確認観点 |
| --- | --- | --- | --- |
| L1 | セクションチェック | 各パーツが単体で正しいか | 論理・根拠・欠落 |
| L2 | 統合チェック | 全体として整合しているか | 矛盾・流れ・トーン一貫性 |
| L3 | 受け手チェック | 受け手にとって価値があるか | 初見で分かるか・アクションしたくなるか |

**重大度語彙（P0-P3）:** 検証・レビューの指摘は共通語彙で表す。P0=正しさ・セキュリティ・データ損失に関わる必須修正（非コーディング例: 受け手への誤情報・実害）/ P1=重要な不具合・リグレッション・検証欠落 / P2=保守性・一貫性・設計上の問題（このループ内で修正すべき）/ P3=nit（任意改善）。backlogのタスク優先度P0-P2とは別概念。

**検証可能な停止条件:** 実装系タスクの完了は「作業完了の自己申告」ではなく機械判定可能な条件で判定する（例:「未解決P0/P1/P2ゼロ」「テスト全通過」）。定義できるタスクでは、その条件を満たすまで実行↔検証を反復する。

## 19. 📋 汎用NFRチェックリスト

全ロール共通4項目（ロール別追加はTPL_role_*に定義）:

| 領域 | 確認内容 |
| --- | --- |
| パフォーマンス | 成果物のサイズ・所要時間が受け手に適切か |
| セキュリティ | 機密・社外秘・個人情報の取り扱いは適切か |
| アクセシビリティ | 専門外の人が理解できるか。略語に説明があるか |
| 再利用性 | テンプレート化・次回再利用が可能か |

## 20. 🔌 汎用Extension opt-in

intent.yamlの`extensions`フィールドで宣言し、該当時のみ追加チェックを適用する。

| Extension | 適用シーン | 追加チェック |
| --- | --- | --- |
| legal | 契約書・規約 | 表現の正確性・免責・準拠法 |
| brand | 外部公開物 | ブランドガイドライン適合 |
| privacy | 個人情報を扱うタスク | GDPR/個人情報保護法準拠 |
| security | コーディング（セキュリティ要件） | OWASP Top 10・依存スキャン・認証認可 |
| testing | コーディング（性能要件） | 負荷・パフォーマンス・カオステスト |

適用: Collection時にextensionsを読み込み、各Stageで追加チェックを適用、§18のL2/L3に項目を追加する。

---
**作成日:** 2026-04-07 ｜ **更新日:** 2026-07-07 ｜ **ステータス:** Active
**バージョン:** 2.0（Fable観点軽量化: §番号据え置きで本文圧縮、§13→§11統合、Lint詳細を分離ファイルへ、Wiki波及はOperation Propagation時のみに一本化）
