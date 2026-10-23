# pm-todo｜ToDo の操作（AIPM）

AIPM の箱の中の「案件のやること」（registers/todo.yaml）の1件を扱う操作の型です。AI-PLC の Stage（Collection〜Operation）は箱づくりを含めた外側の命令で、pm-todo はその箱の中の ToDo に効きます。論点は pm-issue、仮説は pm-hypothesis。

**依頼文の例**：「論点 I2 のためにやることを足して」「D3 を終わりにして」「D4 を WBS の W1.2 につないで」「遅れている ToDo を見せて」

## 使える Layer（最初に確かめる）

`python3 .claude/skills/aipm-guided/package.py op --layer <Layer> --name check` を呼ぶ。`unselected`（AIPM を選んでいない・一覧を選んでいない）か `pass: false`（選択が Hold）なら、何も書かずに理由を伝えて止まる。途中から AIPM にするなら pm-init。

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
- 人の名前・評価・連絡先などは書かない（owner は役割・所属）
