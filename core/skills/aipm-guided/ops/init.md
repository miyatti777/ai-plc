# pm-init｜途中から AIPM にする入口（AIPM）

方式を選ばずに始めた Layer を、途中から AIPM にするときの入口です。今どこにいて、次に何を打てばよいかを返します。AIPM を選ぶ・箱を作る・19文書の Task を足すのは、今までどおり Stage（Collection・Inception）が行います。pm-init は何も書きません。

**依頼文の例**：「この Layer、途中から AIPM にしたい」「AIPM にするには次に何をすればいい？」

## 動き

| 動き | 何をするか | 書くか |
| --- | --- | --- |
| status | Layer の今の状態を判定し、次に打つコマンドを返す | 書かない |

`python3 .claude/skills/aipm-guided/package.py op --layer <Layer> --name init.status` を呼ぶ。返る状態と次の一手：

| 状態 | 意味 | 次の一手 |
| --- | --- | --- |
| held | 選択の食い違い（推薦の記録と intent が違うなど）・intent や backlog が読めない | 止まる。Re-Collection で直す（backlog が読めないときは直してから呼び直す） |
| other_addon | 方式の持ち込みのアドオン（AIPMO など）か、方式かどうかを宣言していない持ち込みのアドオンがある | 止まる。AIPM と方式を重ねないので、組み合わせを Re-Collection で確かめる（方式でないと宣言したもの〔exclusive_group: none〕は止めない） |
| unselected | 方式をまだ選んでいない | `/01-collection` の Re-Collection（Phase 4.5 の推薦と本人の選択 → Phase 7.5 の初期化） |
| question_pending | 推薦の質問に未回答 | 保存してある質問に本人が答える |
| stale_recommendation | 推薦の根拠が変わり、保存してある質問が古い | Re-Collection で推薦を出し直す |
| declined | 前に通常方式を選んだ | 考えを変えるなら Re-Collection |
| selected_not_initialized | AIPM は選んだが箱が無い | Re-Collection で Phase 7.5 の初期化へ |
| initialized_no_tasks | 箱はあるが19文書の Task が無い | `/02-inception` の Re-Inception で19文書の Task を足す。今までの成果（完了 Task の output のうち Layer の中にあるもの）を document_based の取り込み候補として返す |
| running | もう AIPM で動いている | pm-today・pm-issue などへ |

## 進め方

1. `init.status` を呼び、状態と次の一手を本人に見せる。返った次のコマンドは、本人が貼って実行する
2. 方式の選択は、本人の回答（受領記録）でだけ intent に書かれる。AI が代わりに選ばない
3. 今までの成果を19文書に取り込むときは document_based のコースを使う。persona・validation の本人の決定が要る（コースの決まり）。既存の Task・成果は書き換えない

## 守ること

- pm-init は何も書かない。intent・backlog・成果を変えない
- ほかの方式がある Layer では止まる（AIPM と重ねない）
