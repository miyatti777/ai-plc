---
name: 04-operation
description: ai_plc_operation - AI-PLC Stage 4。backlog（Agent定義があればそれ）に従ってタスクを実行し、成果物をArtifact Storeに格納する。
---

# AI-PLC Stage 4: Operation

backlog（Agent定義があればそれ）に従い各タスクを実行する最終ステージ。Context Storeからコンテキストを注入し、成果物をArtifact Store（Documents/）に格納する。実行中に発見したコンテキストはContext Storeに追加する（Hierarchical Context Propagation）。

**共通規約:** 命名は RUL_plc_system §6 / 完了報告は RUL_plc_session §7（説明の詳しさは §7.0）/ Phase遷移通知は §8 / Mob CP出力と質問UIは §9・§9.1 に従う。

**ライブ表示:** 公開版にはライブ表示（BacklogLive）は無い。手元に `tools/BacklogLive/server.py` があるときだけ使える（無ければ何もしない）。

**自動完走モード・既承認:** セッション中に RUL_plc_session §10 を指す /goal があるときは §10 に従い、Mob Checkpoint・Next Action・タスク選択で待たずに進める（無ければ本 SKILL のとおり止まる）。同一の操作・対象・条件で本人が承認済みと照合できた範囲（開始ゲートの一括許可を含む）は聞き直さない。明示 force は §10.1 の force-contract を先に読み、本 SKILL の待機句へ戻らない。重い工程の記録は RUL_plc_session §7.6。

**ゲートは2点＋回数上限（RUL_plc_adaptive §0）:** 開始ゲートは Inception Phase 4 の OK（実装・検証まで一括許可。Task 指定で /04-operation を呼ばれたことも同じ）。完成ゲートは Phase 5.5（AC の ○×＋standard 以上は独立レビュー1回）。途中の保存可否・版一致は git（branch/worktree と diff）に委ね、Layer の作業は branch で始めて完成ゲートで diff を見せる。回数の上限は「修正→再検証は2回まで」、独立レビューは初回1回＋最初の修正後に再レビュー1回、stopped 1回で人へ戻す。分単位の予算・時計の締切・版 hash 照合・同版承認の再提示は行わない。

**選択した方式だけ読む（発動条件は3つ）:** 同梱の PM アドオン（目録 [addon-catalog.yaml](../references/addon-catalog.yaml) の aipm。旧い欄 `work_style: aipm` も同じ）が選ばれた Layer は [aipm-guided](../../aipm-guided/SKILL.md) の工程順を守る。`dev_style: <your_style>`（本人が選んだ開発方式）の Layer は完成ゲートだけをその開発方式の規約（チェックポイント・PR の作り方・レビュー）に委ね、AI-PLC 側に binding・予算・版照合を持たない。持ち込みのアドオン（`intent.addons` の case の件）がある Layer は [addon-seam.md](../references/addon-seam.md) の型を Phase 4 で読む。どれが選ばれているかは、intent の `work_style` が null 以外か `addons` が空でないときだけ、判定関数 `python3 -B .claude/skills/ai-plc/scripts/plc_addon_select.py --layer <Layer>`（目録を読む・書き込まない。持ち込みの件があるときは `--read-root <実許可root>`、scope: common なら `--common-root <root>` も付ける。plc_addon.py と同じ）で確かめる（`route` が `held` なら `hold_reasons` を出して止める。同梱は `selected[].addon_id`、持ち込みは `has_case_addons`）。どれも無い Layer（既定）は判定関数も呼ばず、本 SKILL と rules だけで実行する。

## 入力

| 入力 | 必須 | 説明 |
| --- | --- | --- |
| Backlog + Context Store | ✅ | Stage 1-2の生成物（Agents/ は Stage 3 を通したときだけ） |
| target_task | ⭕ | 未指定時は実行可能タスク一覧を提示 |

## 実行フロー

### Phase 1: 現在成果・未達・実行可能Taskの確認

backlog.yamlを読み込み、依存関係を解決し、実行可能タスク（依存解決済み・未着手）を特定する。`construction.tasks` に入っていて command があるのに Agents/ に定義が無いタスクは、実行可能タスクに含めず /03-construction（そのタスク指定）を案内する（command の無いタスクは外さない。`construction` 欄の無い既存 backlog は RUL_plc_adaptive §6 のみなし規定に従う）。intent.status が cancelled なら RUL_plc_system §21 の再開手順へ案内して止まる。intent に `mode_init` があり state が done でなければ Hold し、/01-collection の Phase 7.5（初期化の段）へ案内する（`mode_init` の無い Layer は今までどおり）。止まった Task を続けるときは [outcome-delivery.md](../references/outcome-delivery.md) の「止まった後に続ける」に従い、Task の result / refactoring_log にある成立済み証拠・未達・次操作から再開する（新セッションを理由に調査をやり直さない）。

**繰り返す運用タスク（`recurrence` のある Task）:** 依存が解決していて `retired_at` の無いものは、通常の実行可能タスクとは分けて「次に回す運用タスク」として示し、最後の `runs` の日付から回す日か（daily は前回が昨日以前・weekly は7日以上前で、`runs` がまだ無ければ回す日とする。per_meeting は会議の後に本人が呼んだとき〔初回も同じ〕）を添える。実行したら、その回の結果を Task の AC で L1 確認して `runs` に1行（date・summary・output・checked_ac）足し、status は `in_progress` のまま completed にしない。Phase 5.5 の独立レビューと P0〜P2 の完成ゲートは run ごとには掛けない（日次・週次の運用が回らないため。運用タスクを足した Inception の承認と、その成果を使う側の Task の Phase 5.5 で受ける）。運用タスクの `scheduled_for` は回し始める日で、その日まで『次に回す運用タスク』に出さない。

**実行時期（`scheduled_for` のある通常 Task）:** `scheduled_for` が今日より後の Task は、依存が解決していても実行可能から外し「待ち（実行時期 ○月○日）」として一覧に示す（`YYYY-Www` はその週の月曜を時期とみなす）。待ちは案内であり禁止ではないので、本人が Task を指定して呼んだときは時期に関わらず実行する。時期を変えたときは `schedule_history` に1行（date・from・to・reason）足す。`due`（期限）は実行可能の判定に使わず、一覧に添えるだけ。`scheduled_for` が読めない（`YYYY-MM-DD`・`YYYY-Www` 以外）Task は時期なしとして並べ、一覧に『時期を読めない（値）』と添えて書き直しを本人に示す。`due` が今日より前の未完了 Task は一覧で『期限超過（M/D）』と添える（並びと実行可能の判定は変えない）。

### Phase 2: Mob Checkpoint — タスク選択（停止）

実行可能タスク一覧を提示し、ユーザーの選択を待つ（自動完走中は待たずに下の一覧の順で選ぶ）。一覧は、実行時期のある Task（今日以前）を時期の早い順に先に並べ、その後に時期の無い Task を優先度順に並べる（同じ時期なら優先度順）。一覧は通常 Task の後に『次に回す運用タスク』を分けて並べる。タスクIDが入力で指定されていても、Agent 定義または backlog の guardrails にある途中の確認点は省略しない。実行可能タスクが複数あり並列委譲条件（Phase 4）を満たす組があれば、「並列委譲候補: TXXX+TYYY / 逐次: TZZZ」も併せて提示する。

### Phase 3: Context Ingestion

タスク実行に必要な追加情報を収集（優先順位: RUL_plc_system §16）→ Context Storeに追加 → context.yamlを更新する。先行タスク（dependencies）の output と Context/ は既定で読む。**モデル選択（opt-in）:** 本人がモデル選択/Advisor を依頼したとき、または Layer/Task に `model_routing: true` があるときだけ `.claude/rules/ai-plc-model-routing.md`（/plc-model-routing）を読む。Advisor は Phase 5.5 の独立 reviewer や BT checker の代替にならない。

### Phase 4: Skill Execution

タスクに Agent 定義があれば読み込み、その Phase 構造に従って実行する。無ければ backlog の description・acceptance_criteria・guardrails・decisions と Context から実行する（RUL_plc_adaptive §6）。どちらでも Autonomous Phase は AI が自動処理し、確認点では止まって人の判断を待つ（自動完走中は RUL_plc_session §10）。実装系タスクは実体（DB・ページ・コード等）を作る（設計書だけで終わらない）。Task の description/AC にある「成立する成果」まで実行・検証し、部品や設計だけで利用者成果を達成したとしない。

**並列委譲（Subagent実行）:** ①`delegable: true`（Agent 定義あり）②依存独立 ③出力パス非競合 の3条件を満たす組だけ、承認を得て Agent tool に並列委譲できる（2-3並列まで）。AGT本文＋絶対パスを prompt に渡し、変更禁止ファイル（backlog / context / intent / sqlite / rules / SKILL）を明示する。ステータス更新・Phase 5.5・Propagation は親が行い、Subagent の自己申告は親の L1 か独立 reviewer で裏取りする。委譲先には成果物パスと実測値を返させる。Agent 定義の無いタスクは委譲せず逐次で実行する。

**スコープ外の発見:** 現在の AC・判断・停止に影響する残件は既存 Task に短く残す。独立した成果として扱う必要がある場合だけ Self-Describing Task 構造（RUL_plc_system §9）でチケット化し、外部に書き出すかを確認する（承認後に push）。発見だけを新 Task や外部書出し質問の必須条件にしない。

**重い工程の開始前:** RUL_plc_session §7.5 で目的の判定可能性・選択肢の費用・⭐を確認する。既知の不成立条件を残したまま、最速という理由だけで本工程へ進まない。

### Phase 5: Artifact Generation

成果物をArtifact Store（Documents/）に格納する。成果物は具体的に記録する（「〇〇を作成」「△△を更新」）。**中断・判断待ちで止まるとき**は、Task の result / refactoring_log に成立済み証拠・Goal/SC の未達・次の操作・必要な許可や実エラーを短く残す（Phase 6 の完了処理とは別。未完了 Task を completed にしない）。外部操作は「準備済み」と「申請/送信の未達」を分けて書き、許可内の独立作業は続ける。段階の成功は局所の AC で確認し、元 Goal 全体の完了へ広げない。

### Phase 5.5: Verification（省略禁止）

intent.yamlのworkflow_depthに応じて3層検証（RUL_plc_system §18）を実行し、結果をチェックリスト形式で必ず出力する。出力しない限りPhase 6に進めない:

```
🔍 Phase 5.5: Verification（[workflow_depth]）
- [x] L1: [チェック内容と結果]（全タスク必須）
- [x] L1: acceptance_criteria を1項目ずつ ○/× とAC達成度・証拠で書く（RUL_plc_session §7.2。backlog の acceptance_criteria、無ければ description の完了条件）。○は達成のみ、一部・未達・未確認は×として残件を明記し、× が1つでもあれば Phase 6 へ進まない。許可内の修正や不足検証で解消できるものだけ Phase 4 へ戻り、検証環境の不成立・外部依存は blocked と残条件を記録して 5.5b へ渡す
- [x] L2: [チェック内容と結果]（standard以上）
- [x] L3 + NFR: [チェック内容と結果]（complexのみ。NFRはRUL_plc_system §19）
```

P0-P2相当の問題はPhase 4に戻って修正する。未解決P0/P1/P2が0件になるまでPhase 6へ進めない。P3は差し戻し対象外（語彙: RUL_plc_system §18）。修正→再検証は2回まで。2回後も P0〜P2 が残る、またはタスク内で修正できない前提崩壊・外部依存・設計矛盾は Phase 5.5b のBT-A判定に委ねる。本人原要求（intent.request_provenance）と現在 Goal の照合は [requirement-review.md](../references/requirement-review.md) の要点（目的逸脱・核心動線の欠落・未実装の手作業代行）を reviewer の入力に含める。本人が Task に `review_profile: gobold` を明示したときだけ [gobold-review.md](../references/gobold-review.md) を基準に使う。

**独立検証（maker≠checker・全タスク既定動作）:** 自己検証チェックリストの直後、質問せず原則毎回、作成文脈から独立した reviewer を起動して結果を取得する（コードに限らない。`delegable: false` は Phase 4 の委譲だけに効き、reviewer 起動には効かない）。CC / Cursor=Subagent reviewer（`TPL_review_agent`）/ Codex=sub-agent / サブエージェントの無い環境=`@SKL_plc_checker` を別チャットで。reviewer には成果物と検証に必要な定義（Goal/Output・受け入れ基準・Level・type のレンズ・snapshot）だけを渡し、会話履歴は渡さない。read-only、出力は P0-P3 か「No findings」、対象 snapshot を1行記録し、結果をチェックリストの該当 Level に転記する。得られなければセルフ検証にフォールバックして理由を1行記録する（silent skip 禁止）。並列委譲されたタスクは独立 reviewer で親の L1 裏取りに代えてよい。

**発動強度（上から順に判定。レンズ表で対象外のtypeは常に対象外）:** 必須=complexのL3検証／受け手に渡る最終成果物（外部向け資料・公開コンテンツ・意思決定文書）→ reviewer結果を得るまで完了しない。既定=workflow_depth standard以上 → 毎回sub-agent reviewerを起動して結果を取得し、返らない場合だけ理由を記録してセルフ検証にフォールバック。省略可=simple・内部メモ・中間生成物・management/coordination・レビュー対象のない意思決定オンリー → セルフ検証L1でよい（省略時は「独立レビュー省略（基準: …）」と1行出力）。

**type別検証レンズ（reviewerへの指示に使う。§18/§19の具体化）:**

| タスクtype | レンズ |
| --- | --- |
| implementation / coding | 動作・回帰・エッジケース・セキュリティ |
| content（記事・資料） | 事実確認・引用の裏取り / 読者視点で最後まで読めるか（L3）/ トーン一貫性 / 専門外への可読性（NFR） |
| planning / design（企画・設計書） | 論理の飛躍・根拠 / 実現可能性・工数妥当性 / 意思決定者が判断できるか（L3）/ 矛盾検出（L2） |
| research | ソースの信頼性・反証可能性 / 主張とエビデンスの対応 / 欠落した対立見解 |
| goal / plan（Re-Collection GAP分析・Re-Inception残タスク再評価） | 元goal+success_criteriaとの充足・未達 / スコープ逸脱（ドリフト） / 見落とされた前提・欠落タスク / 完了宣言の妥当性 |
| validation / review | 対象外（自身がcheckerのため再帰reviewerを起動しない） |
| management / coordination | 対象外（独立レビュー不要・セルフチェックで可） |

backlog.yamlの`type`値が表にない場合は最近縁の行を適用する。complexは実際の成果物typeへ、operationは各量産成果物のtypeへ解決する。validation / reviewは最近縁フォールバックの対象外とする。

### Phase 5.5b: Backtrack判定（タスク単位）

検証結果からBT-A（ブロッカー: critical NG / 外部依存未解決 / 設計矛盾 — RUL_plc_adaptive §5）を判定する。該当時のみNext ActionにD/E選択肢を追加し、該当なしなら何も出力しない。
**Jev監視（opt-in）:** intent.yamlに `jev_monitor: true` があるLayerのみ `python3 scripts/jev_bt_monitor.py --layer <Layer> --phase 5.5b --task <ID>` を実行する。「💡異常の可能性」が出たら種類と提案文はメインモデルが判断し提案のみ行う（ヒントは止める権限を持たない）。判定ごとに `--override <decision_id> accept|reject` で本人の確認を記録する（6b と同じ）。スクリプトは Jev 実験版パッケージ（`--with-jev`）に入っている。無ければスキップ。

### Phase 6: Status Update

全AC達成とPhase 5.5の完了ゲートを満たすことをAC表で確認してから、backlog.yamlを更新（status → completed + 成果物リンク）し、context.yamlに成果物エントリを追加し、進捗ダッシュボードと次の実行可能タスクを表示する。運用タスクの1回はこの更新をせず、Phase 1 の `runs` への追記で代える（context.yaml には output の置き場を初回に1行だけ）。SubLayer内のTaskが親ScopeBacklogのTaskに対応する場合、親側のステータスも連動更新する。
同梱の PM アドオン（旧い欄 `work_style: aipm` も同じ）が選ばれ `aipm.registers: true` の Layer では、完了した Task に wbs_id があれば `python3 .claude/skills/aipm-guided/package.py wbs-candidate --layer <Layer> --task <ID>` で WBS の該当行に output を証拠として足し、同じ wbs_id の Task が全部 completed なら pending_acceptance にして完了報告で「accepted の候補」として出す（accepted にするのは人。残りの Task があれば候補にせず〔既に候補の行は戻さない〕、返却の pending_tasks を完了報告に書く）。output が Layer の外にあるなどで失敗したら候補化を見送り、その旨を完了報告に書く。`scheduled_for` のある Task、または同じ wbs_id のどれかに `scheduled_for` がある Task を completed にするときは `completed_at: YYYY-MM-DD` も書く。wbs-candidate の返却に `schedule_actual_candidate` があれば、完了報告に『WBS <wbs_id> の実績日の候補: <日付>（根拠 <Task>。schedule.actual に書くかは人）』と1行添え、wbs.yaml の schedule は書かない。返却に `schedule_actual_missing` があれば、完了報告に『WBS <wbs_id> の実績日の候補を出せない（completed_at の無い Task: <ID>）』と1行添える。
実行したタスクには `executed_by: <実行環境>`（claude-code / codex / cursor）を書き、`python3 .claude/db/classify.py sync --layer <Layer> --yes` で Registry の分類の表に写す（無い環境ではスキップ）。plc-backfill から通すときは**実際に作業した環境**を書く。Phase 5.5 を通した成果が案件の目的の説明を変える節目に限り、表示名の判断は [plc-registry の命名判断](../../plc-registry/SKILL.md#命名の判断と表示名の限定更新) に従う（全 Task 完了ごとの改名処理は作らない）。

### Phase 6b: Backtrack判定（パイプライン単位）

BT-B（節目再評価: 完了率50% / ゴールドリフト）と BT-C（全完了GAP分析）を判定する（RUL_plc_adaptive §5）。運用タスク（`recurrence` のある Task）は完了率と全完了の数に入れない。運用タスクだけの Layer は BT-C を判定せず、閉じるのは本人の判断（retired_at）。BT-C で Layer を閉じるときは、運用タスクに `retired_at`（日付）と `retired_reason`（Goal 達成など）を付ける（status は変えない）。同梱の PM アドオン（旧い欄 `work_style: aipm` も同じ）が選ばれ `aipm.registers: true` の Layer では、Task の全完了と論点の解決は別の物差しで、完了報告に validate の `issues_summary` と「work done but issue still open」の警告を添える（Registry の Project 状態の決まりは変えない）。**この判定は独立checkerに通すのが既定**（maker≠checker）: checkerに元intent.yamlのgoal+success_criteria+request_provenance（本人原文）+成果物リストを渡し（実行ナラティブは剥ぐが元ゴールと原文は渡す。本人が review_profile: gobold を明示した Task だけ gobold-review.md も）、上表の`goal/plan`レンズで「達成/未達/スコープ逸脱/見落とし前提」を判定させる。checker出力が返らなければmaker自己判定にフォールバックし1行記録。該当時のみNext ActionにD/E選択肢を統合する。
**Jev監視（opt-in）:** `jev_monitor: true` のLayerのみ `python3 scripts/jev_bt_monitor.py --layer <Layer> --phase 6b`。判定ごとに `--override <decision_id> accept|reject` で確認を記録し、未確認分は「🧭 未確認の Jev 判定: N件」（`--pending`）で出す（回収は `/plc-jev-monitor`。自動完走中は完了報告の冒頭にまとめる）。スクリプトと `/plc-jev-monitor` は Jev 実験版パッケージ（`--with-jev`）に入っている。無ければスキップ。

### Phase 7: Propagation（省略禁止）

RUL_plc_system §8 のチェックリスト8項目を「確認→判断→結果出力」で処理し、必ず出力する。**ステータス点検**は Registry DB 更新の後に `python3 .claude/ai-plc-jev/scripts/aiplc_status_audit.py --brief --layer <Layer>`（読み取り専用。SubLayer は `--layer` を重ねる）を実行し、候補があれば1行ずつ提示して承認を求める。反映は承認後に `--quiet --approval-template` で雛形 → 承認行だけ `approve` → `--apply <承認ファイル>`（dry-run）→ `--apply <承認ファイル> --yes`。終了コードは 0=食い違いなし／10=あり。スクリプトが無い／終了コード2なら理由1行でスキップ。Wiki波及はここが唯一の発動ポイント（RUL_plc_system §11）。本人専用情報の差分保存は §22 の発動条件に当たる Layer だけ。

**native memory:** PJ の状態・進捗は書かない（backlog・Registry が正）。この Layer から得た、PJ をまたぐ判断パターン・好みは feedback 型、閉じた後も使う参照は reference 型に書く（既存ファイルへの追記を先に考える）。オーナーの残作業が残るときは、あなたの TODO 管理（AI-PLC の範囲外）へ書く提案行を出す。**Wiki波及** の中で、今月の軽量Lint が未実施なら knowledge-lint.md の手順で実行して log に1行残す。**log** は表の行だけ（RUL_plc_system §11⑥）。

### Phase 8: フル Knowledge Lint [手動]

軽量Lint は Phase 7 で月1回実行する。6項目のフルLint と節の退避は「Knowledge Lintを実行して」の指示のときだけ [knowledge-lint.md](knowledge-lint.md) に従い実行する。

### Phase 9-11: Platform Builder [mode=platform_builder 全タスク完了時のみ]

[platform-builder.md](platform-builder.md) に従い、Production Skill生成 → 量産実行 → Eval Feedbackを実行する。direct modeでは発動しない。

## タスク完了時の出力

RUL_plc_session §7 の4パート（📍現在位置 / ✅完了サマリ / 📊進捗 / 🔜Next Action Protocol）を必ず出力する。Next Action の標準: A=/04-operation で次の実行可能 Task（⭐推奨） / B=/plc-brief で Goal 未達と成立済み成果を確認 / C=現在の成果に関係する補足・計画修正。全タスク終端: 元 Goal/SC と検証証拠を照合し、未達があれば必要な正式入口（Re-Inception / Re-Collection）、全達成なら依頼完了（親/兄弟の続きは実在・状態を照合）。

## 出力

Documents/（成果物） / Context Store・context.yaml（更新） / backlog.yaml（更新） / Production Skills（platform_builder時のみ）。

---
**作成日:** 2026-04-07 ｜ **更新日:** 2026-10-22 ｜ **バージョン:** 3.0（方式の判定を目録と判定関数へ（読み方は同じ）／軽量化: 10/1 版（v2.12）を土台に、DevStyle binding・AIPM 併用の開発呼出し・本人専用情報・命名節目の本文を外し、発動条件3つと1行参照、ゲート2点＋回数上限、再開・中断の要点、requirement-review の要点を残す。以前の版履歴は git）
