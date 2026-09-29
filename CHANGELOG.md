# Changelog

AI-PLC の変更履歴です。版は2種類あり、別々に数えます。

| 版 | どこに出るか | 対象 |
| --- | --- | --- |
| **core の版**（例: `1.8.0`） | インストール先の `.ai-plc-version`、installer の `--help` | installer と、4ステージのスキル・rules・DB スクリプトなどの本体 |
| **実験版パッケージの版**（例: `1.8.0-exp.1`） | `experimental/jev/VERSION`、台帳の `package_version` | `--with-jev` を付けたときだけ入る Jev 監視（`experimental/jev/`） |

実験版の番号は core の版と連動しません。たとえば v1.8.0-exp.1 を入れた環境の `.ai-plc-version` は `1.7.1`（その時点の core の版）です。

この版より前の変更は、GitHub のリリースとタグを見てください。

## [実験版 1.8.1-exp.1] - 2026-09-29

実験版パッケージ（`experimental/jev/`、`--with-jev` のときだけ入る）の新しい版です。前の実験版 1.8.0-exp.1 の次の版で、**core の版は 1.8.1 のまま**です（installer の `--help` の表示も `v1.8.1`）。頭の `1.8.1` はこの実験版を作った時点の core の版、末尾の `exp.1` はその上での通し番号です。1.8.0 の「未対応・既知の点」に書いた、実験版の古い版表記と uninstall の後片付けの制約は、この版で直しました。

### 実験版パッケージ

- スキル（`/01-collection-jev`〜`/04-operation-jev`）を core 1.8.1 のスキル（`01-collection` 2.1・`04-operation` 2.7）に揃えました。core のスキルとの違いは Jev 部分だけです。説明文の古い版表記（「core の版は 1.7.1」など）も直しました
- `jev_bt_monitor.py --override-pending`: `--only` / `--except` の指定で記録対象が0件になったとき、「未確認の Jev 判定なし」ではなく「記録対象なし（未確認は N件残っています・…）」と出します。`--layer` に Layer パスでも scope_id の形でもない値を渡すと「Layer の scope_id が読めません」と出します
- `/02-inception-jev`: カバー判定の採否の記録を、タスクの実行より先に行うことを明記しました
- ステータス点検（`aiplc_status_audit.py`）: Registry のタスク ID が `<scope_id>-T001` の形でも、backlog の `T001` と同じタスクとして突き合わせます（前は「タスク行なし」と誤って出ていました）
- `KNOWN_RELEASES.sha256` に 1.8.0-exp.1 の配布物のハッシュを追加しました。1.8.0-exp.1 から上げたときや、中断した後処理の残り物を掃除するときの照合に使います

### installer（`lib/ai_plc_multi_env.py`）

- 実験版の uninstall の後処理（`.bak` と空ディレクトリの掃除）の最中にプロセスが落ち、次が codex 経路（`install.sh codex` / `install-codex.sh`）だった場合に、実験版の `.bak` とディレクトリが残っていました。cc を含む uninstall（`cc` / `both` / `all`）のときに、中身が既知の版か今の配布物と一致する `.bak` と、それで空になった実験版のディレクトリを掃除します。一致しないものは残して `[WARN]` に件数を出します。台帳が無くて uninstall がエラーで止まる環境でも、残り物だけ掃除してから同じエラーで止まります
- 後処理の再開中にもう一度落ちると、再開の情報が失われていました。再開の情報を先に保存してから後処理するようにしました
- **実験版の残り物が無い環境では、動きは今までと同じです**（`--with-jev` を付けない install・uninstall の出力・終了コードも同じ）。残り物がある環境で cc を含む uninstall のときに掃除することは、意図した変更です。install・`--dry-run`・`--plan-only`・cursor / codex だけの uninstall では掃除しません
- `tests/installers/README.md`: `test_with_jev.py` は git の履歴を読むため、完全な clone が必要なことを書きました

### 上げ方

`./install.sh --target <プロジェクト> cc --with-jev`（先に `--dry-run` で確認できます）。core も 1.8.1 に上がります。`--with-jev` を付けずに更新すると、実験版は 1.8.0-exp.1 のまま残ります。手順の詳細は README の実験版の節にあります。

## [1.8.1] - 2026-09-29

### 修正

- `plc_query.py dashboard` のタスク集計が、日本語の状態（`未着手`・`進行中`・`完了`）で数えていたため、完了したタスクがあっても `0 done` と表示されていました。DB のタスクの状態は `planned` / `active` / `completed` / `paused` しか受け付けないので、todo = `planned`、WIP = `active`、done = `completed` で数えるように直しました（v1.2.0 からの不具合。DB の中身は変わりません）

## [1.8.0] - 2026-09-29

実験版パッケージは **1.8.0-exp.1 のまま**です（中身も変えていません）。

### 追加: 旧版からのアップデート

- **旧版（v1.1.0〜v1.6.0）の自動判別と移行。** 台帳（`.ai-plc-install-manifest`）のない旧版は、どれも `.ai-plc-version` が `1.1.0` と出るため、版番号では本当の版が分かりませんでした。installer が、入っているファイルの中身を旧版ごとの一覧（`migration/legacy-releases/`）と照らし合わせて版を判別し、フラグなしで更新できるようになりました。中身が同じ版（例: v1.2.1〜v1.4.1）はまとめて扱います。判別の結果は `[INFO] legacy release detected: …` と、`--dry-run` の `legacy_release` に出ます
- **`--backup-modified`（新しいオプション）。** 自分で編集したファイルがあると、installer は今までどおり何も書き換えずに止まります。このオプションを付けると、編集したファイルを `<path>.bak.<UTC>.<n>` に退避してから更新します。退避したファイルは `[BACKUP]` 行と、台帳の `user_backups` に記録されます。`cc` / `cursor` / `both` / `all` で使えます。**Codex だけの指定（`codex`）では使えません**（終了コード 2）。Codex 対応は v1.7.0 からで、Codex だけの環境には台帳のない旧版が無いためです
- 手順は README の「アップデート手順」にあります

### 変更: core（スキル・rules）

- rules: `ai-plc-system` 2.1（Phase 7 のチェックリストに8項目目「ステータス点検」を追加）、`ai-plc-adaptive` 2.2（Jev 監視は実験版の `/0x-*-jev` だけで、core からは呼ばないことを明記）
- skills: `01-collection` 2.1（Registry への登録を `plc_query.py` 経由に。intent.yaml の `jev_monitor` 欄は core では常に false）、`03-construction` 2.2（すべての Agent 定義に独立レビューの約束を入れる）、`04-operation` 2.7（独立 reviewer の起動を明示し、未解決の P0/P1/P2 を完了の条件に。Phase 7 にステータス点検）
- **core は Jev を呼びません（外部送信なし）。** ステータス点検は、実験版（`--with-jev`）を入れた環境でだけ動き、ローカルで読むだけです。実験版が無い環境では「点検ツールなし — スキップ」と出して進みます
- Cursor の `ai-plc-system.mdc` にも、Propagation の項目としてステータス点検を追加しました（点検ツールは Claude Code 用の実験版にしか入らないため、Cursor だけの環境では常にスキップになります）

### 同梱: Registry ビューア（アルファ版・installer 対象外）

- `experimental/registry-viewer/` を **0.1.1-alpha** に更新（db8c136 で 0.1.0-alpha を追加、fbfce4c で更新）。空のプロジェクトに入れた試用の結果を README に反映（ポート使用中の対処・`.gitignore` が無いとき・バックアップ名・フル機能にする手順・止め方）、変更記録の時刻にタイムゾーン、simple 深度で backlog が空の Layer の起動プロンプトを `/04-operation` に

### 修正

- 旧版を引き取るとき、`.ai-plc-version` を台帳の管理ファイルに入れないようにしました。途中で失敗したときに、元に戻す処理と次回の再開が失敗することがありました（`.ai-plc-version` は版の目印として別に扱います）
- `core/skills/ai-plc/README.md` に残っていた、特定の組織の作業場所の名前や内部ページの ID を、中立的な説明に置き換えました

### 未対応・既知の点

- **Codex 用のスキル（`codex/skills/ai-plc/`）は、今回の core の変更をまだ取り込んでいません。** Codex 用は core とは別に管理しているコピーで、次の版以降で同期します
- 実験版パッケージ（`experimental/jev/`）の中の説明文には、「core の版は 1.7.1」「公開 core 2.4」などの古い版表記が残っています。インストール済みの実験版の中身を変えると、同じ版番号（1.8.0-exp.1）のまま中身が違うとして、実験版を入れた環境の更新が止まるため、次の実験版で直します。新しい版の関係はこのファイルと README を見てください
