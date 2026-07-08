/**
 * NotificationSettings — 配信設定UI（顧客向け）。
 * 責務: 補充リマインドのオプトイン/チャネル(LINE・メール)選択を編集する最小雛形。
 *        S2の配信可否(Customer.consent)を顧客自身が制御する入口。
 */

import type { NotificationChannel } from "../domain/entities/Customer.js";

export interface NotificationSettingsProps {
  reminderOptIn: boolean;
  channels: Record<NotificationChannel, boolean>;
  onChange?: (next: { reminderOptIn: boolean; channels: Record<NotificationChannel, boolean> }) => void;
}

export function NotificationSettings({ reminderOptIn, channels }: NotificationSettingsProps) {
  // TODO(S2): トグルUIとバリデーション、保存時に CustomerRepository.save を呼ぶ
  return (
    <form aria-label="配信設定">
      <label>
        <input type="checkbox" checked={reminderOptIn} readOnly /> 補充リマインドを受け取る
      </label>
      <label>
        <input type="checkbox" checked={channels.line} readOnly /> LINEで受け取る
      </label>
      <label>
        <input type="checkbox" checked={channels.email} readOnly /> メールで受け取る
      </label>
      {/* TODO: onChange 配線・保存ボタン */}
    </form>
  );
}
