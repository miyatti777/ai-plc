# Story: 送料無料まであと表示

- **Story ID:** ST-KTN-003
- **Feature:** 送料無料まであといくら表示
- **Outcome:** KR2 AOV（あと一点の後押しで客単価を引き上げ）
- **Status:** In Progress
- **Priority:** 中
- **仕様:** 未定

## User Story

> **As a** カートに商品を入れた顧客
> **I want** 送料無料まであといくらかを知りたい
> **So that** もう一点足して送料無料にするか判断できる

## Acceptance Criteria

- [ ] カート/購入画面に「送料無料まであと ¥XXX」を表示する
- [ ] 閾値（7,500円）到達で「送料無料達成」に切り替わる
- [ ] 金額変更（追加/削除）にリアルタイムで追随する

## 背景

AOV(KR2)目標7,500円と同額を送料無料ラインに設定し「あと一点」を誘発する定番施策。

## 実装参考（../../kotonoha-store）

- `src/domain/entities/Order.ts` — 小計・送料無料閾値の判定
- `src/components/MyPage.tsx` / カート系component — 表示追加
