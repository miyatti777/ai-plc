# experimental/jev — Jev 監視つき AI-PLC（実験版 1.8.0-exp.1）

AI-PLC の作業中に、判断専用モデル **Jev**（TypeSafe）で「前の段階に戻るべき兆し」などを安く速く見張り、**1行のヒント**を出す実験版パッケージです。ヒントに作業を止める権限はありません。

- **実験版です。** 通常のインストールには含まれません。core の版は 1.7.1 のままで、このパッケージの版が `VERSION` の 1.8.0-exp.1 です
- **入れ方:** `./install-cc.sh --target <プロジェクト> --with-jev`（または `./install.sh --target <プロジェクト> cc --with-jev`。both / all も可）。**Claude Code 専用**で、cursor / codex だけの指定に `--with-jev` を付けると何も入れずに終了コード 2 になります。`--with-jev` を付けないインストールの結果は変わりません
- **使い方:** `/01-collection-jev` → `/02-inception-jev` → `/03-construction-jev` → `/04-operation-jev`。新しい Layer では `/01-collection-jev` の最後に Jev 監視を有効にするか聞かれ、承認すると intent.yaml に `jev_monitor: true` が書かれます（既存の Layer は手で書く）。公開 core のコマンドとスキルは書き換えません
- **外部送信:** Layer の intent.yaml で `jev_monitor: true` にしたときだけ、ゴール1行・進捗・直近のタスク報告など短い要約を Jev に送ります（公式経路なら TypeSafe、OpenRouter 経由なら OpenRouter と TypeSafe）。APIキーを登録しなければ何も送りません。ステータス点検は、`--jev` を付けたときに `jev_monitor: true` の Layer だけを送ります。会話監視 hook は installer が登録せず、使う人が手で settings に足し、セッションで `/0x-*-jev Layer: <パス>` を打ったときだけ動きます（ハーネスが差し込むメッセージの除外は既知の形式の列挙なので、未知の形式は送られることがあります）
- **止め方:** `JEV_DISABLE=1`（Claude Code を起動する前のシェルか、プロジェクトの `.claude/settings.local.json` の `env` に書き、セッションを開き直す）、Layer の `jev_monitor: false`、会話監視だけなら `python3 .claude/ai-plc-jev/scripts/jev_prompt_hook.py --deactivate`（完全にやめるなら settings から hook を消す）、送信を完全にやめるならキーの削除（キーチェーンでも環境変数でも。両方のキーがあれば両方）。経路を固定したいときは `JEV_PROVIDER=openrouter` / `typesafe`。詳しくは公開 README の実験版の節
- **外し方:** `./uninstall.sh --target <プロジェクト> cc`（both / all も可）で core と一緒に消えます（実験版だけを外すオプションはありません）。`.claude/db/jev_*` などの生成データは残ります。残るデータの一覧と消し方、uninstall の後片付けが残る既知の制約は、公開 README の[実験版の節](../../README.md#-実験版-jev-監視v180-exp1)にあります

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
