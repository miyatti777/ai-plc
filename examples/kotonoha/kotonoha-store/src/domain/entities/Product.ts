/**
 * Product — 商品エンティティ。
 * 責務: 商品属性を保持し、消耗品かどうか/標準的な使い切り日数（補充サイクル）を提供する。
 *        S2の「前回購入からN日後」のNを商品ごとに決める根拠となる。
 */

export type ProductCategory = "consumable" | "durable";

export interface Product {
  id: string;
  shopifyProductId: string;
  title: string;
  category: ProductCategory;
  /**
   * 標準補充サイクル（日数）。消耗品のみ設定。
   * 例: 詰め替え洗剤=45, アロマオイル=60。ReminderServiceのデフォルトN。
   */
  refillCycleDays: number | null;
}

/** 補充リマインドの対象になりうる商品か */
export function isRefillable(product: Product): boolean {
  return product.category === "consumable" && product.refillCycleDays !== null;
}
