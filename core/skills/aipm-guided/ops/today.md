# pm-today｜今日何から（AIPM）

AIPM の箱の中（論点・仮説・ToDo・WBS）から、今日動かす1件を選ぶ操作の型です。AI-PLC の Stage は箱づくりを含めた外側の命令で、pm-today はその箱の中を見て選びます。Task の単位で次を選ぶのは /plc-next。

**依頼文の例**：「今日何から手を付ける？」「基準日 〇/〇 で今日の1件を出して」

## 使える Layer（最初に確かめる）

`python3 .claude/skills/aipm-guided/package.py op --layer <Layer> --name check` を呼ぶ。`unselected`（AIPM を選んでいない・一覧を選んでいない）か `pass: false`（選択が Hold）なら、何も書かずに理由を伝えて止まる。途中から AIPM にするなら pm-init。

## 動き

| 動き | 何をするか | 書くか |
| --- | --- | --- |
| pick | 次の順で候補を並べ、最初の1件と理由・ほかの候補を返す：①期限を過ぎた ToDo ②7日以内が期限の論点 ③受入の候補（WBS の pending_acceptance。受け入れるのは人）④優先度の高い（critical・high）未確定の仮説 ⑤進行中の ToDo。基準日は今日（`today` で変えられる） | 書かない |

## 進め方

1. `package.py op --name today.pick --layer <Layer>` を呼ぶ
2. 1件と理由、ほかの候補を見せる。どれをやるかは本人が選ぶ
3. 選んだ1件を進めるのは、Stage（/04-operation の Task）か、その1件の pm-（論点なら pm-issue、ToDo なら pm-todo）

## 守ること

- pm-today は何も書かない。AI-PLC の backlog・Task の状態も変えない
