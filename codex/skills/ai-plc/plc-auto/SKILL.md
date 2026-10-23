---
name: plc-auto
description: この会話のAI-PLC Layerを自動完走（RUL_plc_session §10）で最後まで進める。Codexは利用可能なGoal継続経路（明示forceは同一ターン実行にも対応）、Claude Code は状態ファイル＋Stop hook で続ける。利用者が $plc-auto（clear・status を含む）またはAI-PLC自動完走の開始を明示したときに使う。
---

# Codex adapter: plc-auto

1. 実行前に [Codex実行環境の読み替え](../references/codex-runtime.md) を読む。
2. リポジトリルートの `.claude/skills/plc-auto/SKILL.md` を最後まで読み、そこで参照する固定Goalと起動手順（§2.2 Codex）を正本として実行する。正本内の `references/goal-preset.md` は正本ディレクトリ基準で解決する。
3. このSkillの明示実行は、正本§2.2で利用可能なGoal継続経路を確認してAI-PLC実行を始める入口への本人指示として扱う。forceのnative経路が未公開なら同一ターンのcodex-inlineで進め、Goal設定/背景継続と偽らない。通常Stage利用だけからGoalを作らないという既定規定は、他のSkillで維持する。作成・編集・説明・引用だけではGoalを開始しない。
4. 先頭の `force` / `--force`、または本人が対象/Goal付きで「権限委譲・人への承認要求なし・最後まで実行」を直接指示した場合は、正本のworkflow-forceへ渡し、force-contractとgoal-force-presetを読む。過去の実行報告/引用/改修依頼は開始指示にしない。通常の固定Goalと混ぜず、既存Goal/対象の束縛、または今回の本人inline実行指示を確認する。force中は各Skillの待機に戻らず、許可内の判断・代替策・実行・検証・記録を進め、許可済み操作の再承認を求めない。代替不能なら理由を報告して終了し、承認質問へ戻さない。
5. `pipeline_variant: jev` のLayerも通常版を使う。その他のツール規約・保留条件・停止条件は正本に従う。
6. 正本や選択したGoal/force契約が欠ける場合はGoal設定もStage実行も行わず、欠落パスを報告する。
