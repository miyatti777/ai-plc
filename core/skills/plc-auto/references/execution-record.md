# Goal・Operation・Resume共通の有効実行判定

既存の `backlog.execution_contract` と `execution_budget` を正とする。
この参照は一括実行として本人が承認した対象だけに適用し、相談・計画・Collectionだけの許可を拡大しない。通常のauto/force、基盤権限、停止/取消、品質条件を維持する。最終時だけ独立レビューする別モードの採用ではない。

## 一つの記録に固定する

開始担当は現在の信頼できる本人指示に照合し、完成物/AC、Layer、許可操作、Task/対象版、時間・追加支出・修正上限、本人へ戻す条件を既存欄へ保存する。最初の実行範囲には、依頼成果に必要な通常の管理記録・準備・保存の具体的な操作と場所を含め、現在の禁止条件と照合する。既承認の範囲をAI自身が誤って狭めたことが原指示から確認でき、本人がその制限を採択していない場合は、その誤記を担当が訂正し、同じ承認を取り直さない。本人・上位規約・実ツールが禁止した操作、又は禁止の出典/承認範囲が不明な操作は解除せず、最初の回答前に必要な差分だけをまとめる。必須手順であることだけから許可を推定せず、本人が採択したAI提案の制限も保持する。追加のReceiptやRegistry表を作らない。重い工程の有限予算はsession §7.6、軽い管理記録には新しい計時を要求しない。

共通コードを使う実行は既存契約へ `record_version: 2` を追加する。`version: 1`、mode、旧履歴は維持する。必要欄は次のとおり。

| 正本 | 欄 |
| --- | --- |
| execution_contract | run_id / status=running / layer / authorization_scope=end_to_end / authorization_ref / scope_revision / approval_revision / scope_tasks / current_task / task_versions / operations / write_set / budget_id / thread_idまたはsession_id |
| 対象Task | id / task_version / status / dependencies / output / acceptance_criteria |
| execution_budget | budget_id / started_at / status / repairs_limit / repairs_used / additional_spend_yen / additional_spend_limit_yen。既存記録はtimezone付きdeadline（必要ならrecording_reserved_from）を維持。新規の明示新区分は次段落の同じ欄へ記録 |

新規の重い実行では、作業総量を有限にし、AIが便宜的な時計期限を許可失効として新設しない。`time_policy: work_budget_v1` を明示し、`work_limit_minutes`（正の有限総量）、`work_used_minutes`（確定済み累積作業）、`active_since`（現在の作業区間開始）、`break_minutes`、`answer_wait_minutes`、`pause_history` を同じ予算内へ残す。作業消費は確定済み累積＋現在作業区間の経過。境界時刻を確認できない区間を休憩/待機として差し引かず、未取得は不明として保留する。休憩/本人回答待ちは `pause_work` で消費を確定し、kind（break/answer_wait）・paused_at・work_used_minutesを保持、現在指示を照合した再開時の `resume_work` でresumed_atと別集計を残す。これらは計時補助であり契約再開や許可付与はしない。総量/修正/支出は再開・登録・工程移行でリセットしない。

本人/サービスの実期限がなければ `deadline_kind: none`、`deadline_source: none` としdeadline欄を置かない。実期限がある場合は `deadline_kind: hard_stop`、`deadline_source: user` 又は `service` とtimezone付きdeadlineを保存し、休憩/回答待ちでも期限到達で止める。見積や進捗見直し時刻はmilestonesへ置き、許可の失効と扱わない。未知/null/矛盾した区分・出典・計時は保留。新区分に旧recording_reserved_fromを混ぜず、終了保存の余地は同じ作業総量内で確保する。time_policyの無い旧v2記録・出典不明の旧deadlineは従来の停止扱いを維持し、黙って移行しない。

operationsは承認範囲にある `plan/register_task/instruct/implement/code_check/test/review/repair/save/management_record/resume` だけ列挙する。Task追加・版変更・工程完了も同じ実行の内部処理にできる範囲へ固定する。scope_tasks外の実装や新しい版へ無断で広げない。旧予算・停止契約は履歴へ同値で保持し、同じ目的の再開で上限をリセットしない。

保存記録は認証証拠でもnative Goalの状態でもない。呼出元は現在の本人指示/ランタイムから `current_authorization` と `runtime_active`、run_id、authorization_ref、scope_revision、Task版、thread/sessionを照合する。runtimeには初期照合時のapproved_scope_sha256も保持する（.claude/skills/plc-auto/scripts/plc_execution.pyのapproval_scope_sha256で生成）。これは承認範囲・版・期限/支出/修正上限・パス、新区分では時間の役割/出典/作業総量上限の同版本人指示への束縛であって本人認証ではない。Resumeで変更後の記録から作り直して承認を捏造しない。JSONにtrueと書いたことを認証と扱わない。inlineのruntime_activeは現在の明示指示を実行する同一assistantターンの事実で、native activeの推定ではない。別threadへのforce伝播はしない。

## 同じ判定で進める

`.claude/skills/plc-auto/scripts/plc_execution.py` の `evaluate(layer, action, runtime)` をGoal境界・Operation開始/工程境界・Resumeの共通判定に使う。CLIは `python3 .claude/skills/plc-auto/scripts/plc_execution.py --layer <実在Layer> --action <操作> --runtime <現在照合したJSONの実在path>`。既定は読取判定だけで、ツール実行・native Goal変更・権限付与は行わない。呼出元が利用可能な現在のAPI/権限に従って実作業を行う。

- `continue_internal`: 同じ有効実行・Task/版/承認・予算・許可操作に一致。計画採用、Task登録、担当指示、コード確認、工程遷移、指定テスト、レビュー、許可内修正、保存を範囲内で続ける。同じA選択を再確認し、同じ開始文を再送させない。
- `read_only` / `record_only`: 許可された読取/管理記録だけ。実装許可へ広げない。
- `scope_limited` / `hold` / `stop` / `busy`: 当該操作を行わない。現在版の読取・許可内独立作業を進め、実行可能な残範囲がなければ理由と残件を返す。force中の承認質問を連発しない。通常の未委譲判断が必要なら具体的な境界を一度に示す。

本人へ戻すのは許可外の権限・送信/公開・支出・範囲/版変更、本人/サービスの実期限・総量/修正上限の変更、安全/品質未達等。具体的に許可済みの同じ操作/条件は内部で進め、工程別の採択/登録/読取/準備/検証/保存承認へ戻さない。読める・試せる不足は担当が解消する。読取対象の現版と前後の版を確認するために、本人へ別担当の共有更新完了証拠を要求しない。書込の排他条件を読取全般へ拡張しない。読取中に版が変わったら現版を再照合し、不成立なら未確認として保留する。

## Resumeと二重起動

Task/版/承認の照合とともに、[成果単位の分解・実行・再開](../../ai-plc/references/outcome-delivery.md)の原要求/明示変更・成立済み成果/証拠・Goal/SC未達・再利用調査/途中成果・次操作/待つ境界を現在正本から復元する。resume_contextや古い開始文は参考に留め、実行許可やGoal完成の証明にしない。新セッションだけを理由に調査/Collectionをやり直さず、未達成果の残範囲から続ける。

Resumeは記録のcurrent_task、scope_tasks、task_versionsと現在backlog、現在の本人許可/ランタイムを先に照合する。「同じ残作業を続けて」という現在の指示で対象が一意かつ残量/版/禁止/実期限/担当競合が成立するなら、既存の同じ許可範囲を保持して再開し、完成物/工程を一括で承認し直させない。見直し時刻や休憩だけを許可失効にせず、保存記録だけでは自動再開しない。古い開始文のTaskはdocument_task_hintとして参考に留め、例えば有効な現行Taskを旧いTaskへ戻さない。本人の現在の明示Task指定が記録と異なる場合は無視せず対象不一致として止める。本人の停止・取消・Collection限定・実期限切れ・旧記録の停止は解除しない。

実行操作を始める担当は `claim(layer, action, runtime)`（CLIでは上の判定に `--claim`）で既存Layer lock下にexecution_contract.runnerを原子的に確保する。runnerはTask/Task版にも束縛し、Task遷移前にreleaseし新しいclaimを取る。runnerがあれば結果待ち/状態確認を行い、同じTaskを再起動しない。操作終了後に `release(layer, run_id, claim_token, owner)` で同じ所有者だけが解放する。別所有者・古いrun/tokenは書き換えない。中断時のrunnerを自動で奪わず現在状態を確認する。claim/releaseは管理更新で、許可や予算を増やさない。

CCの `.claude/skills/plc-auto/scripts/plc_auto.py start` はstateのload/check/saveを排他化する。v2契約には呼出元が照合したJSONを `--execution-request` で渡し、hookも同じ実行判定へ戻る。開始時の承認Task範囲/全版map/範囲fingerprintを保持し、縮小・追加・非current版変更で終端を偽らない。従来の契約は従来経路を保持する。コードの排他は協調writerに対するもので、OS/ツール制約や全workerの独占を保証しない。

## 品質・保存・軽い記録

通常の管理更新は、同目的の既存Task・refactoring_log・context等への最小追記とセルフ整合確認にする。管理更新自体を別計画・別Task・個別reviewerの対象へ再帰させない。Goal/AC/実装/規約の変更を「管理だけ」と扱わない。成果物の独立検証、標準/complexの品質ゲート、BT判定、Phase7は現行の正本を維持する。

最終保存の判定には品質合格・未解決P0〜P2ゼロ・成果版とレビュー版の一致を渡す。CCの一式完了には契約のfinal_verificationにall_acceptance_criteria=true、unresolved_p0_p2=0、reviewed_artifactsのpath→SHA-256を保存し、成果の実在/現SHAも確認する。Task.review_outputsがあればその最終成果範囲、なければoutput全件をレビュー証拠と照合する。管理証拠自体の再帰レビューは要求しない。一式完了を未達のProject全Goal完了へ広げない。

進捗は実在する完成物・動作・AC証拠で報告し、主実装案件を一つに絞る。本人の優先度・停止/取消/Collection限定・他案件の実行枠を勝手に変更しない。

## 長期化を防ぐ継続判断（旧 RUL_plc_session §7.6 の細則を移送）

> session §7.6 は要点だけを残し、記録の形・持越し・続行判定・再評価/終了・実行側の限界はここが正本。

**適用と記録:** 重い自動実行、反復の長期化、方式拡大では、最初の工程前に `backlog.yaml.execution_budget` へ `budget_id`（同じ目的で固定）・`started_at`・`basis`（本人指定/見積に基づく仮定）・`milestones`（時刻/成果の見直し点）・`last_evidence`（受入条件と証拠パス）と有限の作業総量・修正/支出上限を残す。新規記録の時間区分/出典/計時は[共通有効実行判定](#一つの記録に固定する)に従う。本人/サービスの実期限はdeadlineとして保持し、AIが便宜的な時計期限を許可失効として新設しない。見積や見直し時刻は進捗再評価の目安である。本人指定を優先し、未指定なら既存見積から有限の作業上限を仮置きして理由を示す。その範囲で成立根拠のある作業か小さい前提確認だけを選ぶ。軽い既知作業にはこの記録・追加質問・追加レビューを要求しない。

**持越し:** 同じ目的の再試行・再計画・別セッションでも実期限と既消費を引き継ぐ。段階を分けても元の総量上限は残る。新区分では休憩/本人回答待ちを作業消費と別に記録して残量を持越す。本人/サービスの実期限と旧記録の期限は、待機中も経過し停止条件を維持する。実作業時間・待機・turn/tokenは別の値で、未取得は不明とし、換算やゼロ補完をしない。既存記録の欠落/破損時は新規予算と決めつけず復旧/確認まで重い工程を保留。新規の有限上限の仮置きは再開時のリセット許可ではない。予算を変える本人の明示指示だけを `refactoring_log` に変更前後・理由とともに記録し、既消費/開始履歴は消さない。特定の回数上限の解除を、時間等の別上限解除に拡張しない。

**続行判定:** 重い工程の開始前・ツール復帰後・見直し点で、現在時刻、残経路、残予算、次に得るAC証拠を照合する。進捗はACに対応する新しい証拠、または事前に限定した重要な不確実性の解消。ファイル/テスト/レビュー数だけの増加は継続根拠にしない。計画・予算内の長い検証は、途中でAC未達という理由だけで止めない。承認待ちの独立作業も総量上限と残経路に従い、既承認事項を聞き直さない。

**再評価・終了:** 見直し点で証拠が進まない、残予算での成立根拠がない、既存ツール利用から独自基盤開発へ方式が広がる等の場合は、§7.5で代替/限定確認/打切りを比較して既存BTへ接続する。限定確認も同じ予算を消費し、新たな確認を際限なく足さない。見積/見直し時刻の超過だけで再承認を求めず、証拠と残経路を照合する。作業総量上限・本人/サービスの実期限・旧記録の期限への到達、又は本人の早期打切り条件成立では新しい仕事を開始せず、未達・証拠・残件を記録する。次の単体修正が可能でも、全体の成立根拠にはしない。完了条件や安全性を黙って削らない。

**実行側の限界:** この規定と保存欄はモデルが呼出境界で確認する運用であり、時計による全処理の強制停止ではない。処理中の取消し不能やツール帰還の遅れを停止済みと偽らず、帰還後の新規開始を止める。安全に終了/記録する余地を計画に含め、外部書込みを無差別killしない。CCの既存Stop hookはターン終了時、CodexのGoal状態変更は提供ツールの条件内であり、停止文とnative Goal状態は別。追加の常時監視や承認/独立レビューは作らず、既存ゲートを使う。
