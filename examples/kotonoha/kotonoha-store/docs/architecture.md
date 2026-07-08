# アーキテクチャ — コトノハストア

> 🏷️ **Project:** コトノハストア（デモ用スケルトン） / **Type:** draft / **Context:** レイヤ責務とS2補充リマインドのデータフロー

## レイヤ責務

| レイヤ | ディレクトリ | 責務 | 依存先 |
| --- | --- | --- | --- |
| **entities** | `src/domain/entities/` | ドメインの型と純粋なルール（補充期日判定・受信可否判定など） | なし（最下層） |
| **repositories** | `src/domain/repositories/` | 永続化の抽象インターフェース（取得/保存/集約クエリの契約） | entities |
| **infra** | `src/infra/` | 外部SaaSアダプタ（Shopify/LINE/Mail）。interface + stub | なし（外部境界） |
| **services** | `src/services/` | ユースケース/ドメインサービス。判定・組み立て・配信のオーケストレーション | entities / repositories / infra |
| **components** | `src/components/` | UI。顧客向けマイページ・配信設定 | services / stores |
| **stores** | `src/stores/` | クライアント状態（zustand） | entities / services |

依存の向きは常に **上位 → 下位（domain方向）**。domain（entities）は他レイヤを知らない。
repositoriesはinterfaceのみを定義し、実体はinfraを使ってservices側/DI層で組み立てる。

## S2「補充リマインド」データフロー

注文発生から配信までの流れ:

```
[注文確定]
  Order (src/domain/entities/Order.ts)
        │  OrderRepository.save()
        ▼
[購買履歴の導出]
  PurchaseHistory (顧客×商品の最終購入日)
        │  OrderRepository.getPurchaseHistory() / findRefillCandidates()
        ▼
[補充判定]  ← ★ ReminderService.findDueForReminder()
  ・Product.refillCycleDays で N を取得
  ・PurchaseHistory.isDueForRefill(history, N, now) で期日到達を判定
  ・Customer.canReceiveReminder() でオプトイン/チャネルを確認
  ・SegmentService で優先度付け
        │
        ▼
[文面組み立て]  ← ReminderService.buildReminderPayload()
  ・商品名 / 経過日数 / 再購入リンク / セグメント別トーン
        │
        ▼
[配信スケジュール/実行]  ← ReminderService.scheduleReminder() → NotificationService.send()
  ・channel = line  → infra/lineClient.push()
  ・channel = email → infra/mailClient.send()
        │
        ▼
[再訪・再購入]  MyPage / 商品ページへの導線
```

## バッチ実行

日次cronから `ReminderService.run(now)` を呼ぶ想定。
`findDueForReminder → buildReminderPayload → scheduleReminder` を束ねる。
重複配信防止（前回リマインド送信日の記録）と配信時間帯制御は `scheduleReminder` の責務。

## 拡張ポイント（S2実装時の主な差し替え）

1. `infra/shopifyClient.ts` の stub を `@shopify/shopify-api` 実装へ
2. repositories の interface に対する Shopify実装クラスを infra 側に追加
3. `ReminderService` の各 TODO を実装（判定・文面・スケジュール）
4. `NotificationService.send` に consent最終チェック・リトライ・配信ログを追加
