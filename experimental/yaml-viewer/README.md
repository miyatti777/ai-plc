# experimental/yaml-viewer — YamlViewer（AI-PLC の YAML を読みやすく見る・アルファ版 0.1.0-alpha）

AI-PLC が出す YAML を、エディタの生の文字列ではなく「表＋札」で読むためのローカル専用・閲覧専用のビューアです。何も書きません。127.0.0.1 の中だけで動き、外に送りません。

> ⚠️ **アルファ版です。** 画面・ファイル構成は予告なく変わります。UI は日本語だけです。

- **installer の対象外です。** `install.sh` では入りません。下の手順で、プロジェクトに手でコピーして使います

## 入れ方・外し方

```bash
cp -R experimental/yaml-viewer <プロジェクト>/tools/YamlViewer
```

- 置き場は `<プロジェクト>/tools/YamlViewer` にしてください（`server.py` は2つ上のフォルダをリポジトリのルートとして `Flow/` を探します）。外すときはこのフォルダを消すだけです
- Claude Code デスクトップの右ペインで使うなら、プロジェクトの `.claude/launch.json` の `configurations` に次を足します

```json
{"name": "yaml-viewer", "runtimeExecutable": "python3", "runtimeArgs": ["tools/YamlViewer/server.py", "--port", "8772", "--no-browser"], "port": 8772}
```

## 何が見えるか

| 対象 | 見え方 |
| --- | --- |
| AIPM の箱の registers 5ファイル（仮説 hypotheses・論点 issues・WBS wbs・節目 roadmap・ToDo todo） | ファイルごとのタブ。列を絞った表（ID・題名・状態・優先・期限・担当）。行を押すと右に全欄の札（長文は折り返し、配列は箇条書き、日程の入れ子はそのまま） |
| 相互参照（todo の WBS・wbs の節目や依存・roadmap の WBS・論点の答え／親・出典の中の ID） | リンク。押すとそのファイルのタブに移って該当行を選ぶ。リンクにするのは今その箱にある ID だけ |
| `[unknown]`・undecided・未記入 | 本文では薄い斜体、状態の札では点線の枠。本物の値の「未判定」「中止」は実線の枠（見分けがつく） |
| 状態・種類・優先 | 日本語の札（未判定／支持／反証、未解決／解決、下書き／受入待ち／受入、最重要／高 など。語彙は `.claude/skills/aipm-guided/registers_contract.yaml`） |
| Layer の intent・context・backlog（タブ「案件」「Context」「タスク」。箱のタブの右に仕切りで並ぶ） | 案件: Goal・成功条件・分類・業務所属・原要求。Context: 文書の名前と要約。タスク: ID・名前・状態・優先・依存・受入条件の数・実行時期・期限・成果物（行を押すと やること・受け入れ条件・結果）。進み具合の図は作らず、タスクの上の「BacklogLive で見る」で飛ぶ（8770。起動していないときは開けない） |

箱の形は両方読めます: 新しい形 `<Layer>/Sheets/`、古い形 `<Layer>/Documents/aipm_project/registers/`。置き場は画面上の「置き場」で選びます（`--path` で渡したものが先頭、その後にプロジェクトの Flow の新しい3か月分から見つけた箱のある Layer）。箱の無い Layer は Flow の走査では出ないので、見たいときは `--path <Layer>` で渡します（タブは案件・Context・タスクだけ）。

YAML が壊れている（保存の途中など）ときは、画面上部に赤い1行を出し、最後に正しく読めた状態を表示し続けます。保存すると数秒で表示が変わります（再読込は要りません）。

## 起動と停止

**Claude Code デスクトップ（右ペイン）:** `.claude/launch.json` の `yaml-viewer`（ポート 8772）をプレビューとして起動します。チャットで「yaml-viewer を右ペインに出して」と頼めば開きます。止めるときは「yaml-viewer を止めて」（ペインのタブを閉じてもサーバは止まりません）。

**ターミナル:**

```bash
python3 tools/YamlViewer/server.py
```

- `http://127.0.0.1:8772/` が開きます。Ctrl-C で止まります。常駐はしません
- Flow の外の箱を見る: `python3 tools/YamlViewer/server.py --path <Layer のフォルダ>`（`--path` は複数可。箱・Layer・registers フォルダのどれを渡してもよい）
- Flow を走査しない: `--no-flow`（`--path` だけ）。別のポート: `--port 0`（空いている番号）
- 画面の位置は URL の `#i=<置き場の番号>&tab=<ファイル>&id=<行の ID>` に残るので、ブックマークできます

## 一般の YAML（汎用モード）

箱でも Layer でもない YAML（設定ファイル・Documents の中のメモなど）を開くと、タブ「YAML」に Markdown 風で出ます: 最上位のキーが見出し、mapping は「キー: 値」の一覧、list は箇条書き、mapping の list は札（題名は title／name／id など最初の文字列。押すと開閉）、深い所は「N 件」「N 項目」で折りたたみ。ID のリンクや `[unknown]` の薄さは同じです。

- ブラウザ／ターミナル: `python3 tools/YamlViewer/server.py --path <ファイル.yaml>`（箱・Layer のファイルを渡すと、その箱・Layer として開きそのタブが選ばれる）
- 箱か Layer かの決め方: 開いたファイルが registers の5つ（hypotheses・issues・wbs・roadmap・todo）の1つで、隣に別の registers のファイルがある（または親が Layer の中の Sheets／registers）なら箱、intent・context・backlog の1つで隣に intent.yaml があれば Layer、それ以外（variables.yaml・Sheets/meta.yaml・Documents の中の YAML など）は汎用モード
- 大きい YAML: 札は 200 件ずつ「さらに表示」で出し、折りたたみの中身は開いたときに作る（8MB 超・要素 20 万超・深すぎるものは案内1行）。汎用モードでは絞り込みは使えない
- `---` で区切った複数のドキュメント（k8s の manifest など）は一覧（1, 2, …）として出す。数値・真偽値のキーは文字（`1`・`true`）で出す（YAML の決まりで `1:` と `true:` は同じキーに重なり、片方しか残らない）。キーが多い mapping・長い list も 200〜500 ずつ「さらに表示」。ファイルを保存し直すと表示は作り直され、開いていた札は閉じる

## 既存のビューアとの役割分担

| 道具 | 見るもの | かぶらない点 |
| --- | --- | --- |
| **YamlViewer（これ。ブラウザ／右ペイン）** | 箱の registers 5ファイル・Layer の intent/context/backlog を「読む」 | 書かない。図は作らない |
| BacklogLive（`experimental/backlog-live`。コピー先は `tools/BacklogLive/`、8770） | backlog.yaml の進み具合を図（流れ・いま）で見る | backlog の図はこちら。YamlViewer の「タスク」のタブからリンクで飛ぶ |
| Registry ビューア（`experimental/registry-viewer`、8765） | Registry DB の projects の一覧と詳細 | DB を見る道具。YAML のファイルは読まない |
| registers への追記 | `pm-issue`・`pm-todo`・`pm-hypothesis`、保存した箱は `package.py` の改訂の操作 | 書くのはこちら。YamlViewer は読むだけ |

## 作法（守っていること）

- 書き込みの口が無い（POST/PUT/PATCH/DELETE は 405）。listen は 127.0.0.1 だけ。Host が 127.0.0.1／localhost 以外なら 403
- 画面から任意のパスを受け取らない（サーバが見つけた、または `--path` で渡した一覧の番号だけ）。8MB を超えるファイルは読まない
- 外部ライブラリは PyYAML だけ（Python 3.9 以上。`python3 -c "import yaml"` が通ればよい）
- 画面の文字は textContent／createElement で組み立て、innerHTML は使わない

## 知っておく制約

- ID のリンクは「今の置き場にある ID」だけに付きます。文章の中の「別の案件の T003」のように別の案件の番号でも、今の Layer の backlog に同じ番号があれば今の Layer のタスクへ飛びます（別の案件へは飛びません）
- Flow の走査は新しい3か月分・箱のある Layer だけです。古い月や箱の無い Layer は `--path` で渡します
- 画面側（JS）の自動テストはありません（サーバ側の合成テストと、作成時のブラウザ確認のみ）

## テスト

```bash
python3 -m unittest discover -s experimental/yaml-viewer/tests   # AI-PLC のリポジトリで
python3 -m unittest discover -s tools/YamlViewer/tests           # コピーした先で
```

合成の箱を一時フォルダに作って、両方の形の検出・`--path`・壊れた YAML の保持・GET 以外の拒否・Host の検査を確かめます。本物の箱には触りません。
