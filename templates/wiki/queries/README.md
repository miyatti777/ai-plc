> 🏷️ **Type:** wiki-schema
> **Context:** queriesディレクトリの規約 — wikiへの質問と回答のファイリング（LLM Wiki準拠）

# queries/ — Queryページ

wikiに対する問いとその回答をファイリングする。還元判定（RUL_plc_system §11）: 🔴比較分析 / 🟡新見解 / 🔵接続発見 に該当する問いだけをページ化し、単純な事実確認はファイリングしない。

## 命名

`YYYY-MM-DD_[slug].md`（例: `2026-07-07_wiki-vs-native-memory.md`）

## テンプレート

```markdown
> 🏷️ **Type:** query
> **Asked:** YYYY-MM-DD
> **Category:** 比較分析 | 新見解 | 接続発見

# Q: [問い]

## A: [回答の要約]

## 根拠・参照
- [[concept-slug]] / [[sources/YYYY-MM-DD_slug]]

## 概念ページへの還元
- [[concept-slug]] — [何を追記したか1行]
```

## 運用ルール

### いつ・誰が作るか（発火点2種）

1. **Deliver中（Phase 7 Propagation）** — タスク実行で調べた結果が判定基準に該当 → Operationが自動でqueryページ化して概念へ還元
2. **タスク外の調査・相談** — Web調査や設計相談で判定基準に該当する結論が出たら、会話中にAIが「これはquery化候補です」と**1行提案**（Backtrack会話監視と同じ軽さ。ユーザーが「残して」でも自発でも可）

### 判定基準（該当かつ再利用性あり）

- 🔴 **比較分析** — A vs B の判断（例: wiki方式 vs native memory）
- 🟡 **新見解** — 既存概念ページを更新する新事実
- 🔵 **接続発見** — 既存の複数知見をつなぐ発見
- ❌ **スキップ** — 単純事実確認 / PJ固有ローカル / 既存知見の範囲内

### ライフサイクル

- queryページは**残す**（append-only的、問いの記録として価値）
- **概念ページへの還元は必須**（`## 概念ページへの還元`欄を埋める）。還元先が無ければ新概念ページ化を検討
- log.mdに `query-return` エントリ
