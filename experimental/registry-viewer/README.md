# experimental/registry-viewer — Project Registry ビューア（アルファ版 0.3.0-alpha）

AI-PLC の Project Registry（`.claude/db/ai_plc.db`）と Layer のファイルを、ブラウザで見るローカル専用のツールです。**閲覧専用**で、DB にも Layer のファイルにも書きません。

> ⚠️ **アルファ版です。** 画面・API・ファイル構成は予告なく変わります。UI は日本語だけです。試した結果や不具合の報告は Issue で歓迎します。

- **installer の対象外です。** `install.sh` では入りません。下の手順で、プロジェクトに手でコピーして使います。core の版は変わりません
- **外部送信はありません。** 127.0.0.1 でだけ待ち受け、CDN なども読み込みません
- **閲覧専用です（0.3.0-alpha〜）。** 0.2.x にあった画面からの status の変更は外しました。Project の中止・再開は `/plc-lifecycle`、タスクの進行は各 Stage（`/04-operation` など）で行います。GET・HEAD 以外の要求（POST・PUT・PATCH・DELETE・OPTIONS など）には 405 を返します
- 見られるもの:
  - Project の一覧（親子のツリー・status・進捗率・期限・作業記録の更新時刻）
  - 各 Project の詳細（goal・Layer フォルダ・タスク表〔実行時期・期限・運用タスクの印〕・中止の記録・起動プロンプト）
  - Program・業務Project でまとめた一覧（業務Project の表があるとき。下の「Program 別の表示」）
  - ステータス点検の指摘（食い違い）と機密判定（Jev 実験版の `aiplc_status_audit.py` があるとき）
  - 分類（所属・種類・実行環境）のバッジと絞り込み（分類を付けたとき。下の「分類」）
- できること: Layer のパスと起動プロンプトのコピー
- できないこと: status の変更、行の追加・削除、名前や goal の編集、AI-PLC コマンドの実行、Notion への同期

## 前提

- AI-PLC を入れたプロジェクト（`.claude/db/ai_plc.db` があり、Layer が `Flow/` か `.ai-plc/` の下にあるもの）
- Python 3.9 以上と pyyaml（AI-PLC 本体と同じ）
- macOS のメニューバーアプリを使う場合だけ: macOS 13 以上と Command Line Tools（`swiftc`）。Xcode は要りません

## 入れ方・外し方

AI-PLC のリポジトリを checkout した場所で、プロジェクトのフォルダを指定してコピーします。

> 💡 **AI（Claude Code など）に頼むときは、コピー・`.gitignore` への追記・起動を1つずつ別のコマンドで実行させてください。** まとめて1つのコマンドにすると、元に戻せない操作が混ざっているとみなされて、安全判定で止められることがあります。

```bash
cp -R experimental/registry-viewer <プロジェクト>/.claude/db/registry_viewer
```

- 更新するときは、古い `<プロジェクト>/.claude/db/registry_viewer` を消してからコピーし直してください（残したままコピーすると、`registry_viewer/registry-viewer/` という入れ子ができます）。分類の語彙ファイル（`classification_vocab.yaml`）を作っていれば、消す前に退避してください
- 外すときは、`<プロジェクト>/.claude/db/registry_viewer` を消すだけです
- 0.2.x で書いた変更の記録 `viewer_log.jsonl`（`.claude/db/status_hygiene/` の中）は 0.3.0-alpha では使いません。要らなければ消してかまいません
- 分類（`classify.py`）を使うなら、プロジェクトを git で管理している場合は `.gitignore` に次の2行を足してください（分類の記録・承認ファイルと、ローカルの語彙ファイルを commit しないため。Cursor だけの配置では `.cursor/db/status_hygiene/` になります）

```gitignore
.claude/db/status_hygiene/
.claude/db/registry_viewer/classification_vocab.yaml
```

## 起動と停止

プロジェクトのフォルダで実行します。

```bash
python3 .claude/db/registry_viewer/server.py
```

- ブラウザで `http://127.0.0.1:8765/` が開きます。起動したときに、開く URL と `mode: readonly（理由）` を表示します
- **止め方:** ターミナルで動かしているなら Ctrl-C。バックグラウンドで起動したとき（AI に起動を頼んだときなど）は、そのプロセスを終了します（例: `pkill -f registry_viewer/server.py`。同じマシンで他のプロジェクトのビューアも動いていれば、それも止まるので注意）。常駐はしません
- **ポート 8765 が使用中のとき**（他のプロジェクトのビューアやメニューバーアプリが動いているなど）は、理由を表示して終了コード 2 で止まります。`--port 0`（空いているポートを自動で選ぶ）か `--port 8766` のように別の番号を付けて起動し直し、表示された URL を開いてください。**8765 をそのまま開くと、別のプロジェクトの Registry を見てしまう**ことがあります（ヘッダに出る件数や Project 名で見分けてください）
- ブラウザを開きたくないときは `--no-browser` を付けます
- DB の場所（0.3.0-alpha〜）: `--db PATH` → 環境変数 `AIPLC_DB` → core の `aiplc_paths.py`（`.claude/db/aiplc_paths.py`。DB の隣か checkout の `core/db/`）が見つかればその決め方（`.ai-plc/config.yaml` の `id_allocation.db_path` など）→ `<プロジェクト>/.claude/db/ai_plc.db` → `<プロジェクト>/.cursor/db/ai_plc.db` の順です。`aiplc_paths.py` が無い・読めないときは、今までどおり隣の DB を使います
- プロジェクトの場所は、server.py の場所から上にたどって `.claude/db/ai_plc.db`（無ければ `.cursor/db/ai_plc.db`）があるフォルダを使います。別の場所に置いたときは `--root <プロジェクト>` を指定します
- DB やプロジェクトが見つからないときも、理由を表示して終了コード 2 で止まります
- 動いているかの確認は `http://127.0.0.1:<ポート>/api/health`（`{"ok": true, "version": "…"}` を返す軽い応答）です

## ステータス点検（任意）

ビューアは Jev 実験版の `aiplc_status_audit.py` を探し、見つかれば食い違いと機密判定を出します。無くても一覧・詳細はそのまま見られます。

| 探す順番 | 無いとき |
| --- | --- |
| ① 環境変数 `AIPLC_STATUS_AUDIT` ② `<プロジェクト>/scripts/` ③ `<プロジェクト>/.claude/ai-plc-jev/scripts/`（`--with-jev` で入る場所） | 食い違い・`status差`・🔒（機密判定）は出ません。画面共有モードは、分類か Program 別の表示があるときだけ出ます |

- Jev 実験版を入れるとき（Jev の API キーは要りません。外部送信は `--jev` を付けたときだけです）は、AI-PLC のリポジトリを checkout した場所で `./install.sh --target <プロジェクト> cc --with-jev --dry-run` を実行し、予定を確かめてから `--dry-run` を外します。入れたあとはビューアを起動し直してください
- `AIPLC_STATUS_AUDIT` で checkout の `experimental/jev/scripts/aiplc_status_audit.py` を指定しても使えます
- 環境変数でファイルを指定したのに見つからないときは、起動を止めます
- 見つけた `aiplc_status_audit.py` に必要な関数が欠けている（版が違う）・読み込めないときは、使わずに起動し、理由をヘッダの「閲覧のみ」バッジ（マウスを乗せると出ます）に書きます

## 画面の読み方

| 表示 | 意味 |
| --- | --- |
| 左の一覧 | Registry の Project です。`parent_scope` で親子を入れ子にしています。▾ で子をたたみます。薄い行は、絞り込み条件に合わないものの、子が条件に合うため残している親です |
| 並び順 | 「更新順（新しい順）」（既定）・「開始日順（従来）」・「ID順」から選べます。選んだ並び順はブラウザに保存されます。ID は数字の部分を数として比べます（`…-2` が `…-12` より前） |
| 作業記録の更新 | 更新順の根拠です。Layer の `backlog.yaml` と `context.yaml` のうち新しい方のローカルの保存時刻（両方無ければ `intent.yaml`）、Layer の無い Project は Registry の `created_at`（作業の更新は未確認）を、日本時間で出します。業務を実行した日時ではなく、checkout・touch・復元でも変わる目安です。Registry の更新・同期の時刻は使いません。親子の並びは保ったまま、条件に合う子の更新も親のグループの順位に反映します |
| status の絞り込み | 初期値は active です。cancelled（中止）も選べます。選んだ絞り込みと画面共有モードのオン・オフはブラウザに保存されます |
| 「食い違いあり」ボタン | `食い違い` か `status差` のある Project だけに絞ります（ステータス点検が見つかったときだけ出ます） |
| 進捗バー | 完了 / 対象のタスク数です。backlog.yaml にタスクがあればその数を使い、cancelled・dropped・deferred と運用タスク（`recurrence` のあるタスク）は数えません。backlog が無ければ Registry のタスク行をすべて数えます（タスク同期の凍結中は Registry のタスク行を読みません） |
| タスク表の「実行時期・期限」 | backlog.yaml のタスクの `scheduled_for`・`due` を書いたままの値で出します。運用タスクには「運用・<recurrence の値>」の印が付きます。どのタスクにも無ければ列は出ません |
| 中止の記録 | status が cancelled の Project は、詳細に intent.yaml の `cancellation`（理由・判断日・承認・保持した成果・置換先・再検討の条件）を出します。起動プロンプトは出しません（再開は `/plc-lifecycle`） |
| `status差` | intent.yaml と Registry の status が対応していない Project です（ステータス点検が見つかったときだけ出ます）。一致とみなす組み合わせ: active↔active、completed・done↔completed、deferred↔paused、blocked↔active、pending 系↔planned か active、paused↔paused、cancelled↔cancelled |
| `食い違い N` | ステータス点検（`aiplc_status_audit.py`）が出す候補の数です（閉じ忘れ・停滞・タスクの不一致など） |
| 🔒 | ステータス点検と同じ基準で機密と判定された Project、または機密の所属（分類）の Project です。迷うものは機密の側に倒すので、機密でない Project にも付くことがあります |
| 画面共有モード | 🔒 の Project の名前・goal・Layer パス・起動プロンプト・食い違いの理由・作業記録の更新・所属を伏せ、scope_id を `C-xxxxxxxx` にします。Program 別の表示では、私生活の Program（`display_group` が private）の名前をコード（`PG-xxxxxx`）にし、業務Project は名前を出さず `BIZ-xxxx` だけにします。ブラウザの表示を伏せるだけで（API の応答には含まれます）、ハッシュから元の ID を逆引きできるので秘匿化ではありません |
| 起動プロンプト | Claude Code の形式です。intent が completed なら Re-Collection の `/01-collection`、backlog が空なら `/02-inception`（ただし intent の `workflow_depth` が simple なら `/04-operation`）、運用タスクだけの Layer と、それ以外は `/04-operation` を出します。intent に `pipeline_variant: jev` があっても本体版のコマンドを出します（実験版の `-jev` コマンドは凍結中のため）。Cursor・Codex では、それぞれの起動形式に読み替えてください |

- 一覧の応答は、DB が変わっていなければ 15 秒のあいだ使い回します（Layer が多いと一覧の計算に数秒かかるため）。Layer の YAML の変更は、最長 15 秒遅れて反映されます。「再読み込み」でも同じです
- 一覧を作るたびに、全 Layer を読み直します

## Program 別の表示

core の `business_registry.py`（`.claude/db/business_registry.py`）で Program・業務Project を作り、AI-PLC の案件とつないでいると、ヘッダに「表示: 親子ツリー／Program別」の切り替えが出ます。Program 別では、Program → 主な業務Project → Project の順にまとめます（グループの中では親子の入れ子を保ちます）。どこにもつながっていない Project は「未紐付け」にまとめます。

出す条件（両方を満たすときだけ。満たさなければ今までどおりの一覧です）:

- DB に業務Project の4つの表（`programs`・`business_projects`・`program_memberships`・`business_project_links`）があること。`python3 .claude/db/business_registry.py init --yes` で作ります
- DB が Identity v2.0 であること（`projects` に `sync_uid` の列がある）。v1 の DB は `python3 .claude/db/sync.py adopt-existing --dry-run --decisions FILE --writer-id ID --plan-out FILE` で予定を作り、確かめてから `python3 .claude/db/sync.py adopt-existing --plan FILE --plan-id SHA256` で移します（`business_registry.py` も v2.0 の DB でしか動きません）

作り方の例（プロジェクトのフォルダで実行します。どれも `--yes` を付けたときだけ書き込みます）:

```bash
python3 .claude/db/business_registry.py add-program Sample --yes
python3 .claude/db/business_registry.py add-business Sample "合成の業務A" --purpose "目的を1行で" --yes
python3 .claude/db/business_registry.py link L-0000 "合成の業務A" --yes
```

- 私生活の Program は `add-program <名前> --private --yes` で分けます。画面共有モードで名前を伏せるのは、この私生活の Program だけです
- 主ではない関係は `link <scope_id> <業務Project> --related --yes` でつなぎます（詳細の「関連する業務Project」に出ます。件数には入れません）。外すときは `unlink`
- Program は、直接の所属（`program_memberships` の aiplc_project の行）があればそれを、無ければ主な業務Project の Program を使います（詳細に「主な業務Project 経由」と出ます）
- 紐付けは、つないだときの案件の ID（`aiplc_uid`）が今の `projects.sync_uid` と一致するものだけを採ります。一致しない行は採らずに数だけ数えます
- retired の Program・archived の業務Project・retired のつながりは出しません
- 一覧と確認は `python3 .claude/db/business_registry.py list` でもできます

## 分類（所属・種類・実行環境）

各 Project に「所属」（個人・会社・顧客など）、「種類」（開発・調査・コンテンツなど）、「実行環境」（claude-code・codex・cursor）を持たせ、一覧のバッジと絞り込みで見分けられるようにする仕組みです。`classify.py` がこのフォルダに入っています。使わなければ、今までどおりの表示です。**ビューアは分類を読むだけです。** 書き込みは `classify.py` を直接実行したときだけです。

**どこに書かれるか**

- 正本は Layer のファイルです。Registry はその写しです

```yaml
# intent.yaml（トップレベル）
classification:
  affiliation: private      # 所属（語彙のキー）
  kind: dev                 # 種類（語彙のキー）
  executor: claude-code     # この Layer を作った環境: claude-code / codex / cursor
```

```yaml
# backlog.yaml の各タスク
  - id: T003
    status: completed
    executed_by: codex      # そのタスクを実行した環境
```

- Registry（`ai_plc.db`）では、`project_classification`（Project ごと）と `task_execution`（タスクごと）という**別の表**に写します。projects / tasks の表の列は変えません
- この公開版では、core のスキル（`/01-collection`・`/04-operation`）は分類を自動では書きません。intent.yaml に手で書くか、下の `classify.py suggest` → `apply` で付けます

**語彙ファイル**

所属と種類の選択肢は、語彙ファイルで決めます。まずサンプルをコピーして書き換えます（コピーしないとサンプルがそのまま使われます）。

```bash
cp .claude/db/registry_viewer/classification_vocab.example.yaml .claude/db/registry_viewer/classification_vocab.yaml
```

- キーは英小文字・数字・ハイフンで、40字までです（先頭にハイフンは使えません）。intent.yaml と Registry に入るのはキーだけです
- **顧客・取引先のように名前そのものが機密のものは、`c1` のような意味の無いキーにし**、名前は `label` に書いて `confidential: true` を付けます。表示名はこのローカルのファイルにしか入りません。ビューアの画面共有モードでは、その Project を行ごと伏せます（伏せるのは画面の表示だけです）
- `keywords` は、既存の Project に後から付けるときの推定にだけ使います
- 別の場所のファイルを使うときは、環境変数 `AIPLC_CLASSIFICATION_VOCAB` で指定します。形式の確認は `python3 .claude/db/registry_viewer/classify.py vocab --check` です

**使い方**（プロジェクトのフォルダで実行します。`aiplc_status_audit.py`（Jev 実験版）が必要です）

分類の表を作ります。`classify.py` は Registry に書くので、先に下の「バックアップ」で DB の控えを取ってください。

```bash
python3 .claude/db/registry_viewer/classify.py migrate --yes
```

既存の Project に候補を出します。`.claude/db/status_hygiene/approvals/classify_<日付>.json` に、全行 `undecided` の承認ファイルができます。

```bash
python3 .claude/db/registry_viewer/classify.py suggest
```

承認ファイルを開き、正しい行の `decision` を `approve` にします（値は直してかまいません）。**推定はキーワードの一致だけなので、必ず確かめてください。** 予定を確かめてから反映します。

```bash
python3 .claude/db/registry_viewer/classify.py apply <承認ファイル>
```

```bash
python3 .claude/db/registry_viewer/classify.py apply <承認ファイル> --yes
```

intent.yaml を手で直したときは、Registry に写し直します（`--all` で全部の Layer）。

```bash
python3 .claude/db/registry_viewer/classify.py sync --layer <Layer のパス> --yes
```

一覧で確認するときは、次のコマンドを使います（`--reveal` を付けたときだけ機密の表示名が出ます）。

```bash
python3 .claude/db/registry_viewer/classify.py show
```

**安全の決まり**

- `migrate` / `sync` / `apply` は、`--yes` を付けたときだけ書き込みます
- `apply` は、提案の後に intent.yaml の分類が変わっていた行を書きません（`conflict`）。変わった Layer は、`suggest --scope <ID>` で出し直します
- intent.yaml は `classification` のブロックだけを書き換え、ほかが変わらないことを確かめてから置き換えます
- 同じ scope_id のフォルダが複数ある Layer、壊れた YAML の Layer は扱いません（報告に出ます）
- 記録は `.claude/db/status_hygiene/classify_log.jsonl` に残ります

**バックアップ**（`classify.py` で書く前）: DB は WAL モードなので、ファイルのコピーではなく SQLite のバックアップ機能を使います。`YYYYMMDD` は今日の日付にし、保存先は git で管理しない場所にします（`status_hygiene/` が無ければ先に `mkdir -p .claude/db/status_hygiene` で作ります）。

```bash
python3 -c "import sqlite3; s=sqlite3.connect('.claude/db/ai_plc.db'); d=sqlite3.connect('.claude/db/status_hygiene/ai_plc_backup_YYYYMMDD.db'); s.backup(d); d.close(); s.close()"
```

**ビューアでの見え方**

- 一覧の3行目に、所属・種類・実行環境のバッジが出ます。上の欄で絞り込めます。実行環境は、Layer の executor とタスクの executed_by のどれかに一致すれば表示されます。「未設定」も選べます
- 詳細に「分類」の行と、タスク表の「実行環境」の列が出ます
- 分類の表か classify.py が無ければ、分類は表示しません

## セキュリティ

- 127.0.0.1 でだけ待ち受けます。`Host` ヘッダが 127.0.0.1 か localhost でない要求は拒否します（DNS rebinding 対策）
- 受け付けるのは GET と HEAD だけです。それ以外の要求は、`Host`・`Origin` が正しくなければ 403、正しくても 405（`VIEWER_READ_ONLY`）で、何も書きません
- scope_id は英数字と `._-` だけを受け付けます
- DB は SQLite の読み取り専用のモード（`mode=ro`・`query_only`）で開きます

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
- サーバが動いているかは `/api/health` で確かめます（0.3.0-alpha〜。`/api/health` の無い古いサーバが動いているときだけ、一覧の応答で確かめます）
- すでにポート 8765 でサーバが動いていれば、それを使います（別のプロジェクトのサーバでも使ってしまいます。アプリを終了しても、そのサーバは止まりません）
- 起動に失敗したときは、ログの末尾を表示します。全体は `~/Library/Logs/AI-PLC Registry.log` にあります

## テスト

checkout のルートで実行します（インストールはされません）。一時ディレクトリの SQLite と Layer だけを使います。スキーマは `core/db/init_db.py`（日本語語彙）と、v1.14.0 までの公開版 init_db.py（英語語彙。`tests/db/fixtures/init_db_v1_14_0.py`）の両方で、閲覧と 405 を確かめます。Program 別の表示は `core/db/business_registry.py` の表の定義で合成の DB を作って確かめます。status_audit は `experimental/jev/scripts/` のものを自動で使います。分類（`classify.py`）のテストも同じコマンドで流れます。

```bash
python3 -m unittest discover -s experimental/registry-viewer/tests
```

- 画面の並べ替え・伏せ方のテストは `node` があるときだけ動きます（無ければ skip）
- v1.14.0 までのスキーマには cancelled が無いので、その組み合わせの中止のテスト1件は skip になります
- 別の場所の status_audit・init_db.py・business_registry.py で試すときは、`AIPLC_STATUS_AUDIT`・`AIPLC_CORE_INIT_DB`（今の init_db.py）・`AIPLC_INIT_DB`（v1.14.0 までの init_db.py）・`AIPLC_BUSINESS_REGISTRY` で指定します
- checkout の上のフォルダに AI-PLC のプロジェクト（`.claude/db/ai_plc.db`）があると、そのプロジェクトの status_audit を先に使います（DB は開きません）
