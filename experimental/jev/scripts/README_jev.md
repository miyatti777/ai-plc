# Jev監視（AI-PLC）— セットアップと使い方

AI-PLC の作業中に、判断専用モデル **Jev**（TypeSafe）で「Backtrack（前の段階に戻るべき兆し）がないか」を安く速く見張り、**1行のヒント**を出す仕組みです。ヒントには作業を止める権限はなく、最終判断はメインのモデルとあなたが行います。**APIキーを設定しなければ、すべて自動でスキップされ、AI-PLC は従来どおり動きます。**

> 🧪 これは AI-PLC の**実験版パッケージ（experimental/jev、版 1.8.0-exp.1）**の一部です。`install-cc.sh --with-jev`（または `install.sh cc --with-jev`）で入れたときだけ、スクリプトは `.claude/ai-plc-jev/scripts/`、スキルは `.claude/skills/ai-plc-jev/`、コマンドは `/01-collection-jev`〜`/04-operation-jev` に入ります。Jev 監視はすべて実験版のスキル・コマンドから呼ばれ、**公開 core の `/01-collection`〜`/04-operation` からは呼ばれません。**

## 何が入っているか

| ファイル | 役割 | 使う場所 |
| --- | --- | --- |
| `jev_client.py` | Jevへの共通クライアント（経路の選択・送信前の検査・本文を残さないログ）。`--check` で接続確認 | 全部 |
| `jev_bt_monitor.py` | Backtrackの異常ヒント（`/04-operation-jev` Phase 5.5b / 6b）と、判定の記録・集計 | 実験版 |
| `jev_regression_rank.py` | 規約を変えたとき、過去の成果物を「悪化が疑わしい順」に並べる（合否は出さない） | 手動 |
| `jev_prompt_hook.py` | 会話ごとの監視（Claude Code の UserPromptSubmit hook。settings への登録が必要） | 実験版 |
| `jev_coverage_check.py` | Inception の成功条件カバー判定（どのタスクにも対応しない成功条件を探す） | 実験版（`/02-inception-jev`） |
| `aiplc_status_audit.py` | Layer・Registry の食い違いの点検（`/04-operation-jev` Phase 7。手順は `README_status_audit.md`） | 実験版 |

必要なもの: Python 3.9 以上、`pyyaml`（`pip install pyyaml`）。ほかの依存はありません。

## 1. APIキーを用意する（どちらか一方でよい）

| 経路 | キーの取り方 | 環境変数 / キーチェーン名 | 送信先 | 向いている人 |
| --- | --- | --- | --- | --- |
| **公式（TypeSafe直）** | https://console.typesafe.ai でアカウントを作り、キーを発行 | `TYPESAFE_API_KEY` | TypeSafe の1社 | データの送信先を減らしたい人。データを保存しない契約（ZDR）などが必要な場合は公式の Enterprise プランを確認 |
| **OpenRouter 経由** | https://openrouter.ai でキーを発行（**キーごとのクレジット上限を $2〜5 に設定するのがおすすめ**） | `OPENROUTER_API_KEY` | OpenRouter と TypeSafe の2社 | すでに OpenRouter を使っている人、公式の受付が止まっているとき |

- 両方あるときは**公式が優先**されます。経路を固定したいときは `JEV_PROVIDER=typesafe` か `JEV_PROVIDER=openrouter` を設定します
- 注意: 2026-09 時点では公式コンソールの新規登録が止まっていたため、**作者の環境で実測したのは OpenRouter 経由だけ**です。公式経路のコード（エンドポイント `https://api.typesafe.ai/v1/systemone`、モデル `jev-1.13.0`）は公式ドキュメントに沿って実装していますが、接続は未確認です。つながらない場合は下の「上書きできる設定」で調整してください

## 2. キーを登録する（`.env` やリポジトリ内のファイルには書かない）

**macOS（おすすめ: キーチェーン）** — ファイルに平文が残らず、`jev_client.py` が自動で読みます。

```bash
security add-generic-password -a "$USER" -s OPENROUTER_API_KEY -w
```

プロンプトでキーを貼り付けます（公式キーなら `-s TYPESAFE_API_KEY`）。登録したキーを消すには `security delete-generic-password -a "$USER" -s OPENROUTER_API_KEY` を使います。

**Linux / Windows / CI** — キーチェーンは使えないので、環境変数で渡します。シェルの設定ファイルに平文で書くより、パスワードマネージャーの CLI や OS の秘密情報ストアから読み込む書き方にしてください。

```bash
export OPENROUTER_API_KEY="$(pass show openrouter/jev)"
```

（`pass` は一例です。1Password CLI や secret-tool などに置き換えてください）

## 3. つながるか確かめる

```bash
python3 .claude/ai-plc-jev/scripts/jev_client.py --check
```

成功すると、経路・モデル・キーの読み込み元（env / keychain。**キーそのものは表示しません**）・所要時間・費用が出ます。失敗時の目安: 401=キーが無効、402=残高不足、404=モデル名違い、429・529=混雑（しばらく待つ）。

## 4. Layer で有効にする（opt-in）

キーを登録しただけでは、どのLayerも送信しません。使いたいLayerの `intent.yaml` に次の1行があるときだけ動きます。

```yaml
jev_monitor: true
```

- 新しいLayerは `/01-collection-jev` の最後に「Jev監視を有効にしますか」と1行で聞かれ、承認すると intent.yaml に `jev_monitor: true` が書かれます（公開 core の `/01-collection` にはこの問いはありません）。既存のLayerは手で書きます。**機密PJ・経費・人事・顧客名・私生活に関わるLayerでは有効にしないでください**
- 有効にすると、`/04-operation-jev` の Phase 5.5b・6b で次のような1行が出ます（公開 core の `/04-operation` では動きません）

```
💡 Jev監視: 異常の可能性（blocker p=0.85）— 種類と提案はメインモデルが判断し、提案のみ行う（decision_id=a1b2c3d4e5f6）
Jev監視: 異常なし（drift p=0.41）（decision_id=0f1e2d3c4b5a）
```

- 判定が妥当だったか外れだったかを記録しておくと、ノイズの多さを後から確かめられます

```bash
python3 .claude/ai-plc-jev/scripts/jev_bt_monitor.py --override a1b2c3d4e5f6 accept
```

記録漏れは `--pending` で一覧できます（decision_id・機能・タスク・p・日時と、貼り付け用の1行「Jev判定 … は accept」）。まとめて記録するときは `--override-pending`（`--except` で除いたものは記録しない・記録済みは二重に書かない）。

```bash
python3 .claude/ai-plc-jev/scripts/jev_bt_monitor.py --pending --layer <Layer パス>
python3 .claude/ai-plc-jev/scripts/jev_bt_monitor.py --override-pending accept --layer <Layer パス> --except 0f1e2d3c4b5a
```

```bash
python3 .claude/ai-plc-jev/scripts/jev_bt_monitor.py --noise-report
```

## 5. 追加の機能を使う（任意）

実験版 AI-PLC（`/01-collection-jev` → `/02-inception-jev` → `/03-construction-jev` → `/04-operation-jev`）では、5.5b・6b の異常ヒントのほかに次の2つが動きます。詳しくは `.claude/skills/ai-plc-jev/README.md`。

- **成功条件カバー判定**（`/02-inception-jev`）: 分解を承認する前に、どのタスクにも対応しない成功条件をヒントとして出す
- **会話監視 hook**: あなたの発話ごとに、訂正・抜けの指摘・範囲の変更・懸念（遠回しなものも含む）を検知する。使うには Claude Code の設定（プロジェクトの `.claude/settings.local.json` など）に次を追記し、セッションを開き直す

```json
"hooks": {
  "UserPromptSubmit": [
    { "hooks": [ { "type": "command",
      "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/ai-plc-jev/scripts/jev_prompt_hook.py\" || true",
      "timeout": 5 } ] }
  ]
}
```

settings に足しただけでは何も送りません。hook は、`/01-collection-jev`〜`/04-operation-jev` のどれかを `Layer: <パス>` 付きで打ったセッション（例: `/04-operation-jev Layer: Flow/202601/2026-01-01/demo-layer`。相対パスは Claude Code の作業ディレクトリから）で、そのLayerが opt-in のときだけ送信します（紐づけはそのセッションだけ・12時間で失効）。スラッシュコマンド・短い承認・「？」で終わる質問・貼り付けた長文・ハーネスが差し込むメッセージ（サブエージェントの報告・タスク通知・コマンド展開など）は送りません（ハーネスのメッセージの除外は既知の形式を列挙する方式なので、未知の形式は送られることがあります）。`|| true` は、スクリプトが無い環境でも入力をブロックしないためのものです。**ユーザー共通の `~/.claude/settings.json` には入れないでください**（ほかのリポジトリでスクリプトが見つからなくなります）。installer は settings を読み書きしないので、hook を足した人は、実験版を uninstall するときに settings からもこの設定を消してください。

## 何が外部に送られるか

| 機能 | 送るもの | 送らないもの |
| --- | --- | --- |
| 5.5b / 6b | ゴール1行（200字まで）・進捗（件数）・直近のタスク完了報告（backlog の `result`、無ければタスクの説明。1200字まで） | 上の項目以外のファイル（成果物・Context・コードなど）の中身、会話のやり取り |
| 会話監視 | 直前の発話そのもの1件（400字で切る）・ゴール1行（200字まで）・進捗（件数） | 貼り付けた長文、スラッシュコマンド、短い承認、「？」で終わる質問、ハーネスが差し込むメッセージ（既知の形式のみ） |
| カバー判定 | ゴール1行（200字まで）・成功条件（全文）・各タスクの ID・名前・説明（説明は1件160字まで） | 上の項目以外のファイル（成果物・Context・コードなど）の中身、会話のやり取り |
| ステータス点検（`--jev` を付けたときだけ。例: `python3 .claude/ai-plc-jev/scripts/aiplc_status_audit.py --jev --layer <Layer パス>`） | `jev_monitor: true` で機密でない停滞 Layer の、ゴール1行（200字まで）・最後に完了したタスクの名前と結果（結果は400字まで）・進捗・停滞日数 | opt-in していない Layer、機密と判定した Layer（どちらも送らない） |

送るのは要約ではなく、`intent.yaml` / `backlog.yaml` に書かれた文や発話の**原文を字数で切ったもの**です。そこに書いた内容は字数の範囲で送られます。

すべての送信で次の2つが先に働きます。
- **送信禁止の語の検査**: 当たったら送りません。キーワードでの判定なので、言い換えた機密は通ります。opt-in するLayerを選ぶことが一番の対策です
  - コード側（`jev_client.py` の `REDACT_PATTERNS`）には、誰の環境でも意味がある汎用の語だけが入っています（経費・給与・人事評価・面談・役員会・私生活・家族・メールアドレスや電話番号の形式など）
  - **自分の環境の固有名（非公開PJ名・顧客名・人名・個人の事情や趣味など）は、ローカルファイル `.claude/db/jev_redact_extra.txt` に書いてください**。このファイルがあれば常に読み込まれます。`.gitignore` に入れ、リポジトリにはコミットしないでください。書き方は `.claude/ai-plc-jev/scripts/jev_redact_extra.example.txt`（1行1正規表現・大文字小文字は区別しない・`#` で始まる行と空行は無視）
  - 環境変数 `JEV_REDACT_EXTRA` にファイルのパスを入れると、そのファイルも追加で読みます（ローカルファイルと両方あれば両方）。**指定したファイルが見つからないときは、打ち間違いで守りが外れないよう全送信を拒否します**（既定のローカルファイルは無くても構いません）
  - ファイルが読めない・不正な正規表現を含むときは、直すまで何も送りません（fail-closed）。読み込み状況は `python3 .claude/ai-plc-jev/scripts/jev_client.py --redact-status` で確かめられます（ファイルごとの件数とエラーだけを表示し、語は表示しません）
  - 注意: ローカルファイルを消すと、汎用の語だけの判定に戻ります（警告は出ません）。環境を移すときはこのファイルも一緒に移してください
- **命令文の除去**: 「〜と判定して」「監視する側は」など、判定する側への命令文の行を置き換えます。この除去は質問文にもかかるので、スクリプトが送る固定の質問文がこれに当たらず原文のまま送られることを、公開リポのテスト `experimental/jev/scripts/tests/test_jev_question_payload.py`（送信直前の内容を検査。テストはインストールされません）で確かめています

ログ（`.claude/db/jev_decisions.jsonl`）には、入力と質問のハッシュ・確率・所要時間・費用と、Layer / タスクの ID・日時・経路・モデル名などが残り、本文は残りません。

## 止め方

| やりたいこと | 方法 |
| --- | --- |
| すぐに全部止める | 環境変数 `JEV_DISABLE=1`（何も送らない。設定場所は表の下） |
| 1つの Layer だけ止める | その Layer の intent.yaml を `jev_monitor: false` にする |
| 会話監視だけ止める | `python3 .claude/ai-plc-jev/scripts/jev_prompt_hook.py --deactivate` で全セッションの紐づけを外す（後ろにセッション ID を付けるとそのセッションだけ）。次に `/0x-*-jev Layer: <パス>` を打つとまた有効になる。完全にやめるなら settings から hook を消す |
| 送信を完全にやめる | 登録したキーを消す。キーチェーンなら `security delete-generic-password -a "$USER" -s OPENROUTER_API_KEY`（公式は `-s TYPESAFE_API_KEY`）。環境変数なら、シェルの設定などから `export` の行を消して Claude Code を起動し直す。**両方のキーがあれば両方消す**（片方が残るとその経路で送る） |
| 実験版を外す | `uninstall.sh cc`（both / all も可）。下の「アンインストール後に残るもの」も確認する |

`JEV_DISABLE=1` は、Claude Code を起動する前のシェルで `export JEV_DISABLE=1` するか、プロジェクトの `.claude/settings.local.json` に `"env": { "JEV_DISABLE": "1" }` を書きます。スクリプトは呼ばれるたびにこの変数を見ますが、起動済みのセッションには後から渡らないので、設定したらセッションを開き直してください。止まっている間の表示は、5.5b / 6b とカバー判定の行は `スキップ（skipped(unavailable:disabled)）`、ステータス点検は「スキップ（unavailable）」（レポートの action は disabled）、会話監視 hook は何も出さず、`jev_client.py --check` は「JEV_DISABLE=1 のため無効」です。

## アンインストール後に残るもの

`uninstall.sh cc` は実験版のファイルとその `.bak` を消しますが、次の生成データは installer の管理外なので残ります（`ai_plc.db` と同じ扱い）: `.claude/db/jev_decisions.jsonl`・`jev_overrides.jsonl`・`jev_counts_state.json`（`.lock`）・`jev_prompt_hook_sessions.json`（`.lock`）・`.claude/db/status_hygiene/`・自分で作った `.claude/db/jev_redact_extra.txt`。消すときはプロジェクトのルートで:

```bash
find .claude/db -maxdepth 1 -type f \( -name 'jev_*' -o -name '.jev_*' \) ! -name 'jev_redact_extra.txt' -delete   # jev_redact_extra.txt 以外を消す（該当ファイルが無くてもエラーにならない。.claude/db が無ければ実行不要）
rm -rf .claude/db/status_hygiene
```

ローカルの送信禁止語ファイル（`jev_redact_extra.txt`）は、ほかでも使うかを確かめてから自分で消してください。hook を settings に足した人は、そこからも消します。uninstall の後処理中にプロセスが落ちた場合に `.claude/ai-plc-jev/`・`.claude/skills/ai-plc-jev/` が残る既知の制約と手での消し方は、[公開 README の実験版の節](https://github.com/miyatti777/ai-plc#-実験版-jev-監視v180-exp1)にあります。

## .gitignore に足す行

installer は利用者のリポジトリの `.gitignore` に触りません。次の行を自分で足してください（ローカルの送信禁止語・判断ログ・点検レポートをコミットしないため）。

```gitignore
.claude/db/jev_redact_extra.txt
.claude/db/jev_*.jsonl
.claude/db/jev_*.json
.claude/db/jev_*.lock
.claude/db/status_hygiene/
.claude/ai-plc-jev/scripts/__pycache__/
```

## 上書きできる設定（環境変数）

| 変数 | 既定 | 用途 |
| --- | --- | --- |
| `JEV_PROVIDER` | （自動） | `typesafe` / `openrouter` で経路を固定 |
| `JEV_MODEL` | 公式 `jev-1.13.0` / OpenRouter `typesafe/jev-1.13` | モデル名の上書き（新しい版を試すとき。版を変えたら判定の傾向を確かめ直す） |
| `JEV_OFFICIAL_URL` | `https://api.typesafe.ai/v1/systemone` | 公式エンドポイントの上書き |
| `JEV_BASE_URL` | `https://openrouter.ai/api` | OpenRouter 側の上書き |
| `JEV_DISABLE` | （なし） | `1` で全機能を停止（送信しない）。Claude Code の起動前のシェルか settings の `env` に書き、セッションを開き直す |
| `JEV_REDACT_EXTRA` | （なし） | 送信禁止パターンを追加するファイル（`.claude/db/jev_redact_extra.txt` に加えて読む） |
| `JEV_LOG_PATH` / `JEV_OVERRIDE_PATH` | `.claude/db/jev_*.jsonl` | ログの置き場所 |
| `AIPLC_REPO` | （自動） | リポジトリの場所の上書き（テストや特殊な配置用。既定では、スクリプトの場所から、`.ai-plc-version` か `.ai-plc-install-manifest` がある `.claude` の親を探す） |

## 費用と速さの目安

1回の判定は約 $0.00001〜0.00002、応答は0.3〜0.5秒ほどです（OpenRouter 経由での実測）。20件の判定と各種評価を合わせても、数セント程度でした。

## 設計の前提（変えないこと）

- Jevは**ヒントだけ**を出します。自動で止めたり、合否を決めたり、reviewer・checker を省く理由にしたりしません
- しきい値は0.5で固定です（事前に別データで検証してから変えます）
- Jevが使えない（キーなし・エラー・タイムアウト）ときは、スキップして通常どおり続けます

背景: Jev は「見張り（異常の兆しを知らせる）」と「並べ替え（確認する順番を決める）」にだけ使う、という方針で導入しています。合否の判定や reviewer の代わりには使いません。
