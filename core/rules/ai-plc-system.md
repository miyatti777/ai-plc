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

- **個別Projectの表示名:** 現在目的は intent.goal、人向け表示名は intent.display_name（未設定なら scope_name）、Registry の現在名は projects.name への承認済み投影。scope_name・ID・path は固定。改名の判断と反映の手順は `plc-registry/SKILL.md`（命名の判断と表示名の限定更新）が正本

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

**呼び出し名（実行環境での名前）:** 論理名とは別に、Claude Code で打つ名前を次で決める。

| 種別 | 形 | 置き場所（CC） | 例 |
| --- | --- | --- | --- |
| パイプライン Stage | `0N-<stage>`（Jev 実験版の末尾 `-jev` は凍結中 — RUL_plc_adaptive §5 ルール6） | `.claude/skills/ai-plc/`（本体）＋ `.claude/commands/`（呼び出し用ラッパー） | `/01-collection` ・ `/04-operation` |
| ユーティリティ | `plc-<機能>`（kebab-case） | `.claude/skills/plc-<機能>/SKILL.md`（直下。CC は `.claude/skills/` の1階層だけを認識する。中身は SKILL.md 1ファイルで、処理は既存スクリプトを呼ぶ） | `/plc-someday` ・ `/plc-registry` |

ユーティリティの論理名は `SKL_plc_<機能>`（例: SKL_plc_someday）。現行のユーティリティ: plc-someday / plc-registry / plc-project-status（Project中止/再開・§21） / plc-status-audit（実験版のスクリプト）/ plc-viewer / plc-consult / plc-brief / plc-decision / plc-next / plc-backfill / plc-auto / plc-model-routing / plc-db-sync（旧 `ai-plc-db-sync`。Cowork プラグイン版は作り直しまで旧名で残る）。

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

- **wiki（.claude/wiki/）** = プロジェクト横断・共有可能な知見。バグパターン・設計判断・環境固有制約はここ（運用は§11、Lintは§10）
- **CC native memory（~/.claude/projects/&lt;repo&gt;/memory/）** = ユーザーモデル・好み・参照（user/feedback/reference 型のみ。**project 型は作らない**）。PJ の状態は Registry・backlog、Layer の中の約束は intent・backlog、オーナーの残作業はあなたの TODO 管理が正（AI-PLC の範囲外）。Layer が閉じても続く禁止は feedback 型、閉じても使う参照は reference 型に書く。**概念ページ原則（LLM Wiki準拠）:** 1ファイル=独立して参照される1概念。frontmatterのtypeがSchema、MEMORY.mdがindex、`[[名前]]`で相互リンク。時点情報（現在のフォーカス等）は概念ページに置かず、backlog/logに置く

振り分け: バグ・技術知見・PJ横断パターン→wiki / ユーザーの判断パターン・好み→native memory（feedback）。両方に重複させない。native memoryのユーザーモデルに基づいて対応を調整する。本人専用のプロフィール・価値観・期間限定の状況は §22 のとおり共有の置き場へ写さない。

## 8. 🔄 Post-Deliver Propagation ルール

SKL_plc_04_operation Phase 7として必ず実行する（省略禁止）。最後の「ステータス点検」は、Registry DB 更新まで終えた後に完了するLayer自身の食い違い（intent・backlog・Registry・memory）を判定器で確かめる項目（.claude/ai-plc-jev/scripts/README_status_audit.md）。各項目は「確認→判断→結果出力」の3ステップを踏む。確認せずにスキップすることは禁止（確認の結果「該当なし」でのスキップは可）。

Phase 7では以下のチェックリストを必ず出力する:

```
📋 Phase 7: Propagation チェックリスト
- [x] backlog.yaml更新 — [タスクID] status → completed + Output: [成果物パス]
- [x] context.yaml更新 — 成果物エントリ [ファイル名] を追加（運用タスクの1回は runs に追記。context.yaml は初回に置き場を1行だけ）
- [x] native memory — [feedback/reference の追記・新規 or 「変更なし — スキップ」]（§7。PJ の状態は書かない。オーナーの残作業はあなたの TODO 管理へ（AI-PLC の範囲外））
- [x] External Sync — [sync_targets確認: 「未定義→スキップ」 or 「push実行: N件」]（sqlite の tasks は凍結のため対象外 — §9）
- [x] Wiki波及更新 — [ingest / query-return の更新内容 or 「新規性なし — スキップ」]（Query結果が §11発火点①に該当すればqueryページ化＋概念還元）＋軽量Lint（§10）
- [x] log.md — [表の行を追加 or 「Wiki更新なしのためスキップ」]
- [x] Project Registry DB — [「cancelled→中止状態保持」 or 「未完了/Goal未達→スキップ」 or 「全AC達成・検証済み→completed更新」]（§21）
- [x] ステータス点検 — [`python3 .claude/ai-plc-jev/scripts/aiplc_status_audit.py --brief --layer <Layer>` の結果: 「食い違いなし」 or 「N件→承認後に `--quiet --approval-template --layer <Layer>` → `--apply <承認ファイル>` で反映」 or 「点検ツールなし／終了コード2 — スキップ」]（読み取り専用。検出と提示まで・反映は承認後）
```

順序: Phase 5.5 Verification（§18）→ Phase 6 Status Update → Phase 7 Propagation。検証未完了の成果物をPropagationしない。

## 9. 🔗 External Sync 仕様

PJ内で発見したが今実行しないタスクを、独立実行できる形で外部に書き出す機構。intent.yamlの`sync_targets`で同期先を宣言する。

**2つの役割:** 📤 タスク委譲（コンテキスト付きで外部に書き出す） / 🔄 ステータス同期（backlogの変更を外部DBに反映）。

**Self-Describing Task構造（委譲チケットの必須フィールド）:** title / description / context{source_project, source_layer, source_task, decision_ref} / related_docs / constraints / acceptance_criteria / priority / due_date（任意）。そのチケットだけで実行できる状態にする。

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

**実行手順:** ①intent.yamlのsync_targetsを読む ②空→デフォルト（`.claude/db/ai_plc.db` の projects テーブル、push。Project 行の status 等は Phase 7 の Project Registry DB 項目で更新する）を自動適用。sqlite の projects が同期先のときは Phase 7 の Project Registry DB 項目がその更新を兼ねるので、External Sync 行は「Project Registry DB で反映→スキップ」と書く ③mapping/status_mapで変換しsync_directionに従い同期 ④結果をログ出力「✅ External Sync: [type] [target] — [ID] を [ステータス] に更新」。ユーザーが「同期不要」と明言した場合のみ `sync_targets: []` のまま。
**タスクは同期しない（2026-10-01〜）:** Registry のローカル tasks テーブルは backlog.yaml の古い写しとして凍結済み。タスクの正は backlog.yaml だけで、`plc_query.py add-task` で行を足さない（凍結中は `[SKIP]`）。既存 Layer の sync_targets に `#tasks` が書かれていても読む側で無視する。Notion の Tasks DB にもローカルからは送らない。

## 10. 🧹 Knowledge Lint ルール

wiki配下の知識ベース健全性を検証する（軽量はSKL_plc_04_operation Phase 7で月1回必須・フルは手動。実行手順詳細は `.claude/skills/ai-plc/04-operation/knowledge-lint.md`）。

**軽量Lint（月1回・必須）:** その月の最初の Operation Phase 7 で、概念ページの open 矛盾・非ASCIIファイル名・Last Updated 欠落を調べ、60KB超のページ名とあわせて log.md に lint 行を1行残す。**フルLint**（6項目＋`wiki/lint-report-YYYY-MM.md`）は手動指示のときだけ。手順は knowledge-lint.md。

## 11. 🌊 Wiki波及更新ルール（Ingest Ripple — LLM Wiki準拠）

新しい知見を得たら、LLM Wikiのページタイプ型（概念ページ=wiki直下 / sources/ / queries/ — Schema定義はwiki.md）で波及更新する。**発動タイミング: SKL_plc_04_operation Phase 7 Propagation時**（Collection段階では発動しない）。**唯一の例外はQuery capture（下記「Query結果の還元」発火点②）** — 会話中の問いの queries/ へのファイリングは即時可（curated層である概念ページを触らないため）。ただしその**概念ページ還元は Phase 7 に従う**。

**Ingest手順:** ①外部1次ソース由来の知見は `sources/YYYY-MM-DD_[slug].md` にサマリー（1ソース=1ページ。内部知見は不要） ②index.mdで関連概念ページを特定 ③概念ページに `- [YYYY-MM-DD] [Source: [[source-slug]] or 実測] [内容]` を追記（該当節か末尾の `## 追記 YYYY-MM`） ④`[[ascii-slug]]` で相互リンク（エイリアス記法は使わない） ⑤必要なら新規概念ページ＋index.md更新（ファイル名はASCIIスラッグ必須。表示名はH1とindexで保持） ⑥log.mdに表の行1行 `| YYYY-MM-DD | ingest | [ソース] | [影響数] |` ⑦frontmatterのlast_updated/source_count更新

**Query結果の還元:** 発火点は2種 — ①Deliver中（Phase 7 Propagation）のQuery結果 ②タスク外の調査・相談で得た結論（会話中にAIが「query化候補」と1行**提案のみ**。承認後にファイリング／ユーザーが見送ったら同一トピックで再提案しない）。いずれも 🔴比較分析 / 🟡新見解 / 🔵接続発見 に該当するものを `queries/YYYY-MM-DD_[slug].md` にQ&Aファイリングし、概念ページへ還元する（log種別: `query-return`）。単純な事実確認・既存知見の範囲内・PJ固有ローカル情報はスキップ。詳細は queries/README。

**スキップ条件:** 既存wiki知見の範囲内で新規性がない場合（その旨を出力する）。

## 12. ⚠️ 矛盾検出・フラグ機構（CONTRADICTION)

新情報が既存知見と矛盾したら、削除せず両方を保持してフラグを立てる:

```markdown
> ⚠️ CONTRADICTION: [既存主張] vs [新情報]
> Source: [出典] / Date: YYYY-MM-DD / Status: open | resolved | superseded
```

フロー: 既存主張の直下に挿入（Status: open）→ index.mdの該当行に⚠️。解決時: Statusを更新し `> Resolution: [内容] (日付)`、廃止主張は取り消し線（削除しない）、⚠️を除去。log は ingest 行に `+contradiction` の印だけ。open はページのフラグで数える。

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

🔴 Flow日付フォルダ → 🔴 Stock/programs → 🔴 Local横断検索（Grep/Glob/serena） → 🔴 Project Registry照会（plc_query） → 🔴 wiki（設計知見・過去の学び） → 🟡 native memory（ユーザーモデル・好み・参照） → 🟡 接続済みMCP検索（Notion/Drive/Gmail/GitHub等） → 🟡 チームスペース/Slack → 🔵 Web検索。

**内部・既存資産を最優先**し、外部は不足時のみ。**利用可能なものだけ使う**（未接続MCP・未導入ツール・serena無しは黙ってスキップし、エラーにしない）。各収集は §17 に従い件数を絞る。

## 17. ⚠️ 実行エラー回避原則

①一括処理をしない（取得も更新も5〜10件ずつ） ②範囲を絞ってから取得（LIMIT必須） ③一覧取得が不安定なら既知URL起点に切替 ④並列更新は控えめに（少数件で成功パターン確立後に拡大） ⑤再実行可能性を担保（移行済み判定を持ち重複・破壊を避ける）。

## 18. ✅ 汎用検証ステップ（Universal Verification）

全タスク共通の3層検証。workflow_depthと連動: Simple=L1のみ / Standard=L1+L2 / Complex=L1+L2+L3+NFR(§19)。

| Level | 名称 | 内容 | 確認観点 |
| --- | --- | --- | --- |
| L1 | セクションチェック | 各パーツが単体で正しいか | 論理・根拠・欠落 |
| L2 | 統合チェック | 全体として整合しているか | 矛盾・流れ・トーン一貫性 |
| L3 | 受け手チェック | 受け手にとって価値があるか | 初見で分かるか・アクションしたくなるか |

**AC充足の証拠と表記:** 検証レポートと完了報告はRUL_plc_session §7.2のAC達成度を用い、一部・未達・未確認と残件を明示する。検証手順の終了やNo findingsをAC達成と混同しない。重い工程の開始前の判定可能性・費用・推奨は同§7.5に従う。

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

適用: Collection時にextensionsを読み込み、各Stageで追加チェックを適用、§18のL2/L3に項目を追加する。方式（同梱の PM アドオン〔旧い欄 `work_style: aipm` も同じ〕 / `dev_style`）や持ち込みのアドオン（`intent.addons`）を本人が選んだ Layer では、`.claude/skills/ai-plc/extensions/contract.yaml` と `references/addon-seam.md` を各 Stage の該当 Phase で読む（未選択の Layer では読まない）。

## 21. Projectの終了状態と中止判断

Project Registry の状態は `planned / active / paused / completed / cancelled`。Layer の `deferred` は `paused` の互換表現、`blocked` は外部依存による未解決で `active` のまま。`completed` は元Goalの全AC達成と検証済みの場合だけで、Task全終端や中止を成功とみなさない。`cancelled` は元Goal未達の意図的終了で、完了率の分子に数えず別表示する。

- 中止・再開の正式入口は `plc-project-status/SKILL.md`（`project_lifecycle.py`）。AI の自己判断や完了点検だけで中止しない。Goal/AC・Task実績・成果物・元Projectは削除しない
- cancelled の Layer では Operation は再開手順へ案内して停止し、Propagation・Backfill・点検は cancelled を保持する
- 再開は明示の再開承認と replan_ref を伴う active への遷移だけ。異なる Goal なら新 Project を作り置換先として結ぶ
- 外部 Notion への中止 metadata 同期は未対応・別承認（他 status へ黙って変換しない）

## 22. 本人専用情報

公開版には本人専用情報の store は無い。本人のプロフィール・好み・価値観・期間限定の状況を、共有の Context・wiki・native memory・リポジトリへ写さない。

---
**作成日:** 2026-04-07 ｜ **更新日:** 2026-10-14 ｜ **ステータス:** Active
**バージョン:** 3.0（軽量化: 10/1 版（v2.9）を土台に §21 を要点へ、§22・§3 の細則を references / 各スキルへ移した。以前の版履歴は git）
