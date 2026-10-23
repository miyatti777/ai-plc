---
name: 01-collection
description: AI-PLC Stage 1 Collection。GoalとModeからExecution Contextを確立し、Context Store、intent.yaml、context.yaml、backlog.yamlを生成する。新規Scope、Sub-Agent Scope、Re-Collectionで使用する。
---

# Codex adapter: AI-PLC Stage 1

実行前に [Codex実行環境の読み替え](../references/codex-runtime.md)を読む。正本の手順・入力・モードは実行時に読み込み、以下は環境差分として適用する。

このアダプターは、Claude Code版とCodex版のAI-PLCを同じ正本で動かす。

## 実行

1. リポジトリルートの `.claude/skills/ai-plc/01-collection/SKILL.md` を最後まで読み、その手順を正本として実行する。
2. 同ファイルが参照する `.claude/rules/ai-plc-system.md`、`.claude/rules/ai-plc-session.md`、`.claude/rules/ai-plc-adaptive.md` を最後まで読む。
3. パスはリポジトリルート基準で解決する。DB、Wiki、Rules、Templatesは正本に記載された `.claude/` 配下を使用する。
4. 実行環境固有の表記だけCodexに置き換える。Claude Codeの `/01-collection` 等は、Codexでは `$01-collection` またはスキル名の指定として案内する。自動完走モード（/goal で RUL_plc_session §10 を指すとき）は正本と共通。CollectionのPhase 7の最後に出す「自動で進めるなら」の `/goal` 1行では開始列を `$02-inception` 等へ読み替え、詳細は共通の読み替え文書に従う。
5. Codexのsub-agentを使う場合は、ユーザーまたは適用中の指示が明示的に許可・要求した場合に限る。許可されない場合はメインエージェントで実行し、独立検証が必要なら正本のフォールバック規定を使う。

正本が見つからない場合は新しいScopeや成果物を作らず、欠落パスを報告して停止する。
