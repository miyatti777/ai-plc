---
name: plc-consult
description: AI-PLCの進行中に、ユーザーの「ここをこうしたい」を命令ではなく相談として受け、今のLayer（intent・backlog）と照らして「却下／今のタスク内で修正／Re-Inception／Re-Collection／いつかやる」に振り分け、所感と次に打つコマンドを返す（読み取り専用・実行しない）。「どう思う？」「これやるべき？」「Inceptionからやり直すべき？」「次どのコマンド打てばいい？」で使う。
---

# plc-consult（アイデア相談）

> 論理名: SKL_plc_consult ／ 包むもの: なし（判断手順そのものが中身）

**アドオンの前置判定（持ち込みのアドオンがある Layer だけ）:** 対象 Layer の intent の `addons` に、目録（[addon-catalog.yaml](../ai-plc/references/addon-catalog.yaml)）にある同梱の件（`source: bundled`）以外の件が1件でもあるときだけ（判定関数 `.claude/skills/ai-plc/scripts/plc_addon_select.py` の `has_case_addons` とおおむね同じ。判定関数で held になる形も前置判定の側に倒す）、[addon-seam.md](../ai-plc/references/addon-seam.md) の「現在依頼の読取境界を最初に判定する」「全入口の前置条件」を最初に適用し、必要なら `.claude/skills/ai-plc/scripts/plc_addon.py` を実呼出する。addons の中身は、既に許可された intent 読取の範囲内でだけ確認する。addons の無い Layer（既定）と、同梱の PM アドオンだけの Layer（旧い欄 `work_style: aipm` を含む）では Hold 判定をせず本来の手順から始める。ただし本人が今回の依頼で「全体 no-write / trial」を明示している場合は、addons の有無によらず書込前に止めて確認する。

## 何をするスキルか

- スキル実行の合間（例: Operation で成果物が出た後）に、ユーザーのアイデアを**相談として**受け取る
- 今の Layer と照らして5つのどれかに振り分け、**所感・理由・次に打つコマンド**を返す
- **読み取り専用。** ファイルも Registry も書き換えない。判定を返したら止まる（コマンドを貼って実行するのは人）

AI 発の1行ヒント（RUL_plc_adaptive §5）とは逆向きの、ユーザーから持ち込む入口。

## 使い方

| 呼び方 | 動作 |
| --- | --- |
| `/plc-consult <アイデア>` | この会話で直前に扱った Layer を対象に判定 |
| `/plc-consult <Layerパス or L-ID> <アイデア>` | 指定した Layer を対象に判定（先頭の語が `Flow/`・`.ai-plc/`・`Stock/` で始まるか `L-` で始まる ID のときだけ Layer 指定とみなす） |
| 自然文（「T003 の出力、表にしたいけどどう思う？」など） | 同じ手順で判定 |

## 実行手順

リポジトリのルートで実行する。

### 1. 対象 Layer を決める（上から順に）

1. 引数の Layer パスか scope_id。scope_id は次でパスに直す（行頭に固定＝親の sublayers 一覧の行は拾わない。引用符あり・なしの両方に一致。Documents 内のコピーは除く）
   ```bash
   grep -rlE '^scope_id: "?<ID>"?[[:space:]]*(#.*)?$' Flow .ai-plc/projects Stock --include=intent.yaml --exclude-dir=Documents
   ```
   2件以上ヒットしたら（例: 同じ Scope ID が `Flow/` と `.ai-plc/projects/` の両方にある）候補を並べて1問だけ聞く。0件なら ID を確かめてもらう
2. この会話で直前に `/0N-*`（`-jev` を含む）を実行した Layer
3. どちらも無ければ `python3 .claude/db/plc_query.py active` から候補を最大3件示し、1問だけ聞く（推測で決めない。結果にパス列は無いので 1 の検索でパスを引く）

### 2. 読む（件数を絞る — RUL_plc_system §17）

- `intent.yaml`: goal.description・goal.success_criteria・status・workflow_depth・mode・construction_mode（Re-Inception で足すタスクが RUL_plc_adaptive §6 の条件に当たり、`/03-construction` の注記が要るか）（`pipeline_variant` は読まない。`jev` でも本体版 — RUL_plc_adaptive §5 ルール6）
- `backlog.yaml`: 各タスクの id・name・status・dependencies・output（description は関係するタスクだけ）とトップレベルの `construction`
- アイデアが特定の成果物に触れているときだけ、その成果物を読む

### 3. 判定する（3ステップ）

**ステップ1: goal との関係**

| 問い | 答え | 行き先 |
| --- | --- | --- |
| 今の goal・success_criteria のままで、その達成に役立つか | はい | ステップ2へ |
| goal・success_criteria を変える（足す・変える・外す）必要があるか、前提（Context）が崩れているか | はい、かつ**この Layer の完了をこのアイデアまで待たせるべき** | **Re-Collection** |
| 同上 | はい、だが**この Layer は今の goal のまま閉じてよい** | **いつかやる** |
| 今の goal とは別物（役立ちもせず、goal を変えるものでもない） | それ自体に価値がある | **いつかやる**（価値が無ければステップ3で却下） |

**ステップ2: 手当ての大きさ（goal の範囲内のとき）**

| 条件 | 判定 |
| --- | --- |
| pending / in_progress のタスクの完了条件（description・AC）を変えずに、そのタスクの中で直せる | **今のタスク内で修正** |
| タスクの追加・取りやめ、完了条件・依存・優先度の変更が要る。**または completed のタスクを直す**（04-operation に completed の再実行手順が無いため、修正タスクを1件足す） | **Re-Inception** |

**ステップ3: 却下チェック（ステップ1・2の結果に上書きする）** — 次のどれかに当たれば **却下**

- 既存の成果物・タスクで既に満たされている
- goal にも、それ自体の価値にもつながらない
- goal の達成に必要**ではなく**、得られるものに比べて手間が大きい（goal に必要なものは手間が大きくても却下にせず、所感を「条件つき賛成」にする）
- Layer の制約（変更禁止・送信禁止など）を保ったままでは実施できない（制約そのものを変えたいならステップ1の Re-Collection）

**分類ごとのコマンド**

| 判定 | 次に打つコマンド |
| --- | --- |
| 却下 | なし（理由だけ） |
| いつかやる | 将来の PJ（Layer を切る規模）: `/plc-someday <やりたいこと>` ／ Layer にならない小さな差し込み: あなたの TODO 管理へ（AI-PLC の範囲外） |
| Re-Collection | `/01-collection`（Layer パス＋`Re-Collection: <理由>`） |
| Re-Inception | `/02-inception`（Layer パス＋`Re-Inception: <差分の要点>`）。Re-Inception で backlog の `construction` が required になる（足したタスクが RUL_plc_adaptive §6 の条件に当たる）ときだけ、そのタスクに `/03-construction` を通すことを1行添える |
| 今のタスク内で修正 | `/04-operation`（Layer パス＋Task ID＋修正内容） |

- `pipeline_variant: jev` の Layer も本体版（`/01-collection` 〜 `/04-operation`）を出す（実験版 ai-plc-jev は凍結中。既存 Layer は書き換えずに本体版とみなす — RUL_plc_adaptive §5 ルール6）
- **Layer 自体が completed のとき:** 判定の手順は同じ（ステップ1〜3）。タスクは全部 completed なので、ステップ2に来たものは Re-Inception になる。Re-Inception・Re-Collection のときは「Layer と Registry を active に戻す作業が入る」と1行添える

**境目の決め方（実測で補足）**

- **goal の範囲内とは:** goal.description の目的に沿うもの。success_criteria に書かれていない付随の改善（使い勝手・手作業の置き換えなど）も範囲内に入れてよい
- **「この Layer の完了を待たせるべきか」:** ユーザーの言葉（「この Layer でやり切りたい」「今回はいい」など）があればそれに従う。無ければ AI が判断し、もう一方を次点に置く
- **いつかやるの規模:** 複数タスク・複数日になりそうなら `/plc-someday`、1回・1時間程度で終わるなら、あなたの TODO 管理へ（AI-PLC の範囲外）
- **deferred のタスク:** pending と同じ扱い。プロンプトに「deferred を解除して」と書く
- **別 Layer の成果物に関わるアイデア:** 成果物の持ち主の Layer（Registry・output から分かるもの）を理由に書き、その Layer を指定して相談し直す案を次点に置く
- **backlog が実態とずれている:** backlog の値を正として判定し、ずれに気づいたら1行で指摘する（直さない。点検は `/plc-status-audit`）

**迷うとき**

- アイデアが曖昧で、**分類が変わる**不明点があるときだけ1問聞く（RUL_plc_session §9 Material Ambiguity。選択肢は最大3つ）。分類が変わらない不明点は聞かない
- 迷ったら**軽い方**（今の Layer への影響が小さい方）を判定にし、重い方を次点に置く。軽い順: 修正 < いつかやる < Re-Inception < Re-Collection

### 4. 返す（下の形式）。ここで止まる

## 出力の形

RUL_plc_session §7.4 の順（①選択肢テーブル → ②推奨理由 → ③コピペ用プロンプト）の前に、相談への答えの一文と、所感・分類の行を置く形。分類名から書き始めない。

```
📍 <scope_id> への相談: <アイデアの要約1行>

<相談への答えの自然な一文。例: 「はい、今の計画のままでも作れますが、Operation で動かす部分が足りません。」>

所感: <賛成・条件つき賛成・反対> — <1行> ／ 分類: <5分類のどれか>

| 選択肢 | アクション | 選んだ後に起きること |
| --- | --- | --- |
| **A** ⭐ | <判定どおり> | <1行> |
| **B** | <次点。無ければ「採用せず今の作業を続ける」> | <1行> |

推奨理由
- <intent / backlog のどこと照らしたか>（例: goal.success_criteria 3 に含まれない／T004（比較表を作る）の完了条件の範囲内。Task・ペルソナなどの ID は最初に出すときに名前を添える — RUL_plc_session §7.0）
- …

A の依頼内容
- 対象: <Layer・Task とその名前>
- やること: <1〜2行>
- 前提 / してはいけないこと: <あれば>

A のプロンプト: <コピペ用プロンプト>
B のプロンプト: <コピペ用プロンプト。「続ける」なら今のタスクの続きのプロンプト>
```

- 選択肢テーブルは却下のときも含め常に出す（§7.4「代替選択肢も必ず提供」）。却下が A のときは A のプロンプトは無し。B は「却下せず採用するならこの分類」の次点にする（「採用せず続ける」は A と重なるため使わない）
- 実際に出すときはプロンプトをコードブロックに入れない
- プロンプトの前に、依頼の中身（対象・やること・前提・してはいけないこと）を短い箇条書きで示す（RUL_plc_session §7.4）。プロンプトの無い選択肢（却下の A など）では箇条書きも省く

コピペ用プロンプトの例（実際のパスで書く）:

- `/04-operation を実行してください / Layer: Flow/202609/2026-09-29/xxx / Task: T003 / 修正: 出力を表形式にする`
- `/02-inception を実行してください / Layer: Flow/202609/2026-09-29/xxx / Re-Inception: 比較表を作るタスクを追加（T003 の後）`
- `/01-collection を実行してください / Layer: Flow/202609/2026-09-29/xxx / Re-Collection: success_criteria に「社外向け版も作る」を足すか判断したい`

## 注意

- **読み取り専用。** intent.yaml・backlog.yaml・成果物・Registry を書き換えない（読み取りコマンドは実行してよい）。判定を返したら止まる。「じゃあそれで」等の同意だけでは自分でコマンドを実行せず、プロンプトを返して本人の明確な実行指示を待つ（RUL_plc_session §7.4）
- **所感を必ず添える。** ユーザーは分類だけでなく「どう思うか」を聞いている。反対なら反対と書く
- 独立 checker は起動しない（軽さ優先）。Re-Collection のときは GAP 分析を checker に通す依頼をプロンプトに足せると1行添える
- 1回の呼び出しで判定するアイデアは1件。複数あれば1件ずつ判定を並べる
- 判定後の手順は 02-inception / 01-collection の定義を使う
