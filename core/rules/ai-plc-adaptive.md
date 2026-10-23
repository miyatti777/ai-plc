> 🏷️ **Project:** \[YOUR_PROJECT\]
> **Type:** rule
> **Context:** AI-PLC Adaptive Workflow ルール。ワークフロー深度判定・モード判定・Next Action自動提案・Backtrack（方向適応）を定義。

## 0. 使い分け（Layer を作るか・どの守りが要るか）

方針は「記録は広く、手順は絞る」。仕事ごとに、記録（Layer＝intent・backlog・Documents・Registry）が要るかと、どの守りが要るかを分けて決める。①は②〜⑤のどれにも当たらないときだけ。記録は、当たる行に「作る」が1つでもあれば作る。守りは、当たる行の守りをすべて行う。深度の目安は、当たる行の中で重い方。記録と守りは、深度に関係なくこの表のとおり行う（§1 が正になるのは深度だけ）。表の守りは既定の手順（04-operation Phase 5.5 の独立検証など）に上乗せするもので、既定の手順を省く根拠にはしない。

| 仕事 | 記録 | 守り | 深度の目安 |
| --- | --- | --- | --- |
| ① その場限り・汎用・自分用 | 作らない（AI-PLC を使わずに頼む） | — | — |
| ② 後で読み返しそう・学びになりそう・会話やエージェント（CC／Codex）をまたぐ | 作る | 完了の条件を ○/× で確かめる | simple |
| ③ 固有の文脈が要る（このリポジトリや組織の資料を読まないと書けない） | 作る | Collection で資料を集めて渡す | simple（④に当たらなければ） |
| ④ 人に渡す判断材料で、読んで判断するしかない | 作る | タスクごとの独立レビュー（04-operation Phase 5.5） | standard（complex の条件は §1 のまま） |
| ⑤ AI 自身が取り返しにくい操作をする（公開・送信・本体のルールやスキル・外部 DB・削除・お金） | 作る | その操作の前に人の承認（この列挙と、RUL_plc_session §10 の「保留する」の範囲の広い方。自動完走中は §10 の書き込み範囲を優先し、backlog の output に書かれた Layer 外のパスは実行して完了報告で確認してもらう） | ②〜④で決める（⑤だけなら simple） |

- 深度の判定（§1）は、この表の目安と食い違うときは §1 を正とし、食い違いを `workflow_depth_reason` に1行書く
- 実運用で、表のとおりにして誤りやり直しが出たら見直す

## 1. Adaptive Workflow深度判定（全PJ共通）

Stage 1（Collection）で自動判定し、intent.yamlに記録する。コーディングに限らず全タスクに適用。検証レベル（RUL_plc_system §18）と連動する。

| 深度 | 判定条件 | パイプライン挙動 | 検証 |
| --- | --- | --- | --- |
| **simple** | 単一タスク・明確なゴール・既知パターン・1-2日以内 | Stage 1→4直行（Stage 2 は省く。Stage 3 は §6 の条件に当たるときだけ） | L1のみ |
| **standard** | 複数タスク・タスク分解が必要・SubLayerなし | Stage 1→2→4（Stage 3 は §6 の条件に当たるときだけ） | L1+L2 |
| **complex** | 再帰的分解・SubLayer生成・チーム連携 | 全4ステージ + SubLayer再帰 + NFR | L1+L2+L3 |

- workflow_depthは必ず `simple` / `standard` / `complex` の3値（非スキーマ値禁止）
- 判定結果はユーザーに報告する（変更指示があれば従う）
- Simple深度でStage 2をスキップする場合、backlog.yamlのrefactoring_logに理由を記録する（Stage 3 の要否は backlog の construction に書く — §6）
- ロール別の詳細判定基準は templates/roles/TPL_role_* に定義
- 同梱の PM アドオン（旧い欄 `work_style: aipm` も同じ）と明示 DevStyle を併用する新規 Layer は最低 standard（AIPM 上流と開発 Task の依存分解が要るため）。詳細は `.claude/skills/ai-plc/extensions/contract.yaml` と `.claude/skills/ai-plc/references/addon-seam.md`

## 2. モード判定

| モード | 条件 | 挙動 |
| --- | --- | --- |
| **direct** | 一度きりの実行（設計・分析・調査等） | Stage 1-4で完了 |
| **platform_builder** | 繰り返し実行する仕組みの構築 | Stage 1-4 + Production Skill生成→量産（04-operation/platform-builder.md参照） |

## 3. Next Action自動提案

各スキル完了時に次アクションを判定し、RUL_plc_session §7.4の形式で提案する。Stage/Task の完了は現在工程の完了であって Goal の完了ではない。

| 現在の状態 | Next Action |
| --- | --- |
| Stage 1完了 | Stage 2（Inception） |
| Stage 2完了 | backlog の construction.required が true → Stage 3（Construction）／false → Stage 4（Operation）P0タスクから（§6） |
| Stage 3完了 | Stage 4（Operation）P0タスクから |
| Stage 4タスク完了（残あり） | 次の実行可能タスク |
| Stage 4全完了（direct） | パイプライン完了（BT-C判定 → GAP分析提案） |
| Stage 4全完了（platform_builder) | Production Skill生成→量産へ |
| 既存Layer再指定 | 継続は既存Intent/Backlog/成果/未達から現在工程を再開。明示Re-Collection時だけUpdate mode（scope_reinit） |

## 4. Focus Strategy（視点選択）

Stage 1でGoalの性質から自動判定し、templates/roles/ から読み込む。

| Goal性質 | 推奨Role | キーワード |
| --- | --- | --- |
| プロダクト開発 | ROL_plc_product_manager | 機能、UX、ユーザー |
| システム構築 | ROL_plc_system_architect | DB、API、設計 |
| コーディング | ROL_plc_tech_lead / developer | 実装、修正、リファクタ |
| コンテンツ制作 | ROL_plc_content_strategist | 記事、ブログ |
| その他 | ROL_plc_generic | 上記以外 |

## 5. Adaptive Direction — Backtrack（3トリガー）

パイプライン進行中に前ステージへの戻りを検知・提案する仕組み。トリガーは3種に統合（旧BT-1〜10の対応を併記）。

| ID | トリガー | 検知タイミング | 検知条件 | 提案 → 戻り先 | 旧ID |
| --- | --- | --- | --- | --- | --- |
| **BT-A** | ブロッカー | Phase 5.5b（タスク単位） | 検証でcritical NG / 外部依存未解決 / 設計前提との矛盾 / 検証カバレッジ不足 | Re-Inception（修正・検証・依存タスクの差分追加）→ Stage 2 | 1,2,5,6 |
| **BT-B** | 節目再評価 | Phase 6b（パイプライン単位） | 完了率50%到達 / ゴールドリフト兆候（完了5超 or ad-hoc 2件以上） / Conditional Go残 | Re-Inception（残タスク再評価） or Re-Collection（ゴール再確認）→ Stage 2 or 1 | 3,4,8 |
| **BT-C** | 全完了GAP分析 | Phase 6b | backlog全タスクcompleted（運用タスクを除く） | Re-Collection(GAP分析 → 完了宣言 or 追加ゴール）→ Stage 1 | 7 |

運用タスク（recurrence のある Task。02-inception）は、BT-B の完了率と BT-C の全完了の判定に数えない。Layer を閉じるときに retired_at・retired_reason を付ける（status の値は増やさない）。

**長期化の節目:** 重い工程（RUL_plc_session §7.6）の見直し点は、タスク完了数に達する前・同一タスクの途中にも確認する。証拠停滞・残経路の成立根拠不足・方式拡大は BT-A/B へ接続し、時間予算到達は §10 の停止とする。短い既知作業に新しいレビューや質問を足さない。

会話中の監視（旧BT-9/10）: ユーザーの進捗訂正や「〜が足りない」等の新事実が出たら、軽量Re-Inception / Re-Collectionを**1行ヒントで提案のみ**行う（ユーザーが「このまま続行」を選んだら同一トピックで再提案しない）。ユーザーからアイデアを持ち込んで「どう思うか・どのコマンドか」を聞きたいときは `/plc-consult`（判定のみ・読み取り専用）。スキルを通さずに Layer の成果物を作った・直した作業が会話中にあれば `/plc-backfill` での記録を1行で提案する（提案のみ・見送られたら再提案しない）。

**実行ルール:**
1. Backtrackは必ずユーザー承認後に実行（自動実行禁止。自動完走中（RUL_plc_session §10）も同じで、Backtrack が要る判定なら自動完走を停止する）
2. Next Action Protocolの追加選択肢（D: Re-Inception / E: Re-Collection）として提示。該当なしの場合は出力しない
3. 戻り先Stageは scope_reinit モードで実行（既存成果物を保持）
4. 理由をbacklog.yamlのrefactoring_logに記録する
5. **独立checkerによる判定（maker≠checker — BT-B/BT-C既定 / BT-A任意）:** ドリフト検知と GAP 分析は maker 自身が最も盲目な判断のため、作成文脈から独立した checker（04-operation Phase 5.5 と同じ手段）に通す。checker には**元intent.yamlのgoal+success_criteria+実際の成果物リスト**を渡し、出力は P0-P3 or「No findings」。得られなければ maker 自己判定にフォールバックし1行記録する
6. **Jev監視（補助・opt-in）:** intent.yamlで `jev_monitor: true` のLayerだけ、04-operation Phase 5.5b / 6b で `scripts/jev_bt_monitor.py` を呼び、判断専用モデルJevに「異常ありか」の1問を聞く。出力は**1行ヒントのみ**で止める権限を持たず、Backtrackの判断と提案はメインモデルが行う。Jevが使えない・送信禁止に当たる場合はスキップ。判定ごとにユーザーの確認を `--override <decision_id> accept|reject` で記録する（回収は `/plc-jev-monitor`）。スクリプトと `/plc-jev-monitor` は Jev 実験版パッケージ（`--with-jev`）に入っている。無ければスキップ。**実験版 ai-plc-jev は凍結中:** `/0N-*-jev` と会話監視 hook は新しく使わず、ファイルは消さない。新しい Layer に `pipeline_variant: jev` を書かず、既存 Layer の `pipeline_variant: jev` は書き換えずに本体版とみなして読む。Jev 監視をするかは `jev_monitor` だけで決まる。API キーの設定は `scripts/README_jev.md`

## 6. Stage 3 の要否（Construction を作る条件）

Stage 3（Agent 定義の生成）は既定では通さない。backlog を作る者が backlog の `construction` に要否を書き、次のどれかに当たるときだけ通す: ①workflow_depth が complex ②mode が platform_builder ③intent.yaml の `construction_mode: always`（慎重モード・opt-in・Context Cascade は local_only）④`delegable: true` のタスクがある ⑤type が implementation / coding で手順が5つを超えるタスクがある。①〜③は全タスク、④⑤は当たるタスクだけ Agent 定義を作る。通さないとき、Operation は backlog の description・acceptance_criteria・guardrails・decisions と Context から実行する（04-operation Phase 4）。

- 判定は backlog を作る者（standard 以上は Inception、simple は Collection）が行い、結果を backlog のトップレベル `construction`（required・reason・tasks）に書く。`required` は `tasks` が空でないときだけ true（食い違ったら tasks を正とする）。`tasks` には command のあるタスクだけを書く。03-construction の生成対象と 04-operation の除外は `tasks` だけを見る
- `delegable: true` は途中で人の確認が要らない（Autonomous-only）タスクにだけ付ける
- **みなし規定:** `construction` 欄の無い既存 backlog は required: false・tasks 空とみなす（Agents/ に定義のあるタスクは Operation がそれに従い、無いタスクも止めずに backlog から実行する＝進行中の Layer を途中で止めない）。欄は次の Re-Inception で書く
- Re-Inception でタスクを足したときも判定し直す
- simple は従来どおり Stage 1→4 直行で、①〜⑤の判定は standard と同じ
- 運用の実測から決めた（根拠: 5 Layer・Agent 定義30本が Operation 中にほぼ読まれていなかった）

---
**作成日:** 2026-04-07 ｜ **更新日:** 2026-10-14 ｜ **ステータス:** Active
**バージョン:** 3.0（軽量化: 10/1 版（v2.9）を土台に、§5 ルール6 の Jev 凍結を事実だけに、AIPM＋DevStyle の限定条件を §1 の1行と extensions/contract.yaml・references/addon-seam.md へ。以前の版履歴は git）
