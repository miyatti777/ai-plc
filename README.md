# AI-PLC — AI Product Lifecycle Pipeline

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Platform](https://img.shields.io/badge/Platform-Claude_Code%20%7C%20Cursor-green)](https://claude.com/claude-code)

> ## Build the loop. Stay the engineer.
> **AI-PLC は「ループエンジニアリング」の汎用版。**
> コードの1タスクを自律で回す仕組みを、企画書・DB設計・OKR・リサーチ・イベント運営——**あらゆる成果物制作**に一般化した、人間の判断点を保ったままのAIパイプラインです。

真っ白なホワイトボードの前でマーカーを握って「さて、何から書こう」と固まる、あの瞬間。
あの 0→1、まだ全部あなたがやりますか？

AI-PLC は、**GOALだけ渡せば AI が"発散→収束"を回して成果物を組み上げます。** ただし放置はしない。要所であなたが承認し、方向を修正し、「もう十分だ」と打ち切る。**分解と反復はAIに、判断と検証はあなたに。**

```
Collection  →  Inception  →  Construction  →  Operation
(Goal設定)      (タスク分解)    (スキル生成)      (実行・検証・伝播)
   └──────────── 各段でHITL承認・前提が崩れたら前段へ Backtrack ────────────┘
```

| Stage | コマンド | やること |
|-------|---------|---------|
| 1 | `/01-collection` | Goal設定・Context収集・成功条件の確立 |
| 2 | `/02-inception` | Goal分析・再帰的なタスク分解・Backlog生成 |
| 3 | `/03-construction` | 実行スキル(Agent定義)の生成 |
| 4 | `/04-operation` | タスク実行・成果物生成・独立検証・知見伝播 |

---

## なぜ AI-PLC なのか

いまのAI活用は、だいたい**二極化**しています。

- 片方は「とりあえずチャットにボーンと投げて壁打ちする派」
- もう片方は「何でもスキル・ワークフローにガチガチに固める派」

答えは「どっちか」じゃなく **「使い分け」**。この2つは競合ではなく、**使うフェーズが違うだけ**です。

そして従来の制作プロセスの弱点は、**「発散が雑で、収束が手ぬるい」**こと。人は疲れていて、最初に出た"それっぽい案"に固執する——**疲労と妥協の産物**になりがちです。

AI-PLC は、この2フェーズを制御思想ごと切り替えます:

- **発散フェーズ = 非決定論的ループ** — ゴールを渡して AI に自律反復させ、**量と速度**を上げる（人は要所で方向修正）
- **収束フェーズ = 決定論的ワークフロー** — 個別スキルを人が能動的に発動し、**開発に渡せる精緻な成果物**に絞り込む

> 🐕 **たとえるなら、元気すぎる大型犬の散歩。** AIは無限体力で走る犬（発散エネルギー）。あなたは「今日はあの丘へ」という目的（＝Context）を決め、リード（＝ハーネス）で方向だけ制御する。停止条件は「ここまで走ったらお座り」。**AI-PLC はそのハーネスです。**

### AIが実際にぶつかる壁と、AI-PLCの答え

| よくある困りごと | AI-PLC の仕組み |
|---|---|
| 長いチャットで**コンテキストが揮発**する | 状態を `intent.yaml` / `backlog.yaml` / `context.yaml` にファイル外部化。**「エージェントは忘れるが、リポは忘れない」**（セッションが飛んでも「再開して」で続行） |
| 停止条件がなく**ハルシネーションのまま自走** | 各段に Mob Checkpoint（人間の承認点）／完了は自己申告でなく**機械判定可能な停止条件**で判定 |
| ループが**トークンを食い潰す**／文脈汚染 | 適応的に深度（Simple/Standard/Complex）を判定し、要らないループは回さない |
| AIの「できました」を**鵜呑み**にしてしまう | **maker ≠ checker** — 作成文脈から切り離した独立reviewerが検証（`done` は主張であって、証明ではない） |

> 🤖 **「AIに丸投げできるの?」への正直な答え:** 精度は完璧ではありません。でも**「たたき台」としては非常に良い**。0から睨む苦痛から解放され、**構造化済みのものを"編集"するところ**から始められます。コツは **Context を先に集める**こと。あとは HITL で人が要所を育てる。

---

## ループエンジニアリングとの関係

「エージェントにプロンプトを打つ自分をやめ、**ループを設計せよ**」——これがループエンジニアリングの発想です。AI-PLC はその系譜の、**最も広い一般化**にあたります。

```
Anthropic / Claude Code チーム（公式定義）
  「ループ＝停止条件を満たすまで作業サイクルを繰り返すこと」
  ─ Turn-based / Goal-based / Time-based / Proactive の4類型
        │
Addy Osmani（原理・エッセイ）
  「プロンプトするのをやめ、ループを設計せよ」
        │
開発特化の実装（1つの開発タスク = 1ループ）
  interview → plan → 承認 → implement ↔ review
        │
▶ AI-PLC（あらゆる成果物への一般化）
  1プロジェクト = 1パイプライン（+ 再帰分解）
  Collection → Inception → Construction → Operation（+ Backtrack）
```

> 分岐点は「連続推論か、ターン区切りか」ではありません。**「誰が/何が停止を決めるか」**です。
> 全タスクに複雑なループは要らない。**最も単純な解から始め、選択的に使う**のが原則。

### 一般化で足した4つのこと

| 汎用化した軸 | 中身 |
|---|---|
| **発散=ループ / 収束=ワークフロー** | フェーズごとに制御思想を切り替える（上記） |
| **HITL を"あえて多く"** | 最適化目標がスループットではなく**あなたのコントロール感・方向修正性**。選択肢を選んでも即実行せず、確認を挟む |
| **Backtrack（逆方向適応）** | 普通のループは前進のみ。AI-PLC は ブロッカー / 節目再評価 / 全完了GAP分析 の3トリガーで「前のステージへ戻る」を制度化。長いPJで必ず起きる「前提が崩れた」に対応 |
| **maker ≠ checker** | 実行文脈から分離したreviewerが検証。環境非依存（Claude Code=Agent tool / 他=別会話） |

---

## 🚀 5分で試す

```bash
# 1. clone
git clone https://github.com/miyatti777/ai-plc.git
cd ai-plc

# 2. あなたのプロジェクト（git リポジトリ）にインストール
./install-cc.sh --target /path/to/your/project        # Claude Code
#   Cursor: ./install-cursor.sh --target ...  /  両方: ./install.sh --target ... both
#   確認だけ: --dry-run を付ける
```

インストール先を Claude Code / Cursor で開き、最初のGoalを渡すだけ:

```
/01-collection を実行してください
Goal: <達成したいことを1〜2文で>
```

→ AI が Context を集めて構造化し、**成功条件まで提示して止まります**（HITL）。あとは `/02-inception` → `/03-construction` → `/04-operation` と承認しながら進めるだけ。

---

## 🧪 その場で試せるサンプル（発散→収束→仕様化）

`examples/kotonoha/` に、架空のD2C EC「コトノハストア」を題材にした練習用サンプルを同梱しています。
**施策を広げる（発散）→ Story+Specに絞る（収束）→ 画面をワイヤフレーム化（仕様化）** を自分の手で一周できます。

```
examples/kotonoha/
├── context/          # 会社概要・OKR・議事録・現状データ（発散の入力）
├── kotonoha-store/   # 対象ECアプリのDDD骨格（収束の接地先）
└── kotonoha-backlog/ # Product Backlog（board + 既存Story 3本 + テンプレ）
```

3ステップの手順とコピペ用プロンプトは [examples/kotonoha/README.md](examples/kotonoha/README.md) に。
（「答え」＝完成済みStory/Specはあえて同梱していません。あなたがその場で生成する体験になります）

---

## どんな時に効くか（型のグラデーション）

Bizも創作も家のイベントも、**同じ型（ループ×分解）**で回ります。「コンテキストを変えるだけで、AI が構造を変幻自在に切り替える」のがポイント。

| 例 | 型 | 人が決めること | AIに任せること |
|---|---|---|---|
| **OKR/戦略の決定** | **収束型**（多数タスクが1点に合流） | 北極星・停止条件・要所の修正 | タスク分解・反復・育成 |
| **小説/長編コンテンツの執筆** | **多階層型**（設計と制作を別スコープに再帰分解） | 階層の切り方の承認 | 各スコープの分解・制作 |
| **イベント企画（会場×食事×交流）** | **並行統合型**（機能ごとに並行→統合） | 開催 Go/No-Go 判断 | 各機能の並行設計・統合案 |

> **「依存が強い→収束型／設定が先→多階層型／独立→並行型。」**
> 人間がやるのは **Contextを揃える・HITLで方向修正する・打ち切り(Bet)を決める**。分解と反復はAIがやる。

---

## 単なる「ループ」と違う5点

1. **構造化パイプライン** — いきなり作らず、Context収集→分解→計画→実行の関門（Plan Gate）を通す
2. **PM/アジャイル的な管理レイヤーを標準装備** — Project Registry（横断DB）・External Sync（外部チケット委譲）・Wiki波及/Lint（知識ベース健全性）・Persistent Memory
3. **フラクタル（再帰分解）** — SubLayer で子スコープへ再帰分解。規模に応じて階層が伸びる
4. **二層の検証ゲート** — **L1〜L3（観点の広さ：単体/整合/受け手）× P0〜P3（重大度）**。完了は「未解決P0/P1/P2ゼロ」等の**機械判定可能な停止条件**で判定
5. **Backtrack（逆方向適応）** — 前進のみのループと違い、ブロッカー/節目/全完了時に「前段へ戻る」を制度化

> 🔧 **正直な限界:** AI-PLC が持つのは Turn-based（Mob Checkpoint）と Goal-based（独立検証）の2類型。**Time-based / Proactive（イベント駆動・人間不在の自律ルーチン）はまだ未対応**——公式4類型に照らして残るGAPです。誇張はしません。

---

## 🛠 同梱スキル

**コア（4ステージ本体）:** `/01-collection` `/02-inception` `/03-construction` `/04-operation` ＋ `/status`

**ユーティリティ（収束を深める）:**

| スキル | 用途 |
|--------|------|
| `spec-story-starter` | 選定施策を、対象リポの実構造にgroundした **Story + Spec** にSubagentで収束生成（`target_repo` / `backlog` を選べる汎用） |
| `wire-aa-authoring` | Story/Spec と対象リポから、画面UIの **現状→変更後** を **ASCII Artワイヤフレーム**で描く |

---

## 📦 インストール内容 / 安全性

**Claude Code:** `.claude/skills/ai-plc/`（4ステージ+テンプレート）・`.claude/skills/utility/`（新スキル2本）・`.claude/rules/ai-plc-*.md`・`.claude/commands/`・`.claude/agents/`・`CLAUDE.md`/`AGENTS.md`（マージ）・`.claude/soul.md`・`.claude/wiki/`・`.claude/db/`（空DB初期化）
**Cursor:** `.cursor/skills/`（同上）・`.cursor/rules/ai-plc-*.mdc`（alwaysApply）・`.cursor/wiki/`・`.cursor/db/`

- **既存ファイルは上書きしない** — バックアップ（`.bak.YYYYMMDD`）を作成
- **CLAUDE.md / AGENTS.md はマーカーでマージ**（`<!-- AI-PLC START/END -->`）
- **テンプレートはスキップ** — `soul.md`・`wiki/` 等は既存がなければのみ配置
- **dry-run / アンインストール可能** — `--dry-run` で事前確認、`./uninstall.sh` で除去（カスタム済み・DBは残す）

### 記憶とデータ（どこに何が残るか）

| 種別 | 置き場 | 中身 |
|------|--------|------|
| **プロジェクト知見（wiki）** | `.claude/wiki/` | バグパターン・設計判断など横断知見。育てて使う |
| **ユーザーモデル/好み** | Claude Code の native memory（自動管理） | あなたの判断パターン・好み。Cursorには無い |
| **Project Registry / Tasks** | `.claude/db/ai_plc.db`（インストール時に空生成） | PJ横断の台帳＋既定の External Sync 先。核ループはDB無しでも動く任意機能 |

> Notion と同期したい場合のみ `.claude/db/sync.py` を使います（`NOTION_API_TOKEN` と自分の DB ID を環境変数で指定）。詳細は `.claude/db/README.md`。

<details>
<summary>ディレクトリ構造</summary>

```
ai-plc/
├── install.sh / install-cc.sh / install-cursor.sh / uninstall.sh
├── .ai-plc-version / LICENSE / README.md
├── core/
│   ├── skills/ai-plc/     # 4ステージスキル + テンプレート
│   ├── skills/utility/    # spec-story-starter / wire-aa-authoring
│   ├── rules/             # system / session / adaptive
│   └── db/                # init_db.py / plc_query.py / sync.py（Registry/Tasks DB）
├── claude/                # Claude Code固有（commands / agents / *.template / settings）
├── cursor/                # Cursor固有（.mdc rules）
├── templates/             # soul.md / wiki
├── examples/kotonoha/     # 試せるサンプル（発散→収束→仕様化）
└── docs/                  # ARCHITECTURE.md
```
</details>

---

## 💡 コア原理

| 原理 | 説明 |
|------|------|
| **Context Cascade** | 親→子スコープへの3分類コンテキスト伝播（immutable / overridable / local） |
| **Fractal Decomposition** | Goalの再帰的分解とSub-Agent Scope生成 |
| **Adaptive Workflow** | Simple / Standard / Complex の3段階深度を自動判定し、必要なら Backtrack |
| **maker ≠ checker** | 成果物は作成文脈から独立したreviewerが検証する |
| **Self-Describing Task** | コンテキスト付きで外部に委譲できるタスク構造 |

---

> **最も価値あるスキルは、ゴールを描く力と、「もう十分だ」と自分に告げる勇気。**
> もう、真っ白なホワイトボードの前でマーカーを握りしめる人でなくていい。あなたの仕事は、**最初の問いをデザインし、ループを設計し、検証に責任を持つ**こと。
>
> **Build the loop. Stay the engineer.**

## License

MIT License — See [LICENSE](LICENSE).
