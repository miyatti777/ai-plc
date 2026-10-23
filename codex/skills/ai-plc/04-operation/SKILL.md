---
name: 04-operation
description: AI-PLC Stage 4 Operation。Backlog（Agent定義があればそれ）に従ってタスクを実行し、成果物生成、検証、ステータス更新、Propagationを行う。AI-PLCタスク実行と完了処理で使用する。
---

# Codex adapter: AI-PLC Stage 4

実行前に [Codex実行環境の読み替え](../references/codex-runtime.md)を読む。正本の手順・入力・モードは実行時に読み込み、以下は環境差分として適用する。

1. リポジトリルートの `.claude/skills/ai-plc/04-operation/SKILL.md` を最後まで読み、その手順を正本として実行する。
2. `.claude/rules/ai-plc-system.md`、`.claude/rules/ai-plc-session.md`、`.claude/rules/ai-plc-adaptive.md` を最後まで読む。
3. Knowledge Lintでは `.claude/skills/ai-plc/04-operation/knowledge-lint.md`、Platform Builderでは同階層の `platform-builder.md` を読む。
4. DB、Wiki、Rules、Templatesは正本に記載された `.claude/` 配下を使用する。
5. Claude CodeのAgent toolやスラッシュコマンド表記は、利用可能なCodexのsub-agentまたは対応スキル指定へ置き換える。
6. 正本のPhase 5.5の発動強度（必須・既定・省略可）を判定する。対象になる「独立検証（maker≠checker）」は、Codexのsub-agent起動を明示的に要求する適用中の指示として扱う。対象タスクではユーザーへ再確認せず、成果物作成者とは別のsub-agent reviewerを自動起動する。
7. backlog（または Agent 定義）の`delegable: false`はPhase 4の成果物作成を並列委譲しないという意味であり、Phase 5.5の独立reviewer起動を禁止しない。
8. 独立レビュー対象でのセルフ検証へのフォールバックは、sub-agent機能が利用不能、起動失敗、またはreviewer出力を取得できない場合に限る。フォールバック時は理由をVerification recordへ1行記録する。

正本が見つからない場合はタスク実行やbacklog.yaml更新を行わず、欠落パスを報告して停止する。

**モデルの既定:** `.claude/rules/ai-plc-model-routing.md` の「実行環境の既定」に従う。本人のモデル指定が無ければ Operation は Claude Code（Opus）へ切り替える案内を出して止まり、本人が Codex での実行を明示したときだけ続行する。
