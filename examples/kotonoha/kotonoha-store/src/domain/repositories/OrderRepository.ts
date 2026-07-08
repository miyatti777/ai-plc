/**
 * OrderRepository — 注文永続化の抽象インターフェース。
 * 責務: Order取得と、購買履歴(PurchaseHistory)の導出クエリの契約を定義する。
 *        S2の補充判定に必要な「顧客×商品の最終購入日」をここから得る。
 */

import type { Order } from "../entities/Order.js";
import type { PurchaseHistory } from "../entities/PurchaseHistory.js";

export interface OrderRepository {
  findById(id: string): Promise<Order | null>;

  findByCustomerId(customerId: string): Promise<Order[]>;

  /** 指定顧客の商品別購買履歴（最終購入日等）を集約して返す */
  getPurchaseHistory(customerId: string): Promise<PurchaseHistory[]>;

  /**
   * 補充リマインド候補となる購買履歴を横断取得する。
   * consumable商品かつ最終購入日が古い履歴を返す。ReminderServiceのバッチが利用。
   */
  findRefillCandidates(now: Date): Promise<PurchaseHistory[]>;

  save(order: Order): Promise<void>;
}

// TODO(S2): infra/shopifyClient.ts を用いた ShopifyOrderRepository を実装する
