---
name: 02-inception
description: AI-PLC Stage 2 Inception。IntentとContextからGoalを分析し、BacklogとSub-Agent Registryを生成する。Goal分解、Re-Inception、backlog.yaml作成で使用する。
---

# Codex adapter: AI-PLC Stage 2

実行前に [Codex実行環境の読み替え](../references/codex-runtime.md)を読む。正本の手順・入力・モードは実行時に読み込み、以下は環境差分として適用する。

1. リポジトリルートの `.claude/skills/ai-plc/02-inception/SKILL.md` を最後まで読み、その手順を正本として実行する。
2. `.claude/rules/ai-plc-system.md`、`.claude/rules/ai-plc-session.md`、`.claude/rules/ai-plc-adaptive.md` を最後まで読む。
3. Rules、Templates、DB、Wikiへの参照はリポジトリルートの `.claude/` 配下へ解決する。
4. Claude Codeのスラッシュコマンド表記は、Codexでは対応する `$02-inception` 等のスキル指定へ置き換えて案内する。
5. sub-agentは、ユーザーまたは適用中の指示が明示的に許可・要求した場合に限って使う。それ以外はメインエージェントで分解・検証する。

正本が見つからない場合はbacklog.yamlを更新せず、欠落パスを報告して停止する。
