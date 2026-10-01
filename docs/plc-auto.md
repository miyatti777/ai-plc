# plc-auto

固定本文をnative Goalへ渡し、この会話で扱っているAI-PLC Layerを自動完走する専用Skillです。core 1.13.0から同梱し、CodexのSkill一覧にも `plc-auto` と表示します。

## 起動

AI-PLCをインストールしたProjectで、利用者が次のように明示実行します。

```text
$plc-auto
```

対象を明示する場合:

```text
$plc-auto Layer: /path/to/your/project/Flow/.../my-layer
```

新しく始める場合:

```text
$plc-auto Goal: チーム向けの導入ガイドを作成する
```

会話内の直近のStage実行・Layerの話題を使います。候補が複数で決められなければ停止します。対象も新規Goalも無い場合、任意の進行中案件を勝手に選びません。Skillの作成・説明・引用・自動選択ではGoalを開始しません。

## 対応条件と既存Goal

実際の環境で `get_goal`・`create_goal` と状態管理機能が利用できることが条件です。Codex desktopの利用可能な環境で設定成功を確認しています。製品名やバージョンだけから全環境で使えると保証するものではありません。

同じLayer・同じ自動完走条件のactive Goalは再利用します。別の未完了Goalは上書きせず、paused・blocked・budgetLimited・usageLimitedは自動で解除しません。再開・解除は利用者の明示指示と、その環境の実際のGoal管理機能に従います。

Goalツールが無ければ、コピペ用 `/goal <固定本文>` を表示し、**未設定のまま停止**します。Claude Codeでも直接設定ツールの有無を確認し、使えなければ `/goal` を貼る方式に戻ります。Cursorには現在 `/goal` がないため自動完走を開始せず、通常のMob Checkpointで進めます。adapterは内部app-server APIを勝手に呼んで代用しません。

## 実行範囲

成功してactiveのnative Goalがある間だけ、Mob Checkpointの⭐、Next ActionのA、P0→P1→P2・依存順の選択を自動で実行します。仮定・判断はbacklogの `refactoring_log` に `[auto-approved]` として記録します。独立検証と未解決P0〜P2ゼロの完了ゲートは維持します。

次は保留してログへ残します: git commit・push・PR・merge・タグ、外部公開、Notion・Slack・メール・外部DBへの書き込み、承認後の反映、対象外のファイル変更、削除・移動・既存成果物の上書き等。公開版session §10の範囲に従い、ローカルRegistryはprojectsのみを扱い、凍結されたtasks行に書きません。

Layerを決められない、complex/platform_builder、SubLayerの分解、BT-A、Backtrack必要、⭐無し、2回直してもP0〜P2が残る、保留操作が無いと先へ進めない、人のタスクだけが残る場合などは `⛔ 自動完走を停止: <理由>` と残件・再開方法を示します。停止表示だけでnative Goalをcompleteやpausedにしません。Goalの解除は利用可能な環境の `/goal clear` 等の管理機能を利用者が実行します。

`pipeline_variant: jev` でも通常版Stageを使います。凍結中の `-jev` 実験版を起動せず、監視opt-inを自動承認しません。

## 60ターンと測定の限界

60ターンはモデルへの停止指示です。native APIに機械的な60ターン上限を設定した意味ではなく、token_budgetにも換算しません。利用者入力またはGoal自動継続によるメインエージェントの応答1回を数え、ツール・Stage・reviewerは数えません。createdAtをrun IDとして `[plc-auto-turn] run=<createdAt> turn=<N>` をLayerのログに1回記録します。記録が欠けた場合は正確な通算値が分からないことを報告します。

今回の実測は、Project版plc-autoの明示実行によるnative Goal設定・active readbackと、公開候補の一時インストール・Skill検出を分けて確認しています。一時Projectで新規・更新・再導入をcc/codex/cursorの計9シナリオで検証し、Codexのskills/listで表示名 `plc-auto`・repoスコープの検出を確認しました。対象installer回帰は42件Passです。公開候補をインストールした後のモデル実行を含む一連の試験、全停止分岐、60ターン到達は未実測です。配布成功を全自動完走の保証と読み替えないでください。

## 配置と更新

正本は `core/skills/plc-auto/SKILL.md` と `references/goal-preset.md`、Codex adapterとUIは `codex/skills/ai-plc/plc-auto/` です。通常のinstallerでProjectへ配布されます。Codexでは `.claude/skills/plc-auto/` が正本、`.agents/skills/ai-plc/plc-auto/` が入口です。既存利用者はREADMEの通常の更新手順を使います。手編集したファイルがあればinstallerが停止するので、その案内に従って差分を確認してください。
