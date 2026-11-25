# 正規化入力

利用者の選んだ資料からAIがこの形に整理する。`input.json`は元資料と別の中間ファイル。値を捏造しない。資料を取得しただけで内容が正しいと保証しない。sourceは `{ "path": "指定資料の場所", "locator": "行/見出し/JSON pointer", "revision": "取得した版またはSHA256" }`。source欠損は警告、時点不明はnull。

```json
{
  "schema_version": "portfolio-1",
  "portfolio_id": "DEMO",
  "as_of": "2026-09-10",
  "selected_projects": ["A", "B"],
  "staleness_days": null,
  "projects": [
    {"id":"A","name":"架空A","owner":null,"observed_at":null,"source":null,
     "items":[{"id":"X","title":"連携機能","status":"進行中","forecast":null,"confirmed_done":false,"source":null}],"issues":[]},
    {"id":"B","name":"架空B","owner":null,"observed_at":null,"source":null,
     "items":[{"id":"X","title":"接続試験","status":"待機","forecast":null,"confirmed_done":false,"source":null}],"issues":[]}
  ],
  "dependencies":[{"id":"D1","from":{"project_id":"A","item_id":"X"},"to":{"project_id":"B","item_id":"X"},"needed_by":null,"source":null}],
  "resources":[],
  "allocations":[]
}
```

この例は架空の構造例。利用者の値として転用しない。

| 配列 | 項目 |
| --- | --- |
| projects | id必須一意、name、owner、observed_at（YYYY-MM-DD/null）、source、items、issues |
| items | 案件内で一意id、title、status、forecast（日付/null）、confirmed_done（bool）、source |
| issues | 案件内で一意id、kind（issue/risk）、title、status、common_key（明示共通要因の文字列/null）、source |
| dependencies | 一意id、from/to（project_id+item_id）、needed_by（日付/null）、source |
| resources | 一意id、name、unit（hours_per_day等、未確認null）、capacity（1日上限、非負数/null）、observed_at、source |
| allocations | 一意id、resource_id、project_id、start/end（両端含む日付/null）、load（各日の非負数/null）、unit、source |

日付は厳密なYYYY-MM-DD。NaN/Infinity、負荷負数、逆転期間、同一配列内ID重複、未知参照はエラー。別案件の同じitem_idは有効。人名の一致でresource_idを同一化しない。

`staleness_days` は利用者または運用基準が指定した非負整数/null。nullでは経過日数のみ提示し、勝手な閾値を置かない。案件のobserved_atはその資料に含む項目/割当の情報時点として使用。項目ごとの時点が異なる資料は最新としてまとめず、最も古い時点と内訳を記載して確認を促す。

資源上限は期間中一定。変動するなら同じrunで別resourceに分割して関連を失わせず、基準期間を分けたrunで比較する。未知負荷・単位違い・対象外の負荷を数値合計から除くが、その場合の合計は下限的な観測値であり「空いている」とは言えない。容量0は有効。

`analysis.json`に元source・input内pointer・入力ファイルSHA256を残す。IDを報告/議題の根拠として使う。ヘルパーはsourceパスを自動読取りしないので、AIが指定資料を実際に読んで正規化する責任を持つ。

## 資料の欠落と判断権限

projects[].issues_statusはreported（記載あり）/not_provided（記載なし、有無未確認）/confirmed_none（資料上で課題なし確認済み）。省略時はissues非空ならreported、空ならnot_provided。confirmed_noneは資料の明示確認がある場合だけ。課題があるのにconfirmed_none等は入力エラー。

任意トップレベルdecision_authorityに{role, scope, unconfirmed, source}を保持する。roleは判断者、scopeは確認済み権限、unconfirmedは未確認範囲。元資料にない場合null。分析と報告へ引継ぐが、この欄だけで個別変更の確認を代替しない。
