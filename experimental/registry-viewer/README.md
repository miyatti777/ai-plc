# experimental/registry-viewer — Project Registry ビューア（アルファ版 0.1.1-alpha）

AI-PLC の Project Registry（`.claude/db/ai_plc.db` の projects / tasks）を、ブラウザで見て、Project と Task の status を変えられるローカル専用のツールです。

> ⚠️ **アルファ版です。** 画面・API・ファイル構成は予告なく変わります。UI は日本語だけです。status を変えると Layer のファイル（intent.yaml / backlog.yaml）と Registry の両方を書き換えるので、**試す前にバックアップを取ってください**（下の「バックアップと戻し方」）。試した結果や不具合の報告は Issue で歓迎します。

- **installer の対象外です。** `install.sh` では入りません。下の手順で、プロジェクトに手でコピーして使います。core の版は変わりません
- **外部送信はありません。** 127.0.0.1 でだけ待ち受け、CDN なども読み込みません
- 見られるもの: Project の一覧（親子のツリー・status・進捗率・期限）と、各 Project の詳細（goal・Layer フォルダ・タスク表・起動プロンプト）。Jev 実験版を入れていれば、ステータス点検の指摘（食い違い）と機密判定も出ます
- できること: Project と Task の status 変更、Layer のパスと起動プロンプトのコピー
- できないこと: 行の追加・削除、名前や goal の編集、AI-PLC コマンドの実行、Notion への同期

## 前提

- AI-PLC を入れたプロジェクト（`.claude/db/ai_plc.db` があり、Layer が `Flow/` か `.ai-plc/` の下にあるもの）
- Python 3.9 以上と pyyaml（AI-PLC 本体と同じ）
- macOS のメニューバーアプリを使う場合だけ: macOS 13 以上と Command Line Tools（`swiftc`）。Xcode は要りません

## 入れ方・外し方

AI-PLC のリポジトリを checkout した場所で、プロジェクトのフォルダを指定してコピーします。先に下の「バックアップと戻し方」でバックアップを取っておくと安心です。

> 💡 **AI（Claude Code など）に頼むときは、バックアップ・コピー・`.gitignore` への追記・起動を1つずつ別のコマンドで実行させてください。** まとめて1つのコマンドにすると、元に戻せない操作が混ざっているとみなされて、安全判定で止められることがあります。

```bash
cp -R experimental/registry-viewer <プロジェクト>/.claude/db/registry_viewer
```

- 更新するときは、古い `<プロジェクト>/.claude/db/registry_viewer` を消してからコピーし直してください（残したままコピーすると、`registry_viewer/registry-viewer/` という入れ子ができます）
- 外すときは、`<プロジェクト>/.claude/db/registry_viewer` を消すだけです。変更の記録（下の「変更の記録」）の `viewer_log.jsonl` は残るので、要らなければ消してください。`status_hygiene/` フォルダはステータス点検（Jev 実験版）のレポートと共用なので、Jev 実験版を入れていないときだけフォルダごと消してかまいません
- プロジェクトを git で管理しているなら、`.gitignore` に次の1行を足してください。`.gitignore` が無ければ、プロジェクトのフォルダに新しく作ります（変更の記録とバックアップを commit しないため。Jev 実験版を入れていれば、同じ行が既にあるかもしれません。Cursor だけの配置では `.cursor/db/status_hygiene/` になります）

```gitignore
.claude/db/status_hygiene/
```

## 起動と停止

プロジェクトのフォルダで実行します。

```bash
python3 .claude/db/registry_viewer/server.py
```

- ブラウザで `http://127.0.0.1:8765/` が開きます。起動したときに、開く URL と `mode: full` か `mode: readonly（理由）` を表示します（下の「フル機能と閲覧のみ」）
- **止め方:** ターミナルで動かしているなら Ctrl-C。バックグラウンドで起動したとき（AI に起動を頼んだときなど）は、そのプロセスを終了します（例: `pkill -f registry_viewer/server.py`。同じマシンで他のプロジェクトのビューアも動いていれば、それも止まるので注意）。常駐はしません
- **ポート 8765 が使用中のとき**（他のプロジェクトのビューアやメニューバーアプリが動いているなど）は、理由を表示して終了コード 2 で止まります。`--port 0`（空いているポートを自動で選ぶ）か `--port 8766` のように別の番号を付けて起動し直し、表示された URL を開いてください。**8765 をそのまま開くと、別のプロジェクトの Registry を見てしまう**ことがあります（ヘッダに出る件数や Project 名で見分けてください）
- ブラウザを開きたくないときは `--no-browser` を付けます
- プロジェクトの場所は、server.py の場所から上にたどって `.claude/db/ai_plc.db`（無ければ `.cursor/db/ai_plc.db`）があるフォルダを使います。別の場所に置いたときは `--root <プロジェクト>` を、別の DB を見るときは `--db PATH`（または環境変数 `AIPLC_DB`）を指定します
- DB やプロジェクトが見つからないときも、理由を表示して終了コード 2 で止まります

## フル機能と閲覧のみ

ビューアは、AI-PLC の2つのスクリプトを探して使います。

| 探すもの | 探す順番 | 無いとき |
| --- | --- | --- |
| `aiplc_status_audit.py`（ステータス点検。Jev 実験版に入っています） | ① 環境変数 `AIPLC_STATUS_AUDIT` ② `<プロジェクト>/scripts/` ③ `<プロジェクト>/.claude/ai-plc-jev/scripts/`（`--with-jev` で入る場所） | 閲覧のみ。食い違い・機密判定・画面共有モードは出ません |
| `plc_query.py`（core に入っています） | ① 環境変数 `AIPLC_PLC_QUERY` ② `<プロジェクト>/.claude/db/` ③ `<プロジェクト>/.cursor/db/` | 表示はそのまま、書き込みだけできません |

- **両方あればフル機能**です。Jev 実験版を入れていない（core だけの）環境では閲覧のみになります
- **ステータス点検が無いと書き込みもできない理由:** Registry への書き込みは `plc_query.py` が行いますが、書き込みの前後に必要な処理（Project に対応する Layer フォルダの特定、YAML の status 1行だけの安全な書き換え、backlog と Registry の値の対応づけ）は `aiplc_status_audit.py` の関数を使っています。これが無いまま Registry だけを書くと Layer のファイルとずれるので、閲覧のみにしています
- **フル機能にする方法:** Jev 実験版を追加で入れます（Jev の API キーは要りません。外部送信は `--jev` を付けたときだけです）。AI-PLC のリポジトリを checkout した場所で実行します

```bash
./install.sh --target <プロジェクト> cc --with-jev --dry-run
```

  予定を確かめたら `--dry-run` を外して実行します。`install.sh` では環境（`cc`）の指定が必要で、確認なしで進めるときは `--yes` を付けます（`./install-cc.sh --target <プロジェクト> --with-jev` でも同じです）。入れたあとはビューアを起動し直してください。書き込みができるようになるので、その前にバックアップを取り直しておくと安心です

- もう1つの方法として、`AIPLC_STATUS_AUDIT` で checkout の `experimental/jev/scripts/aiplc_status_audit.py` を指定しても、フル機能になります
- 環境変数でファイルを指定したのに見つからないときは、黙って閲覧のみにはせず、起動を止めます
- 見つけた `aiplc_status_audit.py` に必要な関数が欠けている（版が違う）ときも閲覧のみになり、理由に欠けている関数名が出ます
- 閲覧のみのとき、画面のヘッダに「閲覧のみ」のバッジが出ます（マウスを乗せると理由が出ます）

## 画面の読み方

| 表示 | 意味 |
| --- | --- |
| 左の一覧 | Registry の Project です。`parent_scope` で親子を入れ子にしています。▾ で子をたたみます。薄い行は、絞り込み条件に合わないものの、子が条件に合うため残している親です |
| status の絞り込み | 初期値は active です。選んだ絞り込みと画面共有モードのオン・オフはブラウザに保存されます |
| 「食い違いあり」ボタン | `食い違い` か `status差` のある Project だけに絞ります（ステータス点検が見つかったときだけ出ます） |
| 進捗バー | 完了 / 対象のタスク数です。backlog.yaml にタスクがあればその数を使い、cancelled・dropped・deferred は数えません。backlog が無ければ Registry のタスク行をすべて数えます |
| `status差` | intent.yaml と Registry の status が対応していない Project です（ステータス点検が見つかったときだけ出ます）。一致とみなす組み合わせ: active↔active、completed・done↔completed、deferred↔paused、blocked↔active、pending 系↔planned か active |
| `食い違い N` | ステータス点検（`aiplc_status_audit.py`）が出す候補の数です（閉じ忘れ・停滞・タスクの不一致など） |
| 🔒 | ステータス点検と同じ基準で機密と判定された Project です。迷うものは機密の側に倒すので、機密でない Project にも付くことがあります |
| 画面共有モード | 🔒 の Project の名前・goal・Layer パス・起動プロンプト・食い違いの理由・メッセージ中のパスを伏せ、scope_id を `C-xxxxxxxx` にします。ブラウザの表示を伏せるだけで（API の応答には含まれます）、ハッシュから元の ID を逆引きできるので秘匿化ではありません |
| 起動プロンプト | Claude Code の形式です。intent が completed なら Re-Collection の `/01-collection`、backlog が空なら `/02-inception`（ただし intent の `workflow_depth` が simple なら、Stage 2・3 を飛ばせるので `/04-operation`）、それ以外は `/04-operation` を出します。Layer の intent.yaml に `pipeline_variant: jev` があれば `-jev` 付きになります。Cursor・Codex では、それぞれの起動形式（Cursor なら `@SKL_plc_*`）に読み替えてください |

## status を変えると何が書き換わるか

変更の前に、確認ダイアログで「どのファイルのどの値を、何から何に変えるか」を表示します。

| 操作 | 書く順番と書く値 |
| --- | --- |
| Project を active / paused / completed に | ① `intent.yaml` の `status`（active / deferred / completed）→ ② `backlog.yaml` の `summary.status`（キーがあるときだけ、①と同じ値）→ ③ Registry の `projects.status`（active / paused / completed） |
| Task の status を変更（選べるのは pending / in_progress / completed / blocked / deferred / cancelled の6つ） | ① `backlog.yaml` の該当タスクの `status` → ② Registry の `tasks.status`（DB の語彙に合わせます。英語語彙なら completed・cancelled・dropped→completed、in_progress→active、それ以外→planned。日本語語彙なら 完了 / 進行中 / 未着手。英語語彙の DB では、Layer の intent.yaml の `sync_targets`（`type: sqlite`）に `status_map` があればそれに従います）。Registry で完了扱いになる値（completed・cancelled）にするときは、`completed_at` が空の場合だけ今日の日付を入れます。タスクが片方にしか無いときは、ある方だけを書きます |

守っている決まり:

- **行は足しません。** Registry への書き込みは `plc_query.py` の `cmd_sql` を通した UPDATE だけです。行を足すときは `plc_query.py add-project` / `add-task` を使ってください
- **YAML は status の1行だけを書き換えます。** 書き込む前に書き換え後のテキストを解析し、status 以外が変わっていないことを確かめます。コメントや並び順はそのまま残ります
- **画面を読んだ後に値が変わっていたら、何も書きません**（409。再読み込みしてからやり直してください）。Task の変更で書く backlog.yaml は、置き換える直前にも中身が変わっていないかを確かめます
- **Registry への書き込みに失敗したら、先に書いた YAML を元に戻します。** 書き戻しにも失敗したときや、途中でプロセスが止まったときは戻りません。その場合は、次に読み込んだときに `status差` や `食い違い` として表示され、ステータス点検でも検出されます
- **読み取り専用になる Project:** Layer フォルダが見つからないもの、同じ scope_id のフォルダが複数あるもの（Registry だけを変えると食い違いが生まれるため）
- **変更できないタスク:** backlog.yaml で flow 形式（`- {id: T001, status: pending}`）で書かれたタスクや、status の行が無いタスクは「変更不可」と表示します
- **未完了のタスクが残っている Project は completed にできません。** deferred や blocked のタスクも Registry では未完了の値になるので、先に completed か cancelled にしてください
- **この画面から planned にはできません**（選択肢は active / paused / completed だけです）。planned の Project を開くと、選択欄に「planned（現在の値・画面からは選べません）」と出ます

既知の制約:

- Project の変更で書く intent.yaml と backlog.yaml の `summary.status` は、読んでから置き換えるまでの短い間に他で書かれた変更を上書きする可能性があります。CLI（ステータス点検の `--apply` など）と同時に操作しないでください
- 一覧を開くたびに、全 Layer を読み直します（Layer 130件ほどで 0.3〜0.4 秒）
- UI は日本語だけです

## 失敗したとき

- 画面の下に赤いメッセージが約6秒出て、一覧と詳細が自動で読み直されます。例:「画面を読んだ後に値が変わっています。再読み込みしてください」（409）、「未完了のタスクがあります（backlog N 件・Registry N 件）…」（409）、「Registry の更新に失敗しました: …」（500）
- 画面共有モードで 🔒 の Project を操作したときは、パスや理由を出さないよう「変更できませんでした（HTTP 409）」のように HTTP コードだけを表示します
- 書き戻しにも失敗したときは、メッセージの末尾に「Layer ファイルの書き戻しにも失敗しました」と、失敗したファイルが出ます

## 変更の記録

すべての変更を `viewer_log.jsonl` に1件1行（変更前 `before` と変更後 `after` つき）で記録します。時刻 `at` はタイムゾーンつきの現地時刻（例 `2026-09-29T17:17:51+09:00`）です。Registry の `updated_at` は UTC（例 `2026-09-29T08:17:51Z`）なので、突き合わせるときは時差を足し引きしてください。置き場所は、DB と同じフォルダの `status_hygiene/`（既定では `.claude/db/status_hygiene/`）で、環境変数 `AIPLC_STATUS_HYGIENE_DIR` で変えられます。

## バックアップと戻し方

**試す前にバックアップを取ってください。** ビューアは自動ではバックアップを取りません。DB は WAL モードなので、ファイルのコピーではなく SQLite のバックアップ機能を使います。保存先は git で管理しない場所（例: `.claude/db/status_hygiene/`）にし、名前は毎回変えてください。下の例の `YYYYMMDD` を今日の日付にし、同じ日に2回目を取るときは `_2` のように番号を付けます。Layer のファイルは git などで管理しておくと戻しやすくなります。

```bash
python3 -c "import sqlite3; s=sqlite3.connect('.claude/db/ai_plc.db'); d=sqlite3.connect('.claude/db/status_hygiene/ai_plc_backup_YYYYMMDD.db'); s.backup(d); d.close(); s.close()"
```

（`status_hygiene/` が無ければ先に `mkdir -p .claude/db/status_hygiene` で作ります）

戻し方:

1. **画面で選び直す:** Project の active / paused / completed と、Task の6つの値（上の表を参照）は、同じ画面で元の値を選び直せば戻ります。Registry には選んだ値を変換した値が入るので、もともと backlog と Registry が食い違っていた場合や、backlog の値が6択の外（done・dropped など）だった場合は、元どおりにはなりません（2 の手順で戻します）。また、completed・cancelled にした Task を戻しても Registry の `completed_at` は消えません。消すときは `python3 .claude/db/plc_query.py sql "UPDATE tasks SET completed_at=NULL WHERE scope_id='<scope_id>' AND task_id='<task_id>'"` を実行します
2. **画面で選べない値に戻す:** intent の pending・blocked や Registry の planned には、画面からは戻せません。`viewer_log.jsonl` の該当行の `before` を見て、手で戻します
   - YAML: intent.yaml（または backlog.yaml の該当タスク）の `status:` の1行を `before` の値に書き換えます
   - Registry: `python3 .claude/db/plc_query.py sql "UPDATE projects SET status='<before>' WHERE scope_id='<scope_id>'"`（Task は `UPDATE tasks SET status='<before>' WHERE scope_id='<scope_id>' AND task_id='<task_id>'`）
3. `result` が `error` の行には `before` がありません。ほとんどの場合は何も書かれていないか、書き戻し済みです。メッセージに書き戻しの失敗が出ていたときだけ、ステータス点検で食い違いを確かめてください
4. Registry を丸ごと戻すときは、上で取ったバックアップのファイルを `ai_plc.db` の場所に戻します（ビューアと Claude Code を止めてから。バックアップの後に入った変更も消えます）

## セキュリティ

- 127.0.0.1 でだけ待ち受けます。`Host` ヘッダが 127.0.0.1 か localhost でない要求は拒否します（DNS rebinding 対策）
- 書き込みの要求には、起動ごとに作るトークン（画面に埋め込み）と `Content-Type: application/json` が必要です。`Origin` が付いていれば、同じ origin かも確かめます（CSRF 対策）
- scope_id と task_id は英数字と `._-` だけを受け付けます。書き込み先のファイルは、ステータス点検が解決した Layer フォルダの中に限ります

## メニューバーアプリ（macOS・任意）

メニューバーのアイコン（表のマーク）から、専用ウィンドウでビューアを開けます。サーバの起動・停止もアプリが行います。**バイナリは配っていません。** 自分の Mac でビルドします。

```bash
.claude/db/registry_viewer/macapp/build.sh ~/Applications
```

- ビルドのたびに、プロジェクトの場所と pyyaml の入った python3 の場所をアプリに埋め込みます。プロジェクトを移動したらビルドし直してください。出力先を省略すると `macapp/build/` に作ります
- python3 は、環境変数 `AIPLC_PYTHON` → PATH 上の python3（pyenv・conda・venv を含む）→ `/opt/homebrew/bin` → `/usr/local/bin` → `/usr/bin` の順に、pyyaml が import できるものを探し、実体のパスを埋め込みます。venv を消したり python を入れ替えたりしたら、ビルドし直してください
- ad-hoc 署名なので、自分の Mac でビルドしたものだけを使ってください
- Spotlight や Finder から開くとウィンドウが出ます。ログイン時に自動で起動したいときは、システム設定 → 一般 → ログイン項目 に追加します（ログイン時はメニューバーに常駐するだけです）
- メニュー: Registry を開く（⌘O）／再読み込み（⌘R）／ブラウザで開く／サーバの状態／サーバを再起動／終了（サーバも止める）
- すでにポート 8765 でサーバが動いていれば、それを使います（別のプロジェクトのサーバでも使ってしまいます。アプリを終了しても、そのサーバは止まりません）
- うまく開かないときは `~/Library/Logs/AI-PLC Registry.log` を見てください

## テスト

checkout のルートで実行します（インストールはされません）。一時ディレクトリの SQLite と Layer だけを使い、公開版 `core/db/init_db.py` のスキーマ（英語語彙）と、日本語語彙のスキーマの両方で書き込みを確かめます。status_audit は `experimental/jev/scripts/` のものを自動で使います。

```bash
python3 -m unittest discover -s experimental/registry-viewer/tests
```

- plc_query の拡張スキーマ（公開版の `plc_query.py` は未対応）のテスト2件は skip になります
- 別の場所の status_audit・plc_query・init_db.py で試すときは、`AIPLC_STATUS_AUDIT`・`AIPLC_PLC_QUERY`・`AIPLC_INIT_DB` で指定します
- checkout の上のフォルダに AI-PLC のプロジェクト（`.claude/db/ai_plc.db`）があると、そのプロジェクトの依存とスキーマ（読み取り専用で写す）を先に使います
