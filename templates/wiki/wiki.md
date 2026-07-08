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

- 相互リンクは `[[ページ名]]`（wikilink）で張る。A→Bを追加したらB→Aも確認する
- ページ先頭にfrontmatterコールアウト: Type / Status / Sources / Created / Last Updated
- 事実の主張にはソースを明記: `[Source: [[ソース名]] or 実測]`
- 矛盾は削除せず `> ⚠️ CONTRADICTION:` フラグ（Status: open → resolved/superseded）
- 取り込みフロー・還元判定は `rules/ai-plc-system.md` §11、月次Lintは §10 + `skills/ai-plc/04-operation/knowledge-lint.md`

## 記憶の2系統（AI-PLC）

- **wiki（このディレクトリ）** = プロジェクト横断・共有可能な知見（バグパターン・設計判断・環境固有制約）
- **native memory**（Claude Code の `~/.claude/projects/<repo>/memory/` 等・自動管理）= ユーザーモデル・好み・進行中PJの状態

振り分け: バグ・技術知見・PJ横断パターン → wiki ／ ユーザーの判断パターン・好み → native memory。両方に重複させない。

## ページ一覧

<!-- ここに概念ページを 1行索引で追記していく（初期は空） -->
