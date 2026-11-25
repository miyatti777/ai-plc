---
name: aipm-guided
description: AI-PLCで本人が明示選択した同梱のPMアドオン（AIPM。旧い欄 work_style: aipm）のProject初期化・ペルソナからストーリーへの指定形式文書生成・検証。通常Stageから条件付きで読み込む。
---

# AIPMの形式で一歩ずつ進める

## この AIPM モードが扱う範囲

- 扱う：立ち上げの工程（3つのコースとも、1人の利用者について課題→仮説検証→解決策→ストーリーまで）で作る19文書と、その保存（archive で保存先へ写す。下の「箱の形と保存先」）と、保存した後の改訂（apply で版を足す。下の「保存した箱の改訂（apply）」）
- 扱う（箱の中の操作）：論点・仮説・ToDo の1件の操作と、会議・FB の後の取込（下の「箱の中の操作（pm-）」。「案件側の一覧」を選んだ案件だけ）、19文書の改訂の範囲の案（書き換えはしない）
- 扱わない（今は無い）：日次・週次の締めと見直し、フェーズ・契約・PJ の終了時の引継ぎ
- 「AIPM」と呼ぶ別の仕組みとは、名前が同じでも中身が同じとは限らない。この AIPM モードを入れたことを、別の仕組みの置き換え・統合と扱わない。日次・週次の締めや引継ぎについて聞かれたら、このモードでは扱わないと答える（会議の後の取込は pm-suggest、今日の1件は pm-today）

本人が対象LayerでAIPMを明示選択したときだけ `intent.yaml` の `addons` に同梱の1件（`addon_id: aipm`・`source: bundled`）を保存する（新しい Layer に `work_style` は書かない。旧い Layer の `work_style: aipm` は同じに読む）。引用・過去の報告・候補としての説明は選択ではない。未指定/nullは従来経路、保存値は勝手に補わない。`mode` のdirect/platform_builder、Role、深度、通常/auto/forceの権限は共通正本のまま。子への強制伝播や既存Layer一括更新はしない。選択解除はPMの選択を両方の欄（addons の同梱の1件と旧い欄）から外し、文書を保持する。

## 同梱アドオンとしての扱い

このスキルは同梱の PM アドオンとして目録（[addon-catalog.yaml](../ai-plc/references/addon-catalog.yaml) の aipm）に載る。選んだときは `addons` に同梱の1件を書く（上の段落）。旧い Layer の `work_style: aipm` は目録の `legacy_alias` で、判定関数 `.claude/skills/ai-plc/scripts/plc_addon_select.py` が同梱の aipm を選んだものとして読む（intent は書き換えない。一括の移行はしない）。`aipm:` の設定（course・registers・storage・stock_selector など）と `mode_init` の置き場・意味は変えず、`addons` の1件の中へ移さない。同梱の aipm は `addon_init` を使わない。

## 正本・入力

[固定版](canonical.yaml)は上流の aipm-commands の固定 commit（リポジトリと commit は canonical.yaml に記録）。[原文](source/)5コマンド、19raw templates、[形式schema](format_schema.yaml)のhashを確認する。これは元のCursorコマンドをAI-PLCへ接続した手順で、原文シェルをそのまま実行しない。利用者は本人/Contextから理解し、架空属性やインタビューを補完しない。

既存探索型は `question_based/single_persona`、Init→ペルソナ→課題→仮説検証→解決策→ストーリー→保存（archive）。この順序・19成果・本人判断を維持する。単一利用者向けにsolution_based/single_personaとdocument_based/single_personaのローカル拡張を追加し、下記の別生成契約を使う。多人数分岐や05以降の文書生成は未対応。

`aipm` は任意map: `program_id` / `project_id` / `date`（YYYY-MM-DD）/ `persona_id`（P001等）/ `name_slug` / `course`。未指定の project_id は scope_name（無ければ scope_id）、personaはP001、slugはuser。program_id は新しい形（既定）では既定値が無い。保存先を Stock にする設定（下の「保存先の設定」の where: stock）では、archive に `Stock/programs/` に実在する名前が要る（**init の前に書く**。init の後に intent へ足すと、保存した契約と食い違って validate・init・archive が止まり、今は直す道具が無い。intent に書かなければ保存した契約の値が使われる）。Layer の中に保存する既定では要らない。古い形の保存済みの箱は従来どおり scope_id 由来の値（例 `L_1234`）のまま。識別子はASCIIの英数字/ハイフン/underscoreだけ。日本語scope_nameなら明示project_idを設定する。人物属性をこの識別子から推測しない。箱の形は3つ（下の「箱の形と保存先」）。この文書で「新しい形」は箱の直下に文書を置く形（`box_root_v1`・`sheets_v1`）、「古い形」は `nested_v1` を指す。新しい箱の既定は `sheets_v1`：Layer の直下の `Sheets/`（Context/・Documents/ と同じ段）に、工程フォルダ・一覧の5ファイル（issues・hypotheses・todo・wbs・roadmap）・管理ファイル（manifest・format_contract・project_init・README・validation_*）を同じ段に置き、`registers/` も箱の中の Flow/・Stock/ も作らない。保存済みの `box_root_v1`（`Documents/aipm_project/` の直下に19文書、一覧は `registers/`）と `nested_v1`（`Documents/aipm_project/` の中に Flow/・Stock/。layout の無い保存済みの箱）はそのまま読み続ける。`aipm.layout` は普段書かない（保存済みの箱は自分の形を保ち、書いた値と違えば止まる）。別Registry Projectは登録しない。share値はdisabled。

## 箱の中の操作（pm-）

AI-PLC の Stage（Collection〜Operation）は、箱づくりを含めて「この Task をやれ」と命じる外側の命令。pm- は、Stage が作った箱の中のアイテムを1件ずつ扱う操作の型で、AI-PLC を知らなくても操作の名前で分かる（顧客向け PMO の pmo- と同じ2層。AIPM と AIPMO は構造が同じで、作る箱と操作が違う）。本文は `ops/<操作>.md`、呼び出しは `/pm-<操作>`、処理は `package.py op --name <操作>.<動き>`（ops.py）。

| pm- | 扱うもの | 書くか |
| --- | --- | --- |
| pm-issue | 論点を足す・分ける・答えの案・閉じる・解決する・全体を見る | 書く（試す→本人の確定→`--apply`。resolve・close は本人の受領記録か決定の記録が要る。版を持てる保存済みの箱では add・split は止まり redit で足す。propose は止まり、案は一覧に書かない） |
| pm-hypothesis | 仮説を足す・AI の判定の案・崩れた仮説の影響 | 書く（同上。owner／decider の判定は `judge`。版を持てる保存済みの箱では add は止まり redit で足す。propose は止まり、案は一覧に書かない） |
| pm-todo | ToDo を足す・動かす・WBS につなぐ・遅れを見る | 書く（同上。owner・期限は推測しない。版を持てる保存済みの箱では add は止まり redit で足す。link は止まる。空の wbs_id は redit の fill で付ける（付いている wbs_id の直し・source の付け直しは今はできない）。move は今までどおり。move は任意で `updated_on`〔その日〕と `note_add`〔note の末尾に足す出どころの1文。同じ文は二度足さない〕を一緒に書ける〔版3以上。保存済みの箱では status だけ〕） |
| pm-suggest | 会議・FB のメモから、判定の案・論点・ToDo の候補 | 案だけ（確定した候補を上の3本で書く。版を持てる保存済みの箱では redit の入力にする） |
| pm-today | 箱の中から今日の1件 | 案だけ |
| pm-persona | ペルソナと課題の改訂の範囲 | 案だけ（19文書はその場で書き換えない。版を登録した箱は変更案から apply で改訂する〔下の「保存した箱の改訂（apply）」〕。版の無い保存済みの箱と保存前の箱は Stage で工程をやり直す） |
| pm-story | 解決策とストーリーの改訂の範囲 | 案だけ（同上） |
| pm-init | 途中から AIPM にする入口（今の状態と次に打つコマンド） | 案だけ |

- 書く操作は、書く前後で registers の検査（E_REGISTERS）を比べ、新しい問題が出たら書く前に戻す。`--apply` が無ければ試すだけ
- AIPM を選んでいない Layer では止まる（論点・仮説・ToDo・capture・today は「案件側の一覧」も要る）。**例外は pm-init**：方式を選ぶ前の Layer で動き、何も書かない（選ぶのは Collection の推薦と本人の回答）
- pm- は AI-PLC の backlog・Task の状態を変えない。Task の手順には「pm-issue で論点 I3 を分ける」のように名前で書く
- 人が決めること（論点の resolved・仮説の owner／decider の判定・WBS の受入・owner や期限）は pm- が代わりにしない
- **版を持てる保存済みの箱**（archive 済みの sheets_v1・box_root_v1。版の無い箱も含む。共有 Stock〔registry_stock_v1〕の箱は除き、今までどおり書ける）の一覧に材料・note・新しい行を足すのは pm- ではなく下の「保存した箱の一覧の追記（redit）」。pm- の issue.add・split・propose、hypothesis.add・propose、todo.add・link は `held` で止まり、止まった理由と次の手を返す：add と split は redit の add_row（split は row_data に parent）、propose（答えの案・AI の判定の案）は一覧に書かず変更案の reason か判定の下書きの備考に残す、link（既存の ToDo の wbs_id・source）は、空の wbs_id なら redit の fill で付け、付いている wbs_id の直しと source の付け直しは今はできない。issue.resolve・close、todo.move、`package.py judge`・`wbs-candidate` は今までどおり（本人の判定と記録の操作のため）。保存済みの nested_v1 の箱は止めず、書いた結果に「先に migrate-sheets で sheets_v1 へ」の案内（hint）を添える

## AIPM ライトモード（aipm-light）

同梱の方式の1つで、目録の aipm-light の行の entry がこのスキル（aipm と共有）。方式（組 work_method）は必須で、本人の答えが無いときの既定（01-collection Phase 7）。中身は AIPM の Sheets から **WBS と TODO のシートだけ**を残したもの。

- **作るもの:** `Sheets/format_contract.yaml`（ライトの箱の記録。kind `aipm_light`・registers の契約の版と hash）と `Sheets/todo.yaml`・`Sheets/wbs.yaml`（registers の契約の todo・wbs と同じ行の形。空の一覧で始める）。19文書・issues・hypotheses・roadmap・project_init・README は作らない。置き場が衝突する（`Documents/aipm_project/` がある、`Sheets/` が別用途、大文字違いの `sheets/`）ときは何も書かずに止まる。既にあるファイルは上書きしない
- **初期化:** Collection Phase 7.5 で `python3 .claude/skills/aipm-guided/package.py init --layer <Layer> --light`（`--light` は「この Layer の方式が aipm-light であること」の確かめ。無くても aipm-light の Layer ならライトの箱を作る）。返却の `outputs` を `mode_init.outputs` に書く
- **参照の欄は使わない:** wbs の `issue_ids`・`milestone_id`、todo の `source` の I・H の id（論点・仮説・節目のシートが無いため）。source は会議名などの言葉で書く。validate は書かれていれば `E_LIGHT` で知らせる。todo の行には任意の「結び目の3列」（契約 v3 から。v2 に固定済みのシートでは使えず unknown key）を足せる: `done_when`（`task_completed`＝source の Task の完了／`owner_action`＝本人が動く・決める／`external_event`＝相手の返事・承認・付与が届く、の3語だけ）・`updated_on`（作業日 YYYY-MM-DD。同期時刻ではない）・`blocked_by`（`<scope_id>/<Txxx>`、例 `L-1234/T003`。依存があるときだけ）。契約 v4 からは `confirmed_on`（本人が「この行は正しい」と確かめた日 YYYY-MM-DD。任意）も足せる。書けるのは本人の確認の回答（`receipt`）を渡した `todo.link` だけで、受け取りは Layer の `Context/todo_confirmations.yaml` に残る。AI の案（redit の add_row・todo.add）では書かない。語彙の外・日付でない・形の違う値は `E_REGISTERS`。source は backlog の `Txxx` か同じ Layer の `Documents/...` が推奨で、それ以外の書き方（会議名など）は `W_REGISTERS`（警告）に留める。列が無い行はそのまま通る
- **validate:** `validate_package.py --layer <Layer>` はライトの Layer では2つのシートだけを検査する（`route: aipm-light`。19文書は無いので数えない）
- **箱の中の操作:** pm-todo（`package.py op --name todo.add / todo.move / todo.link / todo.overdue`）と wbs-candidate（04-operation Phase 6）がそのまま使える。pm-issue・pm-hypothesis・pm-persona・pm-story・pm-suggest・pm-today はライトでは使わない（op は held を返す）
- **人間の TODO:** inception で人間の予定・TODO を `Sheets/todo.yaml` に入れ、backlog の Task にしない（AI が成果物を作るものだけを Task にする）。あなたの TODO 管理（AI-PLC の範囲外）には案件の行だけを載せ、ToDo は書き写さない（下の「案件側の一覧」と同じ）。owner・期限は本人に確かめていなければ書かない
- **registers の無い aipm の Layer にも2つのシートを足す:** `package.py add-sheets --layer <Layer>`（既定は書かない一覧だけ。`--apply` で書く）。`Sheets/light_sheets.yaml`（kind `aipm_sheets`）と2つのシートを、aipm の箱（format_contract・19文書）を変えずに足す。validate は aipm の検査に加えて2つのシートを見る（返却の `light_sheets_summary`）。既存の Layer へは1つずつ足す
- **AIPM への切り替え:** intent の方式を aipm に替え、`aipm.registers: true`・`aipm.layout: sheets_v1` にしてから `package.py init` を呼ぶ。ライトの箱の記録は `Context/aipm_light_retired/` へ移り、2つのシートはそのまま registers の一部になり、残りの3ファイルと init の文書が足される（19文書は Stage で作る）
- **Stage での読み方:** ライトの Layer では、この節（各 Stage の「選択した方式だけ読む」で目録の aipm-light の行の entry として読む）。AIPM の「Stageとの接続」の 1〜9（19文書・工程順）は読まない

## Stageとの接続

1. Collection: 実選択の根拠とコース/必要IDをContextへ保存し（保存先を Stock にする設定では、新しい形の archive 先の `program_id`〔`Stock/programs/` に実在する名前〕を init の前に本人に確かめる。設定で業務Project を使う〔business: registry〕ときは、Registry の業務Project の表に primary が入るまで archive は止まる。下の「保存先の設定」）、選択を `addons` の同梱の1件で記録する。**初期化は Collection の最後（01-collection Phase 7.5 の初期化の段）で行う**：同梱の aipm の選択（旧い Layer は `work_style: aipm`。目録の aipm の `init`。記録先は `mode_init`）が初期化の宣言で、別の OK の後に下の 4 の init を呼び、init の返却の `outputs`（作った package の format_contract・project_init・README と、registers を選んだときは registers/ の5ファイルの path と sha256）をそのまま `mode_init.outputs` に書く。scope_reinitでは成果を保持する。Phase 7.5 の別の OK では、Goal と Context から書いた WBS の下書き（`--drafts` の YAML）を見せてから init する。aipm の初期化は plc_addon.py を呼ばない（collection_init はアドオンの addon_init 用）。
2. Inception: 形式schemaの19documentsと工程フォルダ（新しい形は箱の直下に1組、古い形は Flow 側と Stock/documents 側の2組）を必須成果/ACへ加える。初期化は Collection で済んでいる前提で、persona→problem→validation→solution→story→archiveの依存をTaskへ束縛する（初期化を Task として登録しない。`mode_init` の無い旧い Layer だけ、従来どおり初期化を依存の先頭に置く）。既存Taskが同じ成果を持つなら追加重複しない。仮説の計画と実結果は別にする。`aipm.registers: true` の Layer は、論点の表（issues.yaml）と charter が作り終えた条件を満たすこと（validate の issues.yaml への `E_REGISTERS` が0件）を必須成果／AC に加える。あわせて、成果物を作る Task に wbs_id（registers の WBS の行）、論点に答える Task に issue_id を書く（成果物に当たらない Task は `wbs_id: none`）。issue_id は論点の表に行を作った後に付ける（先に付けるなら、その I を作る Task を書き、一時的に E_REGISTERS が出ると書く）。
3. Construction: 通す場合はこのSKILL/当該raw template/上流文書をAgent Inputに束縛する。通さない場合もOperationは同じInputと順序を読む。
4. 初期化（Collection Phase 7.5。`mode_init` の無い旧い Layer は Operation）: `python3 .claude/skills/aipm-guided/package.py init --layer <Layer>` で工程フォルダ（新しい形は箱の直下に1組、古い形は Flow 側と Stock 側の2組）とInit14キー/憲章6節の下書きを作る（`aipm.registers: true` なら一覧の5ファイルの下書きも。sheets_v1 は `Sheets/` の直下、それより前の形は `registers/` の中）。既に作られていれば何もしない（Operation で二重に作らない）。既存Projectが別契約なら上書きしない。`contract --layer <Layer>` が実パス/原文step/必須形式を返す。PMO アドオンを案件の設定で選び、その案内（guide）に運用タスクの雛形の宣言（`recurring_templates`）がある案件では、初期化の後の Inception で週次の運用（締めと見直し）を `recurrence: weekly` の運用タスクとして backlog に生む（宣言を足すのはアドオン側の改版。宣言の無い案件では案は出ない。雛形の案は `plc_addon.py --stage inception_recurring` が返し（書き込まない）、分解の承認の後に backlog に書く。運用タスクの扱いは 02-inception・04-operation。pmo- の処理の中身はアドオン側）。`init --drafts <Layer相対YAML>`（wbs の deliverable・exit_criteria・source_refs）で WBS の下書きを Goal に合わせられる（owner・priority・due は `[unknown]`／undecided のまま）。`--brief` で返却を短くできる。Init 直後の validate は19文書と manifest が無いので E_MISSING で不合格になるのが正常（registers だけ見るなら E_REGISTERS の件数を見る）。
5. 工程ごとに該当raw templateと保存済み上流を読み、実出典ID→課題→反証/方法/結果→解決理由→ストーリーを作る。人物/観測/user_reported、hypothesis、inference、unknownを区別する。キー/節/図/IDはschemaどおり。未知属性は[unknown]。同じひとつのProjectに必須19文書を工程フォルダへ保存し、追加資料で代替しない。
6. `validation_record.yaml` は解決策より先に作る。各仮説にid/kind/claim/method/success/falsification/result/scopeを記録。未実施はunknown、構造確認はstructurally_supported、反証ならnot_supported。新心理効果・本人理解済みを検査結果で補わない。
7. 工程の入力→判断→出力を `manifest.yaml` へ記録する。形式schemaのmanifest_schemaに従う。required documentは各1record、source_step/template_sha256/version/branch/stage/status/inputs/evidence_refs/decision/sha256/generated_mtime_ns/archive対応を持つ。inputsは実際に読んだLayer内文書。共通raw templateを読んだ根拠はsource_step/template_sha256で別に残す。stageにtimezone付き開始/終了・checkpoint区別を持たせ、記録した生成時刻（generated_mtime_ns）を各stage内に収める。evidenceのsourceは実在するLayer内の相対path/hash。completion_claimは保守的な `local_trial_only; new human readability/effectiveness unknown` を使い、実導入/機械検証と実ユーザー効果を混同しない。
8. 本人に事実認定/元依頼変更/採否判断を要する節目では、対象版と短い質問を提示し実回答を待つ。通常/auto/forceの承認境界は既存規約に従う。無回答ならrequires_human=true/human_state=pendingで止め、confirmed_actualへ自己変更しない。実回答はContextのYAML receiptにkind=user_reported/actor=actual_user/origin=actual_user_reply/scope_id/stage/answer/question_id/source_thread_id/received_at/target_path/target_sha256を保存する。targetはそのstageの必須文書で、回答時点はtarget生成後・stage終了前。validation工程だけはvalidation_record.yamlからactual_new_user_responseを除いた内容をvalidation_checkpoint.yamlへ回答前に固定し、そのsnapshotをtargetにする。回答の追記で対象hashが循環しないよう、snapshotを上書きせず最終validationの質問内容との一致も確認する。manifest.human_responsesにsource/source_sha256/answer/target_path/target_sha256、checkpoint_targetsにstage→target hash、evidenceに同receiptのuser_reported分類を保存する。仮説/旧引用や自由文メモだけでは実回答として通さない。記録の外部真正性をコードだけで保証できないため独立reviewでUI/本人実発話の原記録を照合する。auto_decision/accepted_localは許可内の可逆な判断だけで、本人理解とは別。受領記録の作成とmanifestへの結びは `package.py receipt --layer <Layer> --input <回答YAML>`（stage・question・answer・question_id・source_thread_id・answered_at〔本人の回答の時刻〕。received_atはコマンドが書いた時刻。新コースのpersona/validationは決まりどおり結び、保存前ならgapsの段の終わりを受領の後へ延ばす）。旧コースの工程（persona・problem・validation・solution・story）も、その工程を閉じるとき（次の工程を始める前）に receipt で結ぶ。
9. `python3 .claude/skills/aipm-guided/validate_package.py --layer <Layer> --phase prearchive` がPASSして必要本人判断が解決した文書だけを、同じ相対 path・同 bytes で保存する（新しい形は保存先の `documents/`〔既定は Layer の中の `Documents/aipm_archive/<project>/documents/`〕、古い形は箱の中の `Stock/.../documents/`。既定コースの新しい形の箱は道具が無い — 下の「箱の形と保存先」）。保存前recordはgenerated/archive=null、保存後はarchived_local_finalと同bytes/hash。Init/憲章はvalidated_local_final。`--phase final`で再検査する。形式PASSだけでTask完了にせずOperationのAC/独立review/Phase7を通す。

## 案件側の一覧（registers・明示選択したときだけ）

intent の `aipm.registers: true` を本人が選んだ Layer だけ、契約の版に `+registers.<版>` が付き（新しい Layer は `.2`、保存済みの Project は保存した版）、[一覧の契約](registers_contract.yaml)に従って箱の一覧の5ファイル（sheets_v1 は `Sheets/` の直下、box_root_v1・nested_v1 は `Documents/aipm_project/registers/`。場所は契約の `registers_contract` を通して決まる）（issues 論点・hypotheses 仮説一覧〔Opportunity 仮説から検証の仮説まで〕・todo・wbs・roadmap）を持つ。未指定・false は従来どおりで、既存の Project を移行しない。

- **論点の表（issues.yaml）**：Init の下書き（I1）から、Collection・Inception で Goal と Context をもとに「決めるべき問い」を埋める。各行は owner と due（日付か、決まっていなければ `undecided`）を持つ。検討不要・中止・保留（not_needed／cancelled／on_hold）の行に限り、代わりに理由（reason）でよい（作り終えた条件）。answer は暫定の答え（仮説 H の id か、答えの文章。h1・H-1 のような id に似た値は警告）を、validation_plan は検証の仮説（kind=validation の H）を、parent は親の問い（I を1つ。自分自身や循環は不可）を指す。evidence_refs は解決の根拠（H の判定や決定）に使い、下書きの出典には使わない。charter の変更の条件・終了の条件を空にしない。論点の採否は人が決め、AI は下書きと案まで。論点に入れるのは、①答えの候補が2つ以上ある ②答えによって後の計画（WBS・ToDo・仮説）が変わる ③答えが出ていて手続きだけが残っているものではない、の3つを満たす問いだけ。満たさないもの（やることが決まっている作業・手続きだけのもの）は todo か AI-PLC の Task に入れる。表題（question）は問いの形で1行1問。立ち上げで論点の表を下書きするときも同じ。論点・仮説の下書きの出典は `sources` に書く（Layer 相対パス、リポジトリ相対パス、作業ツリーに無い別の commit のものは `Flow@<commit>:<Flow 内のパス>`）。evidence_refs と evidence には書かない。仮説の kind は、相手の機会なら opportunity、相手の課題なら problem、こちらの打ち手なら solution、検証の仮説なら validation。
- **論点の解決（作業の完了とは別）**：status は open（未解決）／resolved（解決）／not_needed（検討不要）／cancelled（中止）／on_hold（保留）。resolved だけが「答えが出た」で、answer・evidence_refs（受領記録のある owner／decider の判定を持つ仮説 H、または Layer 内の受領記録か決定の記録〔YAML で kind: decision_record・decided_by・decided_at・decision・scope_id〕のパス）・decided_by（owner か decider）が要る。AI は解決の案まで出し、resolved にするのは人。not_needed／cancelled／on_hold は reason、on_hold は review_at も要る。論点に付いた作業（todo.yaml の source がその I のもの、backlog の Task で issue_id がその I のもの）が全部終わっても open なら、validate が「work done but issue still open」と警告する。解決の割合（`issues_summary.resolved_ratio`）は、検査を通った resolved ÷（全論点 − 検討不要 − 中止 − 保留）。全論点を分母にした `resolved_ratio_all` と、検査に落ちた resolved の数 `invalid_resolved` も返す。resolved の後に残る決裁・署名などの手続きは、論点を開いたままにせず todo にして、source に由来の I を書く（論点は resolved のまま）。todo の owner は論点の owner。決裁・署名をする人（decided_by が decider のときの判断者）は役割・所属で note に書く。その人が担当になると本人が確かめたときだけ owner にし、確かめられないときは owner を `[unknown]` にして候補を registers の外の記録に残す。
- **WBS・ToDo・ロードマップ**：wbs.yaml は成果物・関門・終了条件・受入の証拠だけを持ち、作業や ToDo を写さない。受入は証拠（Task の output のパスか H）つきで、AI が付けられるのは pending_acceptance（accepted の候補）まで、accepted・partially_accepted にするのは人。日程（schedule）は baseline（合意の記録 agreed_at・agreed_by・scope つき）と forecast・actual を分け、forecast を変えたら旧い値を history に残す。roadmap.yaml はマイルストーンと期間の幅を持ち、wbs_ids と WBS の milestone_id が相互に一致する。todo.yaml は案件のやること（source は論点 I・仮説 H・会議名など）で、wbs_id が空なら「WBS の番号なし」として扱い、AI の推測は候補として別に出す。source_of_truth は local だけ（外部の表は未対応）。roadmap の period は、その節目の成果がそろう時期（`開始〜終了` か `undecided`）で、作業の期間ではない。wbs の forecast が節目の period からはみ出す、依存より前に始まる、論点の期限がどの WBS の期間にも入らない、のときは validate が警告する（直すか、理由を history・note に残す）。
- **AI-PLC の Task とのつながり**：成果物を作る Task には wbs_id（W1・W1.1）を、論点に答える Task には issue_id（I1）を書く。成果物に当たらない Task は `wbs_id: none`。運用タスク（recurrence）は wbs_id: none とし、issue_id は付けない（運用の結果で論点が動くときは、その判定を受ける通常 Task に issue_id を付ける）。output を持つ Task に wbs_id が無いと validate が警告する（type が management／coordination、cancelled、`wbs_id: none` の Task は除く）。Task を完了したら（backlog を completed にした後）`python3 .claude/skills/aipm-guided/package.py wbs-candidate --layer <Layer> --task <ID>` で、WBS の該当行に Task の output を証拠として足し、同じ wbs_id の Task（cancelled を除く。deferred・blocked はまだ終わっていないと数える）が全部 completed なら pending_acceptance にする（残りがあれば証拠を足すだけで、返却の pending_tasks に残りを出す。accepted・cancelled の行は変えない。partially_accepted は状態を保って証拠だけ足す。wbs.yaml は書き直されるのでコメントは残らない）。完了報告では「accepted の候補」として出し、受け入れるかは人が決める
- **数珠つなぎの受け口**：会議・FB の後に確定した判定の一覧（上の手順）を受け取り、todo の追加・変更の案（source に H や I を書く）と、wbs の forecast・evidence_refs の更新の案を出す。案は本人の確定の後に書き込む（forecast を変えるときは history に残す）本人に確定を求める質問は、判断に要る中身を質問文と選択肢の説明に入れる。本人に確かめていない欄（期限・priority・担当など）は registers に書かず、案として記録に残す。人の欄（issues・wbs・todo の owner など）に書くのは役割・所属と出典だけで、個人情報・センシティブ情報（評価・報酬・私的な連絡・個人の連絡先）と鍵・トークン・パスワード・口座番号は書かない。参照の欄（issue_id・wbs_id・parent・depends・evidence_refs・source など）は出典（会議の記録・本人の回答・成果物）で確かめたものだけを書き、推測で埋めない。分からない任意の参照の欄は書かずに省き、候補は registers の外の記録に残す。必須の欄を確かめられないときは `[unknown]` と書く（owner と issues の priority）。ただし、案件の持ち主（intent.owner）と同じ本人の呼び名は人の欄に書いてよい。本人以外の人は役割・所属のまま書き、名前を書かない。
- **仕事の分け方**：決まった仕事（手順のある作業）は AI-PLC backlog の Task に手順を持たせる／会議で出た案件のやることは todo.yaml に入れ、AI が成果物を作るものだけ Re-Inception で AI-PLC の Task にする／どちらにも入らないものは相談の入口（plc-consult）で受ける。論点・ToDo の正はこの箱の中で、あなたの TODO 管理（AI-PLC の範囲外）には案件1行だけを載せ、論点・ToDo は書き写さない。会議で出たやることは、AIPM を選んだ案件なら `/pm-suggest` で候補を拾い、確定したものを `/pm-todo`・`/pm-issue` で箱へ入れる
- **id の採番**：Init の Opportunity 仮説が H1… を使うので、手順6の validation_record の仮説 id は、先に hypotheses.yaml に kind=validation の行を作り、その id（空いている次の番号）を使う
- **会議・FB の後**：出来事の記録を読み、関係する仮説ごとに判定の案を judgements に judged_by=ai_proxy で足す（status は変えない）→ 手順8で本人・判断者の実回答を受け、その receipt を evidence_ref にして owner／decider の判定を足し、status を確定する（supported は人の判定があるときだけ）→ 反証・判定の変わった仮説から、見直す文書（課題・解決策・ストーリー）の一覧と確定した判定の一覧を返す。ToDo・WBS の更新の案は、それらの一覧の受け口に渡す。owner／decider の判定は `package.py judge --layer <Layer> --input <YAML>`（date・event・judged_by・evidence_ref〔受領記録〕・judgements の hypothesis_id と verdict）で末尾に足し、status も決まりどおりに直る（ai_proxy の案は `pm-hypothesis` の propose で書く。メモから案を拾うのは `pm-suggest`）
- **解決策の改訂**：改訂の記録（manifest の decision か改訂の注記）に、根拠の仮説 id と判定の日付を残す
- validate は `+registers` の版だけ一覧を検査する（`E_REGISTERS`）。todo・wbs・roadmap は必須の欄・id の書式と重複・status の値に加えて、未知の欄・参照先（wbs_id・milestone_id・depends・source など）・WBS の受入の証拠・日程（schedule）と roadmap との相互の一致まで見る（`minimal_lists`。日程の食い違いは警告だけ）。issues はそれに加えて未知の欄・作り終えた条件・answer／validation_plan／parent の参照先・出典（sources）を検査し、due が undecided・owner か priority が [unknown] の行と、charter の条件がすべて [unknown] のままのときは警告（`W_REGISTERS`。返却の `warnings`。合否には入れない）。hypotheses.yaml は次の決まりまで：人の判定の evidence_ref は Layer 内の受領記録（kind=user_reported・actor=actual_user・origin=actual_user_reply・同じ scope_id）を指す必要があり、status は最新の人の判定に従う（判定不能は unknown）。人の判定が無い行は unknown（validation_record に載った検証の仮説は、その result と同じ値）。judgements は時系列で後ろに追記し、並べ替えない（最新の判定は一覧の最後の人の判定）
- Init（Collection Phase 7.5）が一覧の5ファイル（issues・hypotheses・todo・wbs・roadmap）を必須の欄だけの下書きで作る。既にあれば作らない。どれかが無いと validate が `E_REGISTERS` で不合格にする
- registers_contract.yaml を変えるときは、今の版を `registers_contract.v<N>.yaml` として凍結して残し、版の接尾を上げる。保存済みの Project はその版の契約で組み立て・検査する

## 戻し方・射程

今回の差分manifestと変更直前backupを保持する。`rollback.py --root <repo> --manifest <patch.json> --retire <repo内の新規退避先>` はdry-run、`--apply`で実復元する。全対象current==after/backup hash/未知ファイルなしを先に要求し、他writer変更があれば何も復元せず止める。新規共有分は退避し、既存dirty本文をbeforeへ戻す。全DB/設定/他案件やgit reset/cleanは対象外。

静的な形式/ID/根拠/順序/保存を検査する。ネイティブSkill自動検出、全LLM出力、Viewer描画、実ユーザー負担改善は別の実利用証拠が必要。共通Skillは通常Stage本文から明示参照されるため、Codex側の追加登録や設定変更を必要としない。


## DevStyle併用時の先行順序

既存探索型の必須工程と本人判断は上記のまま。DevStyleを併用してもCollectionで開発インタビューへ直接入らず、InceptionでこのAIPM成果を作るTaskと、その結果を使う開発Taskを先に登録する。AIPMの文書群/ストーリーマップ/最終検証/保存（archive）が終わってから開発TaskをOperationで実行し、完成した内容を質問の前提として渡す。未完成なら開発を待たせ、上流の実行は進められる。新コース追加や既存19文書の省略をこの接続から推定しない。


## 箱の形と保存先

- 形は3つ（この文書の「新しい形」は sheets_v1 と box_root_v1、「古い形」は nested_v1）。保存済みの箱は、その `format_contract.yaml` の `layout`（無ければ `nested_v1`）と置き場で決まり、自分の形を保つ。新しい箱は `sheets_v1`

  | 形 | 箱の置き場 | 一覧の5ファイル |
  | --- | --- | --- |
  | `sheets_v1`（既定） | `<Layer>/Sheets/` | `Sheets/` の直下 |
  | `box_root_v1` | `<Layer>/Documents/aipm_project/`（19文書は直下） | `Documents/aipm_project/registers/` |
  | `nested_v1`（v1.x の公開版が作った形） | `<Layer>/Documents/aipm_project/`（中に Flow/・Stock/） | `Documents/aipm_project/registers/` |

- 何も書かずに止まる: `Sheets/` と `Documents/aipm_project/` の両方に format_contract がある／大文字小文字だけ違う箱（`sheets/` など）がある／箱の置き場と契約の形が合わない（`Sheets/` の契約が別の形を名乗る、`Documents/aipm_project/` の契約が sheets_v1 を名乗る）／古い箱のフォルダが既にある Layer で sheets_v1 の箱を初めて作る／intent の `aipm.layout` が保存済みの形と違う
- validate・receipt・reset-to-init・wbs-candidate・pm- の操作は3つの形を読み分け、黙って読み替えない（箱の置き場は契約の `package_root`、一覧の場所は `registers_contract` から求める）。新しい形の箱の中に Flow/・Stock/ があれば E_BOUNDARY で止まる
- archive（新しい形・新しいコース〔solution_based・document_based〕の `package.py archive`）は初回の apply で、写した後に版 v1（kind first）を manifest の `applies` と保存先の `apply_log.yaml` に書く。保存した後の改訂は下の「保存した箱の改訂（apply）」（archive をもう一度呼ぶと止まる）。点検を最初の写しの前に済ませてから、保存先（下の「保存先の設定」）の `documents/` へ写す。写し先が既にある・Stock へ写す設定で program が無い・実在しない（名前は大文字小文字まで一致・symlink 不可）、は何も書かずに止まる
  - ファイルは新しく作るだけで上書きせず、途中で失敗したら作った写しを Layer の `Documents/aipm_retired/` へ移して保存先を元に戻す。新しい program は作らず、git の commit はしない（本人が決める）。Layer の外（Stock）へ書くのは**本人が求めたときだけ実行する**
  - 写したあと manifest の `archive_target` に行き先（`target_rel`・`source`。業務Project を引いたときはその UID・元の表示名・フォルダ名も）を残す。final はオフラインで、この記録がこの箱の行き先を指すかだけを見る。`archive_target` の無い前の写しの final は今までどおり通る。init の時に決まる `project_init.yaml` の `stock_base`（と format_contract の `stock_target_rel`）は業務Project を含まない形のままで、実際の写し先は manifest の `archive_target` が正
- 業務Project の下へ写す（設定で `business: registry` を選んだときだけ）: `<業務Project>` は archive のたびに、Stock を持つリポジトリの `.claude/db/ai_plc.db`（`--registry-db` で別の DB も可）を読むだけで開き、Layer の `business_project_links` の primary（confirmed）の表示名から決める。表示名は NFC にそろえ、`:` を全角の `：`、`/` を全角の `／` に置き換える。Registry には書かない。表は `.claude/db/business_registry.py`（`init --yes`・`add-program`・`add-business`・`link`・`where`）で作って行を足す（表が無い Registry では止まる）
  - 何も書かずに止まる: intent の scope_id が無い・`pending:`／Layer の Registry の行が無い／primary が無い／業務Project が active でない／その Program がちょうど1つの active な `stock:<program>` でない／表示名がフォルダ名に使えない（`\`・見えない文字・先頭の `.`・前後の空白・末尾の `.`・255バイト超）／同じ Program に、そろえると同じフォルダ名になる active な業務Project がある（大文字小文字だけの違いも）／intent の membership が Registry と違う
  - 業務Project の改名・付け替え・統合のあとは、次の箱が今の primary の今の表示名へ写る。写し済みの Stock は動かさない
  - 写し済みの Stock を今の行き先へ移すのは、本人が1箱ずつ承認したときだけ: `package.py move-archive --layer <Layer>`（dry-run）→ 承認 → `--apply --approval-ref <承認の出典>`。中身・sha256・時刻を保って rename し、manifest の `archive_path`・`archive_target` と `archive_moves` を書く。途中で止まったら、移したファイルを全部戻し、作ったフォルダを消し、manifest を元に戻す。移し終えたら、元の場所で空になったフォルダだけを `projects/` の手前まで消す（ほかのファイルが残るフォルダは消さない）。commit はしない
- 既定コース（question_based）の箱は `package.py archive` を使わない（従来の経路）。新しい形の既定コースの箱を保存先へ写す道具は無いので、写す前に本人に確かめ、写すなら上と同じ条件（上書きしない・同 bytes）を自分で確かめる
- Stock の場所（where: stock のとき）: `--stock-root` → Layer を含む `Flow` フォルダの親 → Layer の近くの `.git`（ファイルならその gitdir が指す親リポジトリ。フォルダなら、その clone の根）。`Stock/programs` のある候補だけを採る。別の場所から archive したなら、その後の `validate_package.py --phase final` にも同じ `--stock-root` を付ける
- git は空のフォルダとファイルの時刻を持たないが、validate は、git に commit して別の場所へ取り出し直した箱でも、作った作業フォルダと同じ合否・エラーになる。中で validate を呼ぶ archive も同じ点検で通る。空の工程フォルダは必須にしない。中身は sha256 で、順序・受領の前後は manifest に記録した時刻（records の generated_mtime_ns・stages・受領の `target_written_ns`）で確かめ、ファイルの時刻は合否に使わない。ファイルの時刻が記録と違う箱には警告 `W_MTIME` が1件出る（エラーではない）
  - 代わりに止めないこと: manifest を書き換えて文書と sha256 を両方直す・stages と records を両方合わせて時刻を偽る・既定コースの工程を後から作ったように記録する、は validate では見抜けない。manifest を直さない書き換え・stages と records の片方だけを変えたもの・受領の target_sha256 と違う文書は今までどおり止まる
  - 作業フォルダの時刻をまだ見る所: 受領記録を作る `package.py receipt` は、回答の時刻（answered_at）より後に対象が書かれていたら止まる。回答の後に取り出し直した写しではファイルの時刻が新しくなって止まるので、本人の回答から受領記録を作るまでは、その作業フォルダを消さない・作り直さない（回答の前に取り出した写しなら使える）。`package.py draft` は1回の実行の中で資料を読み直し、その実行中に資料のファイルの時刻が変わると止まる（plan と draft の間に取り出し直すのは差し支えない）

### 古い形の箱を移す（本人が1件ずつ承認したときだけ）

- **nested_v1・box_root_v1 → sheets_v1（migrate-sheets）:** `package.py migrate-sheets --layer <Layer>`（dry-run）→ 承認 → `--apply --approval-ref <承認の出典>`。Stock へ写す設定で archive 済みの nested_v1 の箱を移すときは `--program <実在する program>` も要る（where: layer なら要らない。`--retire <退避先>` は任意。省くと `Documents/aipm_retired/<時刻>_migrate-sheets`。`--registry-db` も任意）
  - 箱の中のすべてのファイルを1つの対応表で `Sheets/` へ移す（文書は中身と時刻のまま）: 契約の文書は sheets_v1 の置き場へ、一覧は `registers/` から上げ、`Flow/<flow_rel>/<残り>` は `Sheets/<残り>`、箱の直下のファイルは名前のまま。`Stock/` の中で契約の文書でないもの（archive の写しなど）は移さず、空になった箱ごと退避先に残す（消さない）
  - 書き換えるもの: 契約・intent の `aipm.program_id`（選んだ program と違うときだけ）・project_init.yaml（program_id・flow_base・stock_base。生成の時刻は保ち、書き換え前後の sha256 を `layout_migrations` に残す）・manifest（パス・flow_rel・stock_project_rel・contract_version・`layout_migrations` に1件）・intent の `mode_init.outputs` のパス・一覧の中のパス。書き換えないもの: 文書・Context の受領記録・入力の束・validation_record／validation_checkpoint（中の古いパスは dry-run の `kept_old_references` に出すだけ）
  - archive 済みの箱: 箱の中の Stock の写しを、今の保存先へ作るだけで写す（先にファイルがあれば止まり、上書きも削除もしない）。manifest の `archive_path`・`archive_target` を書き、final で確かめる
  - validate の読み替え: 受領記録の古いパスは、移した記録があり受領がそれより前のとき、古い置き場のパスとして読む（回答と対象の sha256 の結び付きは今までどおり照らす）。project_init.yaml に結ばれた init の回答は、移した記録の書き換え前後の sha256 が回答と今のファイルに合い、書き換えた欄が program_id・flow_base・stock_base の内のときだけ結ばれたままと見る
  - さらに移せる形: init だけの箱（manifest が無く mode_init が done。init の下書きを sheets_v1 の契約で作り直し、mode_init.outputs を新しい値にする。前の値は mode_init.migrations）・手の書式の project_init（3つの欄だけを文字で直す）・project_init を指す証拠（validate が移した記録で読む）・箱の中を読み込み元にした箱（写し source_snapshots/ も一緒に移す）・共有 Stock の箱（draft の後・archive の前に限る）
  - 移せない（書く前に止まる）主な箱: 共有 Stock（archive 済み・init だけ）・draft の前・format_contract を手で直した・3つの欄を文字で安全に直せない project_init・記録のある文書や一覧のファイルが欠けている・intent に `aipm.layout`・`Sheets/` が既にある・symlink・1つの置き場に2つのファイル（大文字小文字だけの違いも）・対応表で置けないパス・写しの無い箱の中の読み込み元・退避先が既にある・版のある箱（下の「保存した箱の改訂（apply）」）・業務Project を引く設定で Registry の行や primary が無い。移した後に validate（archive 済みは final、ほかは prearchive）へ新しいエラーが出たら、途中で失敗・中断したら、保存先に作った写しまで全部元に戻す
  - 移した後: reset-to-init は止まる（intent の `mode_init.outputs` の sha256 は init 時の値）。`outside_references` に出た箱の外の古いパス（backlog の output など）は人が直す
- **nested_v1 → box_root_v1（migrate-layout）:** sheets_v1 にするならこれを挟まず migrate-sheets で一度に移せる。`package.py migrate-layout --layer <Layer>`（dry-run）→ 本人の承認 → `--apply`（Stock へ写す設定なら `--program <実在する program>`。`--retire <退避先>` は任意。省くと `Documents/aipm_retired/<時刻>_migrate`）。project_init.yaml 以外の18文書は rename で sha256 そのまま、project_init.yaml だけ基準を書き直して manifest の `layout_migrations` に記録、空になった Flow/・Stock/ は消さずに退避先へ移す。**移せない（書く前に止まる）箱**: 既定コース（question_based）・共有 Stock・archive 済み・本人の回答が結ばれている・混じったファイルがある・文書が欠けている・intent に `aipm.layout` が書いてある・手で直した project_init。移した後に prearchive へ新しいエラーが出たら全部元に戻す

## 保存先の設定（aipm_archive）

新しい形の箱の archive の写し・apply_log の置き場は、リポジトリの `.ai-plc/config.yaml` の `aipm_archive` 節で決める。

```yaml
aipm_archive:
  where: layer       # auto（コードの既定）| stock | layer
  business: none     # registry（コードの既定）| none
```

| キー | 値 | 写す先 |
| --- | --- | --- |
| where | auto | `Stock/programs` のあるリポジトリが見つかれば stock。見つからないとき、`.ai-plc/config.yaml` が無ければ layer、あれば stock のまま止まる（設定したリポジトリで Stock を見失ったまま黙って Layer へ写さないため）。**設定ファイルを置くなら where を明示する** |
| | stock | `<リポジトリ>/Stock/programs/<program>/...`（`--stock-root` で替えられる） |
| | layer | Layer の中の `Documents/aipm_archive/<project>/`（program のフォルダも Registry も要らない） |
| business | registry | Registry の primary の業務Project の下（`.../projects/<業務Project>/<project>/`）。業務Project が決まっていなければ止まる |
| | none | Registry を読まない（stock なら `.../projects/<project>/`）。where: layer のときは business の値によらず Registry を読まない |

- **何も設定しないとき:** `Stock/programs` が無いリポジトリでは Layer の中に写し、Registry は読まない。`Stock/programs` を自分で作ったリポジトリでは where が stock、business が registry になり、Registry（`.claude/db/ai_plc.db`）に業務Project の表と primary が無いと archive は止まる（何も書かない）。業務Project を使わずに Stock へ写すなら `where: stock`・`business: none` を書く
- 設定のファイルは、Stock の場所と同じ候補（`--stock-root` → Flow の親 → `.git` の指す親リポジトリ）の最初の `.ai-plc/config.yaml` を読む。値の誤り・壊れた YAML は止まる
- 写したあとの箱は、記録した行き先（manifest の `archive_target`。設定から決めたものは `source: config`）を使い続ける。設定を後で変えても、写し済みの箱の行き先は変わらない（apply・push・register・clone・change は記録の行き先の頭で Layer か Stock かを決める）。例外: business: none で Stock へ写した箱は、あとで business を registry にすると final が止まる（業務Project を通っていないため）。その箱の間は business: none のままにする（版のある箱は move-archive で移せない）
- move-archive は Stock の写しを動かす道具なので、where: layer の設定や Layer の中の写しでは止まる。migrate-sheets・migrate-layout は where: layer なら `--program` を求めない
- 共有 Stock（`aipm.storage: registry_stock_v1`）の箱には効かない

## 保存した箱の改訂（apply）

保存（archive）した箱も、正本（保存先の写し）から写して直し、版を足して保存先へ反映し直せる。正本は保存先（既定は Layer の中の `Documents/aipm_archive/<project>/`、Stock へ写す設定なら Stock の下）、箱は今までどおり持ち主の Layer の作業の写し。下の表の「Stock」は保存先と読む。

| 段 | 入口 | すること | 書く先 |
| --- | --- | --- | --- |
| 1 登録 | `package.py register --layer <L>`（dry-run）→ `--apply --approval-ref <承認の出典>` | 版の無い保存済みの箱を v1 にする。中身・sha256・manifest の既存の値は動かさない。新しく archive した箱は初めから v1（kind first）なので要らない | manifest の `applies`・Stock の `apply_log.yaml`（`documents/` の隣） |
| 2 clone | `package.py clone --layer <L>` | 箱・Stock・apply_log が同じ版かを確かめ、作業の基準を記録する。文書は写さない（Stock の方が新しいなら止まり、持ち主の Layer の Flow を git で取り込む） | `Context/aipm_changes/base_<project>.yaml` |
| 3 取り込み | pm-suggest・pm-persona・pm-story | 会話・メモ・本人の言葉から、変える文書と箇所の候補を出す | 会話 |
| 4 変更案 | `package.py change --layer <L> --input <候補の YAML>`（dry-run で影響の一覧）→ `--apply` | 変更案を作る。影響の一覧は inputs・後ろの工程（stage_order）・ID が出てくる文書（id_mention）。下書きは id_mention の文書だけ（AI が after を書く。課題・仮説の判定は下書きにしない） | `Context/aipm_changes/C-*.yaml` |
| 5 判定 | `package.py change-list --layer <L>` で番号つきの一覧と digest を見せる → 本人の返事 → `package.py judge-change --layer <L> --list <digest> --quote "<原文>" --at <時刻> --thread <会話の ID>` | 返し方は5つだけ: `OK（全件反映）`／`採用: 1,3`／`修正: 2 は「…」に直す`／`今回はレポートのみ`／`差し戻し`。AI は判定を書かない。差し戻しは次からの一覧から外れる | 変更案の `judgment`・`list_<digest>.yaml` |
| 6 箱へ反映 | `package.py apply --layer <L>`（dry-run）→ `--apply --approval-ref` | 採用された変更案だけを箱に入れ、版 N（未 push）を足す。本人の回答の対象の文書を変えたら、判定の言葉から版の受領を作る（前の版の受領は動かさない） | 箱・`Context/receipt_apply_v<N>_*`・控え `Context/aipm_changes/backup_v<N>_*` |
| 7 push | `package.py apply --layer <L> --push`（dry-run）→ `--push --apply --approval-ref` | clone の後に Stock が変わっていないかを照らしてから Stock へ書き、apply_log に版を足す。base を版 N に進める | 保存先の文書と apply_log・箱の manifest |

- **保存の後に箱の外の読み込み元が変わった箱:** 保存の後に、箱が読んだ Layer の文書・Context（既定コースは証拠のファイル）を本人の承認で直すと、記録の sha256 と合わなくなり、final が E_COURSE・E_EVIDENCE で落ちる（register・clone・apply も止まる）。今のファイルは直さず、archive の時点のバイトを箱に写しとして置く:
  1. `package.py snapshot-sources --layer <L>`（読むだけ）で、変わった読み込み元（id・path・記録と今の sha256・archive の時刻）を見る
  2. AI が持ち主の Layer の Flow のチェックアウトで、`git log -- <path>` と `git show <archive の時点の commit>:<path>` を読むだけで使い、元のバイトをスクラッチのファイルに書く（道具は git を呼ばない）
  3. 入力の YAML `sources: [{id: <id>, bytes: <そのファイル>, from: "git show <commit>:<path>"}]` で `snapshot-sources --input <YAML>`（dry-run）→ 本人の承認 → `--apply --approval-ref <承認の出典>`。bytes が記録の sha256 と同じときだけ、箱の `source_snapshots/external/<path>` に置き、manifest の `source_snapshots` と `source_snapshot_log` に残す。違う・変わっていない・知らない id・承認の出典が無いときは何も書かずに止まる。書いた後の final が前より悪ければ全部戻す
  4. validate は、写しと log（同じ path・記録と同じ sha256）がそろうときだけ写しで照らす（log の無い写し・置き場の違う写し・中身の違う写しは今までどおり誤り）。そのあと register・clone から続ける
  - 同じファイルを指す証拠が複数あるときは、1つの写しを共有する（同じ YAML に並べるか、あとから同じバイトで足す）。本人の受領（user_reported）は写しにしない
  - 写しは manifest を書き換えるので、apply して push していない版があるときに置くと `--revert-unpushed` が止まる。写しは apply の前（または push の後）に置く
  - 写しは持ち主の Layer の箱にだけ書く（保存先には書かない）。写しを置いた箱を migrate-sheets で移すと、写しの置き場の頭が合わなくなるので、移すなら写しの前に移す
- **`--apply` の要るもの:** register・snapshot-sources・change・apply（`--push`・`--revert-unpushed` も）は既定が dry-run で、書くときは `--apply`（register・snapshot-sources・apply は `--approval-ref` も）。clone・change-list・judge-change は持ち主の Layer の Context（base・一覧・判定）だけに書き、`--apply` は要らない
- **戻す:** 箱へ反映して push していない版は、`package.py apply --layer <L> --revert-unpushed`（dry-run）→ `--revert-unpushed --apply --approval-ref` で控えから base に戻す（受領ファイルは残す。同じ一覧でもう一度 apply すると控えと受領の名前に `_2` が付く）。apply の後に manifest が変わっていたら止まる
- **書く操作はどれも、書く前に全部の条件を確かめ、書いた後に validate（final）を回して前より悪ければ全部戻す**（途中の例外・Ctrl-C も同じ）。止まる主な場面: 承認の出典が無い／clone の base が箱の最後の版でない／一覧の後に変更案が変わった／採用が無い／変更案の before が今の箇所に無い／変える文書を指す証拠が manifest にある／回答の対象の文書を変えるのに判定に会話の ID が無い／push の前に Stock や apply_log が変わっていた
- **validate（applies のある箱だけ。無い箱は前と同じ）:** E_APPLY（版の番号・各版の docs・最後の版＝records・changed の前後・未 push は最後の版だけ・Stock の apply_log＝push した版）、apply_v<N> の出来事は stages の末尾、未 push の版は W_UNPUSHED（警告。Stock は最後に push した版と照らす）、本人の回答は最後にその文書を変えた版の受領で照らす、apply で変えた文書は `applied_mtime_ns` を apply_v<N> の時間の中で照らす（`generated_mtime_ns` は変えない）
- **版のある箱では止まる操作:** move-archive・migrate-sheets（apply_log・受領の置き場を移さないため）、migrate-layout（archive 済みの箱はもともと止まる）。版の無い保存済みの箱を sheets_v1 へ移すなら、register の前に移す
- 保存先への書き込み（register・`apply --push`）は**本人が求めたときだけ実行する**。git の commit・push は道具はしない（本人が決める）
- 範囲の外: init の下書き（project_init・README・format_contract）の改訂、共有 Stock と nested_v1 の箱、既定コースの新しい形の箱の初回の archive、一覧（論点・仮説・ToDo）の Stock への写し、同じ箱を並行して clone すること。一覧への追記は下の redit（文書の版とは別の記録）

## 保存した箱の一覧の追記（redit）

箱の一覧（issues・hypotheses・todo・wbs・roadmap）に、**材料・note の追記と新しい行、未定の欄を埋めること**を、apply と同じ型（入力 YAML・dry-run・番号つきの一覧への本人の返事・承認の出典・書く前後の検査と戻し）で入れる。文書の版（`applies[]`）には載せず、manifest の `register_edits[]` に別に記録する。保存前の箱（manifest のある箱）にも使える。

| 段 | 入口 | すること | 書く先 |
| --- | --- | --- | --- |
| 0 抽出案を読む（任意） | `package.py redit-extract --layer <L> --input <抽出案の Markdown>`（読むだけ）→ `--apply` | 採否の印つきの抽出案（節は TODO・WBS・論点・仮説、表の見出しは「案・区分・…・採否（本人の確定）」）の行を分ける：採用の追記・採用の新しい行・既存の更新・判定が要る・但し書きつきの採用・重複なのに採用（本人に確かめる）・不採用など・読めない。判定が要る行は judge・resolve の入力の下書き（判定の値は空）だけを作る。抽出案の採否は案の出どころで、承認ではない | `Context/aipm_changes/rextract_<名前>.yaml`・`judge_draft_case_<案>.yaml` |
| 1 変更案 | `package.py redit --layer <L> --input <YAML>`（dry-run）→ `--apply` | 入力（`source`〔kind・ref〕・`created_by`〔ai／owner〕・`edits[]`）から変更案を作る。未確定の行は保留にして書かない | `Context/aipm_changes/R-*.yaml`・保留は `rheld_<入力>.yaml` |
| 2 一覧 | `package.py redit-list --layer <L>` | 未反映の変更案の番号つきの一覧と digest。本人に見せる | `rlist_<digest>.yaml` |
| 3 判定 | 本人の返事 → `package.py redit-judge --layer <L> --list <digest> --quote "<原文>" --at <時刻> --thread <会話の ID>` | 返し方は apply と同じ5つ（`OK（全件反映）`／`採用: 1,3`／`修正: 2 は「…」に直す`〔note の文だけ〕／`今回はレポートのみ`／`差し戻し`）。`--thread` は必須。AI は判定を書かない。後の返事が先の採用に勝つ（まだ書いていない採用済みの案にも、差し戻し・レポートのみが効く）。ただし部分採用（`採用: N`）は、前の一覧で採用したまだ書いていない案を取り消さない（やめるなら差し戻す） | 変更案の `judgment` |
| 4 書く | `package.py redit-apply --layer <L>`（dry-run）→ `--apply --approval-ref <承認の出典>` | 今の未反映の案に合う一覧の中の採用済みの案だけを書き（採用は、本人が返事した一覧とその返事の記録で照らす。`register_edits[].list_digest` は書いたときの一覧、`judgments[].list_digest` は返事した一覧）、manifest の `register_edits[]` に1件（原文・時刻・会話の ID・一覧の digest・変えた行・書いた後の sha256・控え） | 箱の一覧・manifest・控え `rbackup_<n>_*` |
| 戻す | `package.py redit-revert --layer <L>`（dry-run）→ `--apply --approval-ref` | 最後の1件を控えから戻す（その後に一覧・manifest が変わっていたら止まる）。戻した記録（書いたときの承認の出典・判定・変えた行と、戻したときの承認の出典・時刻）を `rrevert_<番号>_<digest>.yaml` に残す。戻した変更案は採用のまま残るので、もう一度書くなら `redit-apply`（新しい `--approval-ref`）、やめるなら一覧を出し直して差し戻し | 箱の一覧・manifest・`rrevert_*.yaml` |

- **足してよいもの（op: append）:** issues の `sources`、hypotheses の `sources`・`evidence`、wbs の `evidence_refs`・`milestone_id`（空のときだけ）、todo・roadmap の `note`（「日付: 文」の1行）、roadmap の `wbs_ids`。wbs の milestone_id と roadmap の wbs_ids は、同じ一覧で組として採用されたときだけ書く。wbs の evidence_refs は、今ある仮説の H か Layer の中に実在するパスだけ。箱の一覧の契約に無い欄は止まる（一覧の契約 v1 の箱では、issues・hypotheses の sources は足せない）
- **未定の欄を埋める（op: fill）:** 初めに未定のまま置いた欄を、本人が決めた後に入れる。論点の `due`・`owner`・`priority`、ToDo の `due`・`owner`・`priority`・`wbs_id` だけで、今の値が未定（`undecided`・`[unknown]`・「未定」「未確定」「TBD」・空・欄が無い）で、行がまだ動いている（論点は open・on_hold、ToDo は done・cancelled 以外）ときだけ書ける（決まった値は上書きしない）。**値は本人の答え**にする（AI が推測した期限・owner・優先度を案にしない）。期限は `YYYY-MM-DD` の形だけ（`20261115` などは止まる）、ToDo の wbs_id は今ある WBS の行だけ。入力は `{op: fill, register: issues, row: I3, field: due, value: '2026-11-15'}`。一覧には前の値（before）と入れる値が出る。同じ入力・同じ一覧で同じ欄を2回埋めるものは止まる
- **新しい行（op: add_row）:** 5つの一覧すべて。ID は書くときに振り、status は既定値（論点 open・仮説 unknown・ToDo todo・wbs／roadmap は draft か planned）だけ。判定の欄・合意の欄（論点・仮説の answer・evidence_refs など、wbs の参照・gate・evidence_refs・schedule の baseline／actual／history）と、roadmap の wbs_ids は持てない（wbs と roadmap の組は後で append の組で結ぶ）。仮説の kind・priority は契約の値だけ（priority が決まっていなければ欄を書かない）。参照（論点の parent〔1つの ID〕、ToDo の wbs_id、仮説の issue_id）は今ある行だけで、決まっていない参照は欄を書かない。ToDo の source は自由な文も書けるので、I・H の形のときだけ今ある行と照らす（「未定」などは文としてそのまま残る）。入力の引用符の無い日付は文字にして書く。新しい wbs の行の forecast は map で、終わりが始まりより前なら止まる。sources はパスのリスト、論点の owner・due・question と仮説の claim は文字、source_of_truth は local だけ。ここで照らしきれない値は、書いた後の検査で落ち、その一覧の採用を全部戻す（何も書かれない）。論点・ToDo・wbs の owner と論点の due が無ければ、pm- と同じく `[unknown]`・`undecided` を入れる
- **書かないもの:** 判定の欄（status・answer・resolved・judgements・decided_by・reason・verdict）は案の段階で止まる。判定は本人の回答を受領記録にして `package.py judge`、論点は `pm-issue` の resolve・close
- **未確定の行は保留:** 新しい仮説は kind・claim・method・success・falsification のどれか、ほかの一覧は必須の欄（owner と論点の due を除く。この2つは上の既定値が入る）が空・「未定」「未確定」「TBD」「[unknown]」なら変更案にしない（保留の一覧に残る）。決まったら入力を直して redit からやり直す
- **保存済みの箱の条件:** 版がある（無ければ先に `register`）・最後の版が push 済み・書く前に validate final が合格。nested_v1 と共有 Stock の箱は止まる（nested_v1 は先に migrate-sheets）。書いた後の検査（保存済みは final、保存前は E_REGISTERS）が前より悪い・途中の例外・Ctrl-C は、一覧・manifest・変更案を元のバイトに戻す
- **書く前に止まる場面:** 承認の出典が無い／判定が無い・原文・時刻・会話の ID・digest のどれかが欠ける／本人が採用した後に変更案の中身が変わった（一覧を出し直すだけでは通らない。差し戻すか、判定し直す）／一覧の後に変更案が変わった／変更案の後に一覧のファイルや行が変わった／採用が無い／組の片方だけの採用
- **validate:** `register_edits` のある箱だけ照らす。E_REDIT（番号の抜け・判定の4つの欄・approval_ref・base_version が applies の版）、W_REDIT（警告。最後の記録と今の一覧が違う。judge・resolve・todo.move の後は出る）
- **書いた後:** 一覧は保存先へ写さない（上の apply の「範囲の外」）。保存先は変えない。git の commit は道具はしない
- **merge の後に効くこと:** archive 済みの sheets_v1・box_root_v1 の箱は、版が無くても「版を持てる保存済みの箱」に当たる。たとえば版の無い保存済みの箱の一覧を変えるには、`register`（v1）→ redit の順になる。実物の箱への適用は、そのつど本人の承認で行う

## 共通Stockを明示選択した案件

既定では使わない（仕組みだけを同梱している）。`aipm.storage: registry_stock_v1` の案件だけ、上記の保存先への同bytes保存の代わりに [共通Stock契約](shared-stock.md) を読む。Flow必須19文書・工程順・本人判断・独立検証は保持する。憲章はFlowに置き、原文snapshotと整理統合版を分離し、archive時に同版差分を採択して反映する。未指定/旧案件は従来の保存（新しい形は保存先の設定、古い形は箱の中の Stock）を保持し、自動移動しない。共有 Stock の新しい箱も新しい形（工程フォルダと憲章 `_charter/` が箱の直下。保存済みの共有 Stock の箱は古い形のまま読む。migrate-layout は共有 Stock の箱を移さない）。runtime は隔離の FixtureStore か、採択済みの1組だけに発行した LiveStore（shared-stock.md「実runtime」）。発行の無い組・Layer・writer では停止し、intent の値だけで runtime を選ばない。中心の道具は `.claude/db/shared_stock.py`、業務Project の表は `.claude/db/business_registry.py`。


## ソリューション起点・既存資料補完のローカル拡張 v1

[course_contracts.yaml](course_contracts.yaml)はAI-PLCのローカル契約で、canonical/source/rawの上流由来は変更しない。共通schemaの19論理成果・各形式・13フォルダは同じ。探索型のbound contractは従来値を保持し、新しいversion/manifestへの再生成・移行を要求しない。新コースだけ `2.0+courses.1` とcourse契約version/SHA256を束縛する。

- solution_based/single_persona: 実際に示されたsolutionを `kind: hypothesis` として入力し、誰/問題/価値/storyを逆算して下書きする。solutionの存在は課題や実効果の検証完了ではない。
- document_based/single_persona: 許可された実在資料を読み、対応・互換性・不足・矛盾を整理する。互換文書はbytes/元mtimeを保ったまま再利用し、古い形式/別IDはそのまま最終成果にせず変換下書きへ根拠として使う。

Inceptionでは先に同じTask内の19成果と先行/開発依存を登録する。新コースの実生成順は **資料読取→初期化→batch下書き/互換再利用→不足判断→保存（archive）**（`mode_init` で Collection の最後に初期化した Layer は **初期化→資料読取→batch→不足判断→保存（archive）**。manifest の init の段は `origin: mode_init` と mode_init の done_at で記録し、開始時刻は作らない）。これは探索型の質問順を生成時刻として捏造する契約ではない。Construction/Operationは選ばれたcourseの入力・各19形式・source対応・必要判断を引き継ぐ。AIPM完了後の開発への接続は、選んだ開発方式（`dev_style: <your_style>`）の規約（チェックポイント・PR の作り方・レビュー）の既存の入口を使い、技術質問・計画承認待ちへ渡す。UIが不要なSkill/CLI案件へHTMLを強制しない。

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

`package.py plan --layer <Layer> --input Context/course_input.yaml` は実資料を読み、対応・不足・必要質問を返す（書込なし）。担当が同じ証拠からまとめて19下書きを用意し、`package.py draft --layer <Layer> --input Context/course_input.yaml` で新規packageへ実生成する。sources のうち package の中にあるもの（registers など、後の会議で更新し続けるもの）は、draft が `source_snapshots/` に同じバイト・同じ mtime で写して manifest の `source_snapshots` に残し、validate は写しを照合する（この決まりの後に draft した package と、写しを置いて移行した package では、registers を後で更新しても保存済みの19文書は落ちない。写しの改変・付け替えは従来どおり検出。写しの無い旧い package は registers を更新すると落ちる）。旧い package（source_snapshots の無いもの）の写しの移行は個別に行う。既存packageがあれば上書きせず停止し、保存済み文書を移行しない。ただし mode_init の出力だけがある package（manifest・validation_record・19文書のどれも無く、project_init・README が mode_init の hash のまま）は続けて書く：format_contract と registers は保持し、project_init・README は19文書の一部として下書きに置き換わる（手で直してあれば停止）。19文書を作り直すときは、本人の承認の後に `package.py reset-to-init --layer <Layer>` を使い、git で手で戻さない。既定は予定の表示だけで、`--apply --retire <退避先>` で package の外へ移し、初期化直後に戻す。人物・検証をAIが確定するAPIではない。探索型ではこれらbatch APIを使わず従来の工程を実行する。

新manifestはsource_reads、gaps、decisions、claims、生成kind/event/source IDs/reused_fromを既存recordへ追加する。生成ファイルの記録時刻（generated_mtime_ns）は実batch interval内、reuseは元ファイルのhash（bytes）と一致させる（書き出しは元mtimeも保つが、validate は bytes と記録の値で確かめる）。外部時刻や旧順序を捏造しない。必要本人判断の実回答は既存Step8のsource/target/hash/原発話照合を使い、新コースではgaps intervalへ対応付ける。質問待ちの実時間をそのintervalと実行予算へ記録する。

`validate_package.py --phase prearchive` がPASSしてから `package.py archive --layer <Layer>` で保存し（新しい形は保存先へ。上の「箱の形と保存先」）、final検証する。実資料と保存済み文書を改変せず、同bytesを保存する。registry_stock_v1を明示選択した場合は既存shared-stockの具体runtime/prepare/apply手順を使う。runtime未成立で従来の Stock 方式へfallbackしない。形式PASS・可逆なlocal draftと実本人の効果/採否は別で、OperationのTask ACと通常の独立レビューを通す。


入力packetはhashを束縛し、その不足・claims・資料対応・decisionの理由/出典/質問をmanifestで保持する。元のpending/materialをnot_requiredへ下げたり必須gapを削って保存しない。解決時は元の質問を残しstateだけconfirmed_actualへ進め、既存の実receipt・対象版・原発話を照合する。manifestの書換えだけを回答にしない。
