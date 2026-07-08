/**
 * MyPage — マイページ（顧客向け）。
 * 責務: 購買履歴と補充リマインドの受信設定への導線を表示する最小雛形。
 *        S2では「次の補充目安日」の表示や再購入ボタンを足す想定。
 */

export interface MyPageProps {
  displayName: string;
}

export function MyPage({ displayName }: MyPageProps) {
  // TODO(S2): PurchaseHistory の一覧・次回補充目安日・ワンクリック再購入を表示
  return (
    <main>
      <h1>{displayName} さんのマイページ</h1>
      <section aria-label="購買履歴">{/* TODO: 履歴リスト */}</section>
      <nav>{/* TODO: 配信設定(NotificationSettings)への導線 */}</nav>
    </main>
  );
}
