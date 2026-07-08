# コトノハストア Product Backlog

> D2Cライフスタイル雑貨EC「コトノハストア」のプロダクトバックログ。対象リポジトリ: `../kotonoha-store`

## バックログボード

| Story ID | Feature | Status | Priority | Outcome（狙うOKR） | 仕様 |
| --- | --- | --- | --- | --- | --- |
| [ST-KTN-001](stories/ST-KTN-001_再注文ボタン.md) | マイページ 再注文ボタン | Backlog | 中 | KR1 リピート率 | — |
| [ST-KTN-002](stories/ST-KTN-002_配信設定オプトイン.md) | 配信設定 オプトイン管理 | Ready | 高 | KR3 再訪率（S2の前提） | — |
| [ST-KTN-003](stories/ST-KTN-003_送料無料あと表示.md) | 送料無料まであと表示 | In Progress | 中 | KR2 AOV | — |

Status: Backlog → Ready → In Progress → Done ｜ Priority: 高 / 中 / 低

## 起票フォーマット（spec-story-starter 等が従う）

新しいStoryを追加する手順:

1. `stories/ST-KTN-NNN_<feature>.md` を作成（NNNは連番。現在の最大は 003 → 次は **004**）
2. `TEMPLATE_story.md` に従い、Story ID / Feature / Outcome / Status / Priority / 仕様 と本文（User Story + AC + 背景）を記入
3. 本board.mdの表に1行追加
4. 対応Specがある場合は「仕様」列にリンクを張り、Spec側からもStoryへ相互リンク
