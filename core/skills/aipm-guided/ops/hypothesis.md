# pm-hypothesis｜仮説の操作（AIPM）

AIPM の箱の中の「仮説の一覧」（registers/hypotheses.yaml）の1件を扱う操作の型です。AI-PLC の Stage（Collection〜Operation）は箱づくりを含めた外側の命令で、pm-hypothesis はその箱の中の仮説に効きます。論点は pm-issue、やることは pm-todo。

**依頼文の例**：「この仮説を足して」「今日のインタビューで H2 はどうだったか、判定の案を書いて」「崩れた仮説で見直すものを出して」

## 使える Layer（最初に確かめる）

`python3 .claude/skills/aipm-guided/package.py op --layer <Layer> --name check` を呼ぶ。`unselected`（AIPM を選んでいない・一覧を選んでいない）か `pass: false`（選択が Hold）なら、何も書かずに理由を伝えて止まる。途中から AIPM にするなら pm-init。

## 動き

| 動き | 何をするか | 書くか |
| --- | --- | --- |
| impact | 崩れた仮説（status か最新の判定が not_supported。指定した id でもよい）から、見直す候補（論点・ToDo・その id を含む文書）を一覧にする。AI の判定の案だけに基づく行は分けて示す | 書かない |
| add | 仮説を1行足す。kind は誰の話かで選ぶ：相手の機会＝opportunity、相手の課題＝problem、こちらの打ち手＝solution、検証の仮説＝validation。status は unknown | 確定の後 |
| propose | 会議・インタビュー・FB の後に、仮説ごとの判定の**案**（judged_by=ai_proxy）を末尾に足す。status は変えない | 確定の後 |

本人・判断者の判定（owner／decider）は pm-hypothesis では書かない。本人の回答を `package.py receipt` で受領記録にし、`package.py judge` で足す（status もそこで決まる）。

## 進め方

1. 依頼から動きを決め、書く中身の案を会話で見せる（kind・claim、判定の案と理由）。人物の属性や実際の反応を推測で足さない
2. 本人が確定したら、入力の YAML を Layer の中（例 `Context/pm_ops/hypothesis_<日付>.yaml`）に置き、まず `package.py op --name hypothesis.<動き> --layer <Layer> --input <YAML>` で**試す**（書かない。書いた後の検査で新しく出る問題を返す）
3. 問題が無ければ同じコマンドに `--apply` を付けて書く。新しい問題が出たら書かずに理由を返す
4. impact の一覧で見直す文書が出たら、直すかは本人が決める（文書の改訂は pm-persona・pm-story）

## 守ること

- AI-PLC の backlog・Task の状態は変えない
- supported は人の判定があるときだけ（AI の案で status を変えない）
