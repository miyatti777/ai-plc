# Story: 配信設定 オプトイン管理

- **Story ID:** ST-KTN-002
- **Feature:** 配信設定 オプトイン管理（LINE/メール）
- **Outcome:** KR3 再訪率（配信の同意基盤。S2補充リマインドの前提）
- **Status:** Ready
- **Priority:** 高
- **仕様:** 未定

## User Story

> **As a** コトノハストアの顧客
> **I want** LINE / メールで通知を受け取るかを自分で設定したい
> **So that** 欲しい情報だけ、使っているチャネルで受け取れる

## Acceptance Criteria

- [ ] 配信設定画面でLINE・メールそれぞれの受信ON/OFFを切り替えられる
- [ ] 設定変更が即時保存され、次回配信に反映される
- [ ] オプトアウトした顧客には以後その チャネルで配信されない（consent尊重）

## 背景

補充リマインド(S2)含む全配信の土台。`Customer` の consent を顧客自身が管理できるようにする。配信施策の必須前提。

## 実装参考（../../kotonoha-store）

- `src/components/NotificationSettings.tsx` — 配信設定UI（この画面が対象）
- `src/domain/entities/Customer.ts` — consent / `canReceiveReminder`
- `src/stores/customerStore.ts` — 顧客設定の状態管理
