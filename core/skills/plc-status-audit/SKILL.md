---
name: plc-status-audit
description: AI-PLCのステータス点検。intent.yaml・backlog.yaml・Registry の食い違い（閉じ忘れ・Layer不明・停滞・Registry漏れ）を読み取り専用で洗い出し、人が承認した行だけ反映する。「ステータス点検して」「閉じ忘れを探して」「食い違いを見て」で使う。Jev 実験版（--with-jev）を入れたときだけ使える。
---

# plc-status-audit（ステータス点検）

> 論理名: SKL_plc_status_audit ／ 包むもの: `.claude/ai-plc-jev/scripts/aiplc_status_audit.py`（挙動は変えない）／ 詳しい使い方: 同じフォルダの `README_status_audit.md`

## 前提

スクリプトは Jev 実験版パッケージ（installer の `--with-jev`）に入っている。`.claude/ai-plc-jev/scripts/aiplc_status_audit.py` が無ければ「ステータス点検は Jev 実験版を入れたときだけ使えます」と伝えて止める。点検そのものは読み取りだけで、外部送信はない（`--jev` を付けたときを除く）。

## 使い方

| やりたいこと | コマンド | 書き込み |
| --- | --- | --- |
| 件数だけ見る | `python3 .claude/ai-plc-jev/scripts/aiplc_status_audit.py --brief` | なし |
| 1つの Layer だけ見る（04-operation Phase 7 と同じ） | `python3 .claude/ai-plc-jev/scripts/aiplc_status_audit.py --brief --layer <Layerのパス>` | なし |
| 候補の一覧を読む | `… --quiet` → 出力された report.md を読む | レポートだけ |
| 承認ファイルの雛形を作る | `… --quiet --approval-template [--layer <パス>]` | レポートと雛形 |
| 反映の予定を見る（dry-run） | `… --apply <承認ファイル>` | なし |
| 反映する | `… --apply <承認ファイル> --yes` | あり |

`--brief` の終了コード: 0 = 食い違いなし / 10 = 候補あり / 2 = DB や scope_id が無い。

## 手順

1. まず `--brief`（範囲を絞るなら `--layer` か `--scope`）で件数を見せる
2. 候補があれば、1行ずつ「何が食い違っているか・推奨の反映」を示す。**自動で閉じない。** 完了にするかは人が決める
3. 反映を頼まれたら: 雛形を作る → 承認する行だけ `approve` にした承認ファイルをユーザーと確認 → dry-run → `--yes`
4. 反映後にもう一度 `--brief` で件数が減ったことを確かめる

## 注意

- 既定は読み取り専用。書き込むのは `--apply … --yes` のときだけ
- `--jev` は外部送信を伴う（`jev_monitor: true` で機密でない停滞 Layer だけ）。頼まれたときだけ使う
