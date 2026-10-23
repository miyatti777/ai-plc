# pm-capture｜会議の後の取込（AIPM）

会議・インタビュー・FB のメモから、AIPM の箱の中へ入れる候補（仮説の判定の案・論点・ToDo）を拾う操作の型です。AI-PLC の Stage は箱づくりを含めた外側の命令で、pm-capture はその箱の中に効きます。拾った候補を書くのは pm-hypothesis・pm-issue・pm-todo。

**依頼文の例**：「今日のインタビューのメモ（Context/…）から、仮説の判定と論点と ToDo を拾って」

## 使える Layer（最初に確かめる）

`python3 .claude/skills/aipm-guided/package.py op --layer <Layer> --name check` を呼ぶ。`unselected`（AIPM を選んでいない・一覧を選んでいない）か `pass: false`（選択が Hold）なら、何も書かずに理由を伝えて止まる。途中から AIPM にするなら pm-init。

## 動き

| 動き | 何をするか | 書くか |
| --- | --- | --- |
| context | メモ（Layer 内のパス。`notes`）と、今の open の論点・未確定の仮説・終わっていない ToDo、候補の入力の形を返す | 書かない |
| check | 候補の束（`judgements`・`issues`・`todo`）を1件ずつ試し、問題と仮の id を返す | 書かない |

## 進め方

1. `package.py op --name capture.context --layer <Layer> --input <YAML（notes: メモのパス）>` で材料を読む
2. メモに書かれたことだけから候補を作る：仮説ごとの判定の案（supported・not_supported・undetermined と理由）、新しい論点（答えの候補が2つ以上・答えで後の計画が変わる・手続きだけではない問い）、ToDo（由来の I・H・会議名）。発言者の名前・評価は書かない。分からない owner・期限は空のまま
3. 候補の束を Layer の中の YAML に置き、`--name capture.check` で試す。問題が出た候補は直すか外す
4. 候補を本人に見せ、確定したものだけを pm-hypothesis（propose）・pm-issue（add）・pm-todo（add）の `--apply` で書く。本人・判断者の判定（owner／decider）は、回答を受領記録にしてから `package.py judge`

## 守ること

- pm-capture 自身は何も書かない。AI-PLC の backlog・Task の状態も変えない
- メモに無いことを足さない（判定の理由はメモの該当箇所から）
