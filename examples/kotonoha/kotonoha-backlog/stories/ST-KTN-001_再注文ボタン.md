# Story: マイページ 再注文ボタン

- **Story ID:** ST-KTN-001
- **Feature:** マイページ 再注文ボタン
- **Outcome:** KR1 リピート率（過去購入からの再購入を1タップで）
- **Status:** Backlog
- **Priority:** 中
- **仕様:** 未定

## User Story

> **As a** 過去に購入した顧客
> **I want** マイページの購入履歴から同じ商品をワンタップで再注文したい
> **So that** 探す手間なくすぐ買い直せる

## Acceptance Criteria

- [ ] マイページの各購入履歴行に「再注文」ボタンが表示される
- [ ] 押下でカートに同一商品が入り、購入フローに進める
- [ ] 在庫切れ・販売終了商品はボタンを非活性にし理由を表示する

## 背景

リピート率(KR1)向上の定番導線。既存の購入履歴表示に再購入導線を足す軽量施策。

## 実装参考（../../kotonoha-store）

- `src/components/MyPage.tsx` — 購入履歴表示に再注文ボタンを追加
- `src/domain/repositories/OrderRepository.ts` — `findByCustomerId` / `getPurchaseHistory` を利用
- `src/domain/entities/PurchaseHistory.ts` — 履歴行のデータ
