# AI-PLC — AI Product Lifecycle Pipeline

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Platform](https://img.shields.io/badge/Platform-Claude_Code%20%7C%20Cursor%20%7C%20Codex-green)](https://github.com/miyatti777/ai-plc)

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
- [アップデート手順](#-アップデート手順)
- [はじめての AI-PLC（自分のGoalで）](#-はじめての-ai-plc自分のgoalで)
- [自動完走（/goal）](#-自動完走goal)
- [こんな使い方ができる](#-こんな使い方ができる)
- [チュートリアル: コトノハで一周する](#-チュートリアル-コトノハで一周する発散収束仕様化)
- [メモリの仕組み](#-メモリの仕組みwiki--native-memory)
- [Collection が賢く集める（MCP）](#-collection-が賢く集めるmcpを繋ぐほど強くなる)
- [DB の使い方](#-db-の使い方project-registry--tasks)
- [同梱スキル](#-同梱スキル)
- [実験版: Jev 監視](#-実験版-jev-監視)
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

**前提:** インストール先は **git リポジトリ**であること。安全なinstallerとDB初期化に`python3`を使用します。

### いちばん簡単: AI にお願いする ⭐

導入したいプロジェクトを Claude Code / Cursor / Codex で開き、チャットに**このURLを貼ってお願いするだけ**:

```
https://github.com/miyatti777/ai-plc をこのプロジェクトにインストールして。
リポジトリを clone して、使っている環境向けのinstallerを --target . で実行して。
Claude Codeはinstall-cc.sh、Cursorはinstall-cursor.sh、Codexはinstall-codex.sh。
```

AI が clone → インストールまで実行してくれます。

> **重要:** インストールを実行した同じチャット／スレッドでは、新しく配置したSkillやcommandが候補に出ないことがあります。**インストール完了後は、対象プロジェクトで新しいチャット／スレッドを開始してから**Collectionを呼び出してください。まだ表示されない場合はClaude Code/Codexを再起動し、Cursorはウィンドウをリロードします。

| 環境 | 起動形式 |
| --- | --- |
| Claude Code | `/01-collection` |
| Cursor | `/01-collection` |
| Codex | `$01-collection` |

### 手動（CLI でやる場合）

```bash
# 1. clone
git clone https://github.com/miyatti777/ai-plc.git
cd ai-plc

# 2. あなたのプロジェクトにインストール
./install-cc.sh --target /path/to/your/project        # Claude Code
./install-cursor.sh --target /path/to/your/project     # Cursor
./install-codex.sh --target /path/to/your/project      # Codex
./install.sh --target /path/to/your/project both       # Claude Code + Cursor
./install.sh --target /path/to/your/project all        # 3環境すべて

# まず何が起きるか見たいだけ → --dry-run
./install-cc.sh --dry-run --target /path/to/your/project
./install-codex.sh --dry-run --target /path/to/your/project
```

インストールされたら、そのプロジェクトで**新しいチャット／スレッドを開始して**確認:

- Claude Code: チャットで `/01-collection` と打つ
- Cursor: **リロード後**、`/01-collection`（`/`で起動。`@`はファイル参照用なので注意）
- Codex: チャットで `$01-collection` と入力する（CLI/IDEでは`$`またはSkill一覧から選択）

Codexでは次の2点も確認できます:

```bash
test -f /path/to/your/project/.agents/skills/ai-plc/01-collection/SKILL.md
grep -q '<!-- AI-PLC CODEX START -->' /path/to/your/project/AGENTS.md
```

Codex向けSkillは`.agents/skills/`、永続指示は既存本文を保持した`AGENTS.md`のmanaged regionに配置されます。同じスレッドでSkillが表示されない場合は、まず新しいスレッドを開始します。それでも表示されなければ、インストール先のプロジェクトを開いているか確認してCodexを再起動してください。

> うまくコマンドが出ないときは [FAQ](#-faq) を参照。
> すでに入れている人の更新は、次の [アップデート手順](#-アップデート手順) を見てください。

---

## 🔄 アップデート手順

すでに AI-PLC を入れたプロジェクトを、新しい版に上げる手順です。どの版からでも、流すコマンドは同じです。変わった点は [CHANGELOG.md](CHANGELOG.md) にあります。

AI にお願いするなら、プロジェクトを開いたチャットで「AI-PLC（`https://github.com/miyatti777/ai-plc`）を最新版に更新して。README のアップデート手順に沿って、まず `--dry-run` の結果を見せて」のように頼めます。以下は手で行う場合の手順です。

**更新の前に、プロジェクトの変更を git で commit しておくことをおすすめします。** 更新をまるごと取り消したくなったときに、git で元に戻せます（[5. 更新を取り消す・`.bak` を片付ける](#5-更新を取り消すbak-を片付ける)）。

```bash
cd /path/to/your/project
git status                        # 未 commit の変更が無いかを見る
git add .claude CLAUDE.md AGENTS.md   # 例。一覧を見て、commit してよいものだけを足す（.env など秘密のファイルは足さない）
git commit -m "AI-PLC 更新の前"   # 変更があったときだけ
git status --ignored --short -- .claude .cursor .agents CLAUDE.md AGENTS.md .ai-plc-version .ai-plc-install-manifest | grep '^!!'
```

最後の行で表示されたファイル（`!!` の行）は、`.gitignore` で git の管理外になっているので、git では戻せません。その部分は、更新で残る `.bak` から戻すことになります（DB の `.claude/db/ai_plc.db` のように installer が書き換えないものなら、気にしなくてかまいません）。

### 1. 自分の版と入れ方を確かめる

AI-PLC を入れたプロジェクトのフォルダ（installer に `--target` で渡したフォルダ）で、次を実行します。

```bash
ls .ai-plc-install-manifest   # インストール台帳（installer が入れたファイルの記録）があるか
cat .ai-plc-version           # 版の表示
```

| 台帳（`.ai-plc-install-manifest`） | 版 | `.ai-plc-version` の表示 |
| --- | --- | --- |
| ある | v1.7.0 以降 | そのままの版（`1.7.1` など） |
| ない（`No such file or directory`） | v1.1.0〜v1.6.0 の旧版 | どの旧版でも `1.1.0` と出ます。本当の版は、次の手順で installer が中身から自動で判別します |

**どの環境向けに入れたか**も確かめます。更新は、最初に入れたときと同じ指定（`cc` / `cursor` / `both` / `all` / `codex`）で流します。指定を変えると、指定しなかった環境は古いまま残ったり、使っていない環境のファイルが増えたりします。

- 台帳がある場合: 台帳の `environments` に入っている環境が、最初に入れた環境です
  ```bash
  python3 -c "import json; print(sorted(json.load(open('.ai-plc-install-manifest'))['environments']))"
  ```
  `['cc']` なら `cc`、`['cursor']` なら `cursor`、`['cc', 'cursor']` なら `both`、`['cc', 'codex', 'cursor']` なら `all`、`['codex']` なら `codex` です。環境別のスクリプトで別々に入れた `['cc', 'codex']` なら `cc` を流してから `codex`、`['codex', 'cursor']` なら `cursor` を流してから `codex` を、それぞれ `--dry-run` から流します
- 台帳がない場合（旧版は Claude Code と Cursor だけ）: `.claude/commands/01-collection.md` があれば Claude Code、`.cursor/rules/ai-plc-system.mdc` があれば Cursor が入っています。両方あれば `both` です（installer が旧版と判別するには、Claude Code なら `CLAUDE.md` と `AGENTS.md`、Cursor なら `.cursor/skills/ai-plc/01-collection/SKILL.md` も必要です。消していると判別されず、配ったファイルのほとんどが衝突として並びます。そのときも 3-1 の `--backup-modified` で進められますが、編集していないファイルも `[BACKUP]` 行に並びます）
  ```bash
  ls .claude/commands/01-collection.md .cursor/rules/ai-plc-system.mdc
  ```

**実験版（Jev 監視）を入れているか:** `.claude/ai-plc-jev/` フォルダや、`.claude/commands/01-collection-jev.md` のような `-jev` の付いたコマンドがあれば入れています（`ls -d .claude/ai-plc-jev`）。

### 2. 更新する（Claude Code の例）

```bash
cd /path/to/ai-plc   # AI-PLC を clone した場所（無ければ「インストール」の手順で clone し直す）
git pull             # 最新の版を取ってくる（失敗したら git status で、clone に自分の変更が無いか・main ブランチにいるかを確かめる）

# まず何が起きるかを見る（ファイルは1つも書き換えません）
./install.sh --dry-run --target /path/to/your/project cc

# 問題がなければ実行
./install.sh --target /path/to/your/project cc
```

- `--dry-run` の出力の `"conflicts": []`（空）なら、そのまま実行して大丈夫です。`"writes"` が書き換わるファイルの一覧です。`DELETE:` で始まる行は、新しい版で配らなくなったので消すファイル（消す前の中身は `.bak` に残ります）、`CLAUDE.md#ai-plc-cc` のように `#` の付いた行は、そのファイルのマーカーの中だけの書き換えです
- **`"conflicts"` に1行でも入っていたら、実行しても止まります。** 下の [3. 止まったとき](#3-止まったとき) を見てください
- 旧版からの場合は、`[INFO] legacy release detected: cc v1.2.1–v1.4.1 (catalog 1.2.1)` のように、判別した版が出ます。中身が同じ版はまとめて表示されます
- 成功すると `[OK] cc install committed: 13 changed file(s)` のように出て、`.ai-plc-version` が新しい版（`1.9.0` など）になり、台帳 `.ai-plc-install-manifest` ができます（または更新されます）。同じ版でもう一度実行しても何も変わりません（`0 changed file(s)`）
- 書き換える前のファイルは、同じ場所に `<ファイル名>.bak.<日時>.<番号>` として残ります（自分で編集していないファイルの分も残ります。自動では消しません。片付け方は [5.](#5-更新を取り消すbak-を片付ける)）
- wiki・DB・`soul.md`・成果物と、`CLAUDE.md` / `AGENTS.md` の AI-PLC マーカー（`<!-- AI-PLC START -->`〜`END`、Codex では `<!-- AI-PLC CODEX START -->`〜`END`）の外の本文は書き換えません（wiki の説明ファイルや DB のように、無いものだけ新しく足すことはあります）。自分で足したファイル（例: `.claude/rules/` に自作したルール）も触りません
- 更新が終わったら、インストールのときと同じく、**新しいチャット／スレッドを開始して**から使ってください
- **v1.8.x 以前から v1.9.0 に上げるとき:** DB 同期スキルの名前が `ai-plc-db-sync` から **`plc-db-sync`** に変わり、置き場所も `.claude/skills/ai-plc/db-sync/` から `.claude/skills/plc-db-sync/` に移ります（Cursor は `.cursor/skills/plc-db-sync/`、Codex は `.agents/skills/ai-plc/plc-db-sync/`）。`--dry-run` の `DELETE:…/ai-plc/db-sync/SKILL.md` は、この移動で古いほうを消す行です。自分で編集していなければ自動で消え、古いフォルダには `.bak` だけが残ります（要らなければフォルダごと消してかまいません）。編集していた場合は `user-modified stale managed file` で止まるので、`--backup-modified` を付けるか、中身を退避してから古いファイルを消して流し直してください（Codex だけの環境では `--backup-modified` は使えないので、退避の方法で）。呼ぶときは `/plc-db-sync` を使います

- **v1.11.0 以前から v1.12.0 に上げるとき:** タスクの正が各 Layer の `backlog.yaml` だけになり、Registry の tasks テーブルは凍結して使わなくなります（RUL_plc_system §9）。installer は既存の DB を書き換えないので、更新の後にプロジェクトのルートで `python3 .claude/db/sync.py tasks-sync --freeze --approved-by <名前>` を1回実行してください（`--reason "<理由>"` も付けられます。状態の確認は `tasks-sync --status`）。凍結しても tasks テーブルの行は消えず、そのまま残ります。Construction（Stage 3）の既定省略と自動完走（/goal）もこの版から入ります（[CHANGELOG.md](CHANGELOG.md)）

**ほかの環境:** 最後の `cc` を、1. で確かめた指定に置き換えます。`cursor`（Cursor）・`both`（Claude Code + Cursor）・`all`（3環境）・`codex`（Codex）。`./install-cc.sh --target …` のような環境別のスクリプトでも同じように更新できます。旧版（台帳なし）の Claude Code / Cursor 環境に Codex を足すときは、`codex` だけを指定すると旧版を判別できずに止まるので、先に `cc`（または `both`）で上げてから `codex` を実行してください（Claude Code・Cursor・Codex の3つを使うなら `all` でもかまいません）。

**実験版（Jev 監視）を入れている人:** 実験版も一緒に上げるときは `--with-jev` を付けます（`./install.sh --target /path/to/your/project cc --with-jev`）。付けずに更新すると、実験版のファイルは今のまま残ります。前の実験版 1.8.0-exp.1 を入れた環境の `.ai-plc-version` は、その時点の core の版の `1.7.1` と出ます。前の実験版から今の実験版 1.12.0-exp.1 への上げ方は[実験版の節](#-実験版-jev-監視)にあります。

### 3. 止まったとき

installer は、プロジェクトを壊すおそれがあると**書き換えを始める前に止まります**。本実行で最後の行が次のどちらかなら、プロジェクトは何も変わっていません（終了コード 2）。

```
[ERROR] preflight failed; target unchanged                     # cc / cursor / both / all
[ERROR] preflight failed with 1 conflict(s); target unchanged  # codex
```

`--dry-run` ではこの行は出ず、`"conflicts"` が空でない JSON を出して終了コード 1 で終わります（`--dry-run` はもともと何も書き換えません）。

止まった理由は、本実行ではその上の `[CONFLICT]` 行、`--dry-run` では `"conflicts"` の中身です。

- **`[CONFLICT]` の後が `unmanaged …` か `user-modified …` で始まる行**（`CLAUDE.md: unmanaged marker region` のようにファイル名が先に付くものも含む）は、編集が理由です → 3-1
- それ以外の行 → 3-2。両方あるときは、3-2 の行を先に片付けます

最後の行が `preflight failed` ではない `[ERROR]` 行のときは、書き換えの途中や後で止まったことがあります。`git status` で変わったファイルを確かめてから、3-2 の表を見てください。

#### 3-1. 自分で編集したファイルがある場合

AI-PLC が配ったファイルを自分で編集していると、上書きで編集が消えないように止まります。

```
[CONFLICT] unmanaged file collision: .claude/rules/ai-plc-system.md
[HINT] --backup-modified を付けると、編集済みのファイルを .bak に退避して更新を進められます (…)
[ERROR] preflight failed; target unchanged
```

出る行は場合によって違います。

- `[CONFLICT]` 行の頭は、旧版（v1.1.0〜v1.6.0）では `unmanaged file collision`、v1.7.0 以降では `user-modified managed file`、`CLAUDE.md` / `AGENTS.md` のマーカーの中を編集したときは `…: user-modified managed region` か `…: unmanaged marker region`（Codex のマーカーなら `user-modified managed Codex region` か `unmanaged Codex marker region`）、新しい版で配らなくなったファイルを編集していたときは `user-modified stale managed file` です
- **旧版では、編集していないファイルも `unmanaged file collision` として並びます。** 1つでも編集があると installer は旧版の版を中身から決めきれず、どのファイルが元のままかも判断できないためです。`--backup-modified` を付ければ、版を推定して、本当に編集したファイルだけを退避します
- `[HINT]` 行は、旧版からの更新で、しかも止まった理由がすべて `--backup-modified` で解決できるときだけ出ます。v1.7.0 以降からの更新では出ませんが、`--backup-modified` は同じように使えます

編集を退避して先に進めるには、`--backup-modified` を付けます。

```bash
./install.sh --dry-run --target /path/to/your/project cc --backup-modified   # "backups" に退避されるファイルが出る
./install.sh --target /path/to/your/project cc --backup-modified
```

実行すると、編集したファイルごとに1行出ます。

```
[BACKUP] .claude/rules/ai-plc-system.md -> .claude/rules/ai-plc-system.md.bak.20260929T072851Z.8
[NOTE] 自分の変更は上の .bak と diff して戻してください (…)
```

**自分の変更の戻し方:** `[BACKUP]` 行の `.bak` が、編集していたときのファイルそのものです。`diff`（2つのファイルの違う行を表示するコマンド）で差分を見て、必要な部分を手で新しいファイルに戻します。

```bash
cd /path/to/your/project
diff .claude/rules/ai-plc-system.md.bak.20260929T072851Z.8 .claude/rules/ai-plc-system.md
```

- `.bak` は、更新で上書きされたファイルすべてに作られます。自分の編集が入っているのは `[BACKUP]` 行に出たものだけです。**`[BACKUP]` 行に出ていない `.bak` は、編集していないファイルの古い版なので消してかまいません**（diff すると、更新で変わった行が出るだけです）
- 旧版から `--backup-modified` で上げたときは、判別行が `[INFO] legacy release detected: cc v1.2.1–v1.4.1 (catalog 1.2.1, estimated: 1 modified, 0 missing)` のように、編集・欠落の数つきで出ます
- `[BACKUP]` 行を見失ったら、台帳に残っている記録（`user_backups`）で `.bak` の名前を確かめられます:
  `python3 -c "import json; [print(b['path'], '->', b['backup']) for b in json.load(open('.ai-plc-install-manifest')).get('user_backups', [])]"`
- `CLAUDE.md` / `AGENTS.md` のマーカーの中を編集していた場合は、ファイル全体が `.bak` に残り、マーカーの中だけが新しい内容になります（マーカーの外の本文はそのまま）
- 戻した変更は「編集あり」として扱われるので、次に installer を実行したときも止まります。そのときも `--backup-modified` を付け、同じ手順で戻します。**自分用の追記は、AI-PLC が配らない別のファイルや、`CLAUDE.md` のマーカーの外に書くと、更新で止まりません**
- **`--backup-modified` を付けても止まったら、** 編集以外の理由です。出た `[CONFLICT]` / `[ERROR]` 行を、次の 3-2 の表で探してください

**`codex` を指定して流すとき（Codex だけの人、`cc` や `cursor` の後に `codex` を流す人）:** Codex 対応は v1.7.0 からなので、Codex には台帳のない旧版がありません。旧版の判別は要らず、`./install.sh --target /path/to/your/project codex` だけで上がります。ただし `--backup-modified` は `codex` の指定では使えません（`[ERROR] --backup-modified is not supported for Codex-only installs …` で終了コード 2）。編集したファイルがあって止まったら、次のようにします。

- **`AGENTS.md` 以外のファイル**（`.agents/skills/` の下や、Codex 用にも配られる `.claude/skills/`・`.claude/rules/`・`.claude/db/` の下。`[CONFLICT] user-modified managed file: …` や `user-modified stale managed file: …`）: そのファイルをプロジェクトの外へ移してから実行します。移したファイルは新しい版で入れ直される（配らなくなったファイルなら入れ直されない）ので、移したファイルと diff して手で戻します。移す先に同じ名前のファイルが無いことを、先に `ls` で確かめてください
  ```bash
  mv /path/to/your/project/.agents/skills/ai-plc/01-collection/SKILL.md ~/SKILL.mine.md   # 例: 編集したファイルを外へ移す
  ./install.sh --target /path/to/your/project codex
  diff ~/SKILL.mine.md /path/to/your/project/.agents/skills/ai-plc/01-collection/SKILL.md
  ```
- **`AGENTS.md`**（`[CONFLICT] AGENTS.md: user-modified managed Codex region`）: `AGENTS.md` には自分の本文（マーカーの外）も入っているので、**ファイルごと捨てずに、プロジェクトの外へ控えを取ってから**実行します。新しい `AGENTS.md` は AI-PLC の部分（`<!-- AI-PLC CODEX START -->`〜`END`）だけになるので、控えからマーカーの外の本文を貼り戻します。マーカーの中に書いていた自分の追記は、マーカーの外に移して書きます（マーカーの外なら、次の更新で止まりません）
  ```bash
  ls ~/AGENTS.mine.md    # 「No such file or directory」なら次へ（同じ名前のファイルがあれば、別の名前にする）
  mv -n /path/to/your/project/AGENTS.md ~/AGENTS.mine.md   # 控えを取る（-n: 同じ名前があれば上書きしない）
  ./install.sh --target /path/to/your/project codex
  diff ~/AGENTS.mine.md /path/to/your/project/AGENTS.md  # 消えた本文と、マーカーの中の自分の追記が出る
  ```
  Claude Code も入れている人は、新しい `AGENTS.md` から Claude Code 用のマーカー部分（`<!-- AI-PLC START -->`〜`END`）も一時的に無くなります。続けて `cc` を流すと入り直します

#### 3-2. それ以外の理由で止まった場合

| 出た行 | 意味 | どうするか |
| --- | --- | --- |
| `legacy release ambiguous for cc: catalogs 1.2.0.yaml, 1.2.1.yaml (use --migrate-legacy <version>)` | 旧版の版を、中身から1つに決められなかった（`--backup-modified` を付けたときに、候補が並ぶことがあります） | 自分の版を `--migrate-legacy <版>` で指定して、同じコマンドを流し直します（`--migrate-legacy` は「この旧版として扱う」と installer に教えるオプションです）。版には、表示された候補から `.yaml` を除いたもの（例: `1.2.1`）を指定します。どちらか分からなければ新しい方を指定します。合わなかったファイルは編集ありとして `.bak` に退避されるだけです。例: `./install.sh --target /path/to/your/project cc --backup-modified --migrate-legacy 1.2.1` |
| `legacy release not identified for cc: …` や `legacy migration failed: cc matches catalog … only 45%` | ほとんどのファイルが編集されていて、旧版を判別できない | 下の「上のどれにも当たらないとき」へ |
| `target is busy or needs recovery`（`--dry-run` のとき） | 前回の installer が途中で止まった（強制終了・電源断など）跡が残っている | `--dry-run` では直しません。`--dry-run` を外して一度実行すると、installer が前回の途中までの変更を元に戻して（または前回の分を仕上げて）から、今回の更新に進みます。`--dry-run` で先に中身を見たいときは、その後にもう一度 `--dry-run` を流します |
| `[ERROR] target is busy: live installer lock` | 別の installer が、いま同じプロジェクトで動いている | その installer が終わるのを待ってから、もう一度実行します |
| `[ERROR] … manual recovery required` や `[ERROR] … requires manual inspection` など、`recovery` / `manual inspection` を含む `[ERROR]` 行 | 途中で止まった跡が、再起動の前のものや別のマシンのもので、installer が自動では戻せない | **更新の前に commit していなければ、何も消さずに Issue へ。** commit していれば: ① 別の installer が動いていないことを確かめます（`ps aux \| grep '[a]i_plc_'` で何も出なければ、このマシンでは動いていません。共有フォルダや同期フォルダにあるプロジェクトなら、ほかのマシンでも確かめる）② [5.](#5-更新を取り消すbak-を片付ける) の手順で commit の状態に戻します ③ 途中の跡がまだ残っていれば、次の1行目で一覧を見て、途中の跡（`.ai-plc-install.lock`・`.ai-plc-install-journal.…`・`.ai-plc-tmp.…`）だけが並んでいることを確かめてから、2行目で消し、もう一度実行します。一覧: `find . -path ./.git -prune -o \( -name '.ai-plc-install.lock*' -o -name '.ai-plc-install-journal.*' -o -name '.ai-plc-tmp.*' \) -prune -print` / 消す: `find . -path ./.git -prune -o \( -name '.ai-plc-install.lock*' -o -name '.ai-plc-install-journal.*' -o -name '.ai-plc-tmp.*' \) -prune -print -exec rm -rf {} +`（台帳 `.ai-plc-install-manifest` と `.ai-plc-version` は一覧に出ず、消えません） |
| `manifest is detached; resolve residuals before install` | 以前 uninstall したとき、自分で編集したファイルが残された（台帳が「切り離し」状態） | 次のコマンドで、残っている環境と残されたファイルを見ます: `python3 -c "import json; d=json.load(open('.ai-plc-install-manifest')); print(d['environments'], [r['path'] for r in d['residuals']])"`。最初が `{}`（残っている環境なし）なら、表示されたファイルと `.ai-plc-install-manifest` をプロジェクトの外へ移してから実行し、移したファイルと diff して手で戻します。`{}` 以外なら Issue へ |
| `special file at legacy managed path: <パス>`、または `Too many levels of symbolic links` / `Not a directory` を含む `[ERROR]` 行（例: `[ERROR] [Errno 62] Too many levels of symbolic links: …`。番号は OS で違います） | AI-PLC のファイルやフォルダが、シンボリックリンク（別の場所を指す見かけだけのファイル）などになっている | リンクを実物のコピーに置き換えてから、もう一度実行します。ファイルなら `cp <パス> <パス>.real` → `mv <パス>.real <パス>`。フォルダなら、リンク先のフォルダを同じ名前でコピーしてからリンクと入れ替えます |
| `CLAUDE.md: managed region markers are missing or duplicated`（`AGENTS.md` も同じ）、`AGENTS.md: existing AGENTS.md has invalid Codex marker count` | AI-PLC のマーカー（`<!-- AI-PLC START -->` と `<!-- AI-PLC END -->`、Codex なら `<!-- AI-PLC CODEX START -->` と `<!-- AI-PLC CODEX END -->`）が片方だけ、または2つ以上ある | ファイルを開き、`START` と `END` が1つずつになるように、余分な行を消すか足りない行を戻してから、もう一度実行します |
| `downgrade refused`（`component downgrade refused: …` も） | プロジェクトに入っている版より、clone した AI-PLC の方が古い | clone した場所で `git pull` し直して（2. を参照）、もう一度実行します |
| `[ERROR] non-git target requires --yes or interactive confirmation` | プロジェクトが git リポジトリではない | プロジェクトで `git init` してから実行します（git なしで進めるなら、ターミナルから直接実行して確認に `y` と答えます） |

**上のどれにも当たらないとき:** 最後の行が `preflight failed … target unchanged` なら、プロジェクトは変わっていません。それ以外の `[ERROR]` 行なら、`git status` で変わったファイルを確かめておきます。そのうえで、出た行をすべて（`--dry-run` の出力もあれば一緒に）添えて [Issue](https://github.com/miyatti777/ai-plc/issues) で知らせてください。

### 4. installer では更新されないもの

- **Registry ビューア（アルファ版）:** 入れている人だけ。手でコピーしたものなので、自分で入れ直します。AI-PLC を clone した場所で、新しいものを横にコピーしてから入れ替え、最後に古いものを消します（途中で失敗しても、ビューアが無くなることはありません。古いものを残したまま上からコピーすると入れ子になるので、この順にします）
  ```bash
  cd /path/to/ai-plc
  cp -R experimental/registry-viewer /path/to/your/project/.claude/db/registry_viewer.new
  mv /path/to/your/project/.claude/db/registry_viewer /path/to/your/project/.claude/db/registry_viewer.old
  mv /path/to/your/project/.claude/db/registry_viewer.new /path/to/your/project/.claude/db/registry_viewer
  rm -rf /path/to/your/project/.claude/db/registry_viewer.old   # 新しいビューアが動くのを確かめてから
  ```
  Mac のメニューバーアプリを出力先を指定せずにビルドしていた場合、アプリも古いフォルダの中にあるので一緒に消えます。ビルドし直してください

### 5. 更新を取り消す・`.bak` を片付ける

**更新をまるごと取り消す（更新の前に commit していた場合）:** プロジェクトのフォルダで、まず何が変わったかを見ます。

```bash
cd /path/to/your/project
git status --short   # " M" は書き換わったファイル、"??" は増えたファイル
```

` M` の行が AI-PLC のファイル（`.claude/`・`.cursor/`・`.agents/` の下、`CLAUDE.md`・`AGENTS.md`・`.ai-plc-version`）だけなら、次を実行します。**`git restore` は、commit していない変更を確認なしに捨て、取り戻せません。**

```bash
git restore .   # 書き換わったファイルを commit の状態に戻す
git clean -nd   # 更新で増えたファイル（台帳・.bak・新しいファイル）の一覧。まだ消さない
git clean -fd   # 一覧が更新で増えたものだけなら、消す
```

- ` M` の行に、commit していない自分の変更（AI-PLC 以外のファイル）が混ざっていたら、`git restore .` は使わず、AI-PLC のパスだけを指定します: `git restore -- .claude CLAUDE.md AGENTS.md .ai-plc-version`（Cursor も入れているなら `.cursor`、Codex なら `.agents` を足す。入れていない環境のフォルダを書くと、エラーで何も戻りません）。このときも、指定したパスの中の commit していない変更は消えます
- `git clean -nd` の一覧に、自分で作って commit していないファイルが混ざっていたら、`git clean -fd` は使わず、一覧のうち更新で増えたものだけを手で消してください

**commit していなかった場合:** 上書きされたファイルは `.bak` から戻せます（例: `mv .claude/rules/ai-plc-system.md.bak.20260929T072851Z.8 .claude/rules/ai-plc-system.md`）。ただし、更新で新しく足されたファイルと台帳は残るので、まるごと元どおりにするのは難しくなります。

**残った `.bak` の片付け:** 自分の変更を戻し終えたら、`.bak` は消してかまいません。まず一覧を見て、AI-PLC が作った `.bak` だけが並んでいることを確かめてから消します。

```bash
cd /path/to/your/project
find . -path ./.git -prune -o -type f -name '*.bak.[0-9]*T[0-9]*Z.[0-9]*' -print           # 一覧だけ（消さない）
find . -path ./.git -prune -o -type f -name '*.bak.[0-9]*T[0-9]*Z.[0-9]*' -print -delete   # 一覧を確かめた後で消す
```

---

## 🟢 はじめての AI-PLC（自分のGoalで）

一番シンプルな使い方は、**Goalを1つ渡すだけ**です。

> 以下のチュートリアルはClaude Code/Cursorの`/skill-name`表記です。Codexでは4ステージを`$01-collection`、`$02-inception`、`$03-construction`、`$04-operation`として起動します。utility Skillも`$spec-story-starter`、`$wire-aa-authoring`のように`$skill-name`で起動してください。

```
/01-collection を実行してください
Goal: <達成したいことを1〜2文で>
```

すると AI が:

1. **Collection** — 関連情報を集めて構造化し、「成功条件」まで提示して**止まります**（あなたが承認）
2. **Inception** — Goalをタスクに分解して `backlog.yaml` を作る（承認）
3. **Construction**（要るときだけ）— 手順の長い実装・委譲するタスク・complex などのときだけ、各タスクの実行役（Agent 定義）を作る（承認）。それ以外は Inception の後すぐ Operation へ進み、backlog の説明と受け入れ条件から実行します
4. **Operation** — タスクを実行し、成果物を作り、別AIが検証

各段であなたが `OK` / `修正: 〜` / `差し戻し` を選べます。**前提が変わったら「やっぱり〜したい」と言えば、前の段階に戻って作り直します**（Backtrack）。

> コードでも、企画書でも、OKRでも、リサーチでも同じ流れで回ります。
>
> 承認を挟まずに最後まで流したいときは、Collection・Inception の完了報告の最後に出る /goal 1行を貼ります（[自動完走](#-自動完走goal)）。

---

## 🏃 自動完走（/goal）

Claude Code の `/goal`（条件を満たすまで続ける標準機能）で、AI-PLC の Layer を**止まらずに最後まで**進める使い方です（v1.12.0〜）。ルールの本文は `core/rules/ai-plc-session.md` §10 にあります。

- **切り替えは /goal だけです。** そのセッションで貼った /goal の文が RUL_plc_session §10 を指しているか、「AI-PLC 自動完走（自己完結版）」を含むときだけ、その /goal が続いている間だけ自動で進みます。「自動で」と口で言うだけでは切り替わらず、`intent.yaml` にも何も書きません。止めるのは `/goal clear`
- **自動で進めるもの:** Mob Checkpoint は承認ブロックを出したうえで⭐（推奨）を選んで続け、Next Action は A（⭐）をその場で実行します。Stage 4 のタスクは P0→P1→P2・依存順に選び、明確化の質問はせずに最も妥当な仮定を置きます（データの扱い・権限・受け手に見える挙動は最も保守的な案）
- **緩めないもの:** Phase 5.5 の独立検証（未解決 P0〜P2 ゼロが完了の条件。修正→再検証は2回まで）、Backtrack の承認（要る判定なら止まる）
- **実行せずに保留するもの:** git の commit・push・PR・merge・タグ、外部公開、Notion・Slack・メールへの書き込み・送信、ローカル sqlite 以外の外部 DB への書き込み、承認後の決まりがある反映、Layer 外のファイル（backlog の output に書かれたパスと Phase 6・7 の決まった書き込み先を除く）、削除・移動・既存成果物の上書き、上記以外の操作（お金・外部 API への送信・ツールの導入など）。保留したものはログに残して先へ進みます
- **止まるとき:** 行頭に `⛔ 自動完走を停止: <理由>` を出して止まります（complex・platform_builder の Layer、SubLayer が出たとき、Backtrack が要るとき、2回直しても P0〜P2 が残るとき など）。自動で選んだ判断は backlog の `refactoring_log` に `[auto-approved]` で1行ずつ残り、完了・停止のときに表で示され、完了報告の冒頭に「確認してほしいこと」が出ます
- **対応環境:** Claude Code と Codex（Codex では開始列のコマンドを `$02-inception` 等に読み替え）。Cursor には /goal が無いので、これまでどおり各 Mob Checkpoint で止まります

### /goal の3種の使い分け

| 種類 | いつ使うか | 貼る文 |
| --- | --- | --- |
| **短い版** | `/01-collection` か `/02-inception` を承認しながら進めてきて、残りを自動で走らせたいとき。完了報告の最後に「自動で進めるなら:」として、Layer パスと開始列を埋めた1行が出るので、それを貼る（complex・platform_builder の Layer では出ない） | `/goal <Layerパス> を <開始列> で完走する（RUL_plc_session §10 の自動完走）。達成: backlog の全タスクが completed（deferred・blocked は保留理由がログにあるもの）・各 output が実在・Phase 7 チェックリストと自動承認ログを表示、または行頭に「⛔ 自動完走を停止」を表示。or stop after 40 turns` |
| **Goal から版** | 新しい Goal を、Layer を作るところから1本で走らせたいとき | `/goal 「<Goal>」を /01-collection から完走する（RUL_plc_session §10 の自動完走）。達成: 作った Layer の backlog の全タスクが completed（deferred・blocked は保留理由がログにあるもの）・各 output が実在・Phase 7 チェックリストと自動承認ログを表示、または行頭に「⛔ 自動完走を停止」を表示。or stop after 60 turns` |
| **自己完結版** | §10 の無い環境（§10 より前の AI-PLC〔v1.11.0 以前〕を入れた環境・別のリポジトリ・AI-PLC の rules を入れていない環境）で使うとき。編集せずに貼るだけで動く（§10 のある環境で食い違えば §10 が正） | 下の全文 |

ターン上限で `⛔` も出ずに終わったら、同じ /goal を貼り直すと続きから再開します。

<details>
<summary>自己完結版の全文（貼るだけで動く）</summary>

```
/goal AI-PLC 自動完走（自己完結版）。この会話で扱っている AI-PLC Layer を、今の状態から最後まで完走する。対象は、この会話で直前に /01-collection〜/04-operation を実行した Layer か、直前に話題にした Layer。どちらも無ければ、この会話で頼まれた Goal で /01-collection から新しく作る。始める位置は Layer の状態で決める: 承認待ちの Mob Checkpoint があればその承認から、backlog のタスクが空なら /02-inception から（simple は Goal を1タスクにした backlog を作り、refactoring_log に Stage 2 を省いた理由と construction を書いて、required が false なら /04-operation、true なら /03-construction へ）、construction.required が true で Agent 定義の無いタスクがあれば /03-construction から、それ以外は /04-operation から。順序は /01-collection → /02-inception →（construction.required が true のときだけ /03-construction）→ /04-operation。達成: その Layer の backlog の全タスクが completed（deferred・blocked は保留理由がログにあるもの）で、各 output が実在し、Phase 7 チェックリストと自動承認ログ（自動で選んだ判断の一覧）を表示する。または行頭に単独で「⛔ 自動完走を停止: <理由>」を表示する。進め方（各 SKILL の「停止」「承認を待つ」「即実行禁止」より優先）: 自動で進め始めたら、対象 Layer の refactoring_log に「[auto-approved] /goal 開始（自己完結版）」を1行書く（Layer が無ければ作った時点で。この行を自動で進める根拠にはしない）。Mob Checkpoint はブロックを出したうえで同じターンで⭐（承認なら OK）を選ぶ。⭐が下の保留に当たる操作なら保留して先へ進む。Next Action は A（⭐）を選んでその場で実行する（Layer の全タスク完了後の Next Action は実行しない）。Stage 4 のタスク選択は P0→P1→P2・依存順で、並列委譲の条件を満たす組は委譲してよい。明確化質問はせず最も妥当な仮定を置く（データの扱い・権限・受け手に見える挙動は最も保守的な案）。Phase 5.5 の P0〜P2 は修正→再検証を2回まで。BT-B・BT-C は独立 checker の判定まで行い、ドリフトも追加ゴールも無ければ続ける。Web 検索・取得は機密を扱う Layer では行わない。自動で選んだ判断は毎回 backlog.yaml の refactoring_log に「[auto-approved] S<Stage>/P<Phase>: <選んだこと>（<理由>）」で1行書き、完了・停止のときに表にまとめ、完了報告の冒頭に「確認してほしいこと」（仮定で決めたこと・公開の文面・保守的に仮定したこと・Layer 外の既存ファイルを変えたタスク）を1行ずつ出す。保留（実行せず「保留: <内容>」とログに残して先へ進む）: git の commit・push・PR・merge・タグ、外部公開（リポジトリ・パッケージへの反映）、Notion・Slack・メールへの書き込み・送信、ローカル sqlite 以外の同期先・外部DBへの書き込み（ローカル sqlite は projects の追加・更新だけで、tasks 行は書かない）、承認後の決まりがある反映（ステータス点検の反映など）、Layer 外のファイル（backlog の output に書かれたパスと、Phase 6・7 の決まった書き込み先を除く）、削除・移動・既存成果物の上書き、上記以外の操作（お金・外部 API への送信・ツールの導入など）。停止: 対象の Layer を決められない／workflow_depth が complex か mode が platform_builder（開始時に intent.yaml で確かめ、途中で判定されたときもその時点で）／Collection で「Layer を作らない」に当たった／BT-A／P0〜P2 が2回の修正後も残る／Backtrack が要る／⭐が無い／保留したものが無いと進めない／人が担当するタスクだけが残った／分解に SubLayer が含まれる（分解の承認前に停止）。止まるときは再開のしかた（同じ /goal を貼り直す等）も示す。or stop after 60 turns
```

</details>

---

## 💡 こんな使い方ができる

Goalを渡すだけ。AIが**発散→収束**を回し、要所であなたが承認・修正・打ち切る。同じ型が、**仕事にも旅にも創作にも**効きます。

### 📖 Story 1 — PdM「解約が止まらない」月曜の朝

**Before:** ダッシュボードの解約率グラフを睨みながら、施策のアイデアがまとまらない。Slackに投げるには粗すぎ、会議にかけるには根拠が足りない。

そこで Goal を渡す:

```
/01-collection を実行してください
Goal: 解約率を下げる施策を出し切り、上位3つをStory+Specまで落とす
```

- **Collection** — AIがOKR・解約データ・議事録を読み込み、成功条件（「P0のStoryが3本、対象リポにground済み」）を提示して止まる → あなたが承認
- **Inception** — 施策を12個に発散 → 影響 × 実装コストで、あなたが3つに絞る
- **Construction → Operation** — 選んだ施策を、実際のDB構造に接地した Story + Spec に収束生成。作った本人ではない独立reviewerが検証して初めて「done」

**After:** 月曜の午後には、"編集するところから始められる"たたき台が3本。白紙を睨む苦痛はゼロ。 `→ 発散→収束型`

### 📖 Story 2 — 旅行「家族4人、10月に台湾5日間」

**Before:** 航空券、ホテル、子連れで回れる場所、夜市の食事、予算20万——変数が多すぎて、ブラウザのタブだけが増えていく。

```
Goal: 10月・家族4人・予算20万で、台湾5日間の日程/宿/食を組む
```

移動・宿・食・アクティビティを**機能ごとに並行設計** → 統合案が上がってくる。あなたは「2日目は九份、3日目は子ども優先」と方向だけ修正し、最後に Go/No-Go を出す。前提（航空券が高騰）が崩れたら、AIが自分で前段に **Backtrack** して組み直す。

**After:** タブ地獄ではなく、1枚の統合日程。判断だけあなたの手に残る。 `→ 並行統合型`

### 📖 Story 3 — 小説「SF長編、書き出せない」

**Before:** 世界観は頭にあるのに、1行目が書けない。設定と本文が絡まって、どこから手をつけるか決められない。

```
Goal: SF長編を、世界観設定→プロット→章立て→執筆で組む
```

AIが **設計スコープ（世界観・年表・キャラ）** と **制作スコープ（各章）** を別レイヤーに再帰分解。あなたは「階層の切り方」を承認するだけ。設定が固まってから、各章が子スコープとして展開されていく。

**After:** 白紙の1行目ではなく、"構造の上に肉付けする"作業から始まる。 `→ 多階層型（フラクタル分解）`

### 他にもこんな場面で

**仕事:** 要件定義（議論→Story/Spec）／ 市場・競合リサーチ（→比較表）／ 事業計画・企画書 ／ ロードマップ策定
**くらし:** イベント企画（結婚式・誕生日・オフサイト）／ 引っ越し・部屋づくり ／ 1週間の献立
**学び:** 学習計画（→カリキュラム）／ キャリア・副業設計（→3ヶ月アクション）

> 秘訣は**「依存が強い→収束型／設定が先→多階層型／独立→並行型」**。**コンテキストを変えるだけで、AIが構造を変幻自在に切り替えます。** まずは自分の「いま広げて絞りたいこと」を `/01-collection` の Goal にしてみてください。

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

**A-3. Construction**（各タスクの実行役を定義。Inception の Next Action が `/03-construction` を勧めたときだけ。`/04-operation` を勧めたら A-4 へ）:

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

**wikiの構造**（`.claude/wiki/` — LLM Wiki方式 / Second Brain 系）:

知見は「型」で整理されます。増えるほど、あなた専用のナレッジベースに育ちます。

| ページ型 | 場所 | 役割 |
|---|---|---|
| **概念ページ** | `wiki/` 直下 | テーマ別にまとめた知見の本体（いちばん価値がある層） |
| **sources/** | `wiki/sources/` | 読んだ記事・論文の要約（1ソース=1ページ） |
| **queries/** | `wiki/queries/` | 「問いと答え」のファイリング（後述） |
| **index.md / log.md** | 直下 | 索引（最初に読む）／ 追記ログ（いつ何を学んだか） |

**基本はノータッチでOK。** タスクを回す中で「これは再利用できる知見だ」とAIが判断したら、Operation の Propagation 段階で wiki に追記します。あなたは `index.md` を眺めれば、これまでの学びが一望できます。

### wiki の使い方（人間がやること / AI が自動でやること）

wiki は **ほぼ AI が自動で育てます。** 人間がやることは少なく、要点は「① 最初に拡張を1つ入れる ／ ③④ AIの提案に Yes/No を返す・矛盾が出たら決める」だけ。以下、機能ごとに**誰がやるか**を明記します。

**① ファイル名は英数字スラッグ ―― AI が自動**
概念ページのファイル名は `design-decisions.md` のような **ASCIIスラッグ（kebab-case）** になります。**AI が自動でそう名付けるので、あなたは意識しなくてOK**。理由は、日本語ファイル名だと多くのエディタの wikilink 拡張が `[[...]]` を解決できず**クリックで飛べない**から。日本語の表示名はページ先頭の見出し（H1）と `index.md` の「表示名」列に入るので、見た目は日本語・リンクは確実、の両取りです。

**② wikilink 拡張を入れる ―― 人間が最初に一度だけ**
`[[design-decisions]]` をクリックで辿るには wikilink 対応拡張が要ります。**ここだけは人間の初期セットアップ**: **Foam**（`foam.foam-vscode`）を入れておくと、（クラッシュ回避で）raw テキストのまま開いていても編集画面から **Cmd/Ctrl+click** で飛べます。`.vscode/extensions.json` に登録済みなら、リポジトリを開いたとき導入を促されます。AI が書くリンクは常にプレーンな `[[slug]]` です（表示名つきの `[[slug|表示名]]` は非対応の拡張があるため使いません）。

**③ queries/ ＝「調べて出した答え」を残す場所 ―― AI が提案、あなたが Yes/No**
queries/ は、**あとで蒸し返さないための小さなFAQ／決定メモ**です。「◯◯と△△どっちにする？」を調べて結論を出したら、それを1ページに残しておく、というもの。

- **いつ・誰が作る？**
  - タスク実行中に該当する結論が出たら → **AI が自動でファイリング**
  - タスク外の雑談・調査で出たら → **AI が「これ残しますか？」と1行提案 → あなたが Yes なら作成**（勝手には作りません）
- **中身のイメージ**（1ページはこれくらい軽い）:
  ```
  Q: 記憶は wiki と native memory、どちらに置く？
  A: バグ・技術知見・PJ横断パターンは wiki。好み・判断のクセは native memory。
  → 概念ページ「メモリ設計」に反映済み
  ```
- 残した問いは概念ページへ**還元**され、「なぜそう決めたか」の履歴になります。基準とテンプレは `wiki/queries/README.md`。

**④ 健全性チェック（Knowledge Lint）―― AI が実行、あなたは判断だけ**
wiki が育つと、矛盾・孤立ページ・出典なし・非ASCIIファイル名などが混ざります。それを点検するのが Lint で、**チェックとレポート作成は AI が実行**します。あなたが「毎月やる」ような手作業ではありません。

- **いつ？** ページが増えたとき（目安: +5 ページ、または矛盾フラグが 2 件）に **AI が「そろそろ Lint しますか？」と提案** → あなたが承認したら AI が点検（「Knowledge Lint 実行して」と自分から頼んでもOK）。※「毎月」のような時間ベースは忘れがちなので、増加を引き金にしています。
- **あなたがやること**: レポートで 🔴 矛盾が出たときに「どちらが正しいか」を決めるだけ（🟡🔵 は次のついでに直せばOK）。

> **まとめ** ―― 人間 = ② 拡張を一度入れる／③④ で Yes-No と矛盾の解決。 AI = 命名・リンク・ファイリング・Lint実行を全部自動で。

> **振り分けの原則:** バグ・技術知見・PJ横断パターン → wiki ／ あなたの好み・判断のクセ → native memory。両方に重複させない。
> Cursor には native memory 機能が無いため、wiki が主な記憶になります。

---

## 🔎 Collection が賢く集める（MCPを繋ぐほど強くなる）

`/01-collection` は、Goalを渡すと **自分の記憶と手持ちのツールを総動員**してコンテキストを集めます。内部・既存資産を最優先し、**利用可能なものだけ使う**（未接続は黙ってスキップ）:

| 集める先 | 何を拾うか |
|---|---|
| **ワークスペース横断検索**（Grep/Glob） | プロジェクト内の関連ファイル。`serena` があれば意味的に近い過去成果物も |
| **Project Registry**（`.claude/db`） | 関連PJ・親PJ・同ドメインの過去プロジェクト |
| **wiki** | 過去の設計判断・学び・バグパターン |
| **native memory** | あなたの好み・進行中PJの状態（Claude Code） |
| **接続済みMCP検索** | Notion / Google Drive / Gmail / serena 等を検出して検索。GitHubは `gh` CLI |
| **Web検索** | 内部で足りないときだけ外部を補う |

### 💡 検索系MCPをたくさん繋ぐほど、収集は賢くなる

議事録・仕様・過去資料が **Notion / Google Drive** にあるなら、それらのMCPを繋いでおくと、Collectionが**あなたの知識ベースまで横断して**文脈を集めてくれます。おすすめの繋ぎ先:

- **Notion**（`@notionhq/notion-mcp-server`）— 議事録・PRD・PJページ。トークン1つで繋がる
- **Google Drive / Gmail**（Claude Code の Connectors、または各MCP）— 資料・メール
- **serena** — コードベースのセマンティック検索
- **GitHub** — `gh` CLI（`gh search ...`）が確実（auth済みなら追加設定不要）

繋ぎ方はプロジェクト直下の `.mcp.json` に定義（**トークンは env 参照で。平文で書かない**）→ Claude Code をリロード。繋がっていないものは自動でスキップされるので、**まず持っているものから繋げばOK**です。

---

## 🗄 DB の使い方（Project Registry / Tasks）

AI-PLC は、プロジェクト横断の台帳とタスクを**ローカル SQLite**（`.claude/db/ai_plc.db`）で管理します。インストール時に**空のDB**が作られます。

> **核の4ステージループは DB 無しでも動きます。** DBは「複数PJを横断で見る台帳」「外部チケット同期」という**任意の管理レイヤー**です。

### よく使うコマンド

```bash
python3 .claude/db/plc_query.py projects        # プロジェクト一覧
python3 .claude/db/plc_query.py tasks           # タスク一覧（凍結中は各 Layer の backlog.yaml を表示）
python3 .claude/db/plc_query.py tasks L-1234    # 特定Scopeのタスク
python3 .claude/db/plc_query.py active          # activeなPJだけ
python3 .claude/db/plc_query.py dashboard       # ダッシュボード
python3 .claude/db/plc_query.py sql "SELECT ..."  # 任意SQL
```

- **projects テーブル** = Project Registry。Collection で新PJを始めると自動登録され、横断で状況が見られます。
- **tasks テーブル** = 使いません（v1.12.0〜凍結）。**タスクの正は各 Layer の `backlog.yaml`** です。新しく作った DB は最初から凍結され、`plc_query.py add-task` は書き込まずに `[SKIP]` を出し、`plc_query.py tasks` は backlog.yaml を表示します。External Sync の既定は projects テーブルです。v1.11.0 以前から使っている DB は、installer では書き換えないので、`python3 .claude/db/sync.py tasks-sync --freeze --approved-by <名前>` で凍結します（状態は `python3 .claude/db/sync.py tasks-sync --status`、戻すのは `--unfreeze --approved-by <名前>`）

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

> 💡 **Notion のページ本文そのものを往復させたい場合**は、姉妹ツール [nsync](https://github.com/miyatti777/nsync) が使えます。DB だけでなく企画ページ・タスクページの本文・装飾まで Notion⇔ローカル Markdown で双方向同期でき、「企画は Notion／実装・執筆は Claude Code」の往復ワークフローの実行手段になります。

### 画面で見る（アルファ版: `experimental/registry-viewer/`）

Registry をブラウザで一覧（親子のツリー・status・進捗率）し、Project と Task の status を変えられるローカル専用のビューアを、**アルファ版**として置いています。installer の対象外なので、プロジェクトに手でコピーして使います。

```bash
cp -R experimental/registry-viewer <プロジェクト>/.claude/db/registry_viewer
cd <プロジェクト> && python3 .claude/db/registry_viewer/server.py   # http://127.0.0.1:8765/
```

- core だけの環境では**閲覧のみ**、Jev 実験版（`--with-jev`）を入れた環境では status の変更やステータス点検の指摘も使えます
- status を変えると Layer のファイルと Registry の両方を書き換えます。試す前にバックアップを取ってください（手順と、書き換わる範囲・戻し方は [`experimental/registry-viewer/README.md`](experimental/registry-viewer/README.md)）
- 0.2.0-alpha から、各 Project に分類（所属・種類・実行環境）を付けて、一覧のバッジと絞り込みで見分けられます（`classify.py`。手順は同じ README の「分類」）
- macOS のメニューバーアプリのソース（自分でビルドする）も同梱しています。試した結果の報告は Issue で歓迎します

---

## 🛠 同梱スキル

**コア（4ステージ本体）:** `/01-collection` `/02-inception` `/03-construction` `/04-operation` ＋ `/status`

**ユーティリティ（収束を深める）:**

| スキル | 用途 |
|--------|------|
| `spec-story-starter` | 選定施策を、対象リポの実構造にgroundした **Story + Spec** にSubagentで収束生成（`target_repo`/`backlog` を選べる汎用） |
| `wire-aa-authoring` | Story/Spec と対象リポから、画面UIの **現状→変更後** を **ASCII Artワイヤフレーム**で描く |

この2本は `/spec-story-starter`・`/wire-aa-authoring` で呼びます（v1.9.0 から `.claude/commands/` にラッパーを同梱。それまでは `.claude/skills/utility/` の下に入るだけで、Claude Code から呼べませんでした）。

**AI-PLC ユーティリティ（`plc-<機能>`・v1.9.0〜）:** Registry・同期・点検などの道具です。`.claude/skills/plc-<機能>/SKILL.md` に入り、`/plc-<機能>` か自然な言葉で呼べます（書き込みを伴う操作は `/plc-<機能>` で明示的に呼ぶのが確実です）。

| スキル | 用途 | 使える条件 |
|--------|------|------|
| `plc-registry` | Project Registry（`.claude/db/ai_plc.db`）の照会と追加 | いつでも |
| `plc-db-sync` | ローカル DB ⇔ Notion DB の同期（旧 `ai-plc-db-sync`） | Notion の設定をしたとき |
| `plc-status-audit` | ステータス点検（intent・backlog・Registry の食い違いの洗い出しと、承認した行だけの反映） | 実験版（`--with-jev`）を入れたとき |
| `plc-viewer` | Registry ビューア（ブラウザ）の起動・停止 | `experimental/registry-viewer` を手でコピーしたとき（status の変更は実験版も入れたときだけ。無ければ閲覧のみ） |
| `plc-consult` | アイデア相談。「ここをこうしたい」を今の Layer と照らして 却下／今のタスク内で修正／Re-Inception／Re-Collection／いつかやる に振り分け、所感と次に打つコマンドを返す（読み取り専用。v1.10.0〜） | いつでも |
| `plc-backfill` | スキル外作業の事後記録。スキルを通さずに済ませた作業を、承認を得てから対象 Layer の backlog に ad-hoc タスクとして足し、04-operation の Phase 5.5〜7（検証・ステータス更新・Propagation）を通す（v1.11.0〜） | いつでも |

名前の決まりは `.claude/rules/ai-plc-system.md` の §6 にあります（Stage は `0N-<stage>`、ユーティリティは `plc-<機能>`）。

---

## 🧪 実験版: Jev 監視

> ⚠️ **実験版です。通常のインストールには含まれません。** `--with-jev` を付けたときだけ入り、仕様・コマンド名・置き場所は予告なく変わることがあります。
>
> ⚠️ **外部送信あり（opt-in）。** APIキーを登録し、Layer の `intent.yaml` に `jev_monitor: true` を書いたときだけ、Layer の文や発話を字数で切ったもの（下の表。要約ではなく原文の抜粋です）を外部の判断専用モデル **Jev**（TypeSafe）に送ります。キーが無ければ何も送らず、すべてスキップされます。
>
> **版:** 実験版パッケージ（`experimental/jev/`）の版は **`1.12.0-exp.1`** で、前の実験版 `1.8.1-exp.1` の次の版です。実験版の番号は core の版（**1.12.0**）とは別に数えます。`1.12.0-exp.1` は core 1.12.0 に合わせて出した版で、末尾の `exp.1` はその版での通し番号です（頭の数字が core の版と一致するとは限りません。たとえば `1.8.0-exp.1` は core 1.7.1 の上に作ったものです）。スキルは core 1.12.0 のスキルを元にしており、違いは Jev 部分だけです（[CHANGELOG.md](CHANGELOG.md)）。

AI-PLC の作業中に、Jev に「前の段階に戻るべき兆しはないか」などを1問だけ聞き、**1行のヒント**を出します。ヒントに作業を止める権限はなく、判断はメインのモデルとあなたが行います。**Claude Code 専用**で、Jev への問い合わせ（外部送信）は `/01-collection-jev` → `/02-inception-jev` →（要るときだけ `/03-construction-jev`）→ `/04-operation-jev` を使ったときだけ動きます（core の `/01-collection`〜`/04-operation` は Jev を呼びません）。例外として、下の表の「ステータス点検」（Jev には送らず、ローカルのファイルと DB を読むだけの点検）は、core 1.8.0 からは core の `/04-operation` の Phase 7 でも、実験版を入れてあれば動きます（実験版が無ければ「点検ツールなし — スキップ」と出して進みます）。

### できること（4機能）と外部送信の内容

| 機能 | 動く場所 | 外部に送るもの |
| --- | --- | --- |
| 異常ヒント（Backtrack の兆し） | `/04-operation-jev` の Phase 5.5b・6b | ゴール1行（200字まで）・進捗（件数）・直近のタスク完了報告（backlog の `result`、無ければタスクの説明。1200字まで） |
| 成功条件カバー判定 | `/02-inception-jev` の分解承認の前 | ゴール1行（200字まで）・成功条件（全文）・各タスクの ID・名前・説明（説明は1件160字まで） |
| 会話監視 hook（任意・**手動で有効化**） | 発話ごと（Claude Code の `UserPromptSubmit` hook） | あなたの直前の発話1件の原文（貼り付けた部分は除き、空白を詰めて400字で切る）・ゴール1行・進捗（件数） |
| ステータス点検 | `/04-operation-jev` と、core 1.8.0 以降の `/04-operation` の Phase 7（どちらも実験版を入れたときだけ） | 既定は**送らない**（読み取り専用）。スクリプトに `--jev` を手で付けたときだけ、停滞 Layer のうち `jev_monitor: true` で機密でないものについて、ゴール1行・最後に完了したタスクの名前と結果（400字まで）・進捗・停滞日数。例: `python3 .claude/ai-plc-jev/scripts/aiplc_status_audit.py --jev --layer <Layer パス>` |

- 送信先: 公式経路なら TypeSafe の1社、OpenRouter 経由なら OpenRouter と TypeSafe の2社
- 送る前に、送信禁止の語の検査（コードの汎用語＋自分で書くローカルの `.claude/db/jev_redact_extra.txt`）と命令文の除去が働きます。**キーワードでの判定なので、言い換えた機密は通ります。** 機密PJ・経費・人事・顧客名や人名・私生活に関わる Layer では有効にしないでください
- 送るのは上の表の項目だけです。**要約ではなく、`intent.yaml` / `backlog.yaml` に書かれた文や発話の原文を字数で切ったもの**なので、そこに書いた内容は字数の範囲で送られます。それ以外のファイル（成果物・Context・コードなど）や、これまでの会話のやり取りは送りません（会話監視 hook が送るのは直前の発話1件だけです）。接続確認の `jev_client.py --check` は、固定の接続確認文を1回送るだけです（Layer の内容は含みません）。判断ログ（`.claude/db/jev_decisions.jsonl`）に本文は残りません（残るのは入力と質問のハッシュ・確率・所要時間・費用と、Layer / タスクの ID・日時・経路）

### 入れ方

```bash
./install-cc.sh --target /path/to/your/project --with-jev
./install.sh --target /path/to/your/project cc --with-jev     # both / all でも可（Claude Code 側にだけ入る）

# 先に確認するなら
./install-cc.sh --dry-run --target /path/to/your/project --with-jev
```

- 入る場所: スキル `.claude/skills/ai-plc-jev/`、コマンド `.claude/commands/01-collection-jev.md`〜`04-operation-jev.md`、スクリプトと説明書 `.claude/ai-plc-jev/scripts/`。core のファイルは書き換えません。`--with-jev` を付けないインストールの結果は従来と同じです
- **Claude Code 専用です。** `install.sh cursor --with-jev`・`install.sh codex --with-jev`・`install-cursor.sh --with-jev` は「実験版は Claude Code 専用」というエラーで終了コード 2、`install-codex.sh --with-jev` は `unrecognized arguments: --with-jev` で終了コード 2 になります（どちらも何も書き込みません）
- 必要なもの: Python 3.9 以上と `pyyaml`
- インストール後は、新しいチャットで `/01-collection-jev` から始めます。新しい Layer では `/01-collection-jev` の最後に「Jev監視を有効にしますか」と1行で聞かれ、承認すると `intent.yaml` に `jev_monitor: true` が書かれます（機密などに当たる Layer では聞かれず `false` のまま）。既存の Layer で試すなら、`intent.yaml` に `jev_monitor: true` を手で書き、Stage 4 を `/04-operation-jev` で回します

### 前の実験版（1.8.1-exp.1）から上げる

```bash
# 先に確認する（conflicts が [] なら更新できる）
./install.sh --target /path/to/your/project cc --with-jev --dry-run
./install.sh --target /path/to/your/project cc --with-jev
```

- core も同時に 1.12.0 に上がります。上がったかどうかは、`.ai-plc-version` が `1.12.0`、台帳（`.ai-plc-install-manifest`）の `experimental_jev` の `package_version` が `1.12.0-exp.1` になっていることで確かめられます。1.8.0-exp.1 からも同じ手順で上げられます
- `--with-jev` を付けずに更新すると、core だけが上がり、実験版は前の版のまま残ります。前の版の実験版スキルは core 1.8.1 の時点のもので、Construction を既定で省く変更と自動完走（/goal）に対応していないので、実験版も一緒に上げてください
- 1.12.0-exp.1 を入れた後に、前の実験版を配る checkout の installer で `--with-jev` を付けると、`[CONFLICT] component downgrade refused: experimental_jev` などの行を出して止まり、何も書き換えません。前の版に戻したいときは、今の checkout で `uninstall.sh cc` してから、前の版の checkout で入れ直します

**この版で変えたこと**（前の実験版 1.8.1-exp.1 との違い）:

- **スキル:** core 1.12.0 のスキル（`01-collection` v2.2・`02-inception` v2.1・`03-construction` v2.3・`04-operation` v2.8）に揃えました。Construction を既定で省く変更（`/03-construction-jev` は Agent 定義が要るときだけ。`/02-inception-jev` の Next Action は backlog の `construction.required` で `/03-construction-jev` か `/04-operation-jev` を選ぶ）と、深度の理由の記録（`workflow_depth_reason`・`depth_axes`）が入ります
- **自動完走（/goal）での Jev の扱い:** 自動完走中（RUL_plc_session §10 を指す /goal があるセッション）も、opt-in した Layer の Jev の判定は行います。判定ごとの採否の記録とコピペ用プロンプトへの貼り付け用1行はせず、完了報告の冒頭に「🧭 未確認の Jev 判定: N件」と貼り付け用1行をまとめて出します（回収は `python3 .claude/ai-plc-jev/scripts/jev_bt_monitor.py --pending --layer <Layer>`）。Jev 監視の opt-in（`jev_monitor: true`）は自動では承認しません。`/01-collection-jev` の最後に出る /goal 1行は `-jev` 版のコマンドで書かれます
- **`KNOWN_RELEASES.sha256`:** 1.8.1-exp.1 の配布物のハッシュを足しました（1.8.1-exp.1 から上げたときや、中断した後処理の残り物を掃除するときの照合に使います）
- **ステータス点検:** Registry のタスク同期が凍結されているときは、Registry のタスク行を読まず、分類 3・7・8 を出しません（タスクの正は backlog.yaml）
- installer の処理は変えていません

### キー登録

公式（`TYPESAFE_API_KEY`）か OpenRouter（`OPENROUTER_API_KEY`）のどちらか一方でよく、両方あれば公式が優先されます。経路を固定したいときは環境変数 `JEV_PROVIDER=openrouter`（または `typesafe`）を設定します。`.env` やリポジトリ内のファイルには書きません。

```bash
# macOS: キーチェーンに登録（プロンプトでキーを貼る。公式キーなら -s TYPESAFE_API_KEY）
security add-generic-password -a "$USER" -s OPENROUTER_API_KEY -w
# つながるか確かめる（キーそのものは表示しない）
python3 .claude/ai-plc-jev/scripts/jev_client.py --check
```

Linux / Windows / CI では環境変数で渡します。OpenRouter のキーにはクレジット上限（$2〜5 程度）を付けておくのがおすすめです。公式 TypeSafe 経路は公式ドキュメントに沿って実装しただけで、**接続は未確認**です（作者が実測したのは OpenRouter 経由だけ）。両方のキーを持っていて OpenRouter 経由で使いたい場合は `JEV_PROVIDER=openrouter` を設定してください。

### 会話監視 hook は手動で有効化

installer は hook を登録しません（settings を読み書きしません）。使う人だけが、プロジェクトの `.claude/settings.local.json`（または `.claude/settings.json`）に次の JSON を足し、セッションを開き直します（`.claude/ai-plc-jev/scripts/README_jev.md` の §5 と同じもの）。ユーザー共通の `~/.claude/settings.json` には入れないでください。

```json
"hooks": {
  "UserPromptSubmit": [
    { "hooks": [ { "type": "command",
      "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/ai-plc-jev/scripts/jev_prompt_hook.py\" || true",
      "timeout": 5 } ] }
  ]
}
```

settings に足しただけでは何も送りません。有効になるのは、そのセッションで `/01-collection-jev`〜`/04-operation-jev` のどれかを `Layer: <パス>` 付きで打ち（例: `/04-operation-jev Layer: Flow/202601/2026-01-01/demo-layer`。相対パスは Claude Code の作業ディレクトリ（通常はプロジェクトのルート）から。絶対パスも可）、その Layer が `jev_monitor: true` のときだけです。紐づけはそのセッションだけで、12時間で失効します。

スラッシュコマンド・短い承認・「？」で終わる質問・貼り付けた長文・ハーネスが差し込むメッセージ（サブエージェントの報告・タスク通知・コマンド展開など）は送りません。**ただしハーネスのメッセージの除外は既知の形式を列挙する方式なので、未知の形式のメッセージは発話として送られることがあります。**

### 判定の採否の記録

各判定の行に出る decision_id で、妥当なら `accept`、外れなら `reject` を記録します（`python3 .claude/ai-plc-jev/scripts/jev_bt_monitor.py --override <decision_id> accept`）。記録漏れは `python3 .claude/ai-plc-jev/scripts/jev_bt_monitor.py --pending --layer <Layer パス>` で一覧でき（貼り付け用の1行「Jev判定 … は accept」も出ます）、まとめて記録するときは、一覧で見た ID を渡して `--override-pending accept --layer <Layer パス> --only <ID>・<ID> [--except <違うID> ...]` を使います（一覧の後にできた判定は記録せず、記録済みは二重に書きません）。

### 止め方

| やりたいこと | 方法 |
| --- | --- |
| すぐに全部止める | 環境変数 `JEV_DISABLE=1`（設定場所と効くタイミングは表の下） |
| 1つの Layer だけ止める | その Layer の `intent.yaml` を `jev_monitor: false` にする（opt-in を外す）。次の判定から効きます |
| 会話監視だけ止める | `python3 .claude/ai-plc-jev/scripts/jev_prompt_hook.py --deactivate` で、全セッションの紐づけを外します（セッション ID を後ろに付けるとそのセッションだけ）。次にまた `/0x-*-jev Layer: <パス>` を打つと有効に戻ります。完全にやめるなら settings から hook を消す |
| 送信を完全にやめる | 登録したキーを消す。キーチェーンなら `security delete-generic-password -a "$USER" -s OPENROUTER_API_KEY`（公式キーは `-s TYPESAFE_API_KEY`）。環境変数で渡しているなら、シェルの設定などから `export` の行を消し、Claude Code を起動し直す。**両方のキーを持っている人は両方とも消す**（片方が残るとその経路で送ります） |
| 実験版を外す | 下の「外し方」 |

`JEV_DISABLE=1` の設定場所: Claude Code を起動する前のシェルで `export JEV_DISABLE=1` するか、プロジェクトの `.claude/settings.local.json` に `"env": { "JEV_DISABLE": "1" }` を書きます。スクリプトは呼ばれるたびにこの変数を見るので、Claude Code に変数が渡った後の呼び出しから止まります。起動済みのセッションには後から渡らないので、設定したらセッションを開き直してください。止まっている間の表示は、5.5b / 6b とカバー判定の行は `スキップ（skipped(unavailable:disabled)）`、ステータス点検は「スキップ（unavailable）」（レポートの action は disabled）、会話監視 hook は何も出さず、`jev_client.py --check` は「JEV_DISABLE=1 のため無効」です。

### 外し方（uninstall）と残るデータ

実験版だけを外すオプションはありません。`./uninstall.sh --target /path/to/your/project cc`（`both` / `all` でも可）で、core と一緒に実験版のファイル・その `.bak`・空になった `.claude/ai-plc-jev/` と `.claude/skills/ai-plc-jev/` が消えます。

- `uninstall.sh cursor` / `codex` では実験版は消えません（Claude Code 側の持ち物のため）
- `--with-jev` で入れた後にフラグなしで `install cc` し直しても、実験版は残ります。外したいときは `uninstall.sh cc` の後に、フラグなしで入れ直してください
- 自分で編集した実験版のファイルは、core と同じく消さずに残します
- hook を settings に足した人は、settings からもその設定を消してください（`|| true` を付けていれば、消し忘れても入力はブロックされません）

**uninstall 後も残る生成データ**（installer の管理外。`ai_plc.db` と同じく消しません）:

| ファイル | 中身 |
| --- | --- |
| `.claude/db/jev_decisions.jsonl` / `jev_overrides.jsonl` | 判断ログ（本文なし。ハッシュ・確率・Layer / タスクの ID など）と、判定ごとの採否の記録 |
| `.claude/db/jev_counts_state.json`（`.lock`） | 異常ヒントの数え上げ状態 |
| `.claude/db/jev_prompt_hook_sessions.json`（`.lock`） | 会話監視 hook のセッションの紐づけ |
| `.claude/db/status_hygiene/` | ステータス点検のレポート・承認ファイル・実行ログ |
| `.claude/db/jev_redact_extra.txt` | 自分で作ったローカルの送信禁止語（作った場合だけ） |

消すときは、対象プロジェクトのルートで次を実行します。ローカルの送信禁止語ファイルは、ほかでも使うかを確かめてから自分で消してください。

```bash
find .claude/db -maxdepth 1 -type f \( -name 'jev_*' -o -name '.jev_*' \) ! -name 'jev_redact_extra.txt' -delete   # jev_redact_extra.txt 以外を消す（該当ファイルが無くてもエラーにならない。.claude/db が無ければ実行不要）
rm -rf .claude/db/status_hygiene
# rm -f .claude/db/jev_redact_extra.txt   # 送信禁止語ファイルも消す場合だけ
```

### 既知の制約

- **中断した uninstall の後片付け（1.8.1-exp.1 で対応）:** uninstall の後処理（`.bak` と空ディレクトリの掃除）の最中にプロセスが落ち、次に実行したのが codex 経路（`install-codex.sh` / `install.sh codex`）だった場合や、後処理の再開中にもう一度落ちた場合に、実験版のファイルの `.bak` と `.claude/ai-plc-jev/`・`.claude/skills/ai-plc-jev/` が残ることがありました。1.8.1-exp.1 からは、cc を含む uninstall（`uninstall.sh cc` / `both` / `all`）を実行すると残り物を掃除し、`[OK] experimental_jev: removed N leftover backup file(s) of an interrupted cleanup` と出ます。台帳が無くて uninstall がエラーで止まる環境でも、残り物だけを掃除してから同じエラーで止まります。消すのは、中身が既知の実験版（`experimental/jev/KNOWN_RELEASES.sha256`）か今の配布物と一致する `.bak` と、それで空になった2つのディレクトリだけです。一致しない `.bak`（自分で編集したものなど）は消さずに残し、`[WARN] experimental_jev: N backup file(s) with unknown content kept` で始まる行が出ます。残っているのは自分で編集した中身なので、**消す前に一覧で確かめ、残したいものはプロジェクトの外へ退避してください。** 対象プロジェクトのルートで、まず 1・2 を実行します（一覧・退避ファイルは親ディレクトリに書くので、同じ名前のファイルがあれば先に名前を変えてください）:

  ```bash
  # 1. 残ったファイルを一覧にして確かめる
  { find .claude/ai-plc-jev .claude/skills/ai-plc-jev -type f 2>/dev/null; find .claude/commands -maxdepth 1 -type f -name '0[1-4]-*-jev.md.bak.*' 2>/dev/null; } > ../ai-plc-jev-left.txt
  cat ../ai-plc-jev-left.txt
  # 2. 一覧のファイルをプロジェクトの外にまとめて退避し、中身を表示する
  tar -czf ../ai-plc-jev-kept.tar.gz -T ../ai-plc-jev-left.txt && tar -tzf ../ai-plc-jev-kept.tar.gz
  ```

  2 で表示された中身が一覧と同じなのを確かめてから、3 を別に実行します（一覧が空なら不要です）。3 は退避ファイルが読めるときだけ消します:

  ```bash
  # 3. 消す
  tar -tzf ../ai-plc-jev-kept.tar.gz > /dev/null && rm -rf .claude/ai-plc-jev .claude/skills/ai-plc-jev && find .claude/commands -maxdepth 1 -type f -name '0[1-4]-*-jev.md.bak.*' -delete
  ```

  `.claude/commands/` に残した編集済みのコマンド本体（`0x-*-jev.md`。`.bak` でないもの）はこの手順では消えないので、要らなければ手で消してください。

- 会話監視 hook のハーネスメッセージの除外は列挙方式です（上の「会話監視 hook は手動で有効化」）
- 送信禁止の語の検査はキーワード判定です。言い換えた機密は通ります
- 検証は作者の環境での小規模な試行です（異常ヒントの判定 20 件で外れ 0 件。会話監視 hook と成功条件カバー判定は件数が少なく評価中）。保証ではありません

**詳細:** 実験版の入口は [`experimental/jev/README.md`](experimental/jev/README.md)。機能ごとの違い・検証結果・試す人向けの確認観点は [`experimental/jev/skills/ai-plc-jev/README.md`](experimental/jev/skills/ai-plc-jev/README.md)、キー・環境変数・`.gitignore` に足す行は [`experimental/jev/scripts/README_jev.md`](experimental/jev/scripts/README_jev.md)。試した結果の報告は Issue で歓迎します。

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

壊しません。更新対象はtransaction内で`.bak.<timestamp>.<sequence>`へ退避し、`CLAUDE.md`/`AGENTS.md`は環境別managed markerで**マージ**します。Codexのmarkerは`<!-- AI-PLC CODEX START/END -->`です。`--dry-run`で事前確認し、環境を指定した`./uninstall.sh`で除去できます。

更新のときも同じです。AI-PLC が配ったファイルを自分で編集していた場合、installer は何も書き換えずに止まります。`--backup-modified` を付けると、編集したファイルを `.bak` に残してから更新します（Codex だけの指定では使えません）。手順と戻し方は [アップデート手順](#-アップデート手順) を見てください。
</details>

<details>
<summary><b>Q. Cursor でコマンドが出てこない</b></summary>

**Cursorをリロード**してください（コマンドの読み込みに必要）。起動は **`/01-collection`**（スラッシュ）です。`@` はファイル/シンボルのメンション用なので、コマンド起動には使いません。
</details>

<details>
<summary><b>Q. インストール直後、同じスレッドでCollectionが出てこない</b></summary>

Claude CodeとCodexでは、インストール直後のSkill・command追加が現在のチャット／スレッドへ反映されないことがあります。**対象プロジェクトで新しいチャット／スレッドを開始してから**、Claude Codeは`/01-collection`、Codexは`$01-collection`を呼び出してください。それでも見つからない場合はアプリを再起動します。Cursorはウィンドウをリロードして新しいチャットから試します。
</details>

<details>
<summary><b>Q. CodexでAI-PLC Skillが見つからない</b></summary>

対象プロジェクトに`.agents/skills/ai-plc/01-collection/SKILL.md`があること、別のリポジトリを開いていないことを確認してください。明示起動は **`$01-collection`** です。配置済みでも候補に出ない場合は、新しいスレッドを開始し、それでも出なければCodexを再起動します。Claude Code/Cursor用の`/01-collection`とは起動形式が異なります。
</details>

<details>
<summary><b>Q. Codex Pluginとしてインストールするの？</b></summary>

現時点の完成範囲は、このGitHubリポジトリのShell installerでプロジェクト共有Skillと`AGENTS.md`を配置する方式です。Codex Plugin化は将来候補であり、今回のinstallerには含まれません。
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

環境を指定して実行します。Codexだけなら`./uninstall.sh --target /path/to/your/project codex`、3環境すべてなら末尾を`all`にします。変更済みのmanaged fileや`wiki/`・`db/`などのユーザーデータは保持され、残存物がある場合はmanifestがdetached状態として記録します。
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

**Claude Code:** `.claude/skills/`・`.claude/rules/`・`.claude/commands/`・`.claude/agents/`・`CLAUDE.md`/`AGENTS.md`のmanaged region・`.claude/wiki/`・`.claude/db/`

**Cursor:** `.cursor/skills/`・`.cursor/rules/*.mdc`・`.cursor/wiki/`・`.cursor/db/`

**Codex:** `.agents/skills/ai-plc/`・`.agents/skills/utility/`・`AGENTS.md`のCodex managed region。AI-PLCの共通Rules・DB・Wikiは`.claude/`互換runtimeを共有しますが、Claude Codeのnative memoryは読み書きしません。

- 既存のmanaged外本文、変更済みfile、wiki、DB、成果物は保持
- `AGENTS.md`は環境別markerで統合し、Claude CodeとCodexが共存可能
- `--dry-run`で事前確認、`--plan-only`で機械可読planを出力
- 旧版（台帳のない v1.1.0〜v1.6.0）は中身から自動で判別して更新。自分で編集したファイルがあれば止まり、`--backup-modified` で `.bak` に退避して進める（[アップデート手順](#-アップデート手順)）
- manifestのowner情報に基づいて環境別にuninstall

```
ai-plc/
├── install.sh / install-cc.sh / install-cursor.sh / install-codex.sh / uninstall.sh
├── core/
│   ├── skills/ai-plc/     # 4ステージスキル + テンプレート
│   ├── skills/utility/    # spec-story-starter / wire-aa-authoring
│   ├── skills/plc-*/      # plc-db-sync / plc-registry / plc-status-audit / plc-viewer / plc-consult / plc-backfill
│   ├── rules/             # system / session / adaptive
│   └── db/                # init_db.py / plc_query.py / sync.py
├── claude/                # Claude Code固有（commands / agents / templates）
├── cursor/                # Cursor固有（.mdc rules）
├── codex/                 # Codex adapter Skills / AGENTS template
├── lib/                   # transaction・owner対応の共通installer実装
├── templates/             # soul.md / wiki
├── examples/kotonoha/     # 試せるサンプル
├── experimental/jev/      # 実験版（--with-jev のときだけ入る。Claude Code 専用）
├── experimental/registry-viewer/  # Registry ビューア（アルファ版。installer 対象外・手でコピー）
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
