/**
 * SegmentService — 顧客セグメンテーションサービス。
 * 責務: 購買履歴から顧客を分類し（新規/リピーター/離脱リスク等）、リマインドの優先度や文面出し分けの根拠を提供する。
 *        S2では「補充リマインドをどの顧客に強めに出すか」の判断材料に使う。
 */

import type { PurchaseHistory } from "../domain/entities/PurchaseHistory.js";

export type CustomerSegment = "new" | "repeater" | "loyal" | "at_risk";

export class SegmentService {
  /** 購買履歴群から顧客セグメントを判定する */
  classify(histories: PurchaseHistory[]): CustomerSegment {
    // TODO(S2): 回数/頻度/最終購入からの経過でルール判定 or スコアリング
    const totalPurchases = histories.reduce((sum, h) => sum + h.purchaseCount, 0);
    if (totalPurchases <= 1) return "new";
    if (totalPurchases >= 10) return "loyal";
    return "repeater";
  }

  /** セグメントに応じたリマインド優先度（高いほど優先送信）。TODO(S2): チューニング */
  reminderPriority(segment: CustomerSegment): number {
    switch (segment) {
      case "loyal":
        return 3;
      case "repeater":
        return 2;
      case "at_risk":
        return 2;
      case "new":
        return 1;
    }
  }
}
