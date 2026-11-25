---
name: ppm-collection
description: ポートフォリオ層の Collection。依頼や新しい案件を受けたとき、既存の案件（Registry と各 Layer の intent・context）を集めて照らし、似た案件を最大3件と行き先（既存の続き／新しい Layer／いつかやる）を勧める。読み取り専用。
---

# Codex adapter: ppm-collection

実行前に [Codex実行環境の読み替え](../references/codex-runtime.md)を読む。正本の手順・入力・モードは実行時に読み込み、以下は環境差分として適用する。

1. リポジトリルートの `.claude/skills/ppm-collection/SKILL.md` を最後まで読み、その手順を正本として実行する。
2. 候補を絞るのは正本のスクリプト（`.claude/skills/ppm-collection/collect.py`。読み取り専用）。Registry・Layer・Stock には書かない。
3. 勧めた行き先の Stage・補助スキルは `$skill-name` に読み替えて示す。次のコマンドは利用者の明確な実行指示があるまで実行しない。
4. 正本が欠ける場合は実行せず、欠落内容を報告する。
