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

新スレッドに必ず渡すもの: ①AI-PLC system（README） ②RUL_plc_system ③対象Layerのintent.yaml ④同context.yaml ⑤同backlog.yaml。Sub-Layerの場合は追加で: 親intent.yaml + 親backlog.yaml。止まった仕事を続けるときは [outcome-delivery.md](../skills/ai-plc/references/outcome-delivery.md) の「止まった後に続ける」に従い、成立済み成果・未達・次の操作を既存 backlog に短く残す。

起動テンプレート（コマンドは実行環境の起動形式で書く — §7.4）:
- 新規Sub-Layer: 「/01-collection を実行してください / Goal: [Goal] / 親Layer: [パス]」
- タスク継続: 「/04-operation を実行してください / Layer: [パス] / Task: [ID]」

## 4. 親スレッドへの報告

子スレッド完了時のフォーマット: 「📤 子スレッド完了報告 / Layer: [ID] / Status: completed|blocked|partial / 📋 完了 X/Y（運用タスクを除く） / 📝 主な成果物: [URL] / ⚠️ ブロッカー / 💡 学び / 🔜 次のアクション」

## 5. セッション完了前チェック

終了前に必ず: ①親Layerの未着手Sub-Layer確認 ②兄弟Sub-Layerの着手可能性確認 ③実行可能な残Task確認 ④先行構築できる次フェーズ確認。

禁止: 残タスク未確認での終了 / 「他にありますか？」とユーザーに探索を委ねる / 一部のSub-Layerだけ見て終了。
正: 親Layer確認 → 残タスク特定 → 「次は○○です」と提案。

## 6. 再初期化（Update）ルール

鉄則: トップダウン・再帰的・段階的。①トップレベルのみ実行しSub-Layerは別タスクに分解 ②backlog.yamlに再帰タスクを記録してから実行 ③1階層ずつ確認しながら進める ④既存成果物は保持（上書きしない）。

## 7. 出力フォーマット規約（必須）

全Stage・全Taskの完了報告には以下の4パートを必ず含める。

### 7.0 案件ごとの説明の詳しさ

対象 Layer の `intent.explanation.level` を読む: `brief`（要点中心）/ `reasoned`（理由も説明。既定）/ `guided`（前提・用語から説明）。CLI: `python3 .claude/db/plc_explain.py show|set --layer <Layer> [--level brief --yes]`。「以後は短く」は保存し、「ここだけ詳しく」は次の1応答だけ（`show --once guided`）。不正値は警告1行で reasoned。新規案件は Collection の確認表示で3候補を示し、本人の選択があれば保存する（未回答は既定であり本人の選択ではない）。子 Layer は親の明示値を Collection 時にコピーできる overridable で、親の変更を子へ自動で遡及させない。必要な専門用語・略語は初出時に日常の言葉で今回の意味を添える。

どの設定でも、何ができたか・何が残るか・人がすることを具体的な日本語で先に書き、承認対象・選択後に起きること・懸念・費用や手間・推奨根拠と代替案は省かない。タスク・ペルソナ・論点・仮説などの ID は、どの設定でも、その応答で最初に出すときに名前を添える（例：T003（会議の反応を足す））。2回目以降、名前の列がある表、コピペ用プロンプトの中では ID だけでよい。案件を別の人へ渡すときは、`plc_explain.py show` で説明の詳しさの既定を確かめ、受け手に合う詳しさを本人に確かめる（保存は本人が選んだときだけ）。説明設定は承認・Next Action・独立検証・§10 の停止条件を変えない。

### 7.1 現在位置ヘッダー

`📍 [Scope ID] > Stage X: [Stage名] > [Task ID]: [Task名] > Phase Y`

### 7.2 完了サマリテーブル

| 項目 | 内容 |
| --- | --- |
| Scope | [Scope ID + 名称] |
| 完了対象 | [Stage / Task / Phase] |
| 成果物 | [リンク or 「なし」] |
| ステータス | done / partial / blocked |

**AC達成度（検証レポート・完了報告で共通）:** ACごとに `達成 / 一部 / 未達 / 未確認` と証拠を示す。達成=条件全体の充足を確認、一部=充足した部分の証拠はあるが残りがある、未達=条件を満たさないことを確認、未確認=充足を判定する証拠が足りない。一部には**達成部分・残件・証拠**を、未達・未確認には理由と残る対応・確認を添える。例: `AC1: 一部 — 6/10件取込済（csv_log.txt）、残り4件未対応`。証拠の無い部分を達成扱いしない。

一部・未達・未確認が1件でもあれば、サマリを `partial` または既存の阻害理由に応じた `blocked` とし、「全OK」「全達成」「残りなし」とまとめず残件を明記する。検証手順の終了・reviewerの `No findings` とAC達成は別に書く。**taskのcompletedは全AC達成＋既存の検証ゲートを満たすときだけ**（04-operation Phase 5.5・6）。新しいtask status値は作らず、Layer全体の完了も元goalのsuccess_criteriaと照合する。

### 7.3 進捗ダッシュボード

`📊 進捗: X/Yタスク完了（Z%）` + タスク一覧（✅done / ▶️実行可能 / ⬜pending(依存) を明示。各行は ID と名前）。本文で ID に触れるときも §7.0 のとおり最初は名前を添える。X/Y は運用タスク（recurrence のある Task）を除いて数え、運用タスクは別に『運用 N件（最後の run: 日付）』と添える。

### 7.4 Next Action Protocol

全 Stage と全補助スキルの最終応答には「次のアクション」と、その場でコピーして送れる「次のプロンプト」を必ず含める（説明だけの応答は短い2行でよい）。選択肢が要る場面では3パートを**最初の案内で同時に**出す: ①選択肢テーブル（A/B/C + 説明、推奨に⭐） ②推奨理由（箇条書き） ③コピペ用プロンプト。

- **入口と成果:** 実行案には現在地に合う実在の `/01-collection`〜`/04-operation` または `/plc-<機能>`、必要な Layer/Task、選んだ後に得る成果を付ける。読取だけの案にも入口を付ける（説明は plc-brief、点検は plc-status-audit、案内の復元は plc-next）。仮のパス・Task・承認を埋めない
- **工程停止と依頼終了は別:** スキルの「この工程で止まる」は AI の操作境界。Goal/SC に未達があれば次の正式入口を示し、真の達成を証拠で確認したときだけ依頼完了にする。本人の保留・取消は成功完了ではない
- **明確な最終選択回答で開始する:** 初回案内で開始内容・許可範囲・「回答でその処理を開始する」を示し、本人の明確な最終選択（A など）を受けたら同じ担当がその範囲を実行して結果を返す。開始文の再送や同じ承認は求めない。未回答・既定選択・UI 受付・曖昧な回答は開始指示ではなく、対象違い・旧版・範囲外では止める。相談だけ・計画採用だけの許可を実行一式へ広げない
- **実行形式は環境の正:** CC = `/01-collection`〜`/04-operation`（.claude/commands/が正）、Cursor = `@SKL_plc_*`、Notion = SKL_plc_* ページメンション。`SKL_plc_*` は論理名で CC のプロンプトには使わない。実際のパスを使い、コードブロックで囲まない
- **依頼文の中身を先に示す:** コピペ用プロンプトの前に、対象（Layer・Task とその名前）・やること・前提・してはいけないことを短い箇条書きで示す（自明な項目は省いてよい）。コピペ用の1行の形は変えない
- 代替選択肢は現在の成果に関係する確認・補足・計画修正から選ぶ。人の選択を待つときは §9.1 の質問UIを呼ぶ。intent.addons のある Layer では [addon-seam.md](../skills/ai-plc/references/addon-seam.md) の案内を唯一の Next に統合する

**Stage別の標準選択肢（コマンド表記はCC形式の例）:**

| 完了時点 | A（⭐推奨） | B / C |
| --- | --- | --- |
| Stage 1 | /02-inception 実行 | Context追加修正 |
| Stage 2 | construction.required が true → /03-construction／false → /04-operation でP0タスク | backlog修正 / SubLayer Collection先行 |
| Stage 3 | /04-operation でP0タスク実行 | タスク一覧確認 |
| Stage 4 Task完了 | /04-operation で次の実行可能Taskへ | /plc-brief で Goal 未達と成立済み成果を確認 |
| 全タスク終端（運用タスクを除く。RUL_plc_adaptive §5） | 元Goal/SCと検証証拠を照合し、未達があれば必要な正式入口 | 全Goal達成が確認できれば依頼完了 |

※ 表は開始位置の例であり、⭐の妥当性は§7.5で判定する。目的に届かない案へ固定で⭐を付けない。

### 7.5 重い工程の前の判定可能性と推奨

多数の試行・大量生成・長い実装など費用を増やす工程に進むとき、または天井・床・欠測・前提不足など**目的を判定できない証拠**が見つかったとき、開始前に資料から確認する: ①何を判断・達成したいか ②必要な証拠と判定方法 ③既知の不成立条件 ④次の案で判定可能性が変わる根拠。軽い作業や確認済みの事項には足さない。

選択肢表には **目的への到達可否（可能・条件付き・不能・不明）＋根拠/不足、追加費用・作業量（実測・見積・不明を区別）、選んだ後の結果**を入れる。**⭐は目的に届く根拠がある案だけ**。条件付きの案は、前提を確認する小さい工程だけを成功条件とともに推奨でき、その結果が出るまで本工程へ進まない。到達案も前提確認も無ければ⭐なしで不成立理由・不足証拠・再開条件を示す。前提崩壊や GAP は RUL_plc_adaptive §5 へ接続し、Backtrack を勝手に実行しない。関門・⭐は必須 Mob Checkpoint・独立レビュー・BT checker を代替せず、権限・送信承認・Goal 変更を増やさない。

### 7.6 長期化を防ぐ継続判断（重い工程だけ）

§7.5 の重い自動実行・反復の長期化・方式拡大では、最初の工程前に `backlog.yaml.execution_budget` を書き、見直し点で残経路・残予算・次の AC 証拠を照合する。記録の形・持越し・終了条件は [execution-record.md](../skills/plc-auto/references/execution-record.md) に従う。軽い既知作業にはこの記録・追加質問・追加レビューを足さない。

## 8. Phase遷移通知ルール（必須）

各Phase完了時に簡易通知を出力し、ユーザーが割り込めるタイミングを作る（自動完走中に待機を省く扱いは §10）:

`📍 [Scope ID] > Stage X > **Phase Y: [Phase名] 完了** ✅ / [1-2行サマリ] / → Phase Y+1: [次Phase名] に進みます`

| Phase種別 | 通知 | ユーザー待機 |
| --- | --- | --- |
| Autonomous Phase | 簡易通知のみ | 不要（割り込みがあれば即停止） |
| Mob Checkpoint Phase | 簡易通知 + 🙋承認/選択ブロック + §9.1の質問UI | 必須（§10例外） |
| 最終Phase（Stage/Task完了） | §7の4パート出力 | 必須（Next Action選択待ち） |

## 9. Mob Checkpoint出力規約（必須）

自動完走中（§10）は、ブロックを出したうえで待たずに⭐を選ぶ。人の回答が必要な場面では、以下の説明に加え §9.1 の質問UIを呼ぶ。

- **基本Markdownのみ**（太字・区切り線・リスト・テーブル）。callout / toggle等のAdvanced Blockは使わない
- **承認ファースト:** 承認/選択ブロックはメッセージ冒頭に配置し、`---`で囲む。詳細説明はその後
- **選択肢を明示:** 「どうしますか？」で終わらない。§7.5で推奨できる案に⭐を付ける（到達案・前提確認案が無ければ⭐なしで不足と再開条件を示す）
- **Forward Look必須:** 各選択肢に「選んだ後に何が起きるか」を1行で明示する
- **質問の内容基準（Material Ambiguity）:** 明確化質問は「スコープ・検証方法・データの扱い・権限・受け手に見える挙動」を変えうる不確実性だけ。コード・規約・Contextから答えが出る実装詳細は読んで決める。1問ずつ / 選択肢は現実的なもの最大3つ / 各選択肢に「選んだ結果+作業量」/ 推奨理由は選択肢の後。この基準は明確化質問だけに適用し、§7.4・Backtrack 選択肢・必須 Mob Checkpoint の実施要否には影響しない

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

### 9.1 人の承認・選択を質問UIで届け、回答を待つ

人の承認・選択を待つ場面（必須 Mob Checkpoint・Next Action・Backtrack・必要な Material Ambiguity）では、文章に加えてその環境で許された質問UI（Claude Code は AskUserQuestion、Codex は現在の tool schema の質問UI）を実際に呼ぶ。既定: 1問ずつ・選択肢最大3つ・自由文の修正も受ける（4件以上は文章の表で全 ID を保持し UI は3件ずつの段階選択。グループ選択は承認ではない）／UI の質問文と選択肢は会話にも同文で残す／UI の受付・表示・既定値・時間経過は回答ではなく、本人の明示回答を質問・対象版・許可範囲と照合してから再開する／回答待ちは依存作業の停止であり、未回答のまま final で終えない。正規の待機手段が無ければ質問原文・対象版・未回答状態を Layer の Context に保存して中断報告する／明確な最終選択回答の後は §7.4 のとおり同じ担当が続行する。通知の証拠の区別・取消/遅着回答・環境別の細則は [question-ui.md](../skills/ai-plc/references/question-ui.md)。判断に要る中身（対象の要点・数値・各選択肢を選んだ結果）は質問文と選択肢の説明に入れ、質問の前の本文だけに頼らない（Remote Control などでは本文が本人に届かないことがある）。

## 10. 自動完走モード（/goal で本節を指すとき）

このセッションでユーザーが打った（貼った）/goal の文が本節を指しているか、識別句「AI-PLC 自動完走（自己完結版）」を含むとき、その /goal が続いている間だけ適用する。それ以外は本節を読まず §7.4・§8・§9 のとおり止まる。口頭の「自動で」だけでは適用しない。intent.yaml には何も記録しない（旧版の `run_mode: auto` は書き換えず読む側で無視する）。

**専用入口 `plc-auto`:** 利用者が `/plc-auto`・`$plc-auto` を明示実行して開始を確認できたときも、その継続が続いている間だけ本節を適用する（開始のしかた・状態管理は `plc-auto/SKILL.md`）。自動選択・説明だけでは開始しない。本節の保留・停止範囲は緩めない。

**始め方・止め方:** Collection・Inception の完了報告の最後に出る短い版の /goal を貼る。Goal から1本で走らせるなら Goal から版、本節の無い環境では自己完結版（[goal-preset.md](../skills/plc-auto/references/goal-preset.md)。貼るだけで動く。本節を直したら同じ内容にそろえ、食い違いは本節が正）。手動停止は CC が `/goal clear`、Codex は [codex-runtime.md](../../.agents/skills/ai-plc/references/codex-runtime.md)。始めたら対象 Layer の refactoring_log に `[auto-approved] /goal 開始（§10）` を1行書く（印であり適用の根拠ではない）。§7 の定型出力や開始/再開の案内を、不在案内の再送根拠にしない。停止宣言と native Goal の状態は別で、未達を complete にしない。

**対象の Layer:** /goal の Layer パス → 無ければこの会話で直前に `/0N-*` を実行した Layer か直前に話題にした Layer → 無ければ /goal の Goal で /01-collection から作る。決められなければ停止。SubLayer には及ばない。

**自動で進める内容（§7.4 の回答待ち・§8 の待機・§9・各 SKILL の「停止」「承認を待つ」より優先）:**

| 場面 | 扱い |
| --- | --- |
| Mob Checkpoint | ブロックは通常どおり出し、同じターンで⭐（承認なら OK）を選んで続ける（重い工程の前は §7.5 を確認）。⭐が「保留する」に当たる操作なら保留してログに残し先へ。⭐が無ければ停止 |
| Next Action | ⭐の選択肢のコマンドをその場で実行する。前提確認の案はその工程だけ実行して本工程を再判定する。Layer の全タスク（運用タスクを除く）が終わったときの Next Action は実行せず完了報告で止まる |
| simple で backlog が空 | Goal を1タスクにした backlog.yaml を作り、Stage 2 を省いた理由と `construction`（RUL_plc_adaptive §6）を書いてから /04-operation（required が true なら /03-construction）へ |
| Stage 4 Phase 2 | 聞かずに 04-operation Phase 2 の一覧の順（実行時期のある Task を早い順→時期の無い Task を P0→P1→P2・依存順）で選ぶ（実行時期 scheduled_for が今日より後の Task は選ばない）。並列委譲の条件を満たす組は委譲してよい。運用タスク（recurrence）は自動完走では回さず、完了報告と停止の報告で次に回す日を示す（回すのは /04-operation で Task を指定したとき。scheduled_for があればその日から）。 |
| 明確化質問 | 聞かずに最も妥当な仮定を置く。データの扱い・権限・受け手に見える挙動は最も保守的な案（保留・非公開・変更しない） |
| Phase 5.5 検証 | 完了ゲート（未解決 P0〜P2 ゼロ）は緩めない。同じタスクで修正→再検証は2回まで。残れば停止 |
| Backtrack | BT-A は停止。BT-B・BT-C は独立 checker の判定まで行い、ドリフト・追加ゴールが無ければ続行、Re-Inception・Re-Collection が要るなら停止 |
| Jev 監視 | `jev_monitor` の opt-in は自動承認しない。判定とヒント表示は通常どおり、accept / reject は記録しない |

人の明示承認が必要な境界（「保留する」操作を本人が個別に許可する場面など）だけ §9.1 の質問UIで回答を待つ。上表の自動選択・仮定に質問UIの待機は足さない。

**書き込み・送信の範囲:**

| 実行する | 保留する（「保留: <内容>」とログに残して先へ進む） |
| --- | --- |
| Layer 内のファイル／Layer 外は backlog の output に書かれたパスと Phase 6・7 の決まった書き込み先（親 backlog・wiki・log.md・native memory）／ローカル Registry（projects の add-project・UPDATE。tasks 行は書かない）／テスト・ビルド・読み取りスクリプト／Web 検索・取得（機密区分の Layer を除く）／opt-in した Layer の Jev 判定 | 上記以外の Layer 外ファイル／削除・移動・既存成果物の上書き／git の commit・push・PR・merge・タグ／公開OSSへの反映／Notion・Slack・メールへの書き込み・送信／ローカル sqlite 以外の同期先・外部DB／status_audit の `--apply` など承認後の決まりがある反映／お金・外部 API 送信・ツール導入などその他の操作 |

**累積予算:** 重い工程では §7.6 を適用し、作業総量上限・実期限・早期打切り条件の成立を停止理由に加える。

**停止:** 行頭に単独で `⛔ 自動完走を停止: <理由>` を出し、再開のしかたと自動承認ログの表を出して止まる（説明文の中でこの文字列を引用しない）。理由: 対象 Layer を決められない／workflow_depth が complex か mode が platform_builder（判定された時点で）／Collection で §0 ①に当たった／BT-A／P0〜P2 が2回後も残る／Backtrack が要る／⭐が無い／保留したものが無いと進めない／人が担当するタスクだけが残った／実行時期の来ていないタスクだけが残った／運用タスクだけが残った（自動完走では回さない）／分解に SubLayer が含まれる（承認前に停止）／累積予算の上限か実期限に達した。

**自動承認ログ:** 自動で選んだ判断は毎回 backlog.yaml の refactoring_log に `- date: 'YYYY-MM-DD'` ／ `entry: '[auto-approved] S<Stage>/P<Phase>: <選んだこと>（<理由>）'` で1行書く。全完了・停止のときに `[auto-approved]` 行を表にまとめ、完了報告の冒頭に「確認してほしいこと」（仮定で決めた名前・公開の文面・保守的に仮定した事項・Layer 外の既存ファイルを変えたタスク・`jev_monitor: true` の Layer だけ「🧭 未確認の Jev 判定: N件」。回収は `/plc-jev-monitor`。Jev 実験版パッケージ（`--with-jev`）に入っている。無ければスキップ）を1行ずつ出す。

**/goal の書き方:**

- **短い版**（Collection・Inception の完了報告の最後に「自動で進めるなら:」として Layer パスと開始列を埋めて1行出す）:
  `/goal <Layerパス> を <開始列> で完走する（RUL_plc_session §10 の自動完走）。達成: backlog の全タスクが completed（deferred・blocked は保留理由がログにあるもの。recurrence のある運用タスクは除く）・各 output が実在・Phase 7 チェックリストと自動承認ログを表示、または行頭に「⛔ 自動完走を停止」を表示。or stop after 40 turns`
- **Goal から版**: `/goal 「<Goal>」を /01-collection から完走する（RUL_plc_session §10 の自動完走）。達成: 作った Layer の backlog の全タスクが completed（同上）・各 output が実在・Phase 7 チェックリストと自動承認ログを表示、または行頭に「⛔ 自動完走を停止」を表示。or stop after 60 turns`

開始列（短い版）: backlog が空 → standard は `/02-inception → /04-operation`（Inception が `construction.required: true` を書いたら `/03-construction` を挟む）、simple は `/04-operation`／`construction.tasks` に Agents/ 定義の無いタスクがある → `/03-construction → /04-operation`／それ以外 → `/04-operation`。`pipeline_variant: jev` の Layer も本体版のコマンド。ターン上限で ⛔ も出ずに終わったら同じ /goal を貼り直して続きから再開できる（§7.6 の残予算は引き継ぐ）。

### 10.1 明示 workflow-force

`/plc-auto force`・`$plc-auto force`、または /goal に識別句 `AI-PLC workflow-force v1` があるときは [force-contract.md](../skills/plc-auto/references/force-contract.md) を本節より先に読み、人への承認要求を出さずに許可内で最後まで進める（矛盾はその契約が優先。起動例と /goal 全文は [goal-force-preset.md](../skills/plc-auto/references/goal-force-preset.md)）。force はプラットフォーム承認の例外ではない。

---
**作成日:** 2026-04-07 ｜ **更新日:** 2026-10-14 ｜ **ステータス:** Active
**バージョン:** 3.0（軽量化: 10/1 版（v2.6）を土台に §7.0・§7.4 回答後続行・§9.1 を要点だけ残し、§7.6 予算・§10.1 force・自己完結版 /goal・アドオン前置を references へ移した。以前の版履歴は git）
