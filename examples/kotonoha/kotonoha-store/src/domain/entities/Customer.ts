/**
 * Customer — 顧客エンティティ。
 * 責務: 会員の識別情報と、S2「補充リマインド」の配信可否を左右する連絡チャネル/オプトイン状態を保持する。
 */

/** 補充リマインドをどのチャネルで受け取るか */
export type NotificationChannel = "line" | "email";

export interface CustomerConsent {
  /** リマインド配信全体のオプトイン */
  reminderOptIn: boolean;
  /** チャネル別の受信可否（未連携チャネルは false） */
  channels: Record<NotificationChannel, boolean>;
}

export interface Customer {
  id: string;
  shopifyCustomerId: string;
  displayName: string;
  email: string | null;
  /** LINE連携済みの場合のみ設定される */
  lineUserId: string | null;
  consent: CustomerConsent;
  createdAt: Date;
}

/** 少なくとも1チャネルでリマインドを受け取れるか（ReminderServiceの配信対象判定で使用） */
export function canReceiveReminder(customer: Customer): boolean {
  if (!customer.consent.reminderOptIn) return false;
  return Object.values(customer.consent.channels).some(Boolean);
}
