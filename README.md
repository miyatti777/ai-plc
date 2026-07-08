# AI-PLC — AI Product Lifecycle Pipeline

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Platform](https://img.shields.io/badge/Platform-Claude_Code%20%7C%20Cursor-green)](https://claude.com/claude-code)

> ## Build the loop. Stay the engineer.
> **AI-PLC は「ループエンジニアリング」の汎用版。**
> コードの1タスクを自律で回す仕組みを、企画書・DB設計・OKR・リサーチ・イベント運営——**あらゆる成果物制作**に一般化した、人間の判断点を保ったままのAIパイプラインです。

**GOALだけ渡せば、AIが"発散→収束"を回して成果物を組み上げます。** ただし放置はしない。要所であなたが承認し、方向を修正し、「もう十分だ」と打ち切る。**分解と反復はAIに、判断と検証はあなたに。**

```
Collection  →  Inception  →  Construction  →  Operation
(Goal設定)      (タスク分解)    (スキル生成)      (実行・検証・伝播)
   └──────────── 各段でHITL承認・前提が崩れたら前段へ Backtrack ────────────┘
```

---

## 目次

- [🎥 デモ動画で見る](#-デモ動画で見る)
- [なぜ AI-PLC なのか](#なぜ-ai-plc-なのか)
- [ループエンジニアリングとの関係](#ループエンジニアリングとの関係)
- [インストール](#-インストール5分)
- [はじめての AI-PLC（自分のGoalで）](#-はじめての-ai-plc自分のgoalで)
- [チュートリアル: コトノハで一周する](#-チュートリアル-コトノハで一周する発散収束仕様化)
- [メモリの仕組み](#-メモリの仕組みwiki--native-memory)
- [DB の使い方](#-db-の使い方project-registry--tasks)
- [同梱スキル](#-同梱スキル)
- [FAQ](#-faq)
- [単なるループと違う点](#単なるループと違う5点)
- [インストール内容・安全性・構造](#-インストール内容--安全性)

---

## 🎥 デモ動画で見る

架空EC「コトノハストア」を題材に、AI-PLC が **発散→収束** を回す様子。サムネイルをクリックで再生。

| 🔵 発散 — 施策を広げて1本選ぶ | 🟢 収束 — 選んだ施策をエンジニア仕様に落とす |
|:---:|:---:|
| [![発散デモ](https://img.youtube.com/vi/vTga5VbFbGw/hqdefault.jpg)](https://www.youtube.com/watch?v=vTga5VbFbGw) | [![収束デモ](https://img.youtube.com/vi/RuswfXNe-Pk/hqdefault.jpg)](https://www.youtube.com/watch?v=RuswfXNe-Pk) |
| `/01-collection`→`/04-operation` で施策を発散→選定 | `/spec-story-starter`→`/wire-aa-authoring` で Story/Spec→ワイヤフレーム |

> このあとの[チュートリアル](#-チュートリアル-コトノハで一周する発散収束仕様化)は、動画と同じ流れを自分の手で回せます。

---

## なぜ AI-PLC なのか

いまのAI活用は、だいたい**二極化**しています。片方は「チャットにボーンと投げて壁打ちする派」、もう片方は「何でもスキル・ワークフローにガチガチに固める派」。答えは「どっちか」じゃなく **「使い分け」**——この2つは競合ではなく、**使うフェーズが違うだけ**です。

AI-PLC は、この2フェーズを制御思想ごと切り替えます:

- **発散フェーズ = 非決定論的ループ** — ゴールを渡して AI に自律反復させ、**量と速度**を上げる（人は要所で方向修正）
- **収束フェーズ = 決定論的ワークフロー** — 個別スキルを人が能動的に発動し、**渡せる精緻な成果物**に絞り込む

> 🐕 **元気すぎる大型犬の散歩**にたとえると——AIは無限体力で走る犬（発散エネルギー）。あなたは「今日はあの丘へ」という目的（＝Context）を決め、リード（＝ハーネス）で方向だけ制御する。停止条件は「ここまで走ったらお座り」。**AI-PLC はそのハーネスです。**

| よくある困りごと | AI-PLC の答え |
|---|---|
| 長いチャットで**コンテキストが揮発**する | 状態を `intent.yaml`/`backlog.yaml`/`context.yaml` にファイル外部化。**「エージェントは忘れるが、リポは忘れない」** |
| 停止条件がなく**ハルシネーションのまま自走** | 各段に人間の承認点(HITL)／完了は**機械判定可能な停止条件**で判定 |
| ループが**トークンを食い潰す** | 適応的に深度(Simple/Standard/Complex)を判定し、要らないループは回さない |
| AIの「できました」を**鵜呑み**にしてしまう | **maker ≠ checker** — 作った文脈から切り離した別AIが検証（`done`は主張であって、証明ではない） |

---

## ループエンジニアリングとの関係

「エージェントにプロンプトを打つのをやめ、**ループを設計せよ**」——これがループエンジニアリングの発想です。AI-PLC はその系譜の、**最も広い一般化**にあたります。

```
Anthropic / Claude Code チーム（公式定義）
  「ループ＝停止条件を満たすまで作業サイクルを繰り返すこと」（Turn/Goal/Time/Proactive の4類型）
        │
Addy Osmani（原理）「プロンプトするのをやめ、ループを設計せよ」
        │
開発特化の実装（1つの開発タスク = 1ループ）
        │
▶ AI-PLC（あらゆる成果物への一般化）
  1プロジェクト = 1パイプライン（+再帰分解）  Collection → Inception → Construction → Operation
```

一般化で足した4つ: **①発散=ループ/収束=WF ②HITLをあえて多く ③Backtrack(前段に戻る) ④maker≠checker**。

---

## 🚀 インストール（5分）

**前提:** インストール先は **git リポジトリ**であること（Claude Code / Cursor の要件）。`python3`（DB初期化に使用）。

### いちばん簡単: AI にお願いする ⭐

導入したいプロジェクトを Claude Code / Cursor で開き、チャットに**このURLを貼ってお願いするだけ**:

```
https://github.com/miyatti777/ai-plc をこのプロジェクトにインストールして。
リポジトリを clone して install-cc.sh --target . を実行して。
（Cursor を使っているなら install-cursor.sh）
```

AI が clone → インストールまで実行してくれます。オプションを覚える必要はありません。終わったら Claude Code / Cursor を**リロード**して `/01-collection` が使えれば完了です。

### 手動（CLI でやる場合）

```bash
# 1. clone
git clone https://github.com/miyatti777/ai-plc.git
cd ai-plc

# 2. あなたのプロジェクトにインストール
./install-cc.sh --target /path/to/your/project        # Claude Code
./install-cursor.sh --target /path/to/your/project     # Cursor
./install.sh --target /path/to/your/project both       # 両方

# まず何が起きるか見たいだけ → --dry-run
./install-cc.sh --dry-run --target /path/to/your/project
```

インストールされたら、そのプロジェクトを Claude Code / Cursor で開いて確認:

- Claude Code: チャットで `/01-collection` と打つ
- Cursor: **リロード後**、`/01-collection`（`/`で起動。`@`はファイル参照用なので注意）

> うまくコマンドが出ないときは [FAQ](#-faq) を参照。

---

## 🟢 はじめての AI-PLC（自分のGoalで）

一番シンプルな使い方は、**Goalを1つ渡すだけ**です。

```
/01-collection を実行してください
Goal: <達成したいことを1〜2文で>
```

すると AI が:

1. **Collection** — 関連情報を集めて構造化し、「成功条件」まで提示して**止まります**（あなたが承認）
2. **Inception** — Goalをタスクに分解して `backlog.yaml` を作る（承認）
3. **Construction** — 各タスクの実行役（Agent）を定義（承認）
4. **Operation** — タスクを実行し、成果物を作り、別AIが検証

各段であなたが `OK` / `修正: 〜` / `差し戻し` を選べます。**前提が変わったら「やっぱり〜したい」と言えば、前の段階に戻って作り直します**（Backtrack）。

> コードでも、企画書でも、OKRでも、リサーチでも同じ流れで回ります。

---

## 📗 チュートリアル: コトノハで一周する（発散→収束→仕様化）

`examples/kotonoha/` に、架空のD2C EC「**コトノハストア**」を題材にした練習用サンプルが入っています。**施策を広げ（発散）→ Story+Specに絞り（収束）→ 画面をワイヤフレーム化（仕様化）** の一周を、自分の手で体験できます。

### 同梱物

| フォルダ | 中身 | 役割 |
| --- | --- | --- |
| `context/` | 会社概要・OKR・議事録・現状データ（4本） | 発散の入力 |
| `kotonoha-store/` | ECアプリのDDD骨格（entities→services→components…） | 収束の接地先（どのファイルに実装するか） |
| `kotonoha-backlog/` | バックログ board + 既存Story 3本 + テンプレ | Storyの置き場所と書式 |

> 「答え」（完成済みStory/Spec）は**あえて入れていません**。あなたがその場で生成する体験になります。

> このチュートリアルは **実際にスキルを発動**させて回します。各コマンドを打つと AI が動き、要所（Mob Checkpoint）で止まってあなたの承認を待ちます。承認は `OK`、直したいときは `修正: 〜`、やり直しは `差し戻し`。

---

### パートA｜発散: 施策を出す（4ステージを回す）

▶ [発散デモ動画](https://www.youtube.com/watch?v=vTga5VbFbGw)（このパートの流れを動画で）

**A-1. Collection を起動**（発散の入口）。チャットに:

```
/01-collection を実行してください

Goal: コトノハストアのPMとして、今QuarterのOKR（KR1 リピート率 32→38% / KR2 AOV 6,800→7,500円 / KR3 メルマガ・LINE再訪率 15→22%）に効く施策を発散→収束し、最初に着手する1本を根拠付きで選定する。前提コンテキストは examples/kotonoha/context/ の4ファイル（会社概要・OKR・議事録・現状データ）にあります。
Mode: direct
```

→ **何が起きる:** AI が `context/` を読み込み、状況を構造化し、深度判定（standard）と「成功条件」を提示して**停止**します。内容を確認して:

```
OK
```

**A-2. Inception へ**（Goalをタスクに分解）。承認後に案内されるプロンプト、または直接:

```
/02-inception を実行してください
Scope: （A-1でAIが採番した scope_id を貼る。`L-MMDD` 形式）
```

> ⚠️ `Scope:` はA-1でAIが表示した実際の scope_id に置き換えます（そのままでは動きません）。以降のコマンドも同じ。

→ **何が起きる:** Goal が「発散タスク」「評価タスク」「収束・選定タスク」等に分解され `backlog.yaml` になる。→ `OK`

**A-3. Construction**（各タスクの実行役を定義）:

```
/03-construction を実行してください
Scope: （同じ scope_id）
```

→ **何が起きる:** 各タスクに Agent（実行役）が割り当てられる。「AIに何を任せるか」が決まる。→ `OK`

**A-4. Operation で発散を実行**:

```
/04-operation を実行してください
Scope: （同じ scope_id）
Task: （最初のP0タスク＝施策発散のID。例: T001）
```

→ **何が起きる:** AI が OKR に効く施策を**大量に発散**する（型のグラデーションで幅出し）。

**A-5. 収束・選定まで流す**:

```
次のタスクを実行してください
```

→ **何が起きる:** 発散した施策を評価軸でスコアリングし、**最初の1本を根拠付きで選定**（例: 「補充リマインド配信」）。maker≠checker の独立検証も走る。各段の停止で `OK`。

✅ **パートA完了:** 「何をやるか」が根拠付きで1本に決まりました。

---

### パートB｜収束: 選んだ施策をエンジニア仕様に落とす

▶ [収束デモ動画](https://www.youtube.com/watch?v=RuswfXNe-Pk)（このパートの流れを動画で）

**B-1. Story + Spec を生成して起票**（`/spec-story-starter`）。選定結果を入力に:

```
/spec-story-starter
source: （パートAで選定した施策名と選定理由。決定ドキュメントがあればそのパス）
feature_label: 補充リマインド配信
target_repo: examples/kotonoha/kotonoha-store
backlog: examples/kotonoha/kotonoha-backlog
detail_level: standard
```

→ **何が起きる:** AI がまず `kotonoha-store` を探索し「どのファイルに実装するか」（例: `src/services/ReminderService.ts`）を特定 → **Story起草とSpec起草が並列**で走り → 別AIが整合レビュー → `kotonoha-backlog/stories/` に `ST-KTN-004_*.md` が**起票**され、Specも生成される。→ `OK`

**B-2. 画面のワイヤフレームを描く**（`/wire-aa-authoring`）:

```
/wire-aa-authoring
story: examples/kotonoha/kotonoha-backlog/stories/ST-KTN-004_<B-1で付いたfeature名>.md
target_repo: examples/kotonoha/kotonoha-store
screens: NotificationSettings, MyPage
tier: full
```

→ **何が起きる:** AI が component を調査し、画面の**現状→変更後**をASCIIアートで対に描く。Storyに「設計決定ログ」が追記される。→ `OK`

```
+------------------------------------------+
|  配信設定                                 |
|   ● 補充リマインドを受け取る              |  <- トグル化（変更後）
|   ● LINEで受け取る                        |
|   ○ メールで受け取る                      |
|              [ 保存 ]                     |
+------------------------------------------+
```

✅ **パートB完了:** 抽象的な施策が、**実装箇所付きのStory+Spec＋画面ワイヤフレーム**になり、エンジニアに渡せる状態に。

---

### 応用: 途中で方向を変える（差し込みプロンプト）

AI-PLC の本領は「回しながら直せる」こと。どの段でも、こう割り込めます:

| やりたいこと | 打つプロンプト |
| --- | --- |
| もっと広く発散 | `もっと違う切り口の施策も発散して（例: 休眠顧客の掘り起こし）` |
| 評価軸を足す | `評価軸に「実装スピード」を追加して見直して` |
| **軌道修正（Backtrack）** | `やっぱりKR3（再訪率）を主軸に考え直したい` → AIが前段に戻る Re-Inception を提案 |
| 仕様を厚く | `detail_level を deep にして、バリデーションとエラーケースを厚く` |
| 段階分け | `このStoryをMVPと第2版にTier分割して` |

### 一周し終えたら

- `kotonoha-backlog/board.md` に新しいStory行が増え、`stories/` にStory、必要ならSpec・wireframe が生成されています
- **別の施策を選び直して**パートB をやり直すと、収束の当たり外れを比較できます
- これがそのまま、あなたの実プロジェクトでの使い方の雛形です（`target_repo` を自分のリポに変えるだけ）

---

## 🧠 メモリの仕組み（wiki + native memory）

AI-PLC の「記憶」は **2系統**です。役割で使い分けます。

| 種別 | 置き場 | 何を入れるか | 誰が書くか |
|------|--------|-------------|-----------|
| **wiki** | `.claude/wiki/`（Cursorは `.cursor/wiki/`） | プロジェクト横断の知見・バグパターン・設計判断・環境固有の制約 | AIが育て、人がキュレーション |
| **native memory** | Claude Code の機能（`~/.claude/...`・自動管理） | あなたの判断パターン・好み・進行中PJの状態 | Claude Code が自動 |

**wikiの構造**（`.claude/wiki/`）:
- `wiki.md` — スキーマ（ページの型・ルール）
- `index.md` — 全ページの索引
- `log.md` — 追記ログ（いつ何を学んだか）
- 概念ページ（あなたの知見が増えるとここに溜まる）

使い方は特別な操作は不要です。タスクを回す中で「これは再利用できる知見だ」となったら、AIが wiki に追記します（Operation の Propagation 段階）。あなたは `.claude/wiki/index.md` を眺めれば、これまでの学びが一覧できます。

> **振り分けの原則:** バグ・技術知見・PJ横断パターン → wiki ／ あなたの好み・判断のクセ → native memory。両方に重複させない。
> Cursor には native memory 機能が無いため、wiki が主な記憶になります。

---

## 🗄 DB の使い方（Project Registry / Tasks）

AI-PLC は、プロジェクト横断の台帳とタスクを**ローカル SQLite**（`.claude/db/ai_plc.db`）で管理します。インストール時に**空のDB**が作られます。

> **核の4ステージループは DB 無しでも動きます。** DBは「複数PJを横断で見る台帳」「外部チケット同期」という**任意の管理レイヤー**です。

### よく使うコマンド

```bash
python3 .claude/db/plc_query.py projects        # プロジェクト一覧
python3 .claude/db/plc_query.py tasks           # タスク一覧
python3 .claude/db/plc_query.py tasks L-1234    # 特定Scopeのタスク
python3 .claude/db/plc_query.py active          # activeなPJだけ
python3 .claude/db/plc_query.py dashboard       # ダッシュボード
python3 .claude/db/plc_query.py sql "SELECT ..."  # 任意SQL
```

- **projects テーブル** = Project Registry。Collection で新PJを始めると自動登録され、横断で状況が見られます。
- **tasks テーブル** = 既定の External Sync 先。Operation でタスクの完了が反映されます。

### 作り直したいとき

```bash
python3 .claude/db/init_db.py            # スキーマを保証（既存データは残す）
python3 .claude/db/init_db.py --reset    # まっさらに作り直す
```

### Notion と同期したい場合（任意・上級）

`.claude/db/sync.py` で、この SQLite を**自分の Notion DB**と双方向同期できます。使う場合のみ環境変数を設定:

```bash
export NOTION_API_TOKEN=<あなたのNotionトークン>
export AI_PLC_PROJECTS_DB_ID=<あなたの Projects DB のID>
export AI_PLC_TASKS_DB_ID=<あなたの Tasks DB のID>

python3 .claude/db/sync.py status   # 差分プレビュー
python3 .claude/db/sync.py sync     # 双方向同期
```

詳細は `.claude/db/README.md`。使わない場合はローカルDBだけで完結します。

---

## 🛠 同梱スキル

**コア（4ステージ本体）:** `/01-collection` `/02-inception` `/03-construction` `/04-operation` ＋ `/status`

**ユーティリティ（収束を深める）:**

| スキル | 用途 |
|--------|------|
| `spec-story-starter` | 選定施策を、対象リポの実構造にgroundした **Story + Spec** にSubagentで収束生成（`target_repo`/`backlog` を選べる汎用） |
| `wire-aa-authoring` | Story/Spec と対象リポから、画面UIの **現状→変更後** を **ASCII Artワイヤフレーム**で描く |

---

## ❓ FAQ

<details>
<summary><b>Q. AIに丸投げできる？精度は？</b></summary>

完璧ではありません。でも**「たたき台」としては非常に良い**ことが多く、0から睨む苦痛から解放され、構造化済みのものを"編集"するところから始められます。コツは **Context を先に集める**こと。あとは各段の承認(HITL)で人が要所を育てます。
</details>

<details>
<summary><b>Q. トークン/コストが心配</b></summary>

AI-PLC は深度（Simple/Standard/Complex）を自動判定し、**要らないループは回しません**。簡単なタスクは Collection→Operation に直行します。長いPJでは状態をファイルに外部化するので、1つの会話に全部を詰め込む必要がありません。
</details>

<details>
<summary><b>Q. コード以外でも使える？</b></summary>

はい。企画書・OKR・リサーチ・記事・イベント運営など、**「発散して収束する」成果物制作**なら何でも。それが"汎用版"たる所以です。
</details>

<details>
<summary><b>Q. 既存の設定（CLAUDE.md 等）を壊さない？</b></summary>

壊しません。既存ファイルは**バックアップ**（`.bak.YYYYMMDD`）してから更新し、`CLAUDE.md`/`AGENTS.md` は `<!-- AI-PLC START/END -->` マーカーで**マージ**します。`--dry-run` で事前確認、`./uninstall.sh` で除去できます。
</details>

<details>
<summary><b>Q. Cursor でコマンドが出てこない</b></summary>

**Cursorをリロード**してください（コマンドの読み込みに必要）。起動は **`/01-collection`**（スラッシュ）です。`@` はファイル/シンボルのメンション用なので、コマンド起動には使いません。
</details>

<details>
<summary><b>Q. 途中でセッションが切れたら？</b></summary>

大丈夫です。承認済みプラン・タスク・成果物は `intent.yaml`/`backlog.yaml`/`context.yaml` に**ファイルとして残っている**ので、新しい会話で「このLayerを再開して」と言えば続きから進めます。
</details>

<details>
<summary><b>Q. 途中で前提が変わった／方向がずれた</b></summary>

**Backtrack** があります。「やっぱりこの制約が入った」「ゴールを広げたい」と言えば、AIが前の段階に戻ってタスクを組み直すことを提案します（BT-A ブロッカー / BT-B 節目 / BT-C 全完了GAP分析）。
</details>

<details>
<summary><b>Q. DBは必須？メモリはどこに残る？</b></summary>

DBは**任意**（複数PJ横断の台帳・外部同期用。核ループはDB無しで動く）。メモリは **wiki（`.claude/wiki/`）+ native memory**（Claude Code自動管理）の2系統です。上の[メモリ](#-メモリの仕組みwiki--native-memory)/[DB](#-db-の使い方project-registry--tasks)節を参照。
</details>

<details>
<summary><b>Q. アンインストールしたい</b></summary>

`./uninstall.sh --target /path/to/your/project`。カスタマイズ済みの `soul.md`/`wiki/`/`db/`（あなたのデータ）は削除されません。
</details>

---

## 単なる「ループ」と違う5点

1. **構造化パイプライン** — いきなり作らず、Context収集→分解→計画→実行の関門を通す
2. **PM/アジャイル的な管理レイヤーを標準装備** — Project Registry・External Sync・Wiki波及/Lint
3. **フラクタル（再帰分解）** — SubLayer で子スコープへ再帰分解。規模に応じて階層が伸びる
4. **二層の検証ゲート** — L1〜L3（観点の広さ）× P0〜P3（重大度）。完了は機械判定可能な停止条件で
5. **Backtrack（逆方向適応）** — 前進のみのループと違い、前段へ戻る仕組み

> 🔧 **正直な限界:** AI-PLC が持つのは Turn-based（承認）と Goal-based（独立検証）の2類型。**Time-based / Proactive（イベント駆動・人間不在の自律ルーチン）はまだ未対応**——公式4類型に照らして残るGAPです。誇張はしません。

---

## 📦 インストール内容 / 安全性

<details>
<summary>配置されるもの・安全性・ディレクトリ構造</summary>

**Claude Code:** `.claude/skills/ai-plc/`・`.claude/skills/utility/`・`.claude/rules/`・`.claude/commands/`・`.claude/agents/`・`CLAUDE.md`/`AGENTS.md`(マージ)・`.claude/soul.md`・`.claude/wiki/`・`.claude/db/`(空DB)
**Cursor:** `.cursor/skills/`・`.cursor/rules/*.mdc`・`.cursor/wiki/`・`.cursor/db/`

- 既存ファイルは上書きせずバックアップ／テンプレート(soul/wiki)は既存がなければのみ配置
- `--dry-run` で事前確認／`./uninstall.sh` で除去（あなたのデータは残す）

```
ai-plc/
├── install.sh / install-cc.sh / install-cursor.sh / uninstall.sh
├── core/
│   ├── skills/ai-plc/     # 4ステージスキル + テンプレート
│   ├── skills/utility/    # spec-story-starter / wire-aa-authoring
│   ├── rules/             # system / session / adaptive
│   └── db/                # init_db.py / plc_query.py / sync.py
├── claude/                # Claude Code固有（commands / agents / templates）
├── cursor/                # Cursor固有（.mdc rules）
├── templates/             # soul.md / wiki
├── examples/kotonoha/     # 試せるサンプル
└── docs/                  # ARCHITECTURE.md
```
</details>

---

> **最も価値あるスキルは、ゴールを描く力と、「もう十分だ」と自分に告げる勇気。**
> あなたの仕事は、最初の問いをデザインし、ループを設計し、検証に責任を持つこと。
>
> **Build the loop. Stay the engineer.**

## License

MIT License — See [LICENSE](LICENSE).
