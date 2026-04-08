# AI-PLC — AI Product Lifecycle Pipeline

PMBOKの知識体系をAIエージェント向けに再設計した**4ステージパイプライン**。  
Claude Code / Cursor の両環境にインストールでき、既存の設定を壊しません。

## パイプライン概要

```
Collection → Inception → Construction → Operation
(Goal設定)    (タスク分解)  (スキル生成)    (実行・成果物)
```

| Stage | 名称 | 概要 |
|-------|------|------|
| 1 | **Collection** | Goal設定・Context収集・Execution Context確立 |
| 2 | **Inception** | Goal分析・再帰的分解・Backlog生成 |
| 3 | **Construction** | 実行スキル生成・Agent定義 |
| 4 | **Operation** | タスク実行・成果物生成・知見伝播 |

## クイックスタート

### Claude Code

```bash
git clone https://github.com/YOUR_USER/ai-plc.git
cd ai-plc
./install-cc.sh --target /path/to/your/project
```

### Cursor

```bash
git clone https://github.com/YOUR_USER/ai-plc.git
cd ai-plc
./install-cursor.sh --target /path/to/your/project
```

### 両方同時

```bash
./install.sh --target /path/to/your/project both
```

### dry-run（確認のみ）

```bash
./install-cc.sh --dry-run --target /path/to/your/project
```

## インストール内容

### Claude Code

| 配置先 | 内容 |
|--------|------|
| `.claude/skills/ai-plc/` | 4ステージスキル + テンプレート群 |
| `.claude/rules/ai-plc-*.md` | システム・セッション・Adaptiveルール |
| `.claude/commands/` | スラッシュコマンド（sense, focus, deliver, status, daily） |
| `.claude/agents/` | エージェント定義（researcher, reviewer, analyst, syncer） |
| `CLAUDE.md` | AI-PLCセクションをマージ（既存保持） |
| `AGENTS.md` | AI-PLCセクションをマージ（既存保持） |
| `.claude/soul.md` | AI行動原則テンプレート（新規のみ） |
| `.claude/user.md` | ユーザーモデルテンプレート（新規のみ） |
| `.claude/memory.md` | メモリポインタ（新規のみ） |
| `.claude/wiki/` | Knowledge Wiki初期構造（新規のみ） |

### Cursor

| 配置先 | 内容 |
|--------|------|
| `.cursor/skills/ai-plc/` | 4ステージスキル + テンプレート群 |
| `.cursor/rules/ai-plc-*.mdc` | MDCフォーマットのルール（alwaysApply） |

## 安全性

- **既存ファイルは上書きしません** — バックアップ（`.bak.YYYYMMDD`）を作成してから更新
- **CLAUDE.md / AGENTS.md はマージ** — `<!-- AI-PLC START/END -->` マーカーで管理
- **テンプレートファイルはスキップ** — `soul.md`, `user.md` 等は既存がなければのみ配置
- **dry-runモード** — `--dry-run` で事前確認可能
- **アンインストール可能** — `./uninstall.sh` で配置ファイルを除去

## ディレクトリ構造

```
ai-plc/
├── install.sh               # ユニバーサルインストーラ
├── install-cc.sh             # Claude Code用
├── install-cursor.sh         # Cursor用
├── uninstall.sh              # アンインストーラ
├── .ai-plc-version           # バージョン情報
├── LICENSE                   # MIT License
│
├── core/                     # コアファイル（環境共通）
│   ├── skills/ai-plc/        # 4ステージスキル + テンプレート
│   └── rules/                # 3つのルールファイル
│
├── claude-code/              # Claude Code固有
│   ├── CLAUDE.md.template
│   ├── AGENTS.md.template
│   ├── commands/             # スラッシュコマンド
│   └── agents/               # エージェント定義
│
├── cursor/                   # Cursor固有
│   └── rules/                # .mdcフォーマットルール
│
├── templates/                # ジェネリックテンプレート
│   ├── soul.md, user.md, memory.md
│   └── wiki/
│
└── docs/                     # ドキュメント
    └── ARCHITECTURE.md
```

## コア原理

| 原理 | 説明 |
|------|------|
| **Context Cascade** | 親→子スコープへの3分類コンテキスト伝播（immutable / overridable / local） |
| **Fractal Decomposition** | Goalの再帰的分解とSub-Agent Scope生成 |
| **Adaptive Workflow** | Simple / Standard / Complex の3段階深度自動判定 |
| **Self-Describing Task** | コンテキスト付きタスク委譲構造 |

## カスタマイズ

インストール後、以下のファイルをプロジェクトに合わせて編集してください:

1. **`.claude/soul.md`** — AIの行動原則・アイデンティティ
2. **`.claude/user.md`** — あなたのプロフィール・好み
3. **`CLAUDE.md`** — プロジェクト固有の設定を追記

## アンインストール

```bash
./uninstall.sh --target /path/to/your/project
```

`soul.md`, `user.md`, `memory.md`, `wiki/` はカスタマイズ済みの可能性があるため削除されません。

## License

MIT License — See [LICENSE](LICENSE) for details.
