/**
 * NotificationService — チャネル横断の配信実行サービス。
 * 責務: 抽象化された通知ペイロードを、顧客のチャネル設定に応じて LINE/メール の実クライアントへ振り分けて送る。
 *        ReminderServiceが組み立てたペイロードの「送信」だけを担当する（判定は持たない）。
 */

import type { Customer, NotificationChannel } from "../domain/entities/Customer.js";
import type { LineClient } from "../infra/lineClient.js";
import type { MailClient } from "../infra/mailClient.js";

export interface NotificationPayload {
  channel: NotificationChannel;
  subject: string;
  body: string;
  linkUrl?: string;
}

export interface DeliveryResult {
  channel: NotificationChannel;
  delivered: boolean;
}

export class NotificationService {
  constructor(
    private readonly lineClient: LineClient,
    private readonly mailClient: MailClient,
  ) {}

  /** 単一顧客へ、指定チャネルのペイロードを送信する */
  async send(customer: Customer, payload: NotificationPayload): Promise<DeliveryResult> {
    // TODO(S2): consent/連携状態の最終チェック、失敗時リトライ、配信ログ記録
    if (payload.channel === "line" && customer.lineUserId) {
      const r = await this.lineClient.push({
        toLineUserId: customer.lineUserId,
        text: payload.body,
        linkUrl: payload.linkUrl,
      });
      return { channel: "line", delivered: r.delivered };
    }
    if (payload.channel === "email" && customer.email) {
      const r = await this.mailClient.send({
        toEmail: customer.email,
        subject: payload.subject,
        body: payload.body,
      });
      return { channel: "email", delivered: r.delivered };
    }
    return { channel: payload.channel, delivered: false };
  }
}
