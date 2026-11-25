# 共通Stockへの接続 v1（仕組みと使い方）

同梱の PM アドオン（旧い欄 `work_style: aipm` も同じ）で、`aipm.storage: registry_stock_v1` を明示した案件だけが使う保存方式。複数の案件が同じ業務Project の Stock を共有し、案件ごとの原文と、整理統合した版を版つきで積み上げる。

- **既定では使わない。** `aipm.storage` を書かない案件は、SKILL.md の「箱の形と保存先」「保存先の設定」のとおり保存する（新しい形の箱は保存先の設定、古い形の箱は箱の中の Stock）。既存成果の自動移動・削除・ID 置換はしない
- 道具は2つに分かれる: 中心（保存の仕組み）が `.claude/db/shared_stock.py`（隔離の `FixtureStore` と、発行ファイルで1組だけに許す `LiveStore`）、箱の側の入口がこのスキルの `shared_stock.py`（`collection`・`prepare_archive`・`apply_archive` ほか）
- 業務Project の表（programs・business_projects・program_memberships・business_project_links）は `.claude/db/business_registry.py` で作る。共有 Stock はこの表を読むだけで、書かない

## 検証済みの範囲と未検証の範囲

| | 中身 |
| --- | --- |
| 検証済み（合成のデータの試験） | `FixtureStore`（使い捨ての一時フォルダ）での Collection → init → 19文書 → prepare → apply → final → 次の案件の読み込み。中断と再送からの回復、自己補償、並行 writer・期限切れ・未知ファイルの拒否。`LiveStore` の発行ファイルの照合と、`business_registry.py` で作った合成の表の上での install_schema → bind → prepare → commit（`tests/db/test_shared_stock.py`・`tests/db/test_business_registry.py`、このスキルの `tests/test_shared_stock_integration.py`） |
| 未検証 | 実際の Registry・実際の Stock での運用、既存フォルダの取り込み（import。未実装）、矛盾の裁定・置換（未実装）、画面での表示、人の利用効果 |

試験は合成の Registry 行・19文書・固定の判断を使い、実際の本人の回答や実導入の成功としては扱わない。

## Collection から次の案件までの入口

1. Registry の workspace・read_domain・program_uid・business_uid を確かめて `aipm.stock_selector` に保存する。AI-PLC 自身の sync UID は `aipm.aiplc_uid`。表示名、Layer ID、AIPM の書式用の program_id／project_id から業務 UID を作らない
2. `shared_stock.collection(layer, runtime, adopted_folder=...)` で同じ組の binding を再利用する。新しい組は具体的な相対フォルダの採択が要る。同じ組で別のフォルダ、別の組で同じ／内包するフォルダ、未登録の既存フォルダ、所属・所有 epoch・版の不一致は Hold。この処理は方式の選択と保存先の照合で、文書は作らない
3. Inception で既存の Init→persona→problem→validation→solution→story→archive の Task の依存と必須の19文書を保つ。共通 Stock はその archive の保存方法
4. Operation は `package.init(layer, stock_runtime=runtime)` から始める。工程フォルダは箱の側だけに作り（新しい箱は `Sheets/` の直下、保存済みの box_root_v1 は `Documents/aipm_project/` の直下、nested_v1 は箱の中の Flow/…）、憲章は `_charter/README.md`（新しい形は箱の直下、古い形は Flow 内）に置く。箱の中に Stock/ は作らない。`stock_project_rel` は互換の書式の上で憲章のステージングの場所を表す（新しい形は `_charter`）。新しい形では `aipm.program_id` を書かなければ bindings の program_id は `[unknown]`。共有の保存先の正は Registry の binding（program_uid）で、この値を保存先に使わない
5. 19文書と manifest・validation を作り、`prearchive` の検査と必要な本人の判断を満たす。`prepare_archive(layer, runtime, task_id=..., decision_ref=..., units=...)` は読むだけで、今の Stock との差分・矛盾・入力の hash・原文・統合の候補を返す。units は整理した節・主張で `{kind, text, source_paths}`。kind は observed／user_reported／hypothesis／inference／unknown。人物・観測・判断を機械が新しい事実へ上げない。意味と根拠の対応は担当と独立レビューで確かめる
6. 示した全文・差分の `core.digest(proposal)` と、writer・有限の期間・request_id を本人が採択した後、同じ版を `apply_archive(...)` へ渡す。未採択・矛盾・変わった入力は適用しない。複数の案件の異なる節は集約し、同じ節・同じ内容には出典を足す。同じキーで内容・分類が違うものは保留し、勝手に上書きしない。元の原稿は必ずそのまま保存する
7. `validate_package.validate(package, layer=layer, stock_runtime=runtime)` の final、Task の全 AC、独立レビューを通す。次の案件は 1〜2 の同じ組で、今の統合版と出典を再利用する。共通の版を元の案件の原文と同じバイトにする必要はなく、原文の snapshot だけ同じバイト・hash を求める

## 保存と中断

- Registry に足す表は `stock_bindings` と `stock_operations`。業務Project の表と AI-PLC の Project の Identity を参照し、元の表の用途は変えない
- 今の版の正は binding の generation／current_revision で、任意の README や source_ref ではない。各 revision は manifest、organized.json、今回の原文 snapshot を持ち、parent で前の原文へたどる。organized.json は出典ごとの原文の path・hash、AI-PLC の UID・所有 epoch、Task、判断の ref、as_of を持つ
- DB とファイルを一括で atomic とは言わない。準備の ledger → runtime の中の一時ファイルへ書いて fsync → 完成したファイルの排他的な link とディレクトリの fsync → hash の読み戻し → DB の pointer と receipt を同じ transaction で確定、の順に進む。pending があれば別の request を拒み、同じ request・同じ plan・同じ writer の再送で続ける。確定後の同じ request は同じ receipt を返す。同じ内容・同じ出典の再送は新しい版を作らない
- 箱の側も前の manifest と自分の書いた後の hash の journal を残し、確定の後・receipt の前の中断を再送で回復する。その後に別の writer が変えていれば戻さない。UTF-8 の原文はバイトのまま扱い、改行を正規化しない
- 自己補償は、同じ writer の確定した request・今の generation／revision・全ファイルの hash が一致するときだけ、pointer を前の版へ戻して generation を増やす。元の原稿・新しい版を消さない。並行の writer、後の版、未知のファイル、リンク、期限切れ、保留中の別の操作は拒む

## 実際の Registry で使うとき（LiveStore）

`core.LiveStore(<発行ファイルの絶対パス>)` が実際の Registry・Stock への唯一の入口。発行ファイルはリポジトリの根の下の通常のファイルで、`version: live-v1`・`repo_root`・`db_rel`・`stock_rel`・`lock_rel`・`staging_rel`・`host_uid`（今の OS の uid と一致）・`selector`（4つのキーの組）・`scope_id`・`aiplc_uid`・`adopted_folder`・`writer`・`task_id`・`issued_at`・`issued_by`・`approval_ref`・`expires_at`（未来の TZ つき）・`allow_schema_install` をすべて持つ。

- 別の組・別の Layer・別のフォルダ・別の writer・期限切れ・別の uid・symlink・根の外のパスは Hold。bind・identity・read を含むすべての操作で期限を確かめ直す
- 発行しただけでは何も書かない。`install_schema()` は flag が true のときだけ `stock_bindings`／`stock_operations` を CREATE TABLE IF NOT EXISTS で足す（既存の表は触らない）
- 業務Project の行は visibility と Program の read_domain が同じもの（`business_registry.py` が書く形）だけを受け付ける。link の `identity_snapshot` は Project の Identity の digest
- 発行ファイルを作るのは本人の採択の後だけ。発行ファイルの sha256・writer・期限は採択した Task の実行記録に残す
- Layer の intent に `aipm.storage: registry_stock_v1`・`stock_selector`・`aiplc_uid` を本人が書くまで、入口はその Layer で `shared storage not selected` と止まる

## 試験の回し方

リポジトリ（このスキルの元の置き場）で:

```sh
python3 -B -m unittest discover -s tests/db -p test_shared_stock.py -v
python3 -B -m unittest discover -s core/skills/aipm-guided/tests -p 'test_*.py'
```

`tests/test_shared_stock_integration.py` は `tests/db/test_shared_stock.py` の合成の作り置きを読むので、導入した先（`.claude/skills/aipm-guided/tests`）だけで回すと skip になる。
