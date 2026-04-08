# AI-PLC (AI Product Lifecycle) System

AI-PLCは、PMBOKの知識体系をAIエージェント向けに再設計した4ステージパイプライン。
Claude Code / Cursor 環境で動作するスキル群として提供される。

## 4ステージパイプライン

| Stage | Skill | 概要 |
|-------|-------|------|
| 1. Collection | `01-collection/SKILL.md` | Goal設定・Context収集・Execution Context確立 |
| 2. Inception | `02-inception/SKILL.md` | Goal分析・再帰的分解・Backlog生成 |
| 3. Construction | `03-construction/SKILL.md` | Harness（実行スキル）生成・Agent定義 |
| 4. Operation | `04-operation/SKILL.md` | タスク実行・成果物生成・Post-Deliver Propagation |

## 関連ファイル

### Persistent Memory（`.claude/` 直下）
- `soul.md` — AIの行動原則・アイデンティティ
- `user.md` — ユーザーモデル
- `memory.md` — 蓄積型知見 → wiki/ へのポインタ

### Rules（`.claude/rules/`）
- `ai-plc-system.md` — ルートシステムルール（§1〜§20）
- `ai-plc-session.md` — セッション管理ルール
- `ai-plc-adaptive.md` — Adaptive Workflow + 深度判定

### Templates（`templates/` 配下）
- `templates/roles/` — ロールテンプレート（PM / architect / developer / content / tech_lead / generic）
- `templates/agents/` — エージェントテンプレート（research / implementation / coding / review / content / operation / task_patterns）

### Knowledge Wiki（`.claude/wiki/`）
- `index.md` — 全トピック索引
- トピックページ群（運用知見・判断パターン・PJ横断の学び）

## 命名規則

| プレフィクス | 体系 | 例 |
|---|---|---|
| SKL_plc_* | Skills | SKL_plc_01_collection |
| RUL_plc_* | Rules | RUL_plc_system |
| TPL_* | Templates | TPL_role_developer |
| AGT_plc_* | Agents | AGT_plc_linter |

## コア原理

- **Context Cascade** — 親→子スコープへの3分類コンテキスト伝播（immutable / overridable / local）
- **Fractal Decomposition** — Goalの再帰的分解とSub-Agent Scope生成
- **Adaptive Workflow** — Simple / Standard / Complex の3段階深度自動判定
- **Self-Describing Task** — コンテキスト付きタスク委譲構造
