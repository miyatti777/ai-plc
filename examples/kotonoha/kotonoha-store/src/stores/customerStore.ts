/**
 * customerStore — ログイン顧客のクライアント状態（zustand想定）。
 * 責務: 現在の顧客プロフィールと配信設定をUI全体で共有する。NotificationSettings編集の一次状態。
 */

import type { Customer, NotificationChannel } from "../domain/entities/Customer.js";

export interface CustomerState {
  customer: Customer | null;
  setCustomer: (customer: Customer | null) => void;
  /** 配信オプトインをローカルに反映（保存はService経由） */
  setReminderOptIn: (optIn: boolean) => void;
  setChannel: (channel: NotificationChannel, enabled: boolean) => void;
}

// TODO(S2): create<CustomerState>()((set) => ({ ... })) で zustand ストアを実装する
export const customerStoreDefinition = (): CustomerState => ({
  customer: null,
  setCustomer: () => {
    /* TODO */
  },
  setReminderOptIn: () => {
    /* TODO */
  },
  setChannel: () => {
    /* TODO */
  },
});
