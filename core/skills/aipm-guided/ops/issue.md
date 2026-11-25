# pm-issue｜論点の操作（AIPM）

AIPM の箱の中の「論点の表」（issues.yaml。sheets_v1 は `Sheets/` の直下、それより前の形は `registers/` の中）の1件を扱う操作の型です。AI-PLC の Stage（Collection〜Operation）は箱づくりを含めた外側の命令で、pm-issue はその箱の中の論点に効きます。仮説は pm-hypothesis、やることは pm-todo。

**依頼文の例**：「この問いを論点に足して」「I3 を2つに分けて」「I2 の答えの案を出して」「論点の全体像を見せて」

## 使える Layer（最初に確かめる）

`python3 .claude/skills/aipm-guided/package.py op --layer <Layer> --name check` を呼ぶ。`unselected`（AIPM を選んでいない・論点の表を選んでいない）か `pass: false`（選択が Hold）なら、何も書かずに理由を伝えて止まる。途中から AIPM にするなら pm-init。

**保存済みの箱:** 版を持てる保存済みの箱（archive 済みの sheets_v1・box_root_v1。版の無い箱も含む。共有 Stock〔registry_stock_v1〕の箱は除き、今までどおり書ける）では add・split・propose は `held` で止まる。論点を足すとき・分けるときは、SKILL.md の「保存した箱の一覧の追記（redit）」の流れ（`package.py redit` の add_row → `redit-list` → 本人の返事を `redit-judge` → `redit-apply`）で入れる。分けるときは row_data に `parent` を書く（owner・due が無ければ `[unknown]`・`undecided` になる。priority は確かめた値を書き、`[unknown]` のままだと保留になる）。期限・owner・priority が未定の論点は、本人が決めた後に redit の fill（`{op: fill, register: issues, row: I3, field: due, value: '2026-11-15'}`）で入れる。答えの案・検証の仮説の案（propose）は一覧に書かない：案は変更案の reason か、`redit-extract` の判定の下書き（judge_draft）の備考に残し、決めるのは本人の resolve・close。版が無い箱は先に `package.py register`。resolve・close は保存済みの箱でも今までどおり（本人の記録が要る）。保存済みの nested_v1 の箱は止まらず、書いた結果に「先に migrate-sheets で sheets_v1 へ」の案内が付く。

## 動き

| 動き | 何をするか | 書くか |
| --- | --- | --- |
| map | 論点の木（parent）・状態・解決の割合・期限を一覧にする | 書かない |
| add | 問いを1行足す。入れるのは3つを満たす問いだけ：①答えの候補が2つ以上 ②答えで後の計画が変わる ③手続きだけが残るものではない。満たさないものは pm-todo へ | 確定の後 |
| split | 論点を子の論点に分ける（parent を付ける） | 確定の後 |
| propose | 暫定の答え（answer）・検証の仮説（validation_plan）を案として書く。status は open のまま | 確定の後 |
| close | not_needed・cancelled・on_hold にする。本人の確定の記録（受領記録か決定の記録のパス）が要る | 確定の後 |
| resolve | resolved にする。answer・evidence_refs（人の判定のある H か、受領記録／決定の記録）・decided_by（owner か decider）が要る | 確定の後 |

## 進め方

1. 依頼から動きを決め、書く中身の案を会話で見せる（id・question・owner・due など）。分からない owner は `[unknown]`、due は `undecided` のまま。推測で埋めない
2. 本人が確定したら、入力の YAML を Layer の中（例 `Context/pm_ops/issue_<日付>.yaml`）に置き、まず `package.py op --name issue.<動き> --layer <Layer> --input <YAML>` で**試す**（書かない。書いた後の検査で新しく出る問題を返す）
3. 問題が無ければ同じコマンドに `--apply` を付けて書く。新しい問題が出たら書く前に戻り、理由を返す
4. resolve・close は AI が決めない。本人の回答の受領記録（`package.py receipt`。質問か答えにその論点の id を含める）か決定の記録（`kind: decision_record`・`issue_id`・`decided_by`・`decided_at`・`decision`・`scope_id`）が無ければ止まる。決定の記録は本人の発言から作り、AI が自分の判断で作らない。別の論点の記録は使い回せない
5. close・resolve は open・on_hold の論点だけ。解決済み・中止の論点を開き直す操作は無い（本人が手で直す）

## 守ること

- AI-PLC の backlog・Task の状態は変えない（論点に答える Task の issue_id は Stage が書く）
- 人の名前・評価・連絡先などは書かない（owner は役割・所属）。鍵・トークン・パスワード・口座番号も書かない
- 書くときはファイルを書き直すので、人が手で書いたコメントは残らない（package.py の judge・wbs-candidate と同じ）
