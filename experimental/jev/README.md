# experimental/jev — Jev 監視つき AI-PLC（実験版 1.8.1-exp.1）

AI-PLC の作業中に、判断専用モデル **Jev**（TypeSafe）で「前の段階に戻るべき兆し」などを安く速く見張り、**1行のヒント**を出す実験版パッケージです。ヒントに作業を止める権限はありません。

- **実験版です。** 通常のインストールには含まれません。このパッケージの版は `VERSION` の 1.8.1-exp.1 で（前の実験版 1.8.0-exp.1 の次の版）、core の版（1.8.1）とは別に数えます。core 1.8.1 の上に作っており、スキルは core 1.8.1 のスキルとの違いが Jev 部分だけです。前の版からの上げ方と直したことは公開 README の[実験版の節](../../README.md#-実験版-jev-監視)、版の関係は公開リポジトリの `CHANGELOG.md`
- **入れ方:** `./install-cc.sh --target <プロジェクト> --with-jev`（または `./install.sh --target <プロジェクト> cc --with-jev`。both / all も可）。**Claude Code 専用**で、cursor / codex だけの指定に `--with-jev` を付けると何も入れずに終了コード 2 になります。`--with-jev` を付けないインストールの結果は変わりません
- **使い方:** `/01-collection-jev` → `/02-inception-jev` → `/03-construction-jev` → `/04-operation-jev`。新しい Layer では `/01-collection-jev` の最後に Jev 監視を有効にするか聞かれ、承認すると intent.yaml に `jev_monitor: true` が書かれます（既存の Layer は手で書く）。公開 core のコマンドとスキルは書き換えません。Jev への問い合わせは `/0x-*-jev` のときだけで、core の `/01-collection`〜`/04-operation` は Jev を呼びません。例外はステータス点検で、core 1.8.0 からは core の `/04-operation` の Phase 7 でも、このパッケージを入れてあれば `aiplc_status_audit.py --brief` が動きます（ローカルで読むだけ・外部送信なし）
- **外部送信:** Layer の intent.yaml で `jev_monitor: true` にしたときだけ、Layer の文を字数で切ったもの（要約ではなく原文の抜粋: ゴール1行 200字まで・進捗の件数・backlog の直近の完了報告 1200字まで・カバー判定では成功条件と各タスクの名前と説明 160字まで・会話監視 hook では直前の発話の原文 400字まで）を Jev に送ります（それ以外のファイルや会話のやり取りは送りません。公式経路なら TypeSafe、OpenRouter 経由なら OpenRouter と TypeSafe）。APIキーを登録しなければ何も送りません。ステータス点検は、`--jev` を付けたとき（例: `python3 .claude/ai-plc-jev/scripts/aiplc_status_audit.py --jev --layer <Layer パス>`）に `jev_monitor: true` で機密でない停滞 Layer だけについて、ゴール1行・最後に完了したタスクの名前と結果（400字まで）・進捗・停滞日数を送ります。会話監視 hook は installer が登録せず、使う人が手で settings に足し、セッションで `/0x-*-jev Layer: <パス>` を打ったときだけ動きます（ハーネスが差し込むメッセージの除外は既知の形式の列挙なので、未知の形式は送られることがあります）。送る前の送信禁止語の検査はキーワード判定なので、言い換えた機密は通ります。機密に関わる Layer では有効にしないでください
- **止め方:** `JEV_DISABLE=1`（Claude Code を起動する前のシェルか、プロジェクトの `.claude/settings.local.json` の `env` に書き、セッションを開き直す）、Layer の `jev_monitor: false`、会話監視だけなら `python3 .claude/ai-plc-jev/scripts/jev_prompt_hook.py --deactivate`（完全にやめるなら settings から hook を消す）、送信を完全にやめるならキーの削除（キーチェーンでも環境変数でも。両方のキーがあれば両方）。経路を固定したいときは `JEV_PROVIDER=openrouter` / `typesafe`。詳しくは公開 README の実験版の節
- **採否の記録:** 判定ごとに `python3 .claude/ai-plc-jev/scripts/jev_bt_monitor.py --override <decision_id> accept|reject`。記録漏れは `--pending --layer <Layer パス>` で一覧（貼り付け用の1行つき）、まとめて記録するなら一覧で見た ID を渡して `--override-pending accept --layer <Layer パス> --only <ID>・<ID> [--except <ID> ...]`
- **外し方:** `./uninstall.sh --target <プロジェクト> cc`（both / all も可）で core と一緒に消えます（実験版だけを外すオプションはありません）。`.claude/db/jev_*` などの生成データは残ります。残るデータの一覧と消し方、中断した uninstall の後片付け（この版から cc を含む uninstall で掃除します）は、公開 README の[実験版の節](../../README.md#-実験版-jev-監視)にあります

詳細:

| 知りたいこと | 読むもの |
| --- | --- |
| 何が変わるか・外部送信の内容・止め方・検証結果の要約 | `experimental/jev/skills/ai-plc-jev/README.md` |
| キーの登録・接続確認・.gitignore に足す行・環境変数 | `experimental/jev/scripts/README_jev.md` |
| ステータス点検（`/04-operation-jev` と core 1.8.0 以降の `/04-operation` の Phase 7） | `experimental/jev/scripts/README_status_audit.md` |

テスト（インストールはされません。checkout のルートで実行。pyyaml が無い環境では該当テストが skip になります）:

```bash
JEV_DISABLE=1 python3 -m unittest discover -s experimental/jev/scripts/tests
```
