---
name: plc-viewer
description: AI-PLCの Registry ビューア（ブラウザで Project 一覧・詳細・食い違い・起動プロンプトを見る）を起動・停止する。「Registryビューア開いて」「AI-PLCのプロジェクトを画面で見たい」で使う。experimental/registry-viewer を手でコピーしたときだけ使える。
---

# plc-viewer（Registry ビューア）

> 論理名: SKL_plc_viewer ／ 包むもの: `.claude/db/registry_viewer/server.py`（挙動は変えない）／ 詳細: `.claude/db/registry_viewer/README.md`（AI-PLC リポジトリの `experimental/registry-viewer/README.md`）

## 前提

ビューアはアルファ版で、installer では入らない。Cursor だけの配置では `.claude/` を `.cursor/` に読み替える。`.claude/db/registry_viewer/server.py` が無ければ「AI-PLC リポジトリの `experimental/registry-viewer` を `.claude/db/registry_viewer` にコピーすると使えます（手順は同 README）」と伝えて止める。

## 起動と停止

| やりたいこと | 方法 |
| --- | --- |
| 起動（ブラウザが開く） | `python3 .claude/db/registry_viewer/server.py` → `http://127.0.0.1:8765/` |
| ポートが埋まっている | `--port 0`（空いているポート） |
| ブラウザを開かない | `--no-browser` |
| 別の DB・リポジトリを見る | `--db PATH`（または `AIPLC_DB`）/ `--root PATH` |
| 止める | 起動したターミナルで Ctrl-C |

ポート使用中や DB が無いときは理由を表示して終了コード 2 で止まる。

## 注意

- **書き込み（status の変更）ができるのは Jev 実験版（`--with-jev`）も入っているときだけ。** 無ければ閲覧のみ（起動時に `mode: readonly（理由）` と出る）
- 画面から status を変えると **`intent.yaml`・`backlog.yaml`・Registry の3か所**が書き換わる（順番と値は README の「status を変えると何が書き換わるか」）。変更するかは人が決め、確認ダイアログの内容を読んでから押す。試す前にバックアップを取る（README の手順）
- 行の追加・削除や Notion 同期（`/plc-db-sync`）はできない。常駐しないので、使い終わったら止める
