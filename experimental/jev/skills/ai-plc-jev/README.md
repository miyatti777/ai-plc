# ai-plc-jev（実験版 1.8.0-exp.1）

公開 core の AI-PLC（`.claude/skills/ai-plc/`）と並べて使う、**Jev 監視つきの実験版**です。判断専用モデル **Jev**（TypeSafe）に「前の段階に戻るべき兆しがないか」などを1問だけ聞き、**1行のヒント**を出します。ヒントに作業を止める権限はなく、判断はメインのモデルとあなたが行います。

- **実験版です。** 仕様・コマンド名・ファイルの置き場所は予告なく変わることがあります。core の版は 1.7.1 のままで、この実験版パッケージの版が 1.8.0-exp.1 です
- **本体（core）の SKILL・rules は書き換えません。** `/01-collection-jev`〜`/04-operation-jev` を使ったときだけ動きます。公開 core の `/01-collection`〜`/04-operation` の動きは変わりません
- **APIキーを登録しなければ、何も外部に送らず、すべて自動でスキップされます**

セットアップの詳細（キーの取り方・接続確認・環境変数）は `.claude/ai-plc-jev/scripts/README_jev.md`、ステータス点検は `.claude/ai-plc-jev/scripts/README_status_audit.md` にあります。

## 使い方

| Stage | コマンド | 公開 core との違い |
| --- | --- | --- |
| 1 | `/01-collection-jev` | intent.yaml に `jev_monitor` 欄を追加。送信禁止の区分に当たらなければ、有効にするかを1行で聞く。`pipeline_variant: jev` を記録する |
| 2 | `/02-inception-jev` | 公開 core の 02-inception を読む薄いラッパー。**分解承認（Phase 4）の前に Jev 成功条件カバー判定**（`.claude/ai-plc-jev/scripts/jev_coverage_check.py`）を1回行い、どのタスクにも対応しない成功条件をヒントとして示す |
| 3 | `/03-construction-jev` | 公開 core の 03-construction を読む薄いラッパー（Jev の判定なし。Next Action の表記と会話監視の有効化だけ） |
| 4 | `/04-operation-jev` | Phase 5.5b・6b で `.claude/ai-plc-jev/scripts/jev_bt_monitor.py` を呼び、異常ありなら1行ヒントを出す。判定ごとに採否を `--override` で記録する。Phase 7 にステータス点検（`aiplc_status_audit.py --brief --layer`）を足す |

- 既存の Layer で試す場合は、intent.yaml に `jev_monitor: true` を手で書き、Stage 4 を `/04-operation-jev` で回せばよい
- 判断ログは `.claude/db/jev_decisions.jsonl`、採否は `.claude/db/jev_overrides.jsonl` に出る（入力のハッシュと確率だけで、本文は残らない）
- 機密PJ・経費・人事・顧客名や人名・私生活に関わる Layer では有効にしない

### 04-operation-jev と公開 core 04-operation（v2.4）の違い

1. Jev 監視（Phase 5.5b / 6b。opt-in）。規定はスキル本文の「Jev監視ルール」に全文で書いてあり、公開 core の rules には依存しない
2. Phase 7 のステータス点検（8項目目）。公開 core の RUL_plc_system §8 は7項目のままで、8項目目はスキル本文で定義する
3. Phase 5.5 の独立 reviewer 起動を明示的な実行要求にし、未解決 P0/P1/P2 を完了ゲートにした（公開 RUL_plc_system §18 の停止条件に沿ったもの。公開 core 2.4 では P2 の持ち越しを許す）
4. type 別レンズ表に「validation / review は対象外」の行を足し、最近縁フォールバックの書き方を変えた

このほかは、Phase 8 / 9-11 の参照先を本体側のパス（`.claude/skills/ai-plc/04-operation/`）に変えただけです。01-collection-jev は公開 core 01-collection（v2.0）に Jev の段落を足したものです。

## ファイル（インストール後の配置）

| パス | 内容 |
| --- | --- |
| `.claude/skills/ai-plc-jev/01-collection-jev/SKILL.md` | 公開 core 01-collection v2.0 ＋ Jev の opt-in |
| `.claude/skills/ai-plc-jev/02-inception-jev/SKILL.md` | 公開 core 02-inception を読むラッパー（カバー判定） |
| `.claude/skills/ai-plc-jev/03-construction-jev/SKILL.md` | 公開 core 03-construction を読むラッパー |
| `.claude/skills/ai-plc-jev/04-operation-jev/SKILL.md` | 公開 core 04-operation v2.4 を元にした自己完結の実験版（上の4点） |
| `.claude/commands/01-collection-jev.md`〜`04-operation-jev.md` | 起動用のコマンド |
| `.claude/ai-plc-jev/scripts/` | `jev_client.py`・`jev_bt_monitor.py`・`jev_prompt_hook.py`・`jev_coverage_check.py`・`jev_regression_rank.py`・`aiplc_status_audit.py` と README 2 本・送信禁止語の例 |

入れ方は公開 README の実験版の節（`install-cc.sh --with-jev` または `install.sh cc --with-jev`。Claude Code 専用）を参照してください。テストはインストールされません（リポジトリの checkout で `JEV_DISABLE=1 python3 -m unittest discover -s experimental/jev/scripts/tests` を実行します）。

## 外部送信の内容

| 機能 | 送るもの | 送らないもの |
| --- | --- | --- |
| 5.5b / 6b の異常ヒント | ゴール1行・進捗（件数）・直近のタスク完了報告（1200字まで） | ファイルの中身、会話の全文 |
| 会話監視 hook | あなたの発話（400字まで）・ゴール1行・進捗 | 貼り付けた長文、スラッシュコマンド、短い承認、「？」で終わる質問、ハーネスが差し込むメッセージ（既知の形式のみ。下の hook の節） |
| 成功条件カバー判定 | ゴール1行・成功条件・タスク名と説明（160字まで） | ファイルの中身 |
| ステータス点検（`--jev` を付けたときだけ） | 停滞 Layer のゴール1行・最後に完了したタスク・進捗・停滞日数 | 機密と判定した Layer、`jev_monitor: true` でない Layer |

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
| すぐに全部止める | 環境変数 `JEV_DISABLE=1` |
| 1つの Layer だけ止める | intent.yaml を `jev_monitor: false` に |
| 会話監視だけ止める | `python3 .claude/ai-plc-jev/scripts/jev_prompt_hook.py --deactivate`。完全にやめるなら settings から hook を消す |
| 送信を完全にやめる | 登録したキーを消す |
| 実験版を外す | `uninstall.sh cc`（both / all も可）。実験版だけを外すオプションは無い。hook を settings に足した人は、そこからも消す。`.claude/db/jev_*`・`.claude/db/status_hygiene/`・自分で作った `jev_redact_extra.txt` は uninstall 後も残る（一覧・消し方・既知の制約は公開 README の実験版の節: https://github.com/miyatti777/ai-plc#-実験版-jev-監視v180-exp1） |

## 実験機能: 会話監視 hook（任意）

あなたの発話ごとに Jev へ「進捗の訂正・抜けの指摘・範囲の変更・懸念（遠回しも含む）を含むか」を1問だけ聞き、0.5以上なら Claude に1行のヒントを追加の文脈として渡します。**installer は hook を登録しません。** 使う人だけが手で settings に足します。

| 項目 | 仕様 |
| --- | --- |
| スクリプト | `.claude/ai-plc-jev/scripts/jev_prompt_hook.py`（Claude Code の `UserPromptSubmit` hook） |
| 登録先 | プロジェクトの `.claude/settings.local.json`（または `.claude/settings.json`）。コマンドは `python3 "$CLAUDE_PROJECT_DIR/.claude/ai-plc-jev/scripts/jev_prompt_hook.py" \|\| true` とし、スクリプトが無い場合でも exit 0 にする（UserPromptSubmit で exit 2 は入力をブロックするため）。ユーザー共通の `~/.claude/settings.json` には入れない。JSON の例は README_jev.md の §5 |
| 有効になる条件 | hook を登録したうえで、そのセッションで `/01〜04-*-jev` のいずれかを `Layer: <パス>` 付きで打ち、その Layer の intent.yaml に `jev_monitor: true` があるとき。**そのセッションだけ**が対象（session_id で紐づけ、12時間で失効） |
| 送らないもの | スラッシュコマンド、短い承認（OK / A / accept / はい など）、「？」で終わる質問、貼り付けた長文（`pasted_content`）、送信禁止の語を含む発話、ハーネスが差し込むメッセージ（サブエージェントの報告・タスク通知・システム通知・コマンド展開・別セッションからのメッセージ）。送るのは発話の本人の文（400字まで）とゴール1行・進捗だけ。**ハーネスのメッセージの除外は既知の形式を列挙する方式なので、未知の形式のメッセージは発話として送られることがあります** |
| 失敗時 | 常に exit 0 で何も出さない（入力をブロックしない）。Jev のタイムアウトは1.5秒 |
| 止め方 | `JEV_DISABLE=1`、または `python3 .claude/ai-plc-jev/scripts/jev_prompt_hook.py --deactivate` |
| 状態の確認 | `python3 .claude/ai-plc-jev/scripts/jev_prompt_hook.py --status` |
| 評価 | ヒントの行に出る decision_id で `python3 .claude/ai-plc-jev/scripts/jev_bt_monitor.py --override <id> accept\|reject`。集計は `--noise-report --use-case prompt_hook` |

## 検証結果の要約

作者の環境での試行結果です（この数字は保証ではありません）。

- 5.5b / 6b の異常ヒント: **判定 20 件**（機密でない実際の Layer 4 つ）で、人の確認による**外れ 0 件**。ヒントを出した判定のうち1件は、全完了時の GAP 分析のきっかけになった
- 費用と速さ: 判定1回あたり約 $0.00001〜0.00002、応答 0.3〜0.5 秒（OpenRouter 経由の実測）
- 公式 TypeSafe 経路は、公式ドキュメントに沿って実装しただけで、接続は未確認です
- 会話監視 hook と成功条件カバー判定は、件数がまだ少なく評価中です

## 試す人向けの確認観点

実験版を試したら、次の観点で結果を見てください（Issue での報告を歓迎します）。

1. **外れ率:** 各判定のあとに、妥当なら `--override <id> accept`、外れ（ヒントを出すべきでないのに出した／出すべきなのに出さなかった）なら `reject` を記録し、`python3 .claude/ai-plc-jev/scripts/jev_bt_monitor.py --noise-report` の1行目で外れ率を見る。目安は、判定 20 件以上で外れ 10% 以下。会話監視 hook は `--use-case prompt_hook` で、ヒント 20 件で却下率 30% 以下
2. **事故が 0 件か:** 送信禁止のデータを送っていない、ヒントがパイプラインを止めていない、ヒントを理由に reviewer や checker を省いていない
3. **役に立ったか:** 「ヒントのおかげで気づけた」例があるか、少なくとも邪魔ではなかったか

外れが多い場合は、どんな報告で外れたか（ノイズの型）を添えて報告してください。
