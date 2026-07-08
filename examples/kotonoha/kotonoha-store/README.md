# コトノハストア (kotonoha-store)

> 🏷️ **Project:** コトノハストア（デモ用スケルトン） / **Type:** draft / **Context:** AI-PLC収束デモで施策S2をgroundする対象リポジトリ骨格

株式会社コトノハが運営する D2Cライフスタイル雑貨EC「**コトノハストア**」のアプリケーション骨格（スケルトン）です。
**動作は目的ではなく、施策仕様が「どのファイルに実装するか」を指し示せる構造**を提供します。

## 事業概要

- D2Cライフスタイル雑貨（詰め替え洗剤・アロマ・キッチン消耗品など）
- **Shopify** を基盤に、自社の会員体験・CRM配信（LINE/メルマガ）を上乗せ

## 施策コンテキスト: S2「補充リマインド」

消耗品を **前回購入からN日後** に LINE / メルマガで補充を促す配信施策。
触る領域: 顧客(customer)・注文(order)・商品(product)・通知/配信(notification)・再訪/購入導線。
実装の中心は **`src/services/ReminderService.ts`**。

## 技術スタック

- TypeScript / pnpm / Vite / Vitest
- 状態管理: zustand（`src/stores/`）
- 外部SaaS: Shopify Admin API・LINE Messaging API・メール配信SaaS（`src/infra/`にstub）

## アーキテクチャ（DDDレイヤ）

```
entities → repositories → services → components → stores
（infra は repositories / services が依存する外部アダプタ層）
```

依存の向き: 上位(components/stores/services) → 下位(domain)。domainは他レイヤに依存しない。
詳細は [docs/architecture.md](docs/architecture.md)。

## ディレクトリ地図

```
kotonoha-store/
├── README.md
├── package.json / tsconfig.json
├── src/
│   ├── domain/
│   │   ├── entities/        Customer / Order / Product / PurchaseHistory
│   │   └── repositories/    CustomerRepository / OrderRepository (interface)
│   ├── services/            NotificationService / ReminderService(★S2) / SegmentService
│   ├── components/          MyPage / NotificationSettings
│   ├── stores/              customerStore / reminderStore
│   └── infra/               shopifyClient / lineClient / mailClient (stub)
└── docs/architecture.md
```

## 新機能を足す開発者へ（どこに何を書くか）

| やりたいこと | 触るファイル |
| --- | --- |
| 配信判定ロジック（誰にいつ出すか） | `src/services/ReminderService.ts` |
| 配信の実送信（LINE/メール振り分け） | `src/services/NotificationService.ts` + `src/infra/*Client.ts` |
| 補充サイクルNの定義 | `src/domain/entities/Product.ts` (`refillCycleDays`) |
| 最終購入日の取得クエリ | `src/domain/repositories/OrderRepository.ts` |
| 顧客の受信可否/チャネル | `src/domain/entities/Customer.ts` (`consent`) |
| 顧客向け設定UI | `src/components/NotificationSettings.tsx` |

## セットアップ（雛形）

```bash
pnpm install
pnpm dev     # 開発サーバ
pnpm test    # vitest
pnpm check   # 型チェック + lint
```
