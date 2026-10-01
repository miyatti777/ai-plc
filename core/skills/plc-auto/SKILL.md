---
name: plc-auto
description: この会話のAI-PLC Layerに固定文面のネイティブGoalを設定して自動完走を開始する。利用者が $plc-auto またはAI-PLC自動完走の開始を明示したときに使う。
---

# plc-auto

利用者が `$plc-auto` を実行すると、[固定Goal](references/goal-preset.md)を `create_goal` に渡し、この会話で扱うLayerの続きを実行する。`/goal` 文の表示だけで終わらない。Skillの作成・編集・説明・プレビュー依頼ではGoalを開始しない。

## 起動

0. 実際に利用できる `get_goal`・`create_goal` と状態管理ツールの規約を確認する。環境名だけから機能があると推測しない。使えない場合は固定本文のコピペ用 `/goal` を返し、未設定で停止する。`/goal` 自体も無い環境では対応環境での実行を案内する。app-serverの内部APIをSkillから勝手に呼んで代用しない。
1. 実行対象のリポジトリと、存在する `AGENTS.md` / `CLAUDE.md` の指示を確認する。この会話の直近のStage実行・Layerの話題を使って対象を決める。任意のinflight案件を拾わない。明示されたLayerパスがあれば優先し、候補が複数で決められなければ固定Goalの停止文を出す。
2. `references/goal-preset.md` 全文を読み、本文を `objective` にする。Layerが確定していれば絶対パスを末尾に追記する。新規Goalが明示されていればその内容も追記する。ユーザーから追加指定がある場合は、その指定を優先する。
3. `get_goal` で現在のGoalを確認する。同じ対象・同じ自動完走条件のactive Goalなら再利用する。別の未完了Goalは上書きせず、解消に必要な操作を知らせる。blocked・usageLimited・budgetLimitedも自動で上書き・解除しない。paused Goalの再開は利用者の明示指示と利用可能なネイティブ管理機能に従い、再作成や `update_goal` で代用しない。
4. Goalが無いか既存Goalがcompleteなら `create_goal({objective})` を呼ぶ。`$plc-auto` の実行は固定Goalの設定と記載された自動承認範囲への明示指示として扱う。単なるSkill自動選択や引用だけから設定しない。トークン予算の明示指定があるときだけ、正の整数の `token_budget` を追加する。60ターンをトークン数に換算しない。
5. ツールの成功を確認してから「Goalを設定した」と伝え、同じターンでStageの実行に進む。Goal機能が使えない場合は同じ本文のコピペ用 `/goal` を返し、未設定であることを明示して停止する。

## AI-PLCとの接続

- Codex/Claude Codeでは対象リポジトリの `.claude/rules/ai-plc-system.md`、`ai-plc-session.md`、`ai-plc-adaptive.md` と、実行するStageの正本を読む。Cursorでは`.cursor/rules/ai-plc-*.mdc`と`.cursor/skills/`の対応する正本へ読み替える。必要なRules/Stageが無ければ欠落パスを報告して止まる。本文中の `/01-collection` 等はCodexの `$01-collection` 等へ読み替える。アダプターだけ読んでStageの処理を推測しない。
- 固定Goalは識別句「AI-PLC 自動完走（自己完結版）」を含む。このSkillの明示実行で設定されたnative Goalがactiveである間に限り、固定GoalのMob Checkpoint・Next Action・タスク選択の自動承認を適用する。これは利用者が指定した専用入口であり、他のStageの既定動作は変更しない。
- `pipeline_variant: jev` でも通常版を使う。Jev実験版を解凍せず、opt-inを代筆せず、凍結中の会話監視を起動しない。
- Layer作成後、`backlog.yaml` の既存 `refactoring_log` 形式に合わせて `[auto-approved] plc-auto Goal開始（自己完結版）` を記録する。これは実行記録であり、将来の会話の承認根拠にはしない。ユーザーが `/goal` を入力したと偽って記録しない。
- Stage正本が求める検証・独立レビュー・BT判定・Propagation・ステータス点検を行う。`tasks.yaml` と `backlog.yaml` が併存する場合は、そのLayerの正本を確認してから更新する。

## 停止と完了

- 固定Goalの保留・停止条件を守る。保留した作業や未確認ACを検証済み完了と扱わない。`deferred`・`blocked` はタスク完了と区別し、理由・残件・再開条件を報告する。
- 最大60ターンはモデルへの実行指示であり、native Goalの機械的な上限ではない。利用可能な実行情報で把握し、ターンは利用者入力またはGoal自動継続で開始したメインエージェントの応答1回を数える（reviewerは含めない）。GoalのcreatedAtをrun IDとし、最初のLayer作成後は1、以後は当該runの記録から加算して、各ターン開始を `[plc-auto-turn] run=<createdAt> turn=<N>` とLayerのrefactoring_logに1回だけ記録する。同じ応答内の再呼び出しでは加算しない。ツール呼び出しやStage数をターン数と数えない。正確な通算値を確認できない場合はその限界を明示する。
- Goalの状態操作は実際のツール規約に従う。停止文の表示だけで `complete` にしない。`blocked` は同じ障害が3回以上の連続Goalターンで再発し、進捗不能という条件を満たす場合だけ。`paused` は利用者が明示的に一時停止を頼んだ場合だけ。60ターンの実行指示を `token_budget`、`paused`、架空の終了APIで代用しない。
- 完了時は成果物の存在・検証結果・Phase 7チェックリスト・自動承認ログと保留事項を示す。固定Goalの達成条件を満たして必要な作業が残っていない場合だけ `update_goal({status: "complete"})` を呼ぶ。停止時は `⛔ 自動完走を停止: <理由>` と残件・再開方法・native Goalの実際の状態を示す。必要なら利用者が `/goal clear` でGoalを解除できることを添える。
