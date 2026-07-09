# 📚 Knowledge Wiki（Schema）

> LLM Wiki方式（Karpathy Second Brain系）の構造化知識ベース。人間がキュレーション、AIがそれ以外すべて。
> プロジェクト横断・共有可能な知見（バグパターン・設計判断・環境固有制約など）はここに蓄積する。

## ページタイプ（LLM Wiki準拠）

| タイプ | 場所 | 単位 | 役割 |
| --- | --- | --- | --- |
| **概念ページ** | wiki直下 | 1テーマ=1ページ | 複数ソースを横断して整理した知見の本体。**最も価値がある層** |
| **ソースサマリー** | sources/ | 1次ソース1本=1ページ | 取り込んだ記事・論文等の要約。概念ページへの波及の起点 |
| **Queryページ** | queries/ | 1問=1ページ | wikiへの質問と回答のファイリング（比較分析/新見解/接続発見のみ） |
| **index.md** | 直下 | — | タイプ別カタログ。ingest毎に更新 |
| **log.md** | 直下 | — | append-only履歴（ingest / query-return / contradiction / lint） |

## Convention

- 相互リンクは `[[ascii-slug]]`（プレーンwikilink）で張る。A→Bを追加したらB→Aも確認する
- **ファイル名=ASCIIスラッグ（kebab-case）必須**（例: `design-decisions.md`）。日本語ファイル名はwikilink拡張が解決できずクリック不可（実測）
- **表示名（日本語）は必須2箇所で保持**: ①各ページ先頭のH1 `# 表示名` ②index.mdの「表示名」列。frontmatter `title:` は任意。**エイリアス記法 `[[slug|表示名]]` は現行wikilink拡張で非対応のため使わない**
- ページ先頭にfrontmatterコールアウト: Type / Status / Sources / Created / Last Updated
- 事実の主張にはソースを明記: `[Source: [[source-slug]] or 実測]`（ソースサマリーもASCIIスラッグ名でリンク）
- 矛盾は削除せず `> ⚠️ CONTRADICTION:` フラグ（Status: open → resolved/superseded）
- 取り込みフロー・還元判定は `rules/ai-plc-system.md` §11、Lintは §10 + `skills/ai-plc/04-operation/knowledge-lint.md`（非ASCIIファイル名も検出項目）
- Query運用（queries/への問いのファイリング）の発火点2種・判定・ライフサイクルは queries/README（SSoT）。還元判定は §11
- **環境差:** ASCIIスラッグ必須はファイルシステム上のwikilink解決の話。Notion等ページID/mentionで解決する環境ではページタイトルは日本語のままでよく（リネーム不要）、`[[...]]` はmention-pageに読み替える

## 記憶の2系統（AI-PLC）

- **wiki（このディレクトリ）** = プロジェクト横断・共有可能な知見（バグパターン・設計判断・環境固有制約）
- **native memory**（Claude Code の `~/.claude/projects/<repo>/memory/` 等・自動管理）= ユーザーモデル・好み・進行中PJの状態

振り分け: バグ・技術知見・PJ横断パターン → wiki ／ ユーザーの判断パターン・好み → native memory。両方に重複させない。

## ページ一覧

<!-- ここに概念ページを 1行索引で追記していく（初期は空） -->
