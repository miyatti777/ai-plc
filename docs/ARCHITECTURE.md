# AI-PLC Architecture

## 概要

AI-PLC (AI Product Lifecycle) は、PMBOKのプロジェクト管理知識体系を
AIエージェント環境（Claude Code / Cursor）向けに再設計したパイプラインシステム。

## 4ステージパイプライン

```
┌─────────────┐    ┌─────────────┐    ┌──────────────┐    ┌─────────────┐
│  Collection  │───▶│  Inception  │───▶│ Construction │───▶│  Operation  │
│  (Stage 1)   │    │  (Stage 2)  │    │  (Stage 3)   │    │  (Stage 4)  │
│              │    │             │    │              │    │             │
│ Goal設定      │    │ タスク分解    │    │ スキル生成     │    │ 実行+成果物   │
│ Context収集   │    │ Backlog作成  │    │ Agent定義     │    │ 知見伝播     │
└─────────────┘    └─────────────┘    └──────────────┘    └─────────────┘
```

## Adaptive Workflow

Goalの複雑度に応じて自動的にパイプライン深度を調整:

| 深度 | 判定基準 | パイプライン |
|------|----------|-------------|
| **Simple** | 1-2タスク・既知パターン | Stage 1 → Stage 4 直行 |
| **Standard** | 複数タスク・タスク分解必要 | 全4ステージ順次実行 |
| **Complex** | 再帰分解・SubLayer必要 | 全4ステージ + SubLayer再帰 |

## Context Cascade

親スコープから子スコープへのコンテキスト伝播を3分類で管理:

```
Parent Scope
├── global_immutable  →  子で変更不可（vision, tech_stack）
├── overridable       →  子で上書き可能（deadline, scope）
└── local_only        →  子に伝播しない（implementation_details）
```

## Execution Context 構造

各パイプライン実行は以下のファイル構造を持つ:

```
[Scope名]/
├── intent.yaml      # Goal・深度・モード・親子関係
├── context.yaml     # Context Storeの索引
├── backlog.yaml     # タスク定義
├── Context/         # 収集したコンテキスト文書群
├── Skills/          # 生成されたスキル定義
├── sublayers/       # Sub-Agent Scope群
└── Documents/       # 成果物
```

## 3層検証（Universal Verification）

| Level | 名称 | 対応 | 適用 |
|-------|------|------|------|
| L1 | セクションチェック | Unit Test | 全タスク |
| L2 | 統合チェック | Integration Test | Standard以上 |
| L3 | 受け手チェック | E2E Test | Complex |

## Post-Deliver Propagation

タスク完了後に必ず実行するチェックリスト:

1. backlog.yaml更新
2. context.yaml更新
3. memory.md チェック
4. user.md チェック
5. External Sync
6. Wiki波及更新
7. log.md更新

## Knowledge Wiki（Karpathy Second Brain）

- `wiki/index.md` — 全トピック索引
- トピックページ — カテゴリ別知見
- `wiki/log.md` — append-only時系列ログ
- CONTRADICTION検出 — 矛盾は削除せずフラグ
- Knowledge Lint — 月次ヘルスチェック
