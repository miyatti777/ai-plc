/**
 * ReminderService — ★S2「補充リマインド」の主戦場★
 * 責務: 消耗品の「前回購入からN日後」を判定し、対象顧客ごとにリマインド配信ペイロードを組み立て、配信をスケジュール/実行する。
 *
 * データフロー:
 *   OrderRepository.findRefillCandidates()  → 補充期日に達した購買履歴
 *   → CustomerRepository で対象顧客を解決 & オプトインチェック(canReceiveReminder)
 *   → SegmentService で優先度付け
 *   → buildReminderPayload() で文面/導線を生成
 *   → NotificationService.send() で LINE/メール 配信
 *
 * バッチ想定: 日次cronから run() を叩く。
 */

import type { Customer, NotificationChannel } from "../domain/entities/Customer.js";
import { canReceiveReminder } from "../domain/entities/Customer.js";
import type { Product } from "../domain/entities/Product.js";
import type { PurchaseHistory } from "../domain/entities/PurchaseHistory.js";
import { isDueForRefill } from "../domain/entities/PurchaseHistory.js";
import type { CustomerRepository } from "../domain/repositories/CustomerRepository.js";
import type { OrderRepository } from "../domain/repositories/OrderRepository.js";
import type { NotificationPayload, NotificationService } from "./NotificationService.js";
import type { SegmentService } from "./SegmentService.js";

/** 1件のリマインド配信予定 */
export interface ReminderCandidate {
  customer: Customer;
  product: Product;
  history: PurchaseHistory;
  channel: NotificationChannel;
  priority: number;
}

export class ReminderService {
  constructor(
    private readonly orderRepo: OrderRepository,
    private readonly customerRepo: CustomerRepository,
    private readonly notifier: NotificationService,
    private readonly segments: SegmentService,
  ) {}

  /**
   * 補充期日に達した配信対象を洗い出す。
   * TODO(S2): findRefillCandidates の結果を Product.refillCycleDays でフィルタし、
   *           isDueForRefill(history, cycleDays, now) と canReceiveReminder(customer) を満たす候補を返す。
   *           重複配信防止（前回リマインド送信日）もここで除外する。
   */
  async findDueForReminder(now: Date = new Date()): Promise<ReminderCandidate[]> {
    void this.orderRepo;
    void this.customerRepo;
    void this.segments;
    void isDueForRefill;
    void canReceiveReminder;
    void now;
    // TODO(S2): 実装
    return [];
  }

  /**
   * 1候補分のリマインド文面/導線を組み立てる。
   * TODO(S2): 商品名・前回購入からの経過日数・再購入リンク(Shopify商品URL)・セグメント別トーンを反映。
   */
  buildReminderPayload(candidate: ReminderCandidate): NotificationPayload {
    // TODO(S2): テンプレート化。ここは骨格のみ。
    return {
      channel: candidate.channel,
      subject: `${candidate.product.title} の補充時期です`,
      body: "TODO: 補充リマインド本文",
      linkUrl: undefined,
    };
  }

  /**
   * 候補をキューに載せる/送信予約する。
   * TODO(S2): 即時送信ではなく配信時間帯(例: 平日午前)へスケジュール、レート制御、送信ログ記録。
   */
  async scheduleReminder(candidate: ReminderCandidate): Promise<void> {
    void candidate;
    void this.notifier;
    // TODO(S2): 実装（NotificationService.send or ジョブキュー投入）
  }

  /** 日次バッチのエントリポイント。TODO(S2): findDue → build → schedule を束ねる */
  async run(now: Date = new Date()): Promise<{ scheduled: number }> {
    const candidates = await this.findDueForReminder(now);
    for (const c of candidates) {
      await this.scheduleReminder(c);
    }
    return { scheduled: candidates.length };
  }
}
