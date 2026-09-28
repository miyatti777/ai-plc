# experimental/jev — Jev 監視つき AI-PLC（実験版 1.8.0-exp.1）

AI-PLC の作業中に、判断専用モデル **Jev**（TypeSafe）で「前の段階に戻るべき兆し」などを安く速く見張り、**1行のヒント**を出す実験版パッケージです。ヒントに作業を止める権限はありません。

- **実験版です。** 通常のインストールには含まれません。core の版は 1.7.1 のままで、このパッケージの版が `VERSION` の 1.8.0-exp.1 です
- **入れ方:** `./install-cc.sh --with-jev`（または `./install.sh cc --with-jev`）。Claude Code 専用です。`--with-jev` を付けないインストールの結果は変わりません
- **使い方:** `/01-collection-jev` → `/02-inception-jev` → `/03-construction-jev` → `/04-operation-jev`。公開 core のコマンドとスキルは書き換えません
- **外部送信:** Layer の intent.yaml で `jev_monitor: true` にしたときだけ、ゴール1行・進捗・直近のタスク報告など短い要約を Jev に送ります（公式経路なら TypeSafe、OpenRouter 経由なら OpenRouter と TypeSafe）。APIキーを登録しなければ何も送りません
- **止め方:** `JEV_DISABLE=1`、Layer の `jev_monitor: false`、またはキーの削除

詳細:

| 知りたいこと | 読むもの |
| --- | --- |
| 何が変わるか・外部送信の内容・止め方・検証結果の要約 | `experimental/jev/skills/ai-plc-jev/README.md` |
| キーの登録・接続確認・.gitignore に足す行・環境変数 | `experimental/jev/scripts/README_jev.md` |
| ステータス点検（Phase 7） | `experimental/jev/scripts/README_status_audit.md` |

テスト（インストールはされません。checkout のルートで実行。pyyaml が無い環境では該当テストが skip になります）:

```bash
JEV_DISABLE=1 python3 -m unittest discover -s experimental/jev/scripts/tests
```
