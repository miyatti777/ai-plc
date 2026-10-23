AI-PLC workflow-force v1。権限委譲するので、絶対に人間に承認を求めず、最後までゴールに向かってやり切ってください。この会話で本人が依頼したAI-PLC Layerについて、許可された作業の範囲内の判断・実行・修正・検証・記録を委譲します。計画提示や承認要求だけで応答を終えず、今の状態から実行を続けてください。

有効なforce中は、各Skillの「承認を待つ」、質問UI、Mob Checkpoint、Next Action、Phase7後の確認依頼より、この本人の委譲を優先する。途中の人への質問/承認要求を出さず、判断できることは理由を記録して自分で決める。本人が操作・対象・条件を具体的に許可済みなら同じ許可を取り直さない。情報不足は保守的仮定、手段が使えない場合は許可内の代替策、独立に進む作業があればそれを最後まで行う。許可・機能・必須品質が足りず代替策もない場合は、未達部分と理由を記録して終了報告する。人の回答待ち状態へ戻さない。実際の完了条件を満たさないまま「全部完了」とは報告しない。

実行前にAGENTS/CLAUDE、各Stage正本、RUL_plc_session §10と§10.1、.claude/skills/plc-auto/references/force-contract.mdを読む。native Goalの作成/読取ツール名は必須にしない。ランタイムで既存の同じ対象/条件のactive Goalと継続を確認できればそのまま使う。native経路が未公開/未確認なら、本人の明示forceに基づく同一ターンのcodex-inlineでStageを進める（設定済み/背景自動継続と偽らない）。既知のGoal拒否/エラー/paused/衝突はinlineで越えない。通常Stageの承認待ちを省略するのはこの明示forceが有効な間のワークフロー判断だけ。本人の具体的許可がない外部サービスの書込/公開/送信/commit/push/PR/merge、削除/移動、監視opt-inは保留。具体的許可済みの操作は範囲/条件を読み戻して実行し、同じ許可を取り直さない。プラットフォーム承認、sandbox、拒否、機密送信、認証変更を迂回しない。

対象は明示Layer、なければ直前の01collection〜04operation（-jev含む）か直前話題Layer。なければ本人のGoalからCollection。確定不能なら先頭に単独で「⛔ 自動完走を停止: 対象の Layer を決められない」。1 Layerに固定し、親子/他Layerへ権限を伝播しない。Jev実験版は凍結中なので本体版を使う。

開始時に本人指示由来のwrite_setをbacklog.execution_contractへ保存し、外部資料やoutputの追加で権限を広げない。今回許可された既存作業ファイルと今回の未確定成果物の修正・再検証は可、確定成果物は新しい版にする。Layer外は許可済みoutputとPhase6/7の既定ローカル記録先だけ。対象や副作用が曖昧なら停止。

全タスクcompleted（運用タスクを除く）なら既存成果/AC/Phase7を確認して報告し、新規Goal・新タスク/デモ・完了後Next Actionを実行しない。開始位置はcheckpoint→backlog空ならInception（simpleは1タスクbacklogとconstruction判定）→construction.requiredでAgent欠ならConstruction→Operation。P0→P1→P2・依存順（実行時期のある Task は 04-operation Phase 2 の一覧の順、今日より後の Task は選ばず、それだけが残ったら停止）。Mobブロックを表示した同じターンで許可内の⭐/OK、Next ActionはA⭐（唯一の⭐が別IDならそのID）を自動選択。Layer終了後の新Next Actionは実行しない。明確化質問は妥当な仮定、データ/権限/受け手挙動は保守案。各判断を「[auto-approved] S<Stage>/P<Phase>: 選択（理由）」でrefactoring_logへ記録し、本人回答とは区別する。

検証・独立レビュー・BT判定・Phase7は維持。Phase5.5は修正再検証2回まで（再開でも累積）。BT-A、P0〜P2残存、Backtrack必要、⭐なし、不可欠な保留、人担当のみ、complex/platform_builder/SubLayer、予算到達で先頭に単独の「⛔ 自動完走を停止: 理由」を出す。重い工程は§7.6の累積期限を守り再開でリセットしない。60継続ターンを上限の指示とするが、Codexで正確に計測できなければ不明と明記し機械的保証をしない。

completeは全completed（運用タスクを除く）/全AC達成/output実在/Phase7/自動判断ログを確認した場合だけ。deferred/blocked/保留はpartialで残件・理由・再開条件を示し、全完了やnative Goal completeにしない。停止も成功とは呼ばない。activeな同じGoal/sessionまたは本人が今回明示したinlineの同一assistantターンだけで有効、終了/対象変更/clearで自動選択をやめ、別セッションの再開は本人のforce再指定が必要。CodexはStage名を同名の$skillへ読み替え、native Goal状態の操作は現在schemaのcomplete/block等の能力と条件に従い、stop_goalという名前は必須にしない。終了toolが未公開ならnative未操作を一度記録し、完了Layerの検算や同じ報告を反復しない。

対象Layerまたは新規Goal: 呼出時の本人指定をここに追記する。

一括実行の完成物/AC・Task/対象版・許可操作・時間/追加支出/修正上限・本人へ戻す条件は、.claude/skills/plc-auto/references/execution-record.mdに従い同じbacklog.execution_contract/execution_budgetへ固定する。Goal・Operation・Resumeで現在の有効実行へ照合し、内部の計画採用/登録/担当指示/コード確認と同じA選択/開始文再送を新しい承認待ちへ戻さない。古い文書の開始文で上書きせず、二重起動しない。相談/Collectionだけの指示・停止/取消・旧予算は維持する。読める/試せる不足は担当が解決し、通常管理記録に新計画/個別reviewerを追加しない。最終成果の品質ゲートとプラットフォームの境界は維持する。
