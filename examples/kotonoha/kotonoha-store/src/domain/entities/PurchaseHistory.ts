/**
 * PurchaseHistory — 顧客×商品の購買履歴（集約ビュー）。
 * 責務: 注文群から導出した「ある顧客がある商品を最後にいつ買ったか」を保持する。
 *        S2の補充判定（前回購入日 + N日 <= 今日）の中核データ。
 */

export interface PurchaseHistory {
  customerId: string;
  productId: string;
  /** 直近の購入日時。補充サイクル計算の起点 */
  lastPurchasedAt: Date;
  /** これまでの累計購入回数（リピーター判定・優先度付けに利用） */
  purchaseCount: number;
  /** 直近購入時の数量（使い切り日数の補正に利用可能） */
  lastQuantity: number;
}

/** 前回購入日から補充サイクル(cycleDays)が経過し、補充リマインドの対象日に達しているか */
export function isDueForRefill(
  history: PurchaseHistory,
  cycleDays: number,
  now: Date = new Date(),
): boolean {
  const dueAt = new Date(history.lastPurchasedAt);
  dueAt.setDate(dueAt.getDate() + cycleDays);
  return now >= dueAt;
}
