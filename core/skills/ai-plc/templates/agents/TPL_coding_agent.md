> 🏷️ **Type:** template (agent generation) — コード生成・リファクタリング・機能実装タスクのAgent定義生成用

原則: 「計画→承認→実行」の2部構成。Part 1で計画を立て承認を得てからPart 2で実行する。計画なしにコードを生成しない。

## Agent定義の標準構造

- Goal: 「[Feature/Component]のコードを設計・実装し、テスト可能な状態にする」
- Input: 要件定義/User Stories、既存コードベース情報（Brownfield時）、アーキテクチャ設計、NFR要件（opt-in）、SubLayer定義（分割時）
- Output: コード生成計画（チェックボックス付き）、実装コード（ロジック+API+テスト）、テスト指示書、ドキュメント
- frontmatter（必須）: name（kebab-case）/ description / tools（最小権限）/ delegable（FlowにMob CPを含むならfalse）を先頭に付与（03-construction v2.1）

## Execution Flow

### Part 1: Planning

| Step | タイプ | アクション |
| --- | --- | --- |
| 1. Context分析 | Autonomous | SubLayer設計成果物を読み込み、依存関係・インターフェースを特定 |
| 2. コード生成計画 | Autonomous | 実装ステップをチェックボックス付きで列挙: ①構造セットアップ ②ビジネスロジック+テスト ③APIレイヤー+テスト ④リポジトリレイヤー+テスト ⑤フロントエンド+テスト（該当時）⑥DBマイグレーション（該当時）⑦ドキュメント ⑧デプロイアーティファクト |
| 3. 計画承認 | Mob | 計画のレビュー・承認。変更要求があれば修正 |

### Part 2: Generation

| Step | タイプ | アクション |
| --- | --- | --- |
| 4. ステップ実行 | Autonomous | 計画の各ステップを順次実行し、完了ごとに [x] を付ける |
| 5. 進捗更新 | Autonomous | 進捗を記録。Brownfieldでは重複ファイルがないか検証 |
| 6. コードレビュー | Mob | 生成コードのレビュー。変更要求 or 承認 |
| 7. 完了報告 | Autonomous | 実装サマリー + 次ステップ案内（統合テスト or 次SubLayer） |

深度別のスキップ（adaptive §1連動）: Simple=計画承認を省略し直接Code Gen→テスト / Standard=NFR Assessmentを省略 / Complex=フルループ（NFR・Infrastructure含む）。

## Guardrails

- コード配置: アプリケーションコードはワークスペースルート、ドキュメントは成果物ディレクトリ。Brownfieldは既存構造（`src/main/java/`等）、Greenfieldは `src/`・`tests/`・`config/`、複数SubLayer時は `{sublayer-name}/src/`
- Brownfield修正: 既存ファイルはin-place修正（コピー禁止）、生成後に重複ファイルがないことを検証
- 計画フェーズ: 番号付きステップ+User Storyトレーサビリティ+SubLayer依存関係を明記し、生成前に明示的な承認を得る
- 実行フェーズ: 計画に書かれたことだけを実行し、ステップ順序から逸脱しない。SubLayer依存関係が満たされた場合のみ実行
- UIテスト対応: インタラクティブ要素に `data-testid`（`{component}-{element-role}` 命名、動的ID禁止）
