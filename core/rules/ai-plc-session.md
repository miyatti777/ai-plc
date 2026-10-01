> 🏷️ **Project:** \[YOUR_PROJECT\]
> **Type:** rule
> **Context:** AI-PLC セッション管理ルール。セッション分割・引き継ぎ・再初期化と、全スキル共通の出力フォーマット規約（4パート/Next Action/Mob CP）を定義。

## 1. セッション分割トリガー

長いセッションでは初期指示がコンテキストから押し出され品質が劣化するため、以下の閾値で新スレッドへの分割を推奨する。

| 条件 | 閾値 |
| --- | --- |
| Sub-Layerの数 | 3つ以上 |
| タスク総数 | 10タスク以上 |
| 見積時間 | 2時間超 |
| 階層の深さ | 3階層以上 |

## 2. 分割方法

推奨: Sub-Layerごとに1スレッド。代替: ステージ境界で分割（Collection+Inception / Construction+Operation）。

## 3. コンテキスト引き継ぎ

新スレッドに必ず渡すもの: ①AI-PLC system（README） ②RUL_plc_system ③対象Layerのintent.yaml ④同context.yaml。Sub-Layerの場合は追加で: 親intent.yaml + 親backlog.yaml。

起動テンプレート（コマンドは実行環境の起動形式で書く — §7.4）:
- 新規Sub-Layer: 「/01-collection を実行してください / Goal: [Goal] / 親Layer: [パス]」
- タスク継続: 「/04-operation を実行してください / Layer: [パス] / Task: [ID]」

## 4. 親スレッドへの報告

子スレッド完了時のフォーマット: 「📤 子スレッド完了報告 / Layer: [ID] / Status: completed|blocked|partial / 📋 完了 X/Y / 📝 主な成果物: [URL] / ⚠️ ブロッカー / 💡 学び / 🔜 次のアクション」

## 5. セッション完了前チェック

終了前に必ず: ①親Layerの未着手Sub-Layer確認 ②兄弟Sub-Layerの着手可能性確認 ③実行可能な残Task確認 ④先行構築できる次フェーズ確認。

禁止: 残タスク未確認での終了 / 「他にありますか？」とユーザーに探索を委ねる / 一部のSub-Layerだけ見て終了。
正: 親Layer確認 → 残タスク特定 → 「次は○○です」と提案。

## 6. 再初期化（Update）ルール

鉄則: トップダウン・再帰的・段階的。①トップレベルのみ実行しSub-Layerは別タスクに分解 ②backlog.yamlに再帰タスクを記録してから実行 ③1階層ずつ確認しながら進める ④既存成果物は保持（上書きしない）。

## 7. 出力フォーマット規約（必須）

全Stage・全Taskの完了報告には以下の4パートを必ず含める。

### 7.1 現在位置ヘッダー

`📍 [Scope ID] > Stage X: [Stage名] > [Task ID]: [Task名] > Phase Y`

### 7.2 完了サマリテーブル

| 項目 | 内容 |
| --- | --- |
| Scope | [Scope ID + 名称] |
| 完了対象 | [Stage / Task / Phase] |
| 成果物 | [リンク or 「なし」] |
| ステータス | done / partial / blocked |

### 7.3 進捗ダッシュボード

`📊 進捗: X/Yタスク完了（Z%）` + タスク一覧（✅done / ▶️実行可能 / ⬜pending(依存) を明示）。

### 7.4 Next Action Protocol

3パート構成で出力する: ①選択肢テーブル（A/B/C + 説明、推奨に⭐） ②推奨理由（箇条書き） ③コピペ用プロンプト。

**即実行禁止ルール:** ユーザーが「A」等を選んでも即座に実行せず、コピペ用プロンプトを生成して返し、明示的な実行指示を待つ（確認・編集の機会を保証するため）。例外は自動完走中（§10 を指す /goal が続いている間）だけ（§10）。

プロンプト生成ルール:
- **実行形式は環境の正:** コピペ用プロンプトのコマンドは実行環境の起動形式で書く — CC = `/01-collection`〜`/04-operation`（.claude/commands/が正）、Cursor = `@SKL_plc_*` メンション、Notion = SKL_plc_*ページメンション。`SKL_plc_*` は論理名（相互参照用）であり、CCのコピペプロンプトには使わない
- 実際のファイルパス・@mentionを使い、そのままコピペで動く形にする / コードブロックで囲まない
- 代替選択肢（情報追加・セッション終了等）も必ず提供

**Stage別の標準選択肢（コマンド表記はCC形式の例）:**

| 完了時点 | A（⭐推奨） | B / C |
| --- | --- | --- |
| Stage 1 | /02-inception 実行 | Context追加修正 |
| Stage 2 | construction.required が true → /03-construction 実行／false → /04-operation でP0タスク実行 | backlog修正 / SubLayer Collection先行 |
| Stage 3 | /04-operation でP0タスク実行 | タスク一覧確認 |
| Stage 4 Task完了 | 次タスク実行 | 親Layerに戻る / セッション終了 |
| 全タスク完了 | 親Backlog更新→次Sub-Layerへ | パイプライン完了 |

※ Stage 2 完了後の A は backlog の `construction.required` で決まる（RUL_plc_adaptive §6）。

## 8. Phase遷移通知ルール（必須）

各Phase完了時に簡易通知を出力し、ユーザーが割り込めるタイミングを作る（自動完走中に待機を省く扱いは §10）:

`📍 [Scope ID] > Stage X > **Phase Y: [Phase名] 完了** ✅ / [1-2行サマリ] / → Phase Y+1: [次Phase名] に進みます`

| Phase種別 | 通知 | ユーザー待機 |
| --- | --- | --- |
| Autonomous Phase | 簡易通知のみ | 不要（割り込みがあれば即停止） |
| Mob Checkpoint Phase | 簡易通知 + 🙋承認/選択ブロック | 必須 |
| 最終Phase（Stage/Task完了） | §7の4パート出力 | 必須（Next Action選択待ち） |

## 9. Mob Checkpoint出力規約（必須）

自動完走中（§10）は、ブロックを出したうえで待たずに⭐を選ぶ。

- **基本Markdownのみ**（太字・区切り線・リスト・テーブル）。callout / toggle等のAdvanced Blockは使わない
- **承認ファースト:** 承認/選択ブロックはメッセージ冒頭に配置し、`---`で囲む。詳細説明はその後
- **選択肢を明示:** 「どうしますか？」で終わらない。推奨には⭐を付ける
- **Forward Look必須:** 各選択肢に「選んだ後に何が起きるか」を1行で明示する
- **質問の内容基準（Material Ambiguity）:** 不明点を引き出す明確化質問（clarifying question）は「スコープ・検証方法・データの扱い・権限・受け手に見える挙動」を変えうる不確実性のみとする。コード・規約・Contextから答えが出る実装詳細は質問しない。1問ずつ / 選択肢は現実的なもの最大3つ（明らかに選ばれない当て馬は禁止）/ 各選択肢に「選んだ結果+作業量」を付す / 推奨理由の説明は選択肢の後に置く（⭐マーク併記は可）。本基準は明確化質問のみに適用し、Next Action Protocol（§7.4）・Backtrack選択肢（RUL_plc_adaptive §5）・SKILLが停止と定める必須Mob Checkpointの実施要否には影響しない

承認待ちテンプレート:

```
---
🙋 **承認してください**

→ **OK** — [承認後に何が起きるか]
→ **修正: [指示]** — [修正後の再提示フロー]
→ **差し戻し** — [どこに戻るか]
---
```

選択待ちテンプレート（**テーブル形式必須** — 1選択肢1行。説明を`→`で連結して1段落に詰めない）:

```
---
🙋 **選択してください**

| 選択肢 | アクション | 選んだ後に起きること |
| --- | --- | --- |
| **A** ⭐ | [アクション] | [Forward Look] |
| **B** | [アクション] | [Forward Look] |
---
```

## 10. 自動完走モード（/goal で本節を指すとき）

このセッションでユーザーが打った（貼った）/goal の文が本節（RUL_plc_session §10）を指しているか、識別句「AI-PLC 自動完走（自己完結版）」を含むとき、その /goal が続いている間だけ適用する。それ以外のセッションは本節を読まず、§7.4・§8・§9 のとおり止まる。「自動で」などの口頭の指示だけでは適用しない。intent.yaml には何も記録しない。

**始め方・止め方:** Collection・Inception の完了報告の最後に出る /goal 1行（下の短い版）を貼る。新しい Goal から1本で走らせるときは Goal から版、本節の無い環境では自己完結版を貼る。止めるのは `/goal clear`。自動で進め始めたら、対象 Layer の refactoring_log に `[auto-approved] /goal 開始（§10）` を1行書く（Goal から版は Layer ができた時点で。会話が圧縮されても分かるようにするための印で、この行を適用の根拠にはしない — 適用はこのセッションの /goal だけで決める）。

**対象の Layer:** /goal に Layer パスがあればそれ。無ければ、この会話で直前に /01-collection〜/04-operation を実行した Layer か直前に話題にした Layer。どちらも無ければ /goal の Goal で /01-collection から作る。決められなければ停止。SubLayer には及ばない（SubLayer が出たら停止 — 下の「停止」）。

**自動で進める内容（§7.4 即実行禁止・§8 の待機・§9・各 SKILL の「停止」「承認を待つ」より優先）:**

| 場面 | 扱い |
| --- | --- |
| Mob Checkpoint | ブロックは通常どおり出し、同じターンで⭐（承認なら OK）を選んで続ける。Collection の Phase 7 も同じ。⭐が下の「保留する」に当たる操作なら保留してログに残し、次の手順へ進む。⭐が無ければ停止 |
| Next Action | A（⭐）を選び、コピペ用プロンプトのコマンドをその場で実行する。ただし Layer の全タスクが終わったときの Next Action（親 Backlog 更新・次の Sub-Layer など）は実行せず、完了報告で止まる |
| simple で backlog が空 | Collection の後でも、別セッションで /04-operation から始めたときでも、まず Goal を1タスクにした backlog.yaml を作り、refactoring_log に Stage 2 を省いた理由を書き、`construction`（RUL_plc_adaptive §6）を書いてから、required が false なら /04-operation、true なら /03-construction へ進む |
| Stage 4 Phase 2 | 聞かずに P0→P1→P2・依存順で実行可能なタスクを選ぶ。並列委譲の条件を満たす組は委譲してよい |
| 明確化質問 | 聞かずに最も妥当な仮定を置く。§9 の「データの扱い・権限・受け手に見える挙動」に当たるものは最も保守的な選択肢（保留・非公開・変更しない）を仮定する |
| Phase 5.5 検証 | 04-operation のとおり（完了ゲート＝未解決 P0〜P2 ゼロは緩めない）。同じタスクで修正→再検証は2回まで。2回後も P0〜P2 が残れば停止 |
| Backtrack | BT-A は停止。BT-B・BT-C は独立 checker の判定まで行い、ドリフトなし・追加ゴールなしなら続行・完了、Re-Inception・Re-Collection が要るなら停止（RUL_plc_adaptive §5 ルール1 は緩めない） |

**書き込み・送信の範囲:**

| 実行する | 保留する（「保留: <内容>」とログに残して先へ進む） |
| --- | --- |
| Layer 内のファイル／Layer 外は backlog の output に書かれたパスと、04-operation Phase 6・7 の決まった書き込み先（親 backlog・wiki・log.md・native memory）だけ／ローカル Registry（sqlite の add-project・UPDATE。タスク行は書かない — RUL_plc_system §9）／テスト・ビルド・読み取りスクリプト／Web 検索・取得（機密を扱う Layer を除く） | 上記以外の Layer 外ファイル／削除・移動・既存成果物の上書き（§6）／git の commit・push・PR・merge・タグ／外部公開（リポジトリ・パッケージへの反映）／Notion・Slack・メールへの書き込み・送信／ローカル sqlite 以外の sync_targets・外部DBへの書き込み／承認後の決まりがある反映（ステータス点検の反映など）／上記以外の操作（お金・外部 API への送信・ツールの導入など） |

**停止:** 行頭に単独で `⛔ 自動完走を停止: <理由>` を出し、再開のしかたと自動承認ログの表を出して止まる（説明文の中でこの文字列を引用しない）。理由は、対象の Layer を決められない／対象 Layer の workflow_depth が complex か mode が platform_builder と判定された（開始時でも Collection の途中でも、判定された時点で止まる）／Collection の Phase 1 で RUL_plc_adaptive §0 の①（Layer を作らない）に当たった／BT-A／P0〜P2 が2回の修正後も残る／Backtrack が要る／⭐が無い／保留したものが無いと先へ進めない／人が担当するタスクだけが残った／Inception の分解に SubLayer が含まれる（complex。分解の承認前に停止）、のいずれか。

**自動承認ログ:** 自動で選んだ判断は毎回1行、backlog.yaml の refactoring_log に `- date: 'YYYY-MM-DD'` ／ `entry: '[auto-approved] S<Stage>/P<Phase>: <選んだこと>（<理由>）'` で書く。全完了・停止のときに `[auto-approved]` の行を表にまとめて表示し、完了報告の冒頭に「確認してほしいこと」（仮定で決めた名前・公開の文面・保守的に仮定した事項・output に Layer 外の既存ファイル（rules・skills 等）を含むタスク）を1行ずつ出す。

**/goal の書き方:**

- **短い版**（Collection・Inception の完了報告の最後に「自動で進めるなら:」として Layer パスと開始列を埋めて1行出す。止まる挙動は変えない）:
  `/goal <Layerパス> を <開始列> で完走する（RUL_plc_session §10 の自動完走）。達成: backlog の全タスクが completed（deferred・blocked は保留理由がログにあるもの）・各 output が実在・Phase 7 チェックリストと自動承認ログを表示、または行頭に「⛔ 自動完走を停止」を表示。or stop after 40 turns`
- **Goal から版**（Layer を作るところから1本で走らせる）:
  `/goal 「<Goal>」を /01-collection から完走する（RUL_plc_session §10 の自動完走）。達成: 作った Layer の backlog の全タスクが completed（deferred・blocked は保留理由がログにあるもの）・各 output が実在・Phase 7 チェックリストと自動承認ログを表示、または行頭に「⛔ 自動完走を停止」を表示。or stop after 60 turns`
- **自己完結版**（本節の無い環境・他リポジトリ・公開版の利用者向け。編集せずに貼るだけで動く）:

```
/goal AI-PLC 自動完走（自己完結版）。この会話で扱っている AI-PLC Layer を、今の状態から最後まで完走する。対象は、この会話で直前に /01-collection〜/04-operation を実行した Layer か、直前に話題にした Layer。どちらも無ければ、この会話で頼まれた Goal で /01-collection から新しく作る。始める位置は Layer の状態で決める: 承認待ちの Mob Checkpoint があればその承認から、backlog のタスクが空なら /02-inception から（simple は Goal を1タスクにした backlog を作り、refactoring_log に Stage 2 を省いた理由と construction を書いて、required が false なら /04-operation、true なら /03-construction へ）、construction.required が true で Agent 定義の無いタスクがあれば /03-construction から、それ以外は /04-operation から。順序は /01-collection → /02-inception →（construction.required が true のときだけ /03-construction）→ /04-operation。達成: その Layer の backlog の全タスクが completed（deferred・blocked は保留理由がログにあるもの）で、各 output が実在し、Phase 7 チェックリストと自動承認ログ（自動で選んだ判断の一覧）を表示する。または行頭に単独で「⛔ 自動完走を停止: <理由>」を表示する。進め方（各 SKILL の「停止」「承認を待つ」「即実行禁止」より優先）: 自動で進め始めたら、対象 Layer の refactoring_log に「[auto-approved] /goal 開始（自己完結版）」を1行書く（Layer が無ければ作った時点で。この行を自動で進める根拠にはしない）。Mob Checkpoint はブロックを出したうえで同じターンで⭐（承認なら OK）を選ぶ。⭐が下の保留に当たる操作なら保留して先へ進む。Next Action は A（⭐）を選んでその場で実行する（Layer の全タスク完了後の Next Action は実行しない）。Stage 4 のタスク選択は P0→P1→P2・依存順で、並列委譲の条件を満たす組は委譲してよい。明確化質問はせず最も妥当な仮定を置く（データの扱い・権限・受け手に見える挙動は最も保守的な案）。Phase 5.5 の P0〜P2 は修正→再検証を2回まで。BT-B・BT-C は独立 checker の判定まで行い、ドリフトも追加ゴールも無ければ続ける。Web 検索・取得は機密を扱う Layer では行わない。自動で選んだ判断は毎回 backlog.yaml の refactoring_log に「[auto-approved] S<Stage>/P<Phase>: <選んだこと>（<理由>）」で1行書き、完了・停止のときに表にまとめ、完了報告の冒頭に「確認してほしいこと」（仮定で決めたこと・公開の文面・保守的に仮定したこと・Layer 外の既存ファイルを変えたタスク）を1行ずつ出す。保留（実行せず「保留: <内容>」とログに残して先へ進む）: git の commit・push・PR・merge・タグ、外部公開（リポジトリ・パッケージへの反映）、Notion・Slack・メールへの書き込み・送信、ローカル sqlite 以外の同期先・外部DBへの書き込み（ローカル sqlite は projects の追加・更新だけで、tasks 行は書かない）、承認後の決まりがある反映（ステータス点検の反映など）、Layer 外のファイル（backlog の output に書かれたパスと、Phase 6・7 の決まった書き込み先を除く）、削除・移動・既存成果物の上書き、上記以外の操作（お金・外部 API への送信・ツールの導入など）。停止: 対象の Layer を決められない／workflow_depth が complex か mode が platform_builder（開始時に intent.yaml で確かめ、途中で判定されたときもその時点で）／Collection で「Layer を作らない」に当たった／BT-A／P0〜P2 が2回の修正後も残る／Backtrack が要る／⭐が無い／保留したものが無いと進めない／人が担当するタスクだけが残った／分解に SubLayer が含まれる（分解の承認前に停止）。止まるときは再開のしかた（同じ /goal を貼り直す等）も示す。or stop after 60 turns
```

本節を直したら、自己完結版も同じ内容にそろえる（自己完結版は本節の無い環境で唯一の規定になるため）。本節のある環境で自己完結版が貼られて食い違いがあれば、本節を正とする。

開始列（短い版）: backlog のタスクが空 → standard は `/02-inception → /04-operation`（Inception が `construction.required: true` を書いたら間に `/03-construction` を挟む）、simple は `/04-operation`（backlog が空なら上の表の「simple で backlog が空」で先に作る。`construction.required` が true になれば `/03-construction` を挟む）／`construction.required` が true で、`construction.tasks` のうち Agents/ に定義の無いタスクがある（欄が無ければ RUL_plc_adaptive §6 のみなし規定に従う）→ `/03-construction → /04-operation`／それ以外 → `/04-operation`。/goal はユーザーが打つ（スキルは1行出して止まる）。ターン上限で ⛔ も出ずに終わったら、同じ /goal を貼り直して続きから再開できる。

---
**作成日:** 2026-04-07 ｜ **更新日:** 2026-10-01 ｜ **ステータス:** Active
**バージョン:** 2.1（§10 自動完走モード〔/goal で §10 を指すとき〕を新設〔ローカル sqlite は projects だけを書き、tasks 行は書かない — RUL_plc_system §9〕。§7.4・§8・§9 に例外の参照。§7.4 の Stage 2 の後は backlog の construction.required で決める）｜ 2.0（Fable観点軽量化: 重複貼付解消後に本文圧縮。§7-9が全スキル共通の出力規約の唯一の定義箇所）
