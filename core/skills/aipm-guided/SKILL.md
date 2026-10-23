---
name: aipm-guided
description: AI-PLCで本人が明示選択した同梱のPMアドオン（AIPM。旧い欄 work_style: aipm）のProject初期化・ペルソナからストーリーへの指定形式文書生成・検証。通常Stageから条件付きで読み込む。
---

# AIPMの形式で一歩ずつ進める

## この AIPM モードが扱う範囲

- 扱う：立ち上げの工程（3つのコースとも、1人の利用者について課題→仮説検証→解決策→ストーリーまで）で作る19文書と、その内部保存
- 扱う（箱の中の操作）：論点・仮説・ToDo の1件の操作と、会議・FB の後の取込（下の「箱の中の操作（pm-）」。「案件側の一覧」を選んだ案件だけ）、19文書の改訂の範囲の案（書き換えはしない）
- 扱わない（今は無い）：日次・週次の締めと見直し、フェーズ・契約・PJ の終了時の引継ぎ
- 「AIPM」と呼ぶ別の仕組みとは、名前が同じでも中身が同じとは限らない。この AIPM モードを入れたことを、別の仕組みの置き換え・統合と扱わない。日次・週次の締めや引継ぎについて聞かれたら、このモードでは扱わないと答える（会議の後の取込は pm-capture、今日の1件は pm-today）

本人が対象LayerでAIPMを明示選択したときだけ `intent.yaml` の `addons` に同梱の1件（`addon_id: aipm`・`source: bundled`）を保存する（新しい Layer に `work_style` は書かない。旧い Layer の `work_style: aipm` は同じに読む）。引用・過去の報告・候補としての説明は選択ではない。未指定/nullは従来経路、保存値は勝手に補わない。`mode` のdirect/platform_builder、Role、深度、通常/auto/forceの権限は共通正本のまま。子への強制伝播や既存Layer一括更新はしない。選択解除はPMの選択を両方の欄（addons の同梱の1件と旧い欄）から外し、文書を保持する。

## 同梱アドオンとしての扱い

このスキルは同梱の PM アドオンとして目録（[addon-catalog.yaml](../ai-plc/references/addon-catalog.yaml) の aipm）に載る。選んだときは `addons` に同梱の1件を書く（上の段落）。旧い Layer の `work_style: aipm` は目録の `legacy_alias` で、判定関数 `.claude/skills/ai-plc/scripts/plc_addon_select.py` が同梱の aipm を選んだものとして読む（intent は書き換えない。一括の移行はしない）。`aipm:` の設定（course・registers・storage・stock_selector など）と `mode_init` の置き場・意味は変えず、`addons` の1件の中へ移さない。同梱の aipm は `addon_init` を使わない。

## 正本・入力

[固定版](canonical.yaml)はlivyn-inc/aipm-commands commit `2a7cdb8a77cb1b20e1325649faac0d7f177afb62`。[原文](source/)5コマンド、19raw templates、[形式schema](format_schema.yaml)のhashを確認する。これは元のCursorコマンドをAI-PLCへ接続した手順で、原文シェルをそのまま実行しない。利用者は本人/Contextから理解し、架空属性やインタビューを補完しない。

既存探索型は `question_based/single_persona`、Init→ペルソナ→課題→仮説検証→解決策→ストーリー→内部保存。この順序・19成果・本人判断を維持する。単一利用者向けにsolution_based/single_personaとdocument_based/single_personaのローカル拡張を追加し、下記の別生成契約を使う。多人数分岐や05以降の文書生成は未対応。

`aipm` は任意map: `program_id` / `project_id` / `date`（YYYY-MM-DD）/ `persona_id`（P001等）/ `name_slug` / `course`。未指定のIDは既存scope_id/scope_name、personaはP001、slugはuser。識別子はASCIIの英数字/ハイフン/underscoreだけ。日本語scope_nameなら明示project_idを設定する。人物属性をこの識別子から推測しない。保存場所は固定 `Documents/aipm_project`、その内部だけにFlow/Stockを作る。別Registry Projectは登録しない。share値はdisabled。

## 箱の中の操作（pm-）

AI-PLC の Stage（Collection〜Operation）は、箱づくりを含めて「この Task をやれ」と命じる外側の命令。pm- は、Stage が作った箱の中のアイテムを1件ずつ扱う操作の型で、AI-PLC を知らなくても操作の名前で分かる（顧客向け PMO の pmo- と同じ2層。AIPM と AIPMO は構造が同じで、作る箱と操作が違う）。本文は `ops/<操作>.md`、呼び出しは `/pm-<操作>`、処理は `package.py op --name <操作>.<動き>`（ops.py）。

| pm- | 扱うもの | 書くか |
| --- | --- | --- |
| pm-issue | 論点を足す・分ける・答えの案・閉じる・解決する・全体を見る | 書く（試す→本人の確定→`--apply`。resolve・close は本人の受領記録か決定の記録が要る） |
| pm-hypothesis | 仮説を足す・AI の判定の案・崩れた仮説の影響 | 書く（同上。owner／decider の判定は `judge`） |
| pm-todo | ToDo を足す・動かす・WBS につなぐ・遅れを見る | 書く（同上。owner・期限は推測しない） |
| pm-capture | 会議・FB のメモから、判定の案・論点・ToDo の候補 | 案だけ（確定した候補を上の3本で書く） |
| pm-today | 箱の中から今日の1件 | 案だけ |
| pm-persona | ペルソナと課題の改訂の範囲 | 案だけ（19文書はその場で書き換えない。改訂は Stage で工程をやり直す） |
| pm-story | 解決策とストーリーの改訂の範囲 | 案だけ（同上） |
| pm-init | 途中から AIPM にする入口（今の状態と次に打つコマンド） | 案だけ |

- 書く操作は、書く前後で registers の検査（E_REGISTERS）を比べ、新しい問題が出たら書く前に戻す。`--apply` が無ければ試すだけ
- AIPM を選んでいない Layer では止まる（論点・仮説・ToDo・capture・today は「案件側の一覧」も要る）。**例外は pm-init**：方式を選ぶ前の Layer で動き、何も書かない（選ぶのは Collection の推薦と本人の回答）
- pm- は AI-PLC の backlog・Task の状態を変えない。Task の手順には「pm-issue で論点 I3 を分ける」のように名前で書く
- 人が決めること（論点の resolved・仮説の owner／decider の判定・WBS の受入・owner や期限）は pm- が代わりにしない

## Stageとの接続

1. Collection: 実選択の根拠とコース/必要IDをContextへ保存し、選択を `addons` の同梱の1件で記録する。**初期化は Collection の最後（01-collection Phase 7.5 の初期化の段）で行う**：同梱の aipm の選択（旧い Layer は `work_style: aipm`。目録の aipm の `init`。記録先は `mode_init`）が初期化の宣言で、別の OK の後に下の 4 の init を呼び、init の返却の `outputs`（作った package の format_contract・project_init・README と、registers を選んだときは registers/ の5ファイルの path と sha256）をそのまま `mode_init.outputs` に書く。scope_reinitでは成果を保持する。Phase 7.5 の別の OK では、Goal と Context から書いた WBS の下書き（`--drafts` の YAML）を見せてから init する。aipm の初期化は plc_addon.py を呼ばない（collection_init はアドオンの addon_init 用）。
2. Inception: 形式schemaの19documentsと13工程フォルダ×2を必須成果/ACへ加える。初期化は Collection で済んでいる前提で、persona→problem→validation→solution→story→archiveの依存をTaskへ束縛する（初期化を Task として登録しない。`mode_init` の無い旧い Layer だけ、従来どおり初期化を依存の先頭に置く）。既存Taskが同じ成果を持つなら追加重複しない。仮説の計画と実結果は別にする。`aipm.registers: true` の Layer は、論点の表（registers/issues.yaml）と charter が作り終えた条件を満たすこと（validate の issues.yaml への `E_REGISTERS` が0件）を必須成果／AC に加える。あわせて、成果物を作る Task に wbs_id（registers の WBS の行）、論点に答える Task に issue_id を書く（成果物に当たらない Task は `wbs_id: none`）。issue_id は論点の表に行を作った後に付ける（先に付けるなら、その I を作る Task を書き、一時的に E_REGISTERS が出ると書く）。
3. Construction: 通す場合はこのSKILL/当該raw template/上流文書をAgent Inputに束縛する。通さない場合もOperationは同じInputと順序を読む。
4. 初期化（Collection Phase 7.5。`mode_init` の無い旧い Layer は Operation）: `python3 .claude/skills/aipm-guided/package.py init --layer <Layer>` で13フォルダ×2とInit14キー/憲章6節の下書きを作る（`aipm.registers: true` なら registers/ の5ファイルの下書きも）。既に作られていれば何もしない（Operation で二重に作らない）。既存Projectが別契約なら上書きしない。`contract --layer <Layer>` が実パス/原文step/必須形式を返す。PMO アドオンを案件の設定で選び、その案内（guide）に運用タスクの雛形の宣言（`recurring_templates`）がある案件では、初期化の後の Inception で週次の運用（締めと見直し）を `recurrence: weekly` の運用タスクとして backlog に生む（宣言を足すのはアドオン側の改版。宣言の無い案件では案は出ない。雛形の案は `plc_addon.py --stage inception_recurring` が返し（書き込まない）、分解の承認の後に backlog に書く。運用タスクの扱いは 02-inception・04-operation。pmo- の処理の中身はアドオン側）。`init --drafts <Layer相対YAML>`（wbs の deliverable・exit_criteria・source_refs）で WBS の下書きを Goal に合わせられる（owner・priority・due は `[unknown]`／undecided のまま）。`--brief` で返却を短くできる。Init 直後の validate は19文書と manifest が無いので E_MISSING で不合格になるのが正常（registers だけ見るなら E_REGISTERS の件数を見る）。
5. 工程ごとに該当raw templateと保存済み上流を読み、実出典ID→課題→反証/方法/結果→解決理由→ストーリーを作る。人物/観測/user_reported、hypothesis、inference、unknownを区別する。キー/節/図/IDはschemaどおり。未知属性は[unknown]。同じひとつのProjectに必須19文書を工程フォルダへ保存し、追加資料で代替しない。
6. `validation_record.yaml` は解決策より先に作る。各仮説にid/kind/claim/method/success/falsification/result/scopeを記録。未実施はunknown、構造確認はstructurally_supported、反証ならnot_supported。新心理効果・本人理解済みを検査結果で補わない。
7. 工程の入力→判断→出力を `manifest.yaml` へ記録する。形式schemaのmanifest_schemaに従う。required documentは各1record、source_step/template_sha256/version/branch/stage/status/inputs/evidence_refs/decision/sha256/generated_mtime_ns/archive対応を持つ。inputsは実際に読んだLayer内文書。共通raw templateを読んだ根拠はsource_step/template_sha256で別に残す。stageにtimezone付き開始/終了・checkpoint区別を持たせ、生成mtimeを各stage内に収める。evidenceのsourceは実在するLayer内の相対path/hash。completion_claimは保守的な `local_trial_only; new human readability/effectiveness unknown` を使い、実導入/機械検証と実ユーザー効果を混同しない。
8. 本人に事実認定/元依頼変更/採否判断を要する節目では、対象版と短い質問を提示し実回答を待つ。通常/auto/forceの承認境界は既存規約に従う。無回答ならrequires_human=true/human_state=pendingで止め、confirmed_actualへ自己変更しない。実回答はContextのYAML receiptにkind=user_reported/actor=actual_user/origin=actual_user_reply/scope_id/stage/answer/question_id/source_thread_id/received_at/target_path/target_sha256を保存する。targetはそのstageの必須文書で、回答時点はtarget生成後・stage終了前。validation工程だけはvalidation_record.yamlからactual_new_user_responseを除いた内容をvalidation_checkpoint.yamlへ回答前に固定し、そのsnapshotをtargetにする。回答の追記で対象hashが循環しないよう、snapshotを上書きせず最終validationの質問内容との一致も確認する。manifest.human_responsesにsource/source_sha256/answer/target_path/target_sha256、checkpoint_targetsにstage→target hash、evidenceに同receiptのuser_reported分類を保存する。仮説/旧引用や自由文メモだけでは実回答として通さない。記録の外部真正性をコードだけで保証できないため独立reviewでUI/本人実発話の原記録を照合する。auto_decision/accepted_localは許可内の可逆な判断だけで、本人理解とは別。受領記録の作成とmanifestへの結びは `package.py receipt --layer <Layer> --input <回答YAML>`（stage・question・answer・question_id・source_thread_id・answered_at〔本人の回答の時刻〕。received_atはコマンドが書いた時刻。新コースのpersona/validationは決まりどおり結び、保存前ならgapsの段の終わりを受領の後へ延ばす）。旧コースの工程（persona・problem・validation・solution・story）も、その工程を閉じるとき（次の工程を始める前）に receipt で結ぶ。
9. `python3 .claude/skills/aipm-guided/validate_package.py --layer <Layer> --phase prearchive` がPASSして必要本人判断が解決した文書だけを内部Stock/documentsへ同相対pathで保存する。保存前recordはgenerated/archive=null、保存後はarchived_local_finalと同bytes/hash。Init/憲章はvalidated_local_final。`--phase final`で再検査する。形式PASSだけでTask完了にせずOperationのAC/独立review/Phase7を通す。

## 案件側の一覧（registers・明示選択したときだけ）

intent の `aipm.registers: true` を本人が選んだ Layer だけ、契約の版に `+registers.<版>` が付き（新しい Layer は `.2`、保存済みの Project は保存した版）、[一覧の契約](registers_contract.yaml)に従って `Documents/aipm_project/registers/` の5ファイル（issues 論点・hypotheses 仮説一覧〔Opportunity 仮説から検証の仮説まで〕・todo・wbs・roadmap）を持つ。未指定・false は従来どおりで、既存の Project を移行しない。

- **論点の表（issues.yaml）**：Init の下書き（I1）から、Collection・Inception で Goal と Context をもとに「決めるべき問い」を埋める。各行は owner と due（日付か、決まっていなければ `undecided`）を持つ。検討不要・中止・保留（not_needed／cancelled／on_hold）の行に限り、代わりに理由（reason）でよい（作り終えた条件）。answer は暫定の答え（仮説 H の id か、答えの文章。h1・H-1 のような id に似た値は警告）を、validation_plan は検証の仮説（kind=validation の H）を、parent は親の問い（I を1つ。自分自身や循環は不可）を指す。evidence_refs は解決の根拠（H の判定や決定）に使い、下書きの出典には使わない。charter の変更の条件・終了の条件を空にしない。論点の採否は人が決め、AI は下書きと案まで。論点に入れるのは、①答えの候補が2つ以上ある ②答えによって後の計画（WBS・ToDo・仮説）が変わる ③答えが出ていて手続きだけが残っているものではない、の3つを満たす問いだけ。満たさないもの（やることが決まっている作業・手続きだけのもの）は todo か AI-PLC の Task に入れる。表題（question）は問いの形で1行1問。立ち上げで論点の表を下書きするときも同じ。論点・仮説の下書きの出典は `sources` に書く（Layer 相対パス、リポジトリ相対パス、作業ツリーに無い別の commit のものは `Flow@<commit>:<Flow 内のパス>`）。evidence_refs と evidence には書かない。仮説の kind は、相手の機会なら opportunity、相手の課題なら problem、こちらの打ち手なら solution、検証の仮説なら validation。
- **論点の解決（作業の完了とは別）**：status は open（未解決）／resolved（解決）／not_needed（検討不要）／cancelled（中止）／on_hold（保留）。resolved だけが「答えが出た」で、answer・evidence_refs（受領記録のある owner／decider の判定を持つ仮説 H、または Layer 内の受領記録か決定の記録〔YAML で kind: decision_record・decided_by・decided_at・decision・scope_id〕のパス）・decided_by（owner か decider）が要る。AI は解決の案まで出し、resolved にするのは人。not_needed／cancelled／on_hold は reason、on_hold は review_at も要る。論点に付いた作業（todo.yaml の source がその I のもの、backlog の Task で issue_id がその I のもの）が全部終わっても open なら、validate が「work done but issue still open」と警告する。解決の割合（`issues_summary.resolved_ratio`）は、検査を通った resolved ÷（全論点 − 検討不要 − 中止 − 保留）。全論点を分母にした `resolved_ratio_all` と、検査に落ちた resolved の数 `invalid_resolved` も返す。resolved の後に残る決裁・署名などの手続きは、論点を開いたままにせず todo にして、source に由来の I を書く（論点は resolved のまま）。todo の owner は論点の owner。決裁・署名をする人（decided_by が decider のときの判断者）は役割・所属で note に書く。その人が担当になると本人が確かめたときだけ owner にし、確かめられないときは owner を `[unknown]` にして候補を registers の外の記録に残す。
- **WBS・ToDo・ロードマップ**：wbs.yaml は成果物・関門・終了条件・受入の証拠だけを持ち、作業や ToDo を写さない。受入は証拠（Task の output のパスか H）つきで、AI が付けられるのは pending_acceptance（accepted の候補）まで、accepted・partially_accepted にするのは人。日程（schedule）は baseline（合意の記録 agreed_at・agreed_by・scope つき）と forecast・actual を分け、forecast を変えたら旧い値を history に残す。roadmap.yaml はマイルストーンと期間の幅を持ち、wbs_ids と WBS の milestone_id が相互に一致する。todo.yaml は案件のやること（source は論点 I・仮説 H・会議名など）で、wbs_id が空なら「WBS の番号なし」として扱い、AI の推測は候補として別に出す。source_of_truth は local だけ（外部の表は未対応）。roadmap の period は、その節目の成果がそろう時期（`開始〜終了` か `undecided`）で、作業の期間ではない。wbs の forecast が節目の period からはみ出す、依存より前に始まる、論点の期限がどの WBS の期間にも入らない、のときは validate が警告する（直すか、理由を history・note に残す）。
- **AI-PLC の Task とのつながり**：成果物を作る Task には wbs_id（W1・W1.1）を、論点に答える Task には issue_id（I1）を書く。成果物に当たらない Task は `wbs_id: none`。運用タスク（recurrence）は wbs_id: none とし、issue_id は付けない（運用の結果で論点が動くときは、その判定を受ける通常 Task に issue_id を付ける）。output を持つ Task に wbs_id が無いと validate が警告する（type が management／coordination、cancelled、`wbs_id: none` の Task は除く）。Task を完了したら（backlog を completed にした後）`python3 .claude/skills/aipm-guided/package.py wbs-candidate --layer <Layer> --task <ID>` で、WBS の該当行に Task の output を証拠として足し、同じ wbs_id の Task（cancelled を除く。deferred・blocked はまだ終わっていないと数える）が全部 completed なら pending_acceptance にする（残りがあれば証拠を足すだけで、返却の pending_tasks に残りを出す。accepted・cancelled の行は変えない。partially_accepted は状態を保って証拠だけ足す。wbs.yaml は書き直されるのでコメントは残らない）。完了報告では「accepted の候補」として出し、受け入れるかは人が決める
- **数珠つなぎの受け口**：会議・FB の後に確定した判定の一覧（上の手順）を受け取り、todo の追加・変更の案（source に H や I を書く）と、wbs の forecast・evidence_refs の更新の案を出す。案は本人の確定の後に書き込む（forecast を変えるときは history に残す）本人に確定を求める質問は、判断に要る中身を質問文と選択肢の説明に入れる。本人に確かめていない欄（期限・priority・担当など）は registers に書かず、案として記録に残す。人の欄（issues・wbs・todo の owner など）に書くのは役割・所属と出典だけで、個人情報・センシティブ情報（評価・報酬・私的な連絡・個人の連絡先）は書かない。参照の欄（issue_id・wbs_id・parent・depends・evidence_refs・source など）は出典（会議の記録・本人の回答・成果物）で確かめたものだけを書き、推測で埋めない。分からない任意の参照の欄は書かずに省き、候補は registers の外の記録に残す。必須の欄を確かめられないときは `[unknown]` と書く（owner と issues の priority）。ただし、案件の持ち主（intent.owner）と同じ本人の呼び名は人の欄に書いてよい（本人の決定 2026-10-21）。本人以外の人は役割・所属のまま書き、名前を書かない。
- **仕事の分け方**：決まった仕事（手順のある作業）は AI-PLC backlog の Task に手順を持たせる／会議で出た案件のやることは todo.yaml に入れ、AI が成果物を作るものだけ Re-Inception で AI-PLC の Task にする／どちらにも入らないものは相談の入口（plc-consult）で受ける
- **id の採番**：Init の Opportunity 仮説が H1… を使うので、手順6の validation_record の仮説 id は、先に hypotheses.yaml に kind=validation の行を作り、その id（空いている次の番号）を使う
- **会議・FB の後**：出来事の記録を読み、関係する仮説ごとに判定の案を judgements に judged_by=ai_proxy で足す（status は変えない）→ 手順8で本人・判断者の実回答を受け、その receipt を evidence_ref にして owner／decider の判定を足し、status を確定する（supported は人の判定があるときだけ）→ 反証・判定の変わった仮説から、見直す文書（課題・解決策・ストーリー）の一覧と確定した判定の一覧を返す。ToDo・WBS の更新の案は、それらの一覧の受け口に渡す。owner／decider の判定は `package.py judge --layer <Layer> --input <YAML>`（date・event・judged_by・evidence_ref〔受領記録〕・judgements の hypothesis_id と verdict）で末尾に足し、status も決まりどおりに直る（ai_proxy の案は `pm-hypothesis` の propose で書く。メモから案を拾うのは `pm-capture`）
- **解決策の改訂**：改訂の記録（manifest の decision か改訂の注記）に、根拠の仮説 id と判定の日付を残す
- validate は `+registers` の版だけ registers/ を検査する（`E_REGISTERS`）。todo・wbs・roadmap は必須の欄・id の書式と重複・status の値に加えて、未知の欄・参照先（wbs_id・milestone_id・depends・source など）・WBS の受入の証拠・日程（schedule）と roadmap との相互の一致まで見る（`minimal_lists`。日程の食い違いは警告だけ）。issues はそれに加えて未知の欄・作り終えた条件・answer／validation_plan／parent の参照先・出典（sources）を検査し、due が undecided・owner か priority が [unknown] の行と、charter の条件がすべて [unknown] のままのときは警告（`W_REGISTERS`。返却の `warnings`。合否には入れない）。hypotheses.yaml は次の決まりまで：人の判定の evidence_ref は Layer 内の受領記録（kind=user_reported・actor=actual_user・origin=actual_user_reply・同じ scope_id）を指す必要があり、status は最新の人の判定に従う（判定不能は unknown）。人の判定が無い行は unknown（validation_record に載った検証の仮説は、その result と同じ値）。judgements は時系列で後ろに追記し、並べ替えない（最新の判定は一覧の最後の人の判定）
- Init（Collection Phase 7.5）が registers/ の5ファイル（issues・hypotheses・todo・wbs・roadmap）を必須の欄だけの下書きで作る。既にあれば作らない。どれかが無いと validate が `E_REGISTERS` で不合格にする
- registers_contract.yaml を変えるときは、今の版を `registers_contract.v<N>.yaml` として凍結して残し、版の接尾を上げる。保存済みの Project はその版の契約で組み立て・検査する

## 戻し方・射程

今回の差分manifestと変更直前backupを保持する。`rollback.py --root <repo> --manifest <patch.json> --retire <repo内の新規退避先>` はdry-run、`--apply`で実復元する。全対象current==after/backup hash/未知ファイルなしを先に要求し、他writer変更があれば何も復元せず止める。新規共有分は退避し、既存dirty本文をbeforeへ戻す。全DB/設定/他案件やgit reset/cleanは対象外。

静的な形式/ID/根拠/順序/保存を検査する。ネイティブSkill自動検出、全LLM出力、Viewer描画、実ユーザー負担改善は別の実利用証拠が必要。共通Skillは通常Stage本文から明示参照されるため、Codex側の追加登録や設定変更を必要としない。


## DevStyle併用時の先行順序

既存探索型の必須工程と本人判断は上記のまま。DevStyleを併用してもCollectionで開発インタビューへ直接入らず、InceptionでこのAIPM成果を作るTaskと、その結果を使う開発Taskを先に登録する。AIPMの文書群/ストーリーマップ/最終検証/内部保存が終わってから開発TaskをOperationで実行し、完成した内容を質問の前提として渡す。未完成なら開発を待たせ、上流の実行は進められる。新コース追加や既存19文書の省略をこの接続から推定しない。


## 共通Stockを明示選択した案件

公開版には共通 Stock（`aipm.storage: registry_stock_v1`）は無い。既定の内部 Stock で動く。intent で registry_stock_v1 を選ぶと止まる。


## ソリューション起点・既存資料補完のローカル拡張 v1

[course_contracts.yaml](course_contracts.yaml)はAI-PLCのローカル契約で、canonical/source/rawの上流由来は変更しない。共通schemaの19論理成果・各形式・13フォルダは同じ。探索型のbound contractは従来値を保持し、新しいversion/manifestへの再生成・移行を要求しない。新コースだけ `2.0+courses.1` とcourse契約version/SHA256を束縛する。

- solution_based/single_persona: 実際に示されたsolutionを `kind: hypothesis` として入力し、誰/問題/価値/storyを逆算して下書きする。solutionの存在は課題や実効果の検証完了ではない。
- document_based/single_persona: 許可された実在資料を読み、対応・互換性・不足・矛盾を整理する。互換文書はbytes/元mtimeを保ったまま再利用し、古い形式/別IDはそのまま最終成果にせず変換下書きへ根拠として使う。

Inceptionでは先に同じTask内の19成果と先行/開発依存を登録する。新コースの実生成順は **資料読取→初期化→batch下書き/互換再利用→不足判断→内部保存**（`mode_init` で Collection の最後に初期化した Layer は **初期化→資料読取→batch→不足判断→内部保存**。manifest の init の段は `origin: mode_init` と mode_init の done_at で記録し、開始時刻は作らない）。これは探索型の質問順を生成時刻として捏造する契約ではない。Construction/Operationは選ばれたcourseの入力・各19形式・source対応・必要判断を引き継ぐ。AIPM完了後の開発への接続は、選んだ開発方式（`dev_style: <your_style>`）の規約（チェックポイント・PR の作り方・レビュー）の既存の入口を使い、技術質問・計画承認待ちへ渡す。UIが不要なSkill/CLI案件へHTMLを強制しない。

### 実際の生成API

OperationでLayer内の `Context/course_input.yaml`（任意の許可済みLayer相対名）へ、読み取った根拠から次を用意する。これは人に書かせる質問票ではなく、担当AIが実入力を構造化するもの。

- version: 1 / scope_id。solutionコースはsolution.valueとkind=hypothesis。
- sources: id/domain/path/sha256。domain=layerはLayer相対ファイル、method_sourceは固定原文manifest内の `source/...` だけ。シェル/ネットワークは実行しない。実読取後のsource_readsへhash/元mtime/read_atを残す。
- drafts: source_step→19形式の実下書き（YAMLはmap、Markdown/Mermaidは本文）。未知・推測を明記し、出典に無い人物属性・実インタビュー・効果を作らない。
- reuse: source_step→source ID。draftsと重複しない。互換のキー/節を確認し、最終validatorのID/参照照合も必要。固定原文は入力資料として参照し、rawを完成文書へ無条件コピーしない。
- gaps: kind=unknown、reason、requires_user。重大な不足だけquestionを付け、decision_key=persona/validationへ対応付ける。未知の市場仮説は必要なら残せるが、本人判断の未解決を完了扱いしない。下書きの前に本人へ聞いて答えを得た不足は、gap に `prior_answer`（answer・回答の写しのパス・asked_at）を残し、下書きに反映する。prior_answer は受領記録ではない。persona・validation の確定は従来どおり gaps の段の受領記録で行い、その質問は『前の回答を反映した下書きでよいか』の確認にする。
- decisions: persona/validationのstate、reason、source_ids。not_requiredにはscope=reversible_draft_onlyと必要な質問が無い根拠を残す。pendingはquestionを提示して実回答を待つ。confirmed_actualは従来の実checkpoint receipt/対象版の照合なしに記録しない。
- claims: observed/user_reported/hypothesis/inference/unknownとsource_idsを区別。観測したのは資料内容か本人事実かを明記する。
- validation_record: 従来の仮説項目・scope_id・evidence_refs、before_solution=false、actual_new_user_response=null。与えられた/同batchのsolutionより前の検証を行ったと偽らない。結果は未知/反証/構造確認を区別する。

`package.py plan --layer <Layer> --input Context/course_input.yaml` は実資料を読み、対応・不足・必要質問を返す（書込なし）。担当が同じ証拠からまとめて19下書きを用意し、`package.py draft --layer <Layer> --input Context/course_input.yaml` で新規packageへ実生成する。sources のうち package の中にあるもの（registers など、後の会議で更新し続けるもの）は、draft が `source_snapshots/` に同じバイト・同じ mtime で写して manifest の `source_snapshots` に残し、validate は写しを照合する（この決まりの後に draft した package と、写しを置いて移行した package では、registers を後で更新しても保存済みの19文書は落ちない。写しの改変・付け替えは従来どおり検出。写しの無い旧い package は registers を更新すると落ちる）。旧い package（source_snapshots の無いもの）の写しの移行は個別に行う（2026-10-22 時点で対象0件）。既存packageがあれば上書きせず停止し、保存済み文書を移行しない。ただし mode_init の出力だけがある package（manifest・validation_record・19文書のどれも無く、project_init・README が mode_init の hash のまま）は続けて書く：format_contract と registers は保持し、project_init・README は19文書の一部として下書きに置き換わる（手で直してあれば停止）。19文書を作り直すときは、本人の承認の後に `package.py reset-to-init --layer <Layer>` を使い、git で手で戻さない。既定は予定の表示だけで、`--apply --retire <退避先>` で package の外へ移し、初期化直後に戻す。人物・検証をAIが確定するAPIではない。探索型ではこれらbatch APIを使わず従来の工程を実行する。

新manifestはsource_reads、gaps、decisions、claims、生成kind/event/source IDs/reused_fromを既存recordへ追加する。生成ファイルは実batch interval内、reuseは元ファイルのhash/mtimeと一致させる。外部時刻や旧順序を捏造しない。必要本人判断の実回答は既存Step8のsource/target/hash/原発話照合を使い、新コースではgaps intervalへ対応付ける。質問待ちの実時間をそのintervalと実行予算へ記録する。

`validate_package.py --phase prearchive` がPASSしてから `package.py archive --layer <Layer>` で内部Stockへ保存し、final検証する。実資料と保存済み文書を改変せず、同bytesを保存する。registry_stock_v1（共通Stock）は公開版に無く、選ばれていたら止まる（内部Stockへfallbackしない）。形式PASS・可逆なlocal draftと実本人の効果/採否は別で、OperationのTask ACと通常の独立レビューを通す。


入力packetはhashを束縛し、その不足・claims・資料対応・decisionの理由/出典/質問をmanifestで保持する。元のpending/materialをnot_requiredへ下げたり必須gapを削って保存しない。解決時は元の質問を残しstateだけconfirmed_actualへ進め、既存の実receipt・対象版・原発話を照合する。manifestの書換えだけを回答にしない。
