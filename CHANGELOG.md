# Changelog

AI-PLC の変更履歴です。版は2種類あり、別々に数えます。

| 版 | どこに出るか | 対象 |
| --- | --- | --- |
| **core の版**（例: `1.8.0`） | インストール先の `.ai-plc-version`、installer の `--help` | installer と、4ステージのスキル・rules・DB スクリプトなどの本体 |
| **実験版パッケージの版**（例: `1.8.0-exp.1`） | `experimental/jev/VERSION`、台帳の `package_version` | `--with-jev` を付けたときだけ入る Jev 監視（`experimental/jev/`） |

実験版の番号は core の版と連動しません。たとえば v1.8.0-exp.1 を入れた環境の `.ai-plc-version` は `1.7.1`（その時点の core の版）です。

この版より前の変更は、GitHub のリリースとタグを見てください。

## [1.8.0]

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

### 修正

- 旧版を引き取るとき、`.ai-plc-version` を台帳の管理ファイルに入れないようにしました。途中で失敗したときに、元に戻す処理と次回の再開が失敗することがありました（`.ai-plc-version` は版の目印として別に扱います）
- `core/skills/ai-plc/README.md` に残っていた、特定の組織の作業場所の名前や内部ページの ID を、中立的な説明に置き換えました

### 未対応・既知の点

- **Codex 用のスキル（`codex/skills/ai-plc/`）は、今回の core の変更をまだ取り込んでいません。** Codex 用は core とは別に管理しているコピーで、次の版以降で同期します
- 実験版パッケージ（`experimental/jev/`）の中の説明文には、「core の版は 1.7.1」「公開 core 2.4」などの古い版表記が残っています。インストール済みの実験版の中身を変えると、同じ版番号（1.8.0-exp.1）のまま中身が違うとして、実験版を入れた環境の更新が止まるため、次の実験版で直します。新しい版の関係はこのファイルと README を見てください
