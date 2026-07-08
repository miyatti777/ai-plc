/**
 * CustomerRepository — 顧客永続化の抽象インターフェース。
 * 責務: Customerの取得/保存の契約を定義する。実体はShopify顧客API + 自社DBのアダプタで実装する(infra層)。
 */

import type { Customer, NotificationChannel } from "../entities/Customer.js";

export interface CustomerRepository {
  findById(id: string): Promise<Customer | null>;

  findByShopifyId(shopifyCustomerId: string): Promise<Customer | null>;

  /**
   * リマインド配信対象になりうる顧客（オプトイン済み）を返す。
   * S2バッチが最初に叩く入口。channelで絞り込み可能。
   */
  findReminderOptedIn(channel?: NotificationChannel): Promise<Customer[]>;

  save(customer: Customer): Promise<void>;
}

// TODO(S2): infra/shopifyClient.ts を用いた ShopifyCustomerRepository を実装する
