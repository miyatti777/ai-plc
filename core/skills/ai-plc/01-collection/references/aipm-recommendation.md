# CollectionでのAIPM方式の推薦

Goal/Context収集後に適合を判断し、既存のPhase7確認点へ推薦を統合する。モード名の事前指定を必須にしない。推薦の提示と本人による採用は別の状態として保存する。

AIPM方式は同梱の PM アドオン（目録 [addon-catalog.yaml](../../references/addon-catalog.yaml) の aipm）。本人が選んだときは intent の `addons` に同梱の1件（`addon_id: aipm`・`source: bundled`・目録の `addon_version`・`selection_ref` に受領の receipt）だけを書き、旧い欄 `work_style`・`work_style_source` は書かない（残っていれば外す）。旧い Layer の `work_style: aipm` は、判定関数 `.claude/skills/ai-plc/scripts/plc_addon_select.py` が同梱の aipm を選んだものとして読む（目録の `legacy_alias`）。

## 判断と保存

担当AIがGoalと実際に使ったContextを読み、次の3条件をそれぞれyes/no/unknown、理由、根拠参照で評価する。PdM・開発・マーケティング・PMという名称だけでyesにしない。

1. 利用者・課題・価値仮説を整理し、検証してから解決策へ進む必要がある。
2. [ローカル3コース契約](../../../aipm-guided/course_contracts.yaml)の単一利用者コースで扱える。探索型の初期化→ペルソナ→課題→検証→解決策→ストーリー→保存は維持する。
3. 段階的に19の指定形式文書を残す負担に見合う説明・修正・再利用の価値がある。

一つでもnoならnot_fit、noがなくunknownならunknown、全てyesならrecommend。対応外コースはnot_fit。not_fit/unknownは通常経路へ進み、推薦専用の追加必須質問を作らない。Goalの重要な不足は既存Collectionの確認規約に従う。

CLIは意味判断・本人真正性を保証するAIや認証機構ではない。担当AIが実発話を確認し、評価とreceiptを作る。合成fixture、引用、候補、AIの仮定をactual_userの根拠に変えない。

## 補助CLI

repo rootから次を使う。Layerは正規化した現在の明示root、入力ファイルはそのLayer内だけ。`--apply`がない場合は書き込まない。`status`は常に読取専用。`--apply`は既に許可された記録の実行指定で、追加の本人承認を意味しない。

```text
python3 .claude/skills/ai-plc/01-collection/recommendation.py assess --layer <Layer> --assessment Context/assessment.json --execution-mode normal --apply
python3 .claude/skills/ai-plc/01-collection/recommendation.py respond --layer <Layer> --receipt Context/reply.yaml --apply
python3 .claude/skills/ai-plc/01-collection/recommendation.py cancel --layer <Layer> --apply
python3 .claude/skills/ai-plc/01-collection/recommendation.py status --layer <Layer>
```

評価JSONの形（理由/根拠を実案件に合わせて記入する。下記は構文例であり判定済み事実ではない）:

```json
{
  "version": 1,
  "scope_id": "<現在のscope_id>",
  "conditions": {
    "discovery_needed": {"value": "unknown", "reason": "<必要性の理由>", "evidence_refs": []},
    "course_supported": {"value": "unknown", "reason": "<単一利用者コースへの適合理由>", "evidence_refs": []},
    "document_value": {"value": "unknown", "reason": "<19文書を残す価値の理由>", "evidence_refs": []}
  },
  "recommendation_reason": "<利用者に伝える理由>"
}
```

根拠参照は `{"path":"Context/<実資料>","sha256":"<そのbytesのSHA-256>"}`。Goalは正規化した `intent.goal` のhashで自動的に束縛する。Goalだけを判断根拠にした場合はrefsを空にできる。Contextを使った場合は実資料を必ず参照する。意味に影響したGoal以外のintent値は、引用した値を別のContext入力資料に保存して参照する。intent全体/context.yaml/backlog.yaml/推薦自身の状態はrefsに含めず、自己更新による循環を避ける。

runtimeの保存先は `Context/aipm_recommendation/` のimmutable snapshot・state（質問/history含む）・receipt・before/after journalと、本人の選択・解除時のintentのPMの欄（`addons` の同梱の1件。旧い欄 `work_style`/`work_style_source` は外すだけ）のみ。Project初期化、文書生成、Registry登録、他Layerへの書込は行わない。

## 一つの質問原文と実回答

通常モードで未選択かつrecommendなら、保存したquestionのtext/optionsをそのまま質問UIと通常会話へ使う。理由を後から書き換えない。

> {reason}のため、AIPM方式をおすすめします。現在対応する1人の利用者の課題からストーリーまで、19の指定形式文書を段階的に残して進めますか？

- AIPM方式で進める
- 通常方式で進める

範囲を聞かれたら、このモードが扱うのは立ち上げ（1人の利用者の課題からストーリーまで）で、運用の場面は扱わないと添える（[扱う範囲](../../../aipm-guided/SKILL.md#この-aipm-モードが扱う範囲)）。保存してある質問の原文は変えない。

`should_ask: true`の時だけ既存Phase7で新たに提示する。同版pendingの再開は保存原文を読み、重複UIを発行しない。UI消失時の文章再開も同原文・同対象を示す。提供中の質問tool/schemaだけを使い、accepted/resolved/default/待機時間経過を回答として保存しない。UIのquestion IDが取得できればホスト出典として記録し、CLIの安定した論理IDと対応を保存する。CLI receiptのquestion_idはstate.question.id、外部UI IDは追加のhost_question_idで元発話との対応を残す。

質問UIと通常会話の同文ミラーはsession §9.1に従う。上位規約がcommentaryでの質問を禁じる場合は同文をfinalへ置く。正当な待機手段がない場合はpendingと原文/対象/時刻を保存してターンを終了し、UI保持・通知・実回答は未確認とする。

実回答receipt YAML（以下の項目は実発話から記録し、例の値を本人証拠として使わない）:

```yaml
kind: user_reported
actor: actual_user
origin: actual_user_reply
scope_id: <現在scope>
source_thread_id: <実発話のthread出典>
received_at: <timezone付き実受領時刻>
question_id: <state.question.id>
target_path: <state.snapshot>
target_sha256: <state.snapshot_sha256>
answer: <本人の原文>
choice: aipm  # aipm / standard / pending
```

`AIPM方式で進める`など明確な原文のみaipm、`通常方式で進める`などのみstandard。単独のA/B、空回答、引用、曖昧な回答はpending。選択肢との対応が実発話から確実に分かっても、原文を書き換えて自動採用せず、必要なら既存質問の選択文で最小確認をする。scope/質問ID/immutable対象hash/現在Goal・入力版/受領時刻を照合し、旧版・他Layerの回答は拒否する。

## 既存選択・直接指示・auto/force

既選択または辞退済みなら再推薦せず、`assess --layer <Layer>`だけで状態を読む。未指定/nullは未選択。その他のwork_style値はエラーにして保持する。通常方式の辞退はContextに保存し、work_styleへstandardを書かない。取消も採用にせず同版は再質問しない。既存選択をGoal更新だけで自動解除しない。

本人が現Goalで直接AIPM/通常方式を選んだ場合、質問前の指示を先にContextのYAML/JSONへ原文・scope・source_thread_id・received_at・kind/actor/origin付きで保存する。その実発話ファイルを3条件のevidence_refsへ含め、現在版の`assess`を実行する。既選択/辞退でも新しい評価を明示的に渡せばsnapshotを更新するが質問は出さない。その後、同じ原文/出典/時刻のreceiptに `selection_source: actual_direct_selection`、`question_id: null`、`direct_source_path: <束縛した実発話ファイル>`を追加して`respond --direct --apply`を実行する。直接指示はsnapshot作成より前に届くため、時刻だけで未来の質問への回答と見なさず、保存出典との一致で照合する。現在の直接指示であることの判断は担当AIが実会話から行う。

明示の通常方式への解除はPMの選択を両方の欄（`addons` の同梱の1件と、旧い欄 `work_style`・`work_style_source`）から外し、既存AIPM文書を保持する。実選択の出典は Context の receipt に残す。自動解除や過去の指示の再利用は禁止。

auto/forceは現セッションの実行権限から指定し、保存ログだけから推測しない。未選択ならrecommendでもdeferredとして従来経路へ進み、自動採用/追加の必須UI待機を作らない。現本人の明示選択は直接指示の手順で扱える。Role・mode・深度・既存の権限は変えない。AIPM選択後は既存opt-inブロックから共通AIPM Skillを読み、既存の初期化/生成/検証順序で進める。

## 保存失敗と復旧

入力・対象ファイルのhashを全件preflightし、保存中も比較する。multi-file保存はbefore/after bytesとhashをprepared journalへ残し、全保存が済んで初めてcommittedになる。部分保存を成功と報告しない。中断したprepared journalがあれば次の保存を拒否する。

復旧はCLIの独立した第5操作を追加せず、同モジュールの `recover_layer(<canonical Layer>, apply=False)` で点検、許可されたローカル復旧として `apply=True` で実行する。全対象が記録before/afterに一致する時だけbeforeへ戻す。第三者変更や不正pathは全拒否し、原因を報告して既存手順へ戻る。これはruntime保存の復旧であり、共有実装5ファイルの復元は各実装Layerの直前backup/manifestを使う。


## 3コースの判定と選択

`aipm.course` は既存の選択軸で、別のtop-level modeは作らない。対応IDはquestion_based/single_persona、solution_based/single_persona、document_based/single_persona。推薦判定とpackage/schema/validator/Skillはcourse_contracts.yamlの同版を読む。根拠のない自動選択や既存course変更・文書移行は行わない。

明示済みのcourse/work_styleは聞き直さない。未選択なら、利用者の課題から探索する／solutionを仮説として逆算する／実読取した資料を対応付け不足だけ補完する、の入力に合う候補を説明する。未知・コース不適合・多人数は通常の本人判断へ戻す。方式の選択は実装や外部資料アクセスの許可ではない。

新コースの19文書は同じ形式を使い、batch/reuseの実時刻と根拠・未知・必要判断をmanifestへ残す。共通Skillのplan/draft/archive APIを参照し、単に選択状態を保存したことを成果や実Skill試行の成功にしない。
