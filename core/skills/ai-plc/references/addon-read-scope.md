# アドオン相談に必要な読取範囲

通常の相談は、本人が選んだ案内と共通約束を実helperから得て、現在状態に合う次の入口を返す。相談本体はreadonly。型の本文を読んでTaskを実行するA2、全基盤で保存しないA3は別の範囲である。

## 現在依頼の読取境界を最初に判定する（A1R修正1）

**この判定は、対象Layerの探索・一覧取得・metadata読取・選択照合・private・helper利用・claim・記録より先。** 最初に共有の入口Skillを読み、現在の依頼文で既に分かる禁止・不足を判定する。必要範囲の有無を確かめるために、許可外のファイル名やmetadataを先に取得しない。

- 現在依頼が全体no-write/trialを明示している場合、その場で未対応Hold。Layer一覧やintent等を読む通常手順へ進まない。
- 案件read-rootがDocuments/addon/等に限定され、intent/backlog/現在選択の許可が無いと現在依頼から分かる場合、その場で不足理由を返してHold。Layer直下をls/find/rgで一覧取得したり、ファイル名・属性・本文を読んだりしない。現在の作業ディレクトリであることは読取許可ではない。
- 必要な共有helper/固定契約の利用が現在禁止されている場合、その場で正式接続不可のHold。Layerの探索・一覧・選択記録の読取や、helperのhelp/実行、案内の手読みで不足を埋めない。
- 以上に該当しない通常相談だけ、既に許可された必要metadataから実選択・rootを確認する。読取範囲にはファイル内容だけでなく、一覧・ファイル名・属性も含む。共有手順の参照許可から案件データの許可を作らず、rootを広げない。

許可済みの既知パスへ到達するOSの親パス属性確認と、一覧や任意の案件metadataの取得は別である。前者を後者の許可にしない。Hold後は取得0/未確認を正確に返し、未取得データに基づく進捗・成功・Nextを生成しない。通常相談本体readonlyと依頼全体no-writeは従来どおり区別する。

## 案件データと共有プログラムを別に確認する

| 対象 | 必要なもの | 理由 |
|---|---|---|
| 案件Layer | intent.yaml / backlog.yaml | 選択されたaddon/version、参照、現在Task/依存/承認/期限を照合 |
| 案件Layer | selection_refが指す現在の選択記録（通常1件） | callerが実選択を確認。refの存在だけで本人許可を作らない |
| 案件Layerまたは明示common_root | guide_ref / common_contract_refの各1件 | helperが版/hashを固定して読み、案内と約束を返す |
| 案件Layer | 必要なTaskのcommand_template_ref（必要時だけ） | helperが実AGTの有無を確認しConstruction/Operationを案内 |
| callerの通常正本 | context.yamlなど、その相談の判断に必要な箇所 | 通常Skill側の背景確認。helperが全contextを読んだとは言わない |
| 案件Layer（inception_recurring のときだけ） | intent.yaml・guide_ref の案内1件・あれば backlog.yaml | 運用タスクの雛形の宣言を読み、案を返す（書かない） |
| 共有インストール | .claude/skills/ai-plc/scripts/plc_addon.py、入口Skill、addon-seam.md、固定 addon-seam-contract_v0.1/v0.2/v0.3.yaml（使う stage の分） | 稼働中の共有code/契約の利用許可。案件データrootとは独立 |

Case scopeはLayer内の相対名、common scopeは別途許可されたcommon_rootへ解決する。必要rootをcallerが明示し、ファイル・親symlink/外root/不明・hash不一致はHold。案内本文の上限は各64KiB、metadataは各256KiB。A1は型名を返すだけで型本文を読まない。max_form_itemsは型名の返却数上限であり、一Taskに複数型を使う許可ではない。

## 依頼文ごとの扱い

| 指示 | 通常callerの動作 |
|---|---|
| 「相談したい」 | 実選択と必要rootを確認しhelperを実呼出。実環境のexecutorを明示しguide/common/coverageから回答 |
| 「案件データの読取・保存はLayer内だけ。共有helper/契約利用は可」 | Layerを案件データrootとして必要集合だけ読む。外側scratchへ本文/回答を書かない。通常相談readonlyを全体trialに読み替えない |
| 「read-rootはDocuments/addon/だけ」 | intent/backlog/選択確認の許可が不足するためHold。Layer rootへ自動拡大しない |
| 「案件fileは読取可だが共有helper/契約は使わない」 | 正式接続の利用不可を説明してHold。手読み・別toolで代行成功にしない |
| 「この依頼全体は永続副作用なし/no-write trial」 | A3未対応としてprivate/claim/記録/Backfill前にHold。通常処理やQA起動へ進まず、未実施を返す |

`--read-root <Layer>`は境界指定であり全域読取命令ではない。source_refs/ReadCoverageで実取得と不足を示す。helper内部の固定共有契約読取も、現在callerがその利用を許可されている場合だけ行う。

## 実環境と保存境界

正式callerは現在の実環境からClaude Code=`--executor claude-code`、Codex=`--executor codex`を明示する。返却はそれぞれ`/plc-brief`と`$plc-brief`など環境で使える同じ正式入口。既定Codexは旧API互換であり、未知環境を判定する根拠ではない。helperはdispatch/保存を行わず、返却や案件YAMLから操作許可を作らない。

通常caller試験は架空入力で、評価対象のconsultと、準備・tool trace保存・ホストlog/temp/cacheを分ける。明示された保存先の外へ一時ファイルを作らない。ホストの効果が不明/拒否なら試験をHoldし、模擬executorや手読み回答を実AI成功にしない。helper readonlyだけでCLI/全基盤の副作用0やA3完成を保証しない。
