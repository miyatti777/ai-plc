---
name: 03-construction
description: AI-PLC Stage 3 Construction。Agent 定義が要るタスク（RUL_plc_adaptive §6 — complex・platform_builder・慎重モード・委譲・長い実装）に対して実行可能なAgent定義と実行計画を生成する。Agents生成、テンプレート選択、Re-Constructionで使用する。
---

# Codex adapter: AI-PLC Stage 3

実行前に [Codex実行環境の読み替え](../references/codex-runtime.md)を読む。正本の手順・入力・モードは実行時に読み込み、以下は環境差分として適用する。

1. リポジトリルートの `.claude/skills/ai-plc/03-construction/SKILL.md` を最後まで読み、その手順を正本として実行する。
2. `.claude/rules/ai-plc-system.md`、`.claude/rules/ai-plc-session.md`、`.claude/rules/ai-plc-adaptive.md` を最後まで読む。
3. AgentとRoleのテンプレートは `.claude/skills/ai-plc/templates/` を正本として使用する。
4. Claude CodeのAgent toolやスラッシュコマンド表記は、利用可能かつ許可されたCodexのsub-agentまたは対応スキル指定へ置き換える。
5. sub-agentは、ユーザーまたは適用中の指示が明示的に許可・要求した場合に限って使う。許可されない場合もAgent定義自体は生成できるため、メインエージェントで処理する。

正本が見つからない場合はAgents/を更新せず、欠落パスを報告して停止する。
