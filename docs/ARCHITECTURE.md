# AI-PLC Architecture

## 概要

AI-PLC (AI Product Lifecycle) は、PMBOKのプロジェクト管理知識体系を
AIエージェント環境（Claude Code / Cursor / Codex）向けに再設計したパイプラインシステム。

## 環境別アダプターと共有runtime

配布物は、環境固有の起動面を薄いadapterに分離し、AI-PLCの正本を共有する。

| 環境 | Skill / command | 永続指示 | 起動 |
| --- | --- | --- | --- |
| Claude Code | `.claude/skills/`・`.claude/commands/` | `CLAUDE.md` / `AGENTS.md` managed region | `/01-collection` |
| Cursor | `.cursor/skills/`・`.cursor/rules/` | Cursor rules | `/01-collection` |
| Codex | `.agents/skills/` | `AGENTS.md` Codex managed region | `$01-collection` |

Codex adapterの`SKILL.md`は、正本である`.claude/skills/ai-plc/`と`.claude/rules/`を参照する。
このためCodex modeは共有`.claude` runtime（Skills、Rules、DB、Wiki seed）も配置するが、
Claude Code固有のcommands/agentsやnative memoryは利用しない。

```
target repository/
├── AGENTS.md                         # 既存本文 + 環境別managed region
├── .agents/skills/ai-plc/            # Codex adapter
├── .agents/skills/utility/           # Codex共有utility Skill
├── .claude/skills/ai-plc/            # CC/Codex共有の正本runtime
├── .claude/rules/                     # CC/Codex共有Rules
├── .claude/wiki/                      # 初回seed後はユーザーデータ
├── .claude/db/                        # helper + local SQLite
├── .ai-plc-install-manifest           # component / owner / hash
└── .ai-plc-version                    # 配布version
```

## Installer transaction model

`install.sh`は`cc`・`cursor`・`codex`を環境別wrapperへdispatchし、`both`・`all`は
multi-environment plannerで処理する。すべての経路は共通のtransaction・manifest modelを使う。
manifestはfileとmanaged regionごとにcomponent、owner、hashを記録し、共有資産を別環境の
uninstallから保護する。writeはlock・journal・temporary publish・rollbackを使い、
`--dry-run`はtargetを変更せず、`--plan-only`は機械可読planを返す。

`AGENTS.md`は通常本文を置換せず、Claude CodeとCodexで別々のmarker regionを所有する。
uninstallは指定ownerだけを外し、変更済みfileやユーザーデータを残す。残存物があれば
manifestをdetached状態にして、追跡情報を失わない。

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
├── Agents/          # タスクごとのAgent定義
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
3. native memory（ユーザーモデル・好み。Claude Code native memory）
4. External Sync
5. Wiki波及更新
6. log.md更新
7. Project Registry DB更新

## Knowledge Wiki（Karpathy Second Brain）

- `wiki/index.md` — 全トピック索引
- トピックページ — カテゴリ別知見
- `wiki/log.md` — append-only時系列ログ
- CONTRADICTION検出 — 矛盾は削除せずフラグ
- Knowledge Lint — 月次ヘルスチェック
