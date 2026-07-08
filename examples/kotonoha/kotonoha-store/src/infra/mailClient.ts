/**
 * mailClient — メール配信SaaS(例: SendGrid)アクセスの抽象と stub。
 * 責務: メルマガ/トランザクションメール送信を担う。NotificationServiceがチャネル実装として利用する。
 */

export interface MailMessage {
  toEmail: string;
  subject: string;
  body: string;
  /** テンプレートID運用にする場合の識別子（任意） */
  templateId?: string;
}

export interface MailClient {
  send(message: MailMessage): Promise<{ delivered: boolean }>;
}

/** stub実装。TODO(S2): メール配信SaaSのSDKで本実装に差し替える */
export class StubMailClient implements MailClient {
  async send(message: MailMessage): Promise<{ delivered: boolean }> {
    // TODO: POST to mail provider send endpoint
    console.log("[stub][mail] send", message.toEmail, message.subject);
    return { delivered: true };
  }
}
