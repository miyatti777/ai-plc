/**
 * lineClient — LINE Messaging API アクセスの抽象と stub。
 * 責務: LINE経由の補充リマインド送信を担う。NotificationServiceがチャネル実装として利用する。
 */

export interface LinePushMessage {
  toLineUserId: string;
  text: string;
  /** 商品ページ等への導線（再訪リンク） */
  linkUrl?: string;
}

export interface LineClient {
  push(message: LinePushMessage): Promise<{ delivered: boolean }>;
}

/** stub実装。TODO(S2): LINE Messaging API push endpoint を呼ぶ本実装に差し替える */
export class StubLineClient implements LineClient {
  async push(message: LinePushMessage): Promise<{ delivered: boolean }> {
    // TODO: POST https://api.line.me/v2/bot/message/push
    console.log("[stub][line] push", message.toLineUserId);
    return { delivered: true };
  }
}
