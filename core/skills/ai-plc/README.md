# AI-PLC (AI Product Lifecycle) System

Notion版AI-PLCパイプラインをClaude Code / Cursor環境に移植したスキル群。

## 4ステージパイプライン

| Stage | Skill | 概要 |
|-------|-------|------|
| 1. Collection | `01-collection/SKILL.md` | Goal設定・Context収集・Execution Context確立 |
| 2. Inception | `02-inception/SKILL.md` | Goal分析・再帰的分解・Backlog生成 |
| 3. Construction | `03-construction/SKILL.md` | Agent定義（要るときだけ: complex・platform_builder・慎重モード・委譲・長い実装。RUL_plc_adaptive §6） |
| 4. Operation | `04-operation/SKILL.md` | タスク実行・成果物生成・Post-Deliver Propagation |

## 自動完走モード

`/goal` の文で RUL_plc_session §10 を指すと、そのセッションの間は承認待ちで止めずに完走する（intent.yaml には何も記録しない）。Collection・Inception の完了報告の最後に Layer パスと開始列を埋めた短い `/goal` が1行出るので、それを貼る。新しい Goal から1本で走らせる「Goal から版」と、§10 の無い環境でも貼るだけで動く「自己完結版」も §10 にある。規定（自動で選ぶもの・保留する送信・停止・自動承認ログ）は RUL_plc_session §10 だけに定義。

## 関連ファイル

### Persistent Memory（`.claude/` 直下）
- `soul.md` — AIの行動原則・アイデンティティ
- `wiki/` — プロジェクト横断の知見ベース（LLM Wiki型: 概念ページ / sources / queries）
- CC native memory（`~/.claude/projects/<repo>/memory/`）— ユーザーモデル・好み・参照（PJ の状態は書かない。system §7 参照）

### Rules（`.claude/rules/`）
- `ai-plc-system.md` — ルートシステムルール（§1〜§20）
- `ai-plc-session.md` — セッション管理ルール
- `ai-plc-adaptive.md` — Adaptive Workflow + 深度判定

### Templates（`templates/` 配下）
- `templates/roles/` — ロールテンプレート（PM / architect / developer / content / tech_lead / generic）
- `templates/agents/` — エージェントテンプレート（research / implementation / coding / review / content / operation / task_patterns）

### Knowledge Wiki（`.claude/wiki/`）

LLM Wiki方式（Karpathy Second Brain系）の構造化知識ベース。規約は `wiki/wiki.md`（Schema）。

**4ページタイプ:**
- **概念ページ**（wiki直下・ASCIIスラッグ名）— テーマ別知見の本体。例: `ai-plc-operations.md`（AI-PLC運用知見）
- **sources/** — 1次ソース1本=1ページのサマリー
- **queries/** — 問いと回答のファイリング
- **特別** — `index.md`（索引・最初に読む）/ `log.md`（append-only履歴）

**運用:**
- **命名**: ファイル名=ASCIIスラッグ（kebab-case）必須。表示名（日本語）はH1+index表示名列 → `wiki/wiki.md`
- **Query運用**: いつ・誰がqueryを作り還元するか → `wiki/queries/README.md`
- **Lint**: 軽量（open 矛盾・非ASCII名・Last Updated 欠落・60KB超）を Phase 7 で月1回必須、フル6項目は手動 → `04-operation/knowledge-lint.md`（§10）

**📎 エディタ拡張（推奨）**: wikilink `[[slug]]` をクリック到達させるには Foam（`foam.foam-vscode`）等のwikilink対応拡張を導入する（`.vscode/extensions.json` に推奨登録済み）。本wikiはプレーン `[[slug]]` のみ使用（エイリアス `[[slug|表示名]]` は非対応拡張があるため使わない — 実測）。既に `[[...]]` が飛ぶ環境なら追加不要。
  - Cursorは大きな.md（例: `log.md`）のプレビュークラッシュ回避のため .md をrawテキストで開く設定（`.vscode/MARKDOWN_CRASH_TROUBLESHOOTING.md`）。Foamはraw編集画面でも `[[slug]]` を Cmd/Ctrl+click で辿れるため、プレビュー不要でナビゲートできる。

## 命名規則

| プレフィクス | 体系 | 例 |
|---|---|---|
| SKL_plc_* | Skills | SKL_plc_01_collection |
| RUL_plc_* | Rules | RUL_plc_system |
| TPL_* | Templates | TPL_role_developer |
| AGT_plc_* | Agents | AGT_plc_linter |

上は論理名。Claude Code で打つ名前は、パイプライン Stage が `/01-collection`〜`/04-operation`（Jev 実験版の `-jev` は凍結中 — RUL_plc_adaptive §5 ルール6）、ユーティリティが `/plc-<機能>`（`.claude/skills/plc-<機能>/SKILL.md`。この `ai-plc/` の下ではなく `.claude/skills/` 直下に置く）。定義は RUL_plc_system §6。

| ユーティリティ | 用途 |
|---|---|
| `/plc-someday` | いつかやるPJストック（登録・一覧・着手・取り消し） |
| `/plc-registry` | Project Registry の照会・追加 |
| `/plc-status-audit` | ステータス点検（食い違いの洗い出しと承認後の反映） |
| `/plc-viewer` | Registry ビューアの起動 |
| `/plc-jev-monitor` | Jev 判定の回収と記録（Jev 実験版パッケージ `--with-jev` に入っている。無ければ使わない） |
| `/plc-consult` | アイデア相談（判定と次のコマンドだけ返す・読み取り専用） |
| `/plc-backfill` | スキルを通さずに済ませた作業の事後記録（承認後に backlog へ ad-hoc で追加し Phase 5.5〜7 を通す） |
| `/plc-db-sync` | ローカル DB ⇔ Notion DB の同期（旧 `ai-plc-db-sync`） |
| `/plc-brief` | PJ の目的・できたこと・使い方を成果物と根拠から平易に説明（読み取り専用） |
| `/plc-next` | 欠けた Next Action の選択肢・おすすめ・開始文を補う（読み取り専用） |
| `/plc-decision` | 承認・選択の質問1件を背景・変更範囲・推奨根拠つきで解説（読み取り専用・承認は代行しない） |
| `/plc-project-status` | Project の中止（cancelled）と再計画後の再開（RUL_plc_system §21） |
| `/plc-auto` | 対象 Layer の自動完走の開始・状態確認・停止（RUL_plc_session §10） |
| `/plc-model-routing` | タスクに合う担当モデルと Advisor 相談の選択（明示依頼か `model_routing` 指定時） |

## 正本

公開版の正本は本リポジトリの `core/`（rules・skills）。Notion版の規定と同一内容を保つよう同期している。
CC/Cursor/Codex向けの配置は installer（`install.sh`）が行う。

<!-- AIPM-OPT-IN:BEGIN -->

## AIPM方式の明示選択

本人が対象Layerで明示選択した AIPM 方式（同梱の PM アドオン。目録 references/addon-catalog.yaml の aipm。新しい Layer は intent の addons に同梱の1件で書く。旧い Layer の work_style: aipm も同じに読む）は、既存modeと独立した方式。[共通Skill](../aipm-guided/SKILL.md)に従ってDocuments/aipm_project内の標準Projectと指定形式文書を順に作る。未指定/nullは従来動作。通常Stageから条件付きで参照するためCodex adapterや広域設定を変更しない。コースは質問ベース1ペルソナのInit/Discovery01〜04。

<!-- AIPM-OPT-IN:END -->
