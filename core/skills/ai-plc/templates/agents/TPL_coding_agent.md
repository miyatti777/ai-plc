> 🏷️ **Type:** template (agent generation)

  **CC対応:** `.claude/skills/templates/coding_agent.md`

  **AI-DLC参照:** `construction/code-generation.md`（Part 1: Planning → Part 2: Generation）

  **役割:** コード生成・リファクタリング・機能実装タスクのAgent定義を生成する際のテンプレート

---

## 対象タスク例

- 新機能のコード実装（Greenfield / Brownfield）
- 既存コードのリファクタリング
- API設計・実装
- フロントエンドコンポーネント実装
- データベースマイグレーション
- バグ修正（複雑なもの）

---

> 🚨 **最重要原則: 「計画→承認→実行」の2部構成**


  [AI-DLCのcode-generation.md](http://xn--ai-dlccode-generation-0m4t.md/)に準拠。


  Part 1で計画を立て承認を得てから、Part 2で実行する。


  計画なしにコードを生成しない。

---

## Agent定義の標準構造

### Goal

「[Feature/Component Name]のコードを設計・実装し、テスト可能な状態にする」

### Input

- 要件定義 / User Stories（何を実装するか）
- 既存コードベース情報（Brownfieldの場合）
- アーキテクチャ設計（Application Design成果物）
- NFR要件（パフォーマンス・セキュリティ等、opt-in）
- SubLayer定義（複数SubLayerに分割する場合）

### Output

- **コード生成計画**（チェックボックス付きステップリスト）
- **実装コード**（ビジネスロジック + API + テスト）
- **テスト指示書**（unit / integration / e2e）
- **ドキュメント**（README更新、API docs）

---

## Execution Flow（SubLayer内の4ステージ再帰展開）

### Part 1: Planning（SubLayer内 Inception → Construction）

| Step | タイプ | アクション | 出力 |
| --- | --- | --- | --- |
| 1. Context分析 | Autonomous | SubLayer設計成果物を読み込み、依存関係・インターフェースを特定 | Context分析結果 |
| 2. コード生成計画 | Autonomous | 実装ステップを明示的に列挙（チェックボックス付き）:
① プロジェクト構造セットアップ
② ビジネスロジック生成 + テスト
③ APIレイヤー生成 + テスト
④ リポジトリレイヤー生成 + テスト
⑤ フロントエンド生成 + テスト（該当時）
⑥ DBマイグレーション（該当時）
⑦ ドキュメント生成
⑧ デプロイアーティファクト | コード生成計画書 |
| 3. 計画承認 | Mob | 計画のレビュー・承認を得る。変更要求があれば計画を修正 | 承認済み計画 |

### Part 2: Generation（SubLayer内 Operation）

| Step | タイプ | アクション | 出力 |
| --- | --- | --- | --- |
| 4. ステップ実行 | Autonomous | 計画の各ステップを順次実行。完了したらチェック [x] を付ける | コード + テスト |
| 5. 進捗更新 | Autonomous | 各ステップ完了後に進捗を記録。Brownfieldでは重複ファイルがないか検証 | 進捗レポート |
| 6. コードレビュー | Mob | 生成コードのレビュー。変更要求 or 承認 | フィードバック |
| 7. 完了報告 | Autonomous | 実装サマリー + 次ステップ案内（統合テスト or 次SubLayerのCollection開始） | 完了レポート |

---

## Adaptive Skip判定（AI-DLC準拠）

| 深度 | 判定条件 | スキップ対象 | 実行するステップ |
| --- | --- | --- | --- |
| Simple | 単純バグ修正・小さな変更 | Functional Design, NFR, 計画承認 | 直接Code Generation → テスト |
| Standard | 機能追加・中規模変更 | NFR Assessment | Functional Design → Code Gen Plan → 承認 → 実行 |
| Complex | 新サービス・大規模変更 | なし（フルループ） | Functional Design → NFR → Infrastructure → Code Gen → Build & Test |

---

## Critical Rules（AI-DLCから移植）

### コード配置ルール

- **アプリケーションコード**: ワークスペースルートに配置（成果物ディレクトリには置かない）
- **ドキュメント**: 成果物ディレクトリに配置（マークダウンのみ）
- Brownfield: 既存構造を使用（`src/main/java/`, `lib/`, `pkg/`等）
- Greenfield単体: `src/`, `tests/`, `config/`
- Greenfield複数SubLayer（マイクロサービス）: `{sublayer-name}/src/`, `{sublayer-name}/tests/`

### Brownfieldファイル修正ルール

- ファイルが存在する場合: in-place修正（コピーを作成しない）
- ファイルが存在しない場合: 新規作成
- 生成後に重複ファイルがないことを検証

### 計画フェーズルール

- 全生成活動について明示的で番号付きのステップを作成
- User Storyトレーサビリティを含める
- SubLayerコンテキストと依存関係を文書化
- 生成前にユーザーの明示的な承認を得る

### 実行フェーズルール

- **ハードコードロジック禁止**: 計画に書かれたことだけを実行
- **計画に厳密に従う**: ステップ順序から逸脱しない
- **チェックボックス更新**: 各ステップ完了後すぐに [x] を付ける
- **依存関係尊重**: SubLayer依存関係が満たされた場合のみ実行

### UI自動テスト対応ルール

- インタラクティブ要素に `data-testid` を追加
- 一貫した命名: `{component}-{element-role}`
- レンダー間で変わる動的IDを避ける

---

## 環境別実現

| 環境 | 計画 | 実行 | 成果物 |
| --- | --- | --- | --- |
| Notion | PJ配下にコード生成計画ページ作成 | チャットベースで逐次実行 | Documentsに保存 |
| Claude Code | aidlc-docs/construction/plans/ に計画ファイル | Task/Subagentとして並列実行 | ワークスペースルートにコード |
| Cursor | .cursor/rules/ に計画ルール | Agent Modeで実行 | ワークスペースルートにコード |

---

**作成日:** 2026-04-08

**AI-DLC参照:** `aidlc-workflows/construction/code-generation.md`

**ステータス:** Active