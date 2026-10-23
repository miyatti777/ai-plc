---
name: plc-viewer
description: AI-PLC Registry ビューア（ブラウザ）の起動・停止。「Registryビューア開いて」で使用する。
---

# Codex adapter: plc-viewer

実行前に [Codex実行環境の読み替え](../references/codex-runtime.md)を読む。正本の手順・入力・モードは実行時に読み込み、以下は環境差分として適用する。

1. リポジトリルートの `.claude/skills/plc-viewer/SKILL.md` を最後まで読み、その手順を正本として実行する。
2. ビューアは installer の対象外。AI-PLC リポジトリの `experimental/registry-viewer` を `.claude/db/registry_viewer` に手でコピーしたときだけ、`.claude/db/registry_viewer/server.py` を使う。無ければ正本のとおりコピー手順を伝えて止める。
3. 常駐させない。画面からの status 変更は intent.yaml・backlog.yaml・Registry の3か所を書き換えるので、変更するかは人が決める。
4. 正本が欠ける場合は実行せず、欠落内容を報告する。
