---
name: plc-someday
description: AI-PLCの「いつかやるPJストック」。思いついた将来やりたいPJを Registry に貯め（Layerは作らない）、暇なときに一覧から1件選んで Collection の起動プロンプトにする。「いつかやりたい」「将来やりたいPJをためておいて」「いつかやるリスト見せて」「ストックから次やるの選びたい」で使う。
---

# plc-someday（いつかやるPJストック）

> 論理名: SKL_plc_someday ／ 包むもの: `.claude/db/plc_query.py` の someday 系コマンド（挙動は変えない）

## 何をするスキルか

- **ためる:** 思いつきを1行で Registry（`.claude/db/ai_plc.db` の projects）に置く。仮ID `S-MMDD`（同じ日の2件目から `S-MMDD-2` …）が自動で付き、状態は `planned`。Layer フォルダは作らない
- **見る:** ストック（`planned` かつ `S-` 始まり）を登録日の古い順に一覧する
- **始める:** 1件選ぶと、ストック行を `completed` に閉じ、`/01-collection` のコピペ用プロンプトを出す（実験版 `-jev` は凍結中）。正式な `L-MMDD` は Collection が新しく採る
- **戻す:** 始めるのをやめたときは、ストックに戻す

ストックは `aiplc_status_audit.py`（ステータス点検）には出ない。

## 使い方（引数で切り替える）

| 呼び方 | 動作 |
| --- | --- |
| `/plc-someday` | 一覧 |
| `/plc-someday <やりたいこと>`（例: `/plc-someday Notionからもアイデアを入れたい`） | 登録 |
| `/plc-someday start <S-ID>` | 着手（`/01-collection` のプロンプト。旧フラグ `--no-jev` は受け付けるが効果なし） |
| `/plc-someday revert <S-ID>` | 着手の取り消し |

## 実行手順

リポジトリのルートで実行する。

1. **一覧**（引数なし）
   ```bash
   python3 .claude/db/plc_query.py someday
   ```
   0件なら「ストックは空です」と伝え、登録の例を1行示す。1件以上なら表をそのまま見せ、「着手するなら `/plc-someday start <S-ID>`」と添える。どれを選ぶかは人が決める（AI が選ばない）

2. **登録**（引数が文）
   1. 入力をタイトル（全角25文字以内の「やりたいこと」1行）と、背景のメモに分ける。ユーザーが書いた固有名はそのまま残す
   2. 規模を確かめる: 1回の作業で終わる小さなこと（雑務）なら、ストックではなく、あなたの TODO 管理（AI-PLC の範囲外）に書くよう勧めて止める。着手するなら Layer を切る規模なら次へ
   3. 登録する
      ```bash
      python3 .claude/db/plc_query.py someday-add "<タイトル>" "<メモ>"
      ```
   4. 出力の `[OK] Someday added: S-xxxx - …` をそのまま伝える

3. **着手**（`start <S-ID>`）
   ```bash
   python3 .claude/db/plc_query.py someday-start <S-ID>
   ```
   出力のコピペ用プロンプトを**コードブロックに入れずに**そのまま示す。ここで Collection を実行しない（貼るのは人）

4. **取り消し**（`revert <S-ID>`）
   ```bash
   python3 .claude/db/plc_query.py someday-revert <S-ID>
   ```

## 注意

- 登録・着手・取り消しは Registry に書き込む。ユーザーが頼んだ操作だけを行い、複数件をまとめて着手しない
- 行を SQL で直接 INSERT しない（`someday-add` が S-ID の採番・`planned`・登録日をそろえて登録する）
- `[BLOCKED] SOMEDAY_NOT_FOUND` は ID の形式違いか未登録、`SOMEDAY_NOT_PLANNED` は着手済み、`SOMEDAY_NOT_STARTED` は `someday-start` で閉じた行ではない（取り消せない）
- 見送り（やらないと決めた）用のコマンドは無い。頼まれたら次で閉じる
  ```bash
  python3 .claude/db/plc_query.py sql "UPDATE projects SET status='completed', goal=goal||' [見送り]' WHERE scope_id='<S-ID>'"
  ```
- Notion 同期は停止中なので、ストックは Notion には出ない
- 仕様の詳細: `.claude/db/README.md` の「いつかやるPJストック（someday）」節
