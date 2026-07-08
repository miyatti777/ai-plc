# Knowledge Lint（04-operation Phase 8 — 月次/手動発動）

> 発動: 月次、または「Knowledge Lintを実行して」の明示指示。通常のタスク実行フローには含めない。
> チェック項目の定義: RUL_plc_system §10

## 実行フロー

1. wiki の `index.md` を読み込み、全ページを走査する（概念ページ=直下 / sources/ / queries/ の3層。索引漏れページの検出も含む）
2. 5項目のLintチェックを実行:
   - 🔴 **矛盾検出** — `> ⚠️ CONTRADICTION:` フラグ（Status: open）のあるページを特定し、既存知見との不整合を検証
   - 🟡 **孤立ページ** — 他トピックからのバックリンクがないページ
   - 🟡 **引用なし** — 「Source:」記載がない事実主張
   - 🔵 **未説明概念** — 他ページで言及されるが専用トピックがない概念
   - 🔵 **欠落相互参照** — 関連すべきトピック間のリンク欠落
3. レポートを `wiki/lint-report-YYYY-MM.md` に出力:

```markdown
# Knowledge Lint Report - YYYY-MM

## 🔴 Errors（要対応）
- CONTRADICTION: [トピック] — [内容]
## 🟡 Warnings（推奨対応)
- ORPHAN / NO_SOURCE: [トピック] — [内容]
## 🔵 Info（改善提案）
- UNDEFINED / MISSING_LINK: [内容]
## 📊 Summary
- Total pages / 🔴 / 🟡 / 🔵 の件数
- 推奨アクション: [最優先3件]
- 知識ギャップを埋めるために読むべき3記事（Karpathy方式）
```

4. 🔴があればオーナーに通知する
5. `log.md` に `| YYYY-MM-DD | lint | wiki全体 | [件数サマリ] |` を追加する
