---
name: plc-backfill
description: AI-PLCのスキル（/04-operation 等）を通さずに済ませた作業を、あとから対象 Layer に記録する。どの Layer の作業かを決め、会話にしか無い中間生成物を Documents/ に書き起こし、backlog に ad-hoc タスクとして足し、04-operation の Phase 5.5〜7（検証・ステータス更新・Propagation）を通す。書き込み前に必ず承認を取る。「Propagationして」「さっきの作業を記録して」「Layerに残して」「backlogに後追いで入れて」で使う。
---

# plc-backfill（スキル外作業の事後記録）

> 論理名: SKL_plc_backfill ／ 包むもの: 04-operation の Phase 5.5〜7（参照で呼ぶ・書き写さない）

## 何をするスキルか

- 急いでいるときなどに、スキルを通さず頼んで**済んだ**作業を、あとから Layer の記録に載せる
- ①対象 Layer を決める ②会話にしか無い中間生成物を書き起こす ③backlog に ad-hoc タスクを足す（検証を通ったら completed） ④04-operation の Phase 5.5〜7 を通す
- **書き込みの前に必ず承認を取る**（何をどこに書くかを見せてから）
- 記録するのは済んだ作業だけ。作業のやり直し・続きの実装はしない

## 使い方

| 呼び方 | 動作 |
| --- | --- |
| `/plc-backfill` | この会話でスキルを通さずに行った作業を棚卸しし、対象 Layer を推定して記録案を出す |
| `/plc-backfill <Layerパス or L-ID> [作業のメモ]` | 指定した Layer に記録する（先頭の語が `Flow/` で始まるパスか `L-` で始まる ID のときだけ Layer 指定とみなす） |
| 自然文（「Propagationして」「さっきの作業を記録して」など） | 同じ手順 |

## 実行手順

リポジトリのルートで実行する。手順 1〜3 は読むだけで、書き込むのは手順 4 の承認の後。

### 1. 作業を棚卸しする

会話を振り返り、スキルを通さずに行った作業を書き出す。

- **1タスク=1つの目的。** 成果物か目的が違えば別タスクにする
- 各作業に「名前・何をしたか・成果物・判断したこと」を付ける。成果物は2つに分ける
  - **既にファイルがある**（コード・文書・画像など）→ パスを output に書くだけ（複製しない）
  - **会話にしか無い**（調査結果・比較・判断・方針）→ 手順 5 で書き起こす
- **一部だけ済んだ作業**は済んだ部分だけを記録する。残りの扱い（修正・Re-Inception・いつかやる）は `/plc-consult` に回すよう1行添える
- **未完了の作業**は記録しない（同じく `/plc-consult` へ）

### 2. 対象 Layer を決める（上から順に）

1. 引数の Layer パスか scope_id。scope_id は次でパスに直す（2件以上なら候補を並べて1問だけ聞く。0件なら ID を確かめてもらう）
   ```bash
   grep -rlE '^scope_id: "?<ID>"?[[:space:]]*(#.*)?$' Flow --include=intent.yaml --exclude-dir=Documents
   ```
2. 会話から推定する: この会話で直前に `/0N-*` を実行した Layer か、作業で触ったファイルが入っている Layer（`Flow/…/<Layer>/` 配下、または Layer の backlog の output に書かれたパス）。**推定は手順 4 の承認ブロックで「推定」と明示して見せ、承認で確定する**
3. どちらも無ければ `python3 .claude/db/plc_query.py active` から候補を最大3件示し、1問だけ聞く（結果にパス列は無いので、選ばれたら 1 の grep でパスを引く）

作業ごとに対象 Layer が違ってよい（Layer ごとに手順 3〜6 を回す）。

**当てはまる Layer が無いとき**は何も書き込まず、次の行き先とコピペ用プロンプトを返して止まる。

| 作業の中身 | 行き先 |
| --- | --- |
| 続きがあり、複数タスク・複数日になる | `/01-collection` で新しい Layer を作り、そのあと `/plc-backfill <新Layer>` で済んだ分を記録 |
| それ以外（済んだ小さな作業・将来やりたいこと・続きの小さなタスク） | コマンドは出さない。「メモに残す」（Layer の外の ToDo・日報・メモに1行で書き留める）と書き、書き留める1行の文案を示す |

### 3. Layer を読み、足し方を決める

- `intent.yaml`: status・workflow_depth・sync_targets（手順 4 の「外部 push」）。SubLayer の作業ならその SubLayer の intent.yaml
- `backlog.yaml`: 各タスクの id・name・status・output（件数を絞る — RUL_plc_system §17）
- **既存タスクの作業だった場合** → タスクは足さず、そのタスクを手順 6 に通す（origin は変えない）。当たるのは ①pending / in_progress のタスクの中身を済ませた ②completed だが Phase 7 のチェックリスト出力・Registry 反映が済んでいない（04-operation の途中で Phase 7 だけ忘れた）。②は手順 6 で済んでいない Phase から通す
- それ以外は新しいタスクとして足す。フィールドは次のとおり

| フィールド | 値 |
| --- | --- |
| id | その backlog の ID の形式（接頭辞・区切り・桁数。例 T001 / T-01）に合わせ、同じ形式の最大番号 +1。形式が混在していれば承認ブロックで確認する |
| name / description | 手順 1 の名前と「何をしたか」 |
| type / priority | type は作業の中身から（implementation / content / design / research …）。priority は対象 Layer の同じ type のタスクに合わせ、無ければ P2 |
| status | in_progress（手順 6 の Phase 6 で completed にする。検証の前に completed と書かない） |
| owner | AI（ユーザー自身がやった作業なら user） |
| estimated_hours | 見積もりの欄だが、事後記録では実際にかかったおおよその時間を流用する（不明なら null） |
| dependencies | [] |
| command | `/plc-backfill` |
| command_template_ref | null |
| origin | `"ad-hoc YYYY-MM-DD（<理由>・plc-backfill で事後登録）"` — 必ず `ad-hoc` を含める（04-operation Phase 6b の BT-B「ad-hoc 2件以上」で、後から足したタスクと数えるための印） |
| output | 既存ファイルのパスと書き起こしのパス（カンマ区切り） |
| completed_at | 作業した日 |

### 4. 承認を取る（ここで止まる）

何も書かずに、次の承認ブロックを出して返事を待つ（RUL_plc_session §9）。

```
---
🙋 **記録してよいか承認してください**

→ **OK** — 下の内容を書き込み、04-operation の Phase 5.5〜7 を通します
→ **修正: [指示]** — 対象 Layer・タスクの分け方・書き起こしを直して出し直します
→ **差し戻し** — 何も書かずに終わります
---

📍 対象 Layer: <パス>（<scope_id>）［推定］

| 操作 | ID | name | type | output | origin |
| --- | --- | --- | --- | --- | --- |
| 追加 | <ID> | … | … | … | ad-hoc YYYY-MM-DD（…・plc-backfill で事後登録） |
| 既存を通す | <ID> | … | … | … | （変えない） |

書き起こす: Documents/<ID>_<slug>.md — 見出し: …
このあと: Phase 5.5 検証 → Phase 6 ステータス更新 → Phase 7 Propagation（Registry への追加は Phase 7 の External Sync で行う）
外部 push: なし ／ あり: <sync_targets の sqlite 以外の type>
ID の形式: <採った形式>（backlog 内で混在しているときだけ書く）
```

### 5. 書き込む（承認の後）

1. **書き起こし**（会話にしか無い成果物があるときだけ）: `Documents/<タスクID>_<slug>.md` に置く。フロントマターコールアウト（RUL_plc_system §14）の直後に次の1行を必ず置く。中身は会話で出た結論・根拠・判断に限り、会話に無いことを足さない
   ```
   > 📝 事後に書き起こしたもの（元: 会話 YYYY-MM-DD・/plc-backfill）。作業時に作った原本ではない
   ```
2. **backlog.yaml**: 手順 3 の表のとおりタスクを足す。`refactoring_log` に `plc-backfill: <ID> を事後登録（<理由>）` を1行足す。summary の件数も合わせる

### 6. 04-operation の Phase 5.5〜7 を通す

`.claude/skills/ai-plc/04-operation/SKILL.md` の **Phase 5.5 → 5.5b → 6 → 6b → 7** をその定義のまま実行する（ここに書き写さない）。事後記録で押さえる点だけを挙げる。

- **Phase 5.5 の強さ**は、対象 Layer の workflow_depth と成果物で 04-operation の「発動強度」を上から順に判定する。standard 以上の Layer では少なくとも「既定」（complex の L3・受け手に渡る最終成果物なら「必須」）で reviewer を起動する。simple の Layer は定義どおり「省略可」（セルフ L1）
- **L1 に1項目足す**（強さにかかわらず必ず行う）: 書き起こしが会話の内容と食い違っていないか
- **検証で P0〜P2 が出たとき**: 直してよいのは書き起こしと backlog の記入欄だけ。既にある成果物（コード等）の欠陥は作業のやり直しになるので直さず、そのタスクは completed で記録しない。足した行は description・output を済んだ部分に絞り直し、済んだ部分が無ければ status を cancelled にする（物理削除しない — 02-inception の Re-Inception と同じ）。どちらも refactoring_log に1行残す。04-operation の完了ゲート（P0〜P2 は Phase 4 に戻って修正）は、事後記録ではこう読み替える: 絞った後の行に P0〜P2 が0件であることを確かめ、Phase 5.5b（BT-A 判定）を経て Phase 6 へ進む。欠陥の扱いは `/plc-consult` に回す
- **Phase 6b**: 足した ad-hoc タスクは BT-B「ad-hoc 2件以上」に数えられる（Layer が全完了のときは数えられず、BT-C だけが再成立する — 下の completed の項）。スキル外作業が続いた合図なので、出たら 04-operation の定義どおり Backtrack の提案に乗せる。件数を増やす目的でタスクを細かく分けない（1目的=1タスク）
- **Layer 自体が completed のとき**: 足したタスクは Phase 6 で completed（または cancelled）になるので、Layer と Registry は completed のままにする（active に戻さない）。Phase 7 のステータス点検（`--layer` には L-ID ではなく Layer のパスを渡す。点検ツールが無い環境では intent・backlog を目視）で食い違いが無いことを確かめる。Phase 6b で BT-C（全完了→GAP分析）がもう一度成立するが、完了宣言は済んでいるので GAP分析は実行せず「記録した作業で goal の達成状況が変わるなら /plc-consult で相談」と1行の提案に留める
- **Phase 7 の External Sync**: 定義どおり intent.yaml の sync_targets に従う（sqlite: 足したタスクは `plc_query.py add-task` で追加してから状態を UPDATE。既存を通すタスクは Registry に行があれば UPDATE だけ、無ければ add-task。Layer の project 自体が Registry に無く add-task が止まるときは、要点を1行出して RUL_plc_system §8 の Registry 項目に従う）。sqlite 以外（notion_db 等）への push は、手順 4 の承認ブロックで「外部 push あり」と示して承認を得たときだけ行う

## 出力の形

- 手順 4: 承認ブロック（上のテンプレ）で止まる
- 手順 6 の後: 04-operation の「タスク完了時の出力」（RUL_plc_session §7 の4パート）。完了サマリの「完了対象」は `plc-backfill: <ID>〜` と書く

## 注意

- **書き込みは承認の後だけ。** 承認前に Documents・backlog・context・Registry を書かない
- **記録だけ。** 作業のやり直し・続きの実装・04-operation の Phase 1〜5（タスク選択・実行）・git commit / push はしない。外部への push は承認ブロックで示したものだけ
- 手順は増やさない: 検証・ステータス更新・Propagation は 04-operation、対象 Layer の決め方は plc-consult と同じ形（ただし推定を許し、承認ブロックで確定する）、振り分け先は各 Stage の定義を使う
- AI から「記録しますか」と持ちかける入口は RUL_plc_adaptive §5 の会話中監視（1行の提案のみ）。こちらはユーザーから頼む入口
