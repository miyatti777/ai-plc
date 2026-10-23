# Codexで正本を実行するときの読み替え

手順・入力・モード・完了条件は、毎回読む `.claude/` 側の正本で決める。このファイルは実行環境の差分だけを扱い、Stageの手順や新しいモードの規定を複製しない。

## 正本と参照先

- Stage: `.claude/skills/ai-plc/<skill>/SKILL.md`。Jev実験版（凍結中）: `.claude/skills/ai-plc-jev/<skill>/SKILL.md`。補助スキル: `.claude/skills/plc-*/SKILL.md`。
- 全Stageの共通ルールは `.claude/rules/ai-plc-system.md`、`ai-plc-session.md`、`ai-plc-adaptive.md`。正本に参照が追加されたら、その追加先も読む。
- 案件ごとの説明設定は `.claude/rules/ai-plc-session.md` §7.0を正とする。intentの読み込み・継続/一時変更・判断材料の保持を共通正本から適用し、Codex固有の説明仕様や別modeは作らない。
- `.claude/`・`scripts/`・`Flow/` で始まるパスはリポジトリルート基準。Markdownの相対リンクはリンクを書いた正本のディレクトリ基準で解決する。
- `templates/roles/`・`templates/agents/` は `.claude/skills/ai-plc/templates/`。`.agents/skills/ai-plc/templates/` の互換コピーを新規実行に使わない。
- Jev版Operationの `[knowledge-lint.md](knowledge-lint.md)` と `[platform-builder.md](platform-builder.md)` は通常版 `.claude/skills/ai-plc/04-operation/` の同名ファイルを使う（Jev版ディレクトリには存在しない）。
- 正本や実行に必要な参照が欠ける場合は欠落パスを報告し、影響する処理を止める。任意の未接続MCPは正本の規定どおりスキップする。

## コマンド・ツール・権限

- 分類の実行環境の値は `codex`。01-collection の intent.yaml の `classification.executor` と、04-operation の Phase 6 でタスクに書く `executed_by` に使う（正本の雛形の `claude-code` を置き換える）。
- `/01-collection`〜`/04-operation`、`/plc-*` は同名の `$skill-name` 指定に読み替える（各 `-jev` 版は凍結中。`$0N-*-jev` が指定されたら実行せず、凍結中であることと本体版の `$0N-*` を案内する。`pipeline_variant: jev` の Layer も本体版として扱う）。引数・Layer・Task・variantは保持し、正本に追加された入力もそのまま扱う。
- スキル一覧に未掲載なら、該当アダプターの絶対パスを添えて「このSKILL.mdを読んで実行」と案内できる。スキル追加の自動検出が反映されない場合はCodexを再起動する。
- Codexアダプターがないコマンドを存在する `$skill` として案内しない。`.claude/commands/<command>.md` を読み、そこで指す正本SKILL.mdの絶対パスで案内する（この参照だけでは実行・書き込みの承認にならない）。
- ClaudeのRead/Grep/Glob/Bash/Editは、利用可能なファイル読み取り・`rg`・シェル・編集ツールに置き換える。AGTの `tools` は役割の権限宣言として扱い、利用不能なClaude tool名を呼ばない。
- sub-agentの成果物作成委譲と独立レビューを区別する。Operation Phase 5.5およびBT-B/BT-Cは正本の発動強度・明示要求に従う。`delegable: false` は成果物作成の委譲を制限し、独立reviewerの起動を禁止しない。reviewerには成果物と検証用定義だけを渡し、会話履歴は渡さない。
- Mob Checkpoint、Next Action、Backtrack、外部送信の扱いは正本とユーザーの明示指示に従う。アダプターを更新したこと自体で承認済みにはしない。
- 全AI-PLCスキルの最終応答（plc-brief等の説明・読取専用も含む）で、共通session §7.4の最低出力「次のアクション＋次のプロンプト」を省略しない。実行/読取案には現在地に合う同名の `$skill`・具体対象・得る成果とコピー可能な全文を添え、未掲載時は実在adapterを示す。AIの工程停止をユーザー向け終了案にせず、Stage/Task完了後もGoal未達の正式な次入口を案内する。真の完了・本人保留取消・承認待ち・結果待ちは状態を保持した返信文にでき、存在しない入口を作らない。既存の有効案は欠落だけ補い、追加質問・必須中継・自動実行・再承認を増やさない。送信前の照合は共通正本に従う。
- Next Actionの初回案内で、共通正本session §7.4の選択肢・推奨理由・コピペ用開始プロンプトを同時提示する。A選択後までプロンプトを遅らせず、UI質問/選択肢の同文ミラーとは別項目にする。開始文は上の実在する `$skill-name` 読み替え、未掲載時は正本SKILL.mdの絶対パス案内を使い、Layer/Task/variantと本人指定の条件を保持する。未選択・未回答・先出し/UI受付は実行承認ではない。開始内容1件・許可範囲・条件と回答時の開始動作を事前提示した現在の有効な質問への本人の明確なA等の最終選択回答は、その範囲の明示開始指示として扱う。候補クリック/UI自由文/通常チャットを同じ照合にかけ、同じ担当が回答受信から既許可処理を実行し結果を返す。開始文のコピー/再送・同じ承認・追加A確認を要求しない。対象違い/旧版/取消/範囲外/必要な専用権限不足では止め、実行中/処理済みを二重起動しない。同処理続行の前提に新しい投稿API・操作ID基盤を追加しない。提示済み開始文の直接送信にも追加A確認を要求せず、共通正本session §7.4/§9.1の品質・予算・停止条件を適用する。非同期質問の待機/終了/保存はsession §9.1を維持し、表示のためのfinalや新しい承認ゲートを作らない。
- 公開版にはライブ表示（BacklogLive）は無い。手元に `tools/BacklogLive/server.py` があるときだけ使える（無ければ何もしない）。

## 人の承認・選択の質問UI

明示force中はsession§10.1/force-contractの承認非要求を優先し、以下の通常判断待ちへ戻らない。

全AI-PLC Stageと補助スキルの開始時に `.claude/rules/ai-plc-session.md` を読み、§9.1を既存の人の判断点に適用する。説明だけで終えず現在のtool schema/モードで用途に許されたUIを呼ぶ。承認範囲、通常Next Actionの明確な最終選択回答による開始（§7.4）、Material Ambiguity、§10自動選択/保留/停止は共通正本を維持する。

- `functions.request_user_input_async` が提供され用途を許可されている場合、呼出しは直ちに帰還し、本人回答は後続ユーザーメッセージで届く。awaitは発行受付までであり回答待機ではない。現在の環境に正規の回答待機手段があるか確認し、ある場合は未回答のままfinal/ターン完了にせずその手段で待つ。ない場合はsession §9.1の保存・文章再開経路を使い、UI保持やSkillだけでの修復を保証しない。accepted・既定選択・要求解消/resolvedを本人回答とみなさない。別用途のwait・反復sleep・空呼出しで延命しない。
- UIへ送る質問文と選択肢を通常会話にも同文で必ず残す。質問前に説明/準備を済ませ、許された非終端メッセージで提示する。上位規約で不可ならsession §9.1の文章再開経路に同文と制約を残す。UI回答/文章回答を質問ID・対象版・許可範囲へ照合して保存し、取消済み・旧版・別質問への回答を流用しない。
- `functions.request_user_input` は承認/権限昇格へ転用しない。明確化にも現在のPlan専用/任意質問用などの制約を確認する。別環境での利用可能性・用途許可をこの記述から推定しない。
- 許可された質問UIがない・用途禁止・失敗なら原因と対象依存処理の保留、許可された環境での再提示/再開方法を示す。UI目的のモード切替や禁止ツールの代用をしない。明確な本人文章指示は既存権限どおり扱い、UI/通知の未確認を分けて残す。
- §10で自動選択/仮定する判断に質問UI・本人回答待ちを追加しない。人の明示承認が必要な境界だけUIで待つ。既承認作業への重複質問や追加の承認ゲートを作らない。
- UI発行/表示・OS通知到達・本人回答は別の証拠。macOS通知許可/アプリ設定/CLI notifyやhookだけでは質問のバナー到達を証明しない。実通知はアプリを離れた本人観測とUI回答、版/ホスト/設定/時刻を記録し、未取得は未確認にする。設定変更や別チャット送信を自動承認したとは扱わない。
- [App Server仕様](https://learn.chatgpt.com/docs/app-server#toolrequestuserinput)では未回答要求のターン開始/完了/中断によるクリアもresolvedで通知される。Desktopのasyncと同じ実装かは、その環境の証拠なしに断定しない。静的規約の確認と実UI寿命・回答配送・回答後の正常完了は別に検証する（2026-10-08確認）。

## タスク別モデル選択の環境差分

Operationのモデル選択は正本のopt-in条件に従い、`.agents/skills/ai-plc/plc-model-routing/SKILL.md` から共通正本を読む。選択CLIは `--environment codex`。現在のtool schema/CLI helpで実在するmodel・推論強度を確認して渡し、モデルoverrideのあるspawnではfull-history forkを使わずTaskと必要入力を明示する。担当/Advisorの委譲権限をこの読み替えで増やさない。

保存されたexec JSONにserved-model IDが無ければactual_model=null/未確認とする。要求値や設定から補完せず、親チャットの自動切替を実証したとは報告しない。Advisorと独立reviewerの契約は共通正本を維持する。

## 自動完走モードとCodexのGoal

**明示forceの入口:** `$plc-auto force`、または本人が対象/Goal付きで「権限委譲・人への承認要求なし・最後まで実行」を直接指示した場合は本ファイル末尾の経路節とsession§10.1へ（過去の報告/引用/改修依頼は除く）。force中の承認非要求と許可済み操作の扱いはforce-contractを読み、上の通常質問UI/待機へ戻らない。既存native Goalの継続は作成ツールを必須にしない。native経路が未公開/未確認なら今回本人が指定したforceを同一assistantターンのcodex-inlineで実行する。以下の通常Stage向け「Goalを提示して待つ」はこの専用入口の代わりに適用しない。既知の拒否/エラー/paused/対象衝突をfallbackで越えず、native設定や背景継続と偽らない。終端ツールの存在だけからactive Goalを推定しない。通常autoと明示forceの境界・終了/再開は正本を読む。

自動完走の規定は `.claude/rules/ai-plc-session.md` §10を読む（`/goal` の文が §10 を指すセッションの間だけ適用。intent.yaml には記録せず、旧版の `run_mode: auto` は無視する）。通常版・Jev版とも同じ規定を適用し、ここには承認範囲や停止条件を複製しない。

Codexにもネイティブの `/goal` がある。Collection・Inceptionの完了報告の最後に出す `/goal` 1行は、正本のLayerパス・達成条件・§10への参照を保持し、開始列だけ同名の `$skill` 指定へ変える（例: `/goal <Layerの絶対パス> を $02-inception → $04-operation で完走する …`。`$03-construction` を挟むかは正本 §10 の開始列に従う）。`pipeline_variant: jev` の Layer も本体版の `$skill` にする（Jev 実験版は凍結中）。スキル側ではGoalを設定せず、利用者がこの1行を送るのを待つ。

正本末尾の `or stop after 40 turns` をCodexの設定項目やトークン予算に変換しない。CodexのGoal用プロンプトでは「最大40ターンで終了し、未完了なら残件と再開手順を報告する」という実行指示に読み替える。これはモデルへの指示であり、Codexの機械的なターン上限を設定したと報告しない。Goal機能が利用不能なら、同じ達成条件と開始列を持つ通常の実行プロンプトを提示し、継続が必要なときの再開方法を添える。

**手動停止の導線:** デスクトップでは対象チャットの入力欄上のGoal進捗行から一時停止／クリアを選ぶ。CLIでは当該CLIが対応する `/goal pause`・`/goal resume`・`/goal clear` を案内し、デスクトップの操作方法へ一般化しない（[Desktop公式資料](https://learn.chatgpt.com/docs/reference/slash-commands)）。Goalを作る・止める操作はユーザーの明示指示時だけ行い、スキルの利用だけからGoal設定を推測しない。

**Goal終了時の共通処理:** 通常の `/goal` から進めた場合も、本ファイル末尾の「Codex の実行許可と Goal 継続の経路」節の公開能力確認・「停止能力の通知」・終端処理（6）を参照する（plc-auto/SKILL.md §2.2 は要点のみ）。この参照だけではplc-autoを開始しない。停止toolの不在からGoal不在を推定せず、能力不足だけで本人のGoal実行を禁止しない。不在案内や上の手動停止導線は毎回の応答へ添えず、通知条件は正本に従う。native停止成功は正式操作の成功を確認した場合だけ報告する。Skillや停止文だけでアプリの自動継続を停止できるとは保証しない。

累積予算は共通正本session §7.6のbacklog.execution_budgetを使い、Goal作成/再開や会話の分割でリセットしない。提供ツールに時間期限の設定引数がなければ、モデルが呼出境界で確認する運用であることを明示する。停止表示だけでGoalをcompleteにせず、paused/blocked等は現在のツール条件に従う。

## 通常3Phaseの表示補助（Codex限定）

通常の `02-inception` Phase4（分解承認前）・Phase6（登録後案内）・`04-operation` Task完了報告を作る直前は、[Phase別の表示補助](phase-output.md)の該当節から骨格・別場面の例・送信前照合を読む。手順・権限・形式の正は既に読む共通正本で、この資料は表示の補助だけに使う。共通正本・上位指示・本人指示と食い違う場合はそれらを優先し、不整合を記録する。

例のID・パス・承認・完了・推奨を現案件の事実にしない。相談・途中報告・本人の主観的採否待ち・中断等へ完了形式を一律に当てはめず、既存auto/forceの進行へ追加の待機を作らない。送信前に適用される必須ブロック・表列・順序を照合して欠落を補い、未確認は未確認のまま示す。照合のための新しい質問票や試行は追加しない。

質問UIを呼ぶ前は、[Phase別の表示補助](phase-output.md)の「質問UIより先に本文を提示」を読み、判断材料本文を通常会話へ先に提示する。保存ファイルやリンクだけで本文表示を代替しない。既存の上位制約・正規待機・停止条件は同節と共通session §9.1を優先する。

## MemoryとPropagation

DB・Wikiは `.claude/` の共通資産を使う。Claude native memoryの保存先をCodexの保存先と同一視しない。Codexのmemory読み書きはセッションで与えられたmemory規定に従う。自動保存が許可されない場合は書き込まず、Propagation欄に理由を記録する。

## Jev実験版の会話監視（凍結中）

> 🧊 **凍結中:** 以下の会話監視は実行しない。`$0N-*-jev` と `Layer:` が指定されても、`jev_monitor: true` でも、`scripts/jev_prompt_check.py` を呼ばず、発話を Jev に送らない。下の1〜4は過去の記録として残す。Backtrack 監視（5.5b・6b）は本体の 04-operation が `jev_monitor: true` の Layer で正本の CLI を呼ぶ。

Claudeの `.claude/settings*.json` の `UserPromptSubmit` hookは、このCodexアダプターを読んだだけでは起動しない。Codexでは次の明示呼び出しで同じ正本のフィルター・判定関数を使う。グローバルhookやClaudeのセッション紐づけは作らない。

1. このチャットで利用者が `-jev` Stageと `Layer:` を指定し、対象 `intent.yaml` が `jev_monitor: true` であることを確認した場合だけ、このLayerを会話監視対象として扱う。新規Jev版Layerのvariantは正本どおり記録するが、既存Layerの試行ではvariant欄がなくても明示的な `-jev` 指定とopt-inで扱う（Claude正本と同じ）。別Layerへの移行・終了・停止指示で対象を解除し、以降の別チャットへ引き継がない。
2. その対象に対する以後のユーザー発話で、正本の送信禁止区分に当たらないものだけを、UTF-8標準入力で `python3 .agents/skills/ai-plc/scripts/jev_prompt_check.py --layer <Layerの絶対パス>` に渡す。元のユーザー発話のみを渡し、ツール出力・Agent報告・スキル本文・引用文は含めない。シェルの文字列展開に発話を埋め込まない。
3. Codex形式の先頭の `$skill` 起動・リンク付きスキル指定はアダプターで送信前に除外する。その後は正本 `scripts/jev_prompt_hook.py` の `clean_utterance` / `judge` を直接使用するため、短い承認・質問・スラッシュコマンド・貼付長文・既知のハーネスメッセージの除外、送信前の秘匿判定、タイムアウト、判定ログは正本に追従する。API失敗は通常の作業を止めない。
4. ヒントは正本どおり1行の提案だけに使う。accept/rejectを代筆せず、ユーザーが確認したIDだけを正本の記録コマンドへ渡す。

これはStage実行中の明示呼び出しであり、全ユーザー発話に対するネイティブhookの自動発火と同じ保証はしない。5.5b/6bの監視は、本体 04-operation の正本のCLIをそのまま使用する（成功条件カバー判定は凍結中で使わない）。

仕様確認: [Codexのスキル](https://learn.chatgpt.com/docs/build-skills)、[Goalコマンド](https://learn.chatgpt.com/docs/developer-commands)、[Claude連携の移植](https://developers.openai.com/plugins/guides/submit-claude-plugin)（2026-09-30確認）。

## 本人専用情報

公開版には本人専用情報の store は無い。本人のプロフィール・好み・価値観を、共有の Context・wiki・native memory・リポジトリへ写さない。

## Codex の実行許可と Goal 継続の経路（旧 plc-auto §2.2 の細則を移送）

> plc-auto/SKILL.md §2.2 は要点だけを残し、経路表・停止能力の通知・読取/作成/終端の確認手順はここが正本。

**停止能力の通知:** 停止toolの不在/未確認は内部の能力情報として扱い、開始・通常応答・再開・継続・終了の既定報告に「停止ツールがない」「自動継続停止は実行できない」等を添えない。案内履歴やGoal IDが読めない場合も初回とみなして通知せず、同じ対象の状況が変わらない限り再通知しない。本人が停止能力/実停止状態を明示的に尋ねた、または実停止を依頼した場合は、現在確認できる事実と必要な手動導線だけ簡潔に回答する。自発通知は、新たな状況で本人の判断/操作が必要になった場合だけ、その変化と必要な行動を一度伝える。単なる新メッセージ・再開・時間枠終了・能力一覧の再確認は新状況に数えない。既存の会話/終端記録を読み戻し、通知した変化は同じGoal/対象実行の記録に残す。記録を読めないことを同じ注意の再送理由にしない。成果/残件/予算境界の報告は続けるが、報告を省いたことはnative停止の成功を意味しない。

1. `.agents/skills/ai-plc/references/codex-runtime.md` とforce時の追加契約を読む。Stage名は同名の `$skill` に読み替える。
2. 現在の公開namespace一覧とtool schemaの名前・説明から、Goalの読取／作成／終端能力を確認する。遅延ツール検索が提供されている場合だけそれも使い、公開されない名前を推測して呼ばない。`get_goal/create_goal/update_goal/stop_goal` という特定名だけを必須にせず、たとえば `codex_goals` の正式namespaceにある能力も確認する。`current turn's goal` 限定のtoolは現在ターンのGoalにだけ作用し、親から別threadを指定する停止へ流用しない。未提供の判断は観測した環境に限定し、別環境のカタログを現在の能力とみなさない。終端操作の `complete/block` 等だけがあることはactive Goal・対象・自動継続の証拠ではない。ユーザーの `/goal` 明示実行をツール不在だけで否定せず、信頼できるランタイムの対象/状態/継続情報を使う。未提供のGoal状態はunknownとし、設定済み・activeとは報告しない。結果は内部記録とし、上の「停止能力の通知」に当たるときだけ案内する。手動停止導線はcodex-runtimeを参照し、能力不足を新しい実行承認ゲートにしない。
3. 使える読取ツールがあれば既存Goalを読む。アクセス拒否/読取エラー、既知のpaused・別対象/別モードGoal・対象未確定のactive Goalは停止し、inlineで回避しない。読取手段が未公開で、Goal/衝突も未確認という場合は「native状態未確認」と表示する。Goal作成/更新の拒否や失敗を機能不在と読み替えない。
4. 経路は次の表で決める。判断用CLIは `python3 .claude/skills/plc-auto/scripts/codex_route.py --force --goal-state unknown` 等。引数は観測した機能/状態だけから渡す。これは経路判断だけで、Goal設定・ワークフロー実行・権限付与を行うスクリプトではない。

| 観測した状態 | 実行経路 |
| --- | --- |
| 同じ対象・同じforce条件のactive Goalと継続経路がランタイム/読取結果で確認できる | **native-existing**。作成ツールは不要。既存Goalの継続としてStageを進める |
| Goalなし/completeが確認でき、作成ツールが公開されている | **native-created**。通常autoは固定Goal、forceはforce Goalをobjectiveにし、本人指定を追記。ツールの成功後だけ「Goalを設定した」と報告する |
| native経路が未公開/未確認で、今回本人がforce実行を明示し、既知の拒否/paused/衝突がない | **codex-inline**。native作成を待たず同じターンで許可内のStageを実行する。「native Goalは未設定/状態未確認、背景の自動継続は未設定、今回は同一ターンのforce実行」と明示。プロンプト表示だけで終わらない |
| forceなしでnative経路が使えない | 通常autoの既定を維持。コピペ用Goal/再開方法を返し未設定と明示。forceを補完しない |

5. inlineの権限は今回の本人実行指示から取り、履歴・状態ファイルから復元しない。`execution_contract.runtime: codex-inline`、`run_id`、取得できるときだけ実thread ID、`status: running` と範囲を記録する（run_idは記録用、セッションの証明ではない）。同じassistantターン内のツール操作・Stage遷移に限って自動判断を続け、終了/停止/partial/clear/対象変更で状態を閉じる。中断・応答終了後はrunning記録が残っても自動再開しない。現在の「同じ残作業を続けて」という本人指示又はforce再指定で、共通有効実行判定の対象/版/残量/実期限/禁止/競合を照合して再開する。同じ有効な範囲の完成物や内部工程を承認し直させず、取消/打切り/条件変更は別の本人判断を維持する。別スレッド作成/送信・heartbeat等の監視を勝手に設定しない。
6. native Goalの作成/終了/blocked/paused操作は現在のtool schemaと条件に従う。2で確認した正式な能力を使い、全Layerタスク終了だけでGoal全体達成とはせず、元Goal/AC/範囲を確認してから正式completeを使い、成功後だけnative終了を報告する。blockedは現在schemaのブロック条件を満たす場合だけ使う。停止表示・partial・時間枠終了をGoal completeにしない。inlineではnative状態を更新したと報告せず、ローカルexecution_contractにcomplete/partial/stopped/clearedと残件/再開条件を記録する。終端経路の判断は同CLIの `--finish-result complete|partial|stopped` と観測済み能力を使える。終了ツールが未公開/対象未確認ならローカル終端結果・native未操作/未確認・`terminal_reported: true` を同じGoal／実行に対して一度記録する。この内部記録を不在案内の出力義務と解釈しない。以後の継続ターンで完了Layerの再検算/再audit/同じ最終報告を反復しない。本人の新指示/状態確認に応じた作業や再判定でも、変わらない停止能力の通知は上の条件に従い省く。手動停止導線も必要な通知/回答時だけ使い、Skill・停止文・ローカル終了記録だけでnativeエンジンを停止できたと偽らない。終了toolの拒否/失敗は原因を記録し、別toolへの置換や自動再試行で越えない。60ターンをtoken_budgetへ換算しない。inlineにはターンを越える機械的継続/上限はなく、累積予算§7.6を境界で確認する。
