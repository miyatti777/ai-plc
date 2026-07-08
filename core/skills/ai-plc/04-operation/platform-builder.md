# Platform Builder（04-operation Phase 9-11 — mode=platform_builder 全タスク完了時のみ）

> 発動: intent.yamlの mode が platform_builder で、backlogの全タスクがcompletedになったとき。direct modeでは発動しない。

## Phase 9: Production Skill自動生成

1. 実行結果から変数化ポイントを抽出し、variables.yaml（Parameter Store）を更新する
2. Production Skill（量産用スキル定義: 実行手順 + 変数バインド箇所 + ガードレール）を自動生成する
3. Phase 10に遷移する

## Phase 10: Production Run（量産実行ループ）

1. Production Skill と variables.yaml を読み込む
2. 変数をバインドする（処理対象データがあれば適用）
3. **Mob Checkpoint（停止）:** 実行内容を人間が確認
4. Runtime Execution: DB操作・AI生成・ページ作成等を実行する
5. Eval Output: 実行結果の記録・品質評価
6. 繰り返しが必要ならステップ1に戻る

出力: 量産された成果物 / ステータス・プロパティ更新 / 品質評価データ。

## Phase 11: Eval Feedback（知見蓄積）

1. 量産実績の知見をContext Storeに追加し、context.yamlを更新する
2. 有価値な知見があればWiki波及更新（RUL_plc_system §11）
3. 次回改善ポイントを記録し、Stage 1: Collection にフィードバックを戻す（継続改善サイクル）
