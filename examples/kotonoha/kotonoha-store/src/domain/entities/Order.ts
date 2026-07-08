/**
 * Order — 注文エンティティ。
 * 責務: 1回の購買を表す。どの顧客がいつ何を買ったかを保持し、補充サイクルの起点(前回購入日)を提供する。
 */

export interface OrderLine {
  productId: string;
  quantity: number;
}

export interface Order {
  id: string;
  shopifyOrderId: string;
  customerId: string;
  lines: OrderLine[];
  /** 注文確定日時。補充リマインドの「前回購入日」の基準 */
  orderedAt: Date;
}

/** 指定商品を含む注文か */
export function containsProduct(order: Order, productId: string): boolean {
  return order.lines.some((line) => line.productId === productId);
}
