# ai-plc-jev（実験版 1.12.0-exp.2）

公開 core の AI-PLC（`.claude/skills/ai-plc/`）と並べて使う、**Jev 監視つきの実験版**です。判断専用モデル **Jev**（TypeSafe）に「前の段階に戻るべき兆しがないか」などを1問だけ聞き、**1行のヒント**を出します。ヒントに作業を止める権限はなく、判断はメインのモデルとあなたが行います。

> 🧊 **1.12.0-exp.2 から、会話監視 hook と成功条件カバー判定は凍結中です。** 作者の試行で、会話監視は人が判定したヒントの約3分の2が外れ、成功条件カバー判定は役に立ったヒントがありませんでした。どちらも新しく有効にしないでください（カバー判定は `/02-inception-jev` から呼ばなくなりました。会話監視 hook を settings に登録している場合は外してかまいません）。スクリプトは残しますが、更新はしません。Backtrack の異常ヒント（5.5b・6b）とステータス点検は、これまでどおり使えます。

- **実験版です。** 仕様・コマンド名・ファイルの置き場所は予告なく変わることがあります。この実験版パッケージの版は 1.12.0-exp.2 で、公開 core 1.12.0 の上に作っています（前の実験版 1.12.0-exp.1 の次の版）。スキルは公開 core 1.12.0 のスキル（01-collection v2.2・02-inception v2.1・03-construction v2.3・04-operation v2.8）を元にしており、違いは Jev 部分だけです
- **本体（core）の SKILL・rules は書き換えません。** `/01-collection-jev`〜`/04-operation-jev` を使ったときだけ動きます。公開 core の `/01-collection`〜`/04-operation` の動きは変わりません
- **APIキーを登録しなければ、何も外部に送らず、すべて自動でスキップされます**

セットアップの詳細（キーの取り方・接続確認・環境変数）は `.claude/ai-plc-jev/scripts/README_jev.md`、ステータス点検は `.claude/ai-plc-jev/scripts/README_status_audit.md` にあります。

## 使い方

| Stage | コマンド | 公開 core との違い |
| --- | --- | --- |
| 1 | `/01-collection-jev` | intent.yaml に `jev_monitor` 欄を追加。送信禁止の区分に当たらなければ、有効にするかを1行で聞く。`pipeline_variant: jev` を記録する |
| 2 | `/02-inception-jev` | 公開 core の 02-inception を読む薄いラッパー（-jev 表記だけ）。成功条件カバー判定（`.claude/ai-plc-jev/scripts/jev_coverage_check.py`）は凍結中で呼ばない |
| 3 | `/03-construction-jev` | 要るときだけ（RUL_plc_adaptive §6）。公開 core の 03-construction を読む薄いラッパー（Jev の判定なし。Next Action の表記だけ。会話監視の有効化は凍結中） |
| 4 | `/04-operation-jev` | Phase 5.5b・6b で `.claude/ai-plc-jev/scripts/jev_bt_monitor.py` を呼び、異常ありなら1行ヒントを出す。判定ごとに採否を `--override` で記録する。Phase 7 のステータス点検は公開 core 04-operation v2.8 と同じ（点検ツール `aiplc_status_audit.py` はこのパッケージに同梱） |

- 既存の Layer で試す場合は、intent.yaml に `jev_monitor: true` を手で書き、Stage 4 を `/04-operation-jev` で回せばよい
- 判断ログは `.claude/db/jev_decisions.jsonl`、採否は `.claude/db/jev_overrides.jsonl` に出る（入力のハッシュと確率だけで、本文は残らない）
- 機密PJ・経費・人事・顧客名や人名・私生活に関わる Layer では有効にしない

### 公開 core との違い（Jev 部分だけ）

- **04-operation-jev** は公開 core 04-operation（v2.8）の全文に、次の Jev 部分だけを足したものです: ①冒頭の「Jev監視ルール」（core の rules は Jev 監視を実験版だけに限定しており、その具体的な手順をスキル本文で定める）②Phase 5.5b / 6b の Jev 呼び出し（core の「Jev を呼ばない」段落を置き換え）③未確認の Jev 判定の件数表示と回収 ④Next Action のコピペ用プロンプトを `-jev` 表記に ⑤自動完走中（RUL_plc_session §10 を指す /goal があるセッション）の Jev の扱い: 判定そのものは行い、採否の記録とコピペ用プロンプトへの貼り付けはせず、完了報告の冒頭に「🧭 未確認の Jev 判定: N件」と貼り付け用1行をまとめて出す（Jev監視ルールの例外）。このほかは、Phase 8 / 9-11 の参照先を本体側のパス（`.claude/skills/ai-plc/04-operation/`）に変えただけです
- **01-collection-jev** は公開 core 01-collection（v2.2）の全文に、Jev の opt-in 判定（core の「Collection では判定しない」段落を置き換え。自動完走中も opt-in は自動で承認しない）・intent.yaml の `jev_monitor` 欄のコメント・Next Action と自動で進める /goal 1行の `-jev` 表記を足したものです
- **02-inception-jev・03-construction-jev** は公開 core の 02-inception・03-construction をそのまま読む薄いラッパーで、差分だけを書いています

## ファイル（インストール後の配置）

| パス | 内容 |
| --- | --- |
| `.claude/skills/ai-plc-jev/01-collection-jev/SKILL.md` | 公開 core 01-collection v2.2 ＋ Jev の opt-in |
| `.claude/skills/ai-plc-jev/02-inception-jev/SKILL.md` | 公開 core 02-inception を読むラッパー（-jev 表記。カバー判定は凍結中） |
| `.claude/skills/ai-plc-jev/03-construction-jev/SKILL.md` | 公開 core 03-construction を読むラッパー |
| `.claude/skills/ai-plc-jev/04-operation-jev/SKILL.md` | 公開 core 04-operation v2.8 の全文＋ Jev 部分（上の①〜⑤）の自己完結の実験版 |
| `.claude/commands/01-collection-jev.md`〜`04-operation-jev.md` | 起動用のコマンド |
| `.claude/ai-plc-jev/scripts/` | `jev_client.py`・`jev_bt_monitor.py`・`jev_prompt_hook.py`・`jev_coverage_check.py`・`jev_regression_rank.py`・`aiplc_status_audit.py` と README 2 本・送信禁止語の例 |

入れ方は公開 README の実験版の節（`install-cc.sh --with-jev` または `install.sh cc --with-jev`。Claude Code 専用）を参照してください。テストはインストールされません（リポジトリの checkout で `JEV_DISABLE=1 python3 -m unittest discover -s experimental/jev/scripts/tests` を実行します）。

## 外部送信の内容

| 機能 | 送るもの | 送らないもの |
| --- | --- | --- |
| 5.5b / 6b の異常ヒント | ゴール1行（200字まで）・進捗（件数）・直近のタスク完了報告（backlog の `result`、無ければタスクの説明。1200字まで） | 上の項目以外のファイル（成果物・Context・コードなど）の中身、会話のやり取り |
| 会話監視 hook（凍結中・新しく有効にしなければ送らない） | 直前の発話1件の原文（空白を詰めて400字で切る）・ゴール1行（200字まで）・進捗（件数） | 貼り付けた長文、スラッシュコマンド、短い承認、「？」で終わる質問、ハーネスが差し込むメッセージ（既知の形式のみ。下の hook の節） |
| 成功条件カバー判定（凍結中・呼ばない） | ゴール1行（200字まで）・成功条件（全文）・各タスクの ID・名前・説明（説明は1件160字まで） | 上の項目以外のファイル（成果物・Context・コードなど）の中身、会話のやり取り |
| ステータス点検（`--jev` を付けたときだけ） | 停滞 Layer のゴール1行（200字まで）・最後に完了したタスクの名前と結果（結果は400字まで）・進捗・停滞日数 | 機密と判定した Layer、`jev_monitor: true` でない Layer |

- 送信先は、公式経路なら TypeSafe の1社、OpenRouter 経由なら OpenRouter と TypeSafe の2社です
- どの送信の前にも、送信禁止の語の検査（コードの汎用語＋ローカルの `.claude/db/jev_redact_extra.txt`）と命令文の除去が働きます。キーワードでの判定なので、言い換えた機密は通ります。**opt-in する Layer を選ぶことが一番の対策です**
- ローカルの送信禁止語ファイルは `.claude/ai-plc-jev/scripts/jev_redact_extra.example.txt` をコピーして作り、自分で `.gitignore` に足してください

## キー登録

公式（`TYPESAFE_API_KEY`）か OpenRouter（`OPENROUTER_API_KEY`）のどちらか一方でよく、`.env` やリポジトリ内のファイルには書きません。macOS ならキーチェーンに登録します。

```bash
security add-generic-password -a "$USER" -s OPENROUTER_API_KEY -w
python3 .claude/ai-plc-jev/scripts/jev_client.py --check
```

Linux / Windows / CI では環境変数で渡します（パスワードマネージャーの CLI などから読み込む書き方を推奨）。詳細は `.claude/ai-plc-jev/scripts/README_jev.md`。

## 止め方

| やりたいこと | 方法 |
| --- | --- |
| すぐに全部止める | 環境変数 `JEV_DISABLE=1`（Claude Code の起動前のシェルか settings の `env` に書き、セッションを開き直す。止まっている間は 5.5b / 6b とカバー判定の行が `skipped(unavailable:disabled)`、ステータス点検は「スキップ（unavailable）」、会話監視 hook は無出力） |
| 1つの Layer だけ止める | intent.yaml を `jev_monitor: false` に |
| 会話監視だけ止める（凍結中。登録済みの hook を外すとき） | `python3 .claude/ai-plc-jev/scripts/jev_prompt_hook.py --deactivate`。完全にやめるなら settings から hook を消す |
| 送信を完全にやめる | 登録したキーを消す（キーチェーンでも環境変数でも。両方のキーがあれば両方） |
| 実験版を外す | `uninstall.sh cc`（both / all も可）。実験版だけを外すオプションは無い。hook を settings に足した人は、そこからも消す。`.claude/db/jev_*`・`.claude/db/status_hygiene/`・自分で作った `jev_redact_extra.txt` は uninstall 後も残る（一覧・消し方・既知の制約は[AI-PLC 公開リポジトリの README](https://github.com/miyatti777/ai-plc#readme)の実験版の節） |

## 実験機能: 会話監視 hook（凍結中）

> 🧊 凍結中です。新しく登録しないでください。登録している場合は settings から hook を外してかまいません。下の表は記録として残します。

あなたの発話ごとに Jev へ「進捗の訂正・抜けの指摘・範囲の変更・懸念（遠回しも含む）を含むか」を1問だけ聞き、0.5以上なら Claude に1行のヒントを追加の文脈として渡します。**installer は hook を登録しません。** 使う人だけが手で settings に足します。

| 項目 | 仕様 |
| --- | --- |
| スクリプト | `.claude/ai-plc-jev/scripts/jev_prompt_hook.py`（Claude Code の `UserPromptSubmit` hook） |
| 登録先 | プロジェクトの `.claude/settings.local.json`（または `.claude/settings.json`）。コマンドは `python3 "$CLAUDE_PROJECT_DIR/.claude/ai-plc-jev/scripts/jev_prompt_hook.py" \|\| true` とし、スクリプトが無い場合でも exit 0 にする（UserPromptSubmit で exit 2 は入力をブロックするため）。ユーザー共通の `~/.claude/settings.json` には入れない。JSON の例は README_jev.md の §5 |
| 有効になる条件 | hook を登録したうえで、そのセッションで `/01〜04-*-jev` のいずれかを `Layer: <パス>` 付きで打ち、その Layer の intent.yaml に `jev_monitor: true` があるとき。**そのセッションだけ**が対象（session_id で紐づけ、12時間で失効） |
| 送らないもの | スラッシュコマンド、短い承認（OK / A / accept / はい など）、「？」で終わる質問、貼り付けた長文（`pasted_content`）、送信禁止の語を含む発話、ハーネスが差し込むメッセージ（サブエージェントの報告・タスク通知・システム通知・コマンド展開・別セッションからのメッセージ）。送るのは発話の本人の文（400字まで）とゴール1行・進捗だけ。**ハーネスのメッセージの除外は既知の形式を列挙する方式なので、未知の形式のメッセージは発話として送られることがあります** |
| 失敗時 | 常に exit 0 で何も出さない（入力をブロックしない）。Jev のタイムアウトは1.5秒 |
| 止め方 | `JEV_DISABLE=1`（Claude Code の起動前のシェルか settings の `env` に書き、セッションを開き直す）、または `python3 .claude/ai-plc-jev/scripts/jev_prompt_hook.py --deactivate`（全セッションの紐づけを外す。セッション ID を付けるとそのセッションだけ。次に `/0x-*-jev Layer: <パス>` を打つとまた有効になる） |
| 状態の確認 | `python3 .claude/ai-plc-jev/scripts/jev_prompt_hook.py --status` |
| 評価 | ヒントの行に出る decision_id で `python3 .claude/ai-plc-jev/scripts/jev_bt_monitor.py --override <id> accept\|reject`。集計は `--noise-report --use-case prompt_hook` |

## 検証結果の要約

作者の環境での試行結果です（この数字は保証ではありません）。

- 5.5b / 6b の異常ヒント: **判定 20 件**（機密でない実際の Layer 4 つ）で、人の確認による**外れ 0 件**。ヒントを出した判定のうち1件は、全完了時の GAP 分析のきっかけになった
- 費用と速さ: 判定1回あたり約 $0.00001〜0.00002、応答 0.3〜0.5 秒（OpenRouter 経由の実測）
- 公式 TypeSafe 経路は、公式ドキュメントに沿って実装しただけで、接続は未確認です
- 会話監視 hook は、人が判定したヒント15件のうち10件が外れ（却下率約67%）、継続の基準（30%以下）に届きませんでした。成功条件カバー判定は、出したヒントに役に立ったものがありませんでした。どちらも 1.12.0-exp.2 から凍結中です

## 試す人向けの確認観点

実験版を試したら、次の観点で結果を見てください（Issue での報告を歓迎します）。

1. **外れ率:** 各判定のあとに、妥当なら `--override <id> accept`、外れ（ヒントを出すべきでないのに出した／出すべきなのに出さなかった）なら `reject` を記録し、`python3 .claude/ai-plc-jev/scripts/jev_bt_monitor.py --noise-report` の1行目で外れ率を見る。目安は、判定 20 件以上で外れ 10% 以下。会話監視 hook は `--use-case prompt_hook` で、ヒント 20 件で却下率 30% 以下
2. **事故が 0 件か:** 送信禁止のデータを送っていない、ヒントがパイプラインを止めていない、ヒントを理由に reviewer や checker を省いていない
3. **役に立ったか:** 「ヒントのおかげで気づけた」例があるか、少なくとも邪魔ではなかったか

外れが多い場合は、どんな報告で外れたか（ノイズの型）を添えて報告してください。
