/**
 * shopifyClient — Shopify Admin API アクセスの抽象と stub。
 * 責務: 顧客/注文/商品の生データ取得を担う。Repository実装がこれをラップする。
 */

export interface ShopifyClient {
  fetchCustomer(shopifyCustomerId: string): Promise<unknown>;
  fetchOrdersByCustomer(shopifyCustomerId: string): Promise<unknown[]>;
  fetchProduct(shopifyProductId: string): Promise<unknown>;
}

/** stub実装。TODO(S2): @shopify/shopify-api で本実装に差し替える */
export class StubShopifyClient implements ShopifyClient {
  async fetchCustomer(): Promise<unknown> {
    // TODO: Admin API GET /customers/{id}
    return null;
  }

  async fetchOrdersByCustomer(): Promise<unknown[]> {
    // TODO: Admin API GET /orders?customer_id=...
    return [];
  }

  async fetchProduct(): Promise<unknown> {
    // TODO: Admin API GET /products/{id}
    return null;
  }
}
