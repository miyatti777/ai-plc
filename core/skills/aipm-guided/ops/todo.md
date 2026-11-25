# pm-todo｜ToDo の操作（AIPM）

AIPM の箱の中の「案件のやること」（todo.yaml。sheets_v1 は `Sheets/` の直下、それより前の形は `registers/` の中）の1件を扱う操作の型です。AI-PLC の Stage（Collection〜Operation）は箱づくりを含めた外側の命令で、pm-todo はその箱の中の ToDo に効きます。論点は pm-issue、仮説は pm-hypothesis。

**依頼文の例**：「論点 I2 のためにやることを足して」「D3 を終わりにして」「D4 を WBS の W1.2 につないで」「遅れている ToDo を見せて」

## 使える Layer（最初に確かめる）

`python3 .claude/skills/aipm-guided/package.py op --layer <Layer> --name check` を呼ぶ。`unselected`（AIPM を選んでいない・一覧を選んでいない）か `pass: false`（選択が Hold）なら、何も書かずに理由を伝えて止まる。途中から AIPM にするなら pm-init。

**保存済みの箱:** 版を持てる保存済みの箱（archive 済みの sheets_v1・box_root_v1。版の無い箱も含む。共有 Stock〔registry_stock_v1〕の箱は除き、今までどおり書ける）では add・link は `held` で止まる。ToDo を足すとき・既存の ToDo に note を足すときは、SKILL.md の「保存した箱の一覧の追記（redit）」の流れ（`package.py redit` → `redit-list` → 本人の返事を `redit-judge` → `redit-apply`）で入れる。**既存の ToDo に WBS をつなぐ（link）は、wbs_id が空なら redit の fill（`{op: fill, register: todo, row: D3, field: wbs_id, value: W1}`）で付ける。** 付いている wbs_id の直しと source の付け直しは、今は redit でもできない（必要なら本人に確かめる）。期限・owner・priority が未定の ToDo も fill で埋められる。move（状態を変える）は保存済みの箱でも今までどおり。版が無い箱は先に `package.py register`。保存済みの nested_v1 の箱は止まらず、書いた結果に「先に migrate-sheets で sheets_v1 へ」の案内が付く。

## 動き

| 動き | 何をするか | 書くか |
| --- | --- | --- |
| overdue | 期限を過ぎて終わっていない ToDo と、WBS の番号なしの ToDo を一覧にする（基準日は今日。`today` で変えられる） | 書かない |
| add | ToDo を1行足す。source は由来（論点 I・仮説 H・会議名）、wbs_id は出典で確かめたときだけ | 確定の後 |
| move | 状態を変える（todo・doing・done・cancelled） | 確定の後 |
| link | wbs_id か source を付ける・直す | 確定の後 |

## 進め方

1. 依頼から動きを決め、書く中身の案を会話で見せる。分からない owner は `[unknown]`（入力に無ければそうなる）。期限・優先度・担当を推測で埋めない
2. 本人が確定したら、入力の YAML を Layer の中（例 `Context/pm_ops/todo_<日付>.yaml`）に置き、まず `package.py op --name todo.<動き> --layer <Layer> --input <YAML>` で**試す**（書かない。書いた後の検査で新しく出る問題を返す）
3. 問題が無ければ同じコマンドに `--apply` を付けて書く。新しい問題（存在しない wbs_id など）が出たら書かずに理由を返す

## 守ること

- AI-PLC の backlog・Task の状態は変えない。AI が成果物を作る仕事なら、ToDo ではなく Re-Inception で AI-PLC の Task にする
- WBS の受入（accepted）は人。pm-todo は WBS を書き換えない
- 人の名前・評価・連絡先などは書かない（owner は役割・所属）。鍵・トークン・パスワード・口座番号も書かない
