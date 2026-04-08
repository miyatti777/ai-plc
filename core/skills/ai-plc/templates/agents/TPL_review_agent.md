> 🏷️ **Type:** template (agent generation)

  **CC対応:** `.claude/skills/templates/review_agent.md`

  **AI-DLC参照:** `construction/build-and-test.md`（Build Instructions + Test Execution + Summary）

  **役割:** コードレビュー・品質チェック・テスト戦略策定タスクのAgent定義を生成する際のテンプレート

  **汎用対応:** v2.0—コーディング以外の成果物レビューにも対応（RUL_plc_system §18-19連動）

---

## 対象タスク例

### コーディング（従来）

- コードレビュー（PR単位 / ファイル単位）
- ユニットテスト設計・実装
- 統合テスト設計・実装
- パフォーマンステスト計画
- セキュリティレビュー
- コード品質監査（Lint / Coverage / 技術的負債）

### 汎用（v2.0で追加）

- 企画書・提案資料の品質レビュー
- ブログ記事・ホワイトペーパーの事実確認・可読性チェック
- DB設計・システム設計の整合性検証
- イベント企画の実現可能性チェック
- 契約書・規約の法務チェック（Extension: legal）

---

> 🚨 **最重要原則: 「テスト指示書を生成する」**


  [AI-DLCのbuild-and-test.md](http://xn--ai-dlcbuild-and-test-gm4s.md/)に準拠。


  レビュー結果は「指摘リスト」ではなく「実行可能なテスト指示書」として出力する。


  unit / integration / performance / security / e2e の各テスト種別ごとに指示書を生成。

---

## Agent定義の標準構造

### Goal

- **コーディング:** 「[Component/Feature]のコードを検証し、品質基準を満たすテスト指示書を生成する」
- **汎用:** 「[成果物名]をRUL_plc_system §18の3層検証 + §19のNFRチェックで検証し、改善指示を生成する」

### Input

**コーディング時:**

- 生成されたコード（Code Generation出力）
- コード生成計画（何を実装したか）
- NFR要件（パフォーマンス・セキュリティ基準、opt-in）
- 既存テストスイート（Brownfieldの場合）

**汎用時:**

- 成果物（企画書・記事・設計書等）
- タスクの複雑度（Simple / Standard / Complex → 検証Level決定）
- ロール固有NFRチェックリスト（TPL_role_*から取得）
- 有効なExtension（intent.yamlから取得）

### Output

**コーディング時:**

- **ビルド指示書**（[build-instructions.md](http://build-instructions.md/)）
- **ユニットテスト指示書**（[unit-test-instructions.md](http://unit-test-instructions.md/)）
- **統合テスト指示書**（[integration-test-instructions.md](http://integration-test-instructions.md/)）
- **パフォーマンステスト指示書**（[performance-test-instructions.md](http://performance-test-instructions.md/)、opt-in）
- **テストサマリー**（[build-and-test-summary.md](http://build-and-test-summary.md/)）

**汎用時:**

- **検証レポート**（L1/L2/L3各レベルの結果 + 改善指示）
- **NFR適合判定**（Pass / Warning / Fail）

---

## Execution Flow（AI-DLC Build & Test準拠）

| Step | タイプ | アクション | 出力 |
| --- | --- | --- | --- |
| 1. テスト要件分析 | Autonomous | プロジェクト分析 → 必要なテスト種別を判定:
  • Unit tests（必須）
  • Integration tests（複数Unit時）
  • Performance tests（NFR要件時）
  • Contract tests（マイクロサービス時）
  • Security tests（opt-in）
  • E2E tests（ユーザーワークフロー時） | テスト戦略 |
| 2. ビルド指示書生成 | Autonomous | ビルドツール・依存関係・環境変数・ビルドコマンドを文書化 | build-instructions.md |
| 3. ユニットテスト指示書 | Autonomous | 実行コマンド・期待結果・カバレッジ目標・失敗時の対処を文書化 | unit-test-instructions.md |
| 4. 統合テスト指示書 | Autonomous | テストシナリオ・環境セットアップ・サービス間テスト・クリーンアップを文書化 | integration-test-instructions.md |
| 5. 追加テスト指示書 | Autonomous | 必要に応じてperformance / security / contract / e2eテスト指示書を生成 | 追加テスト指示書群 |
| 6. テストサマリー生成 | Autonomous | 全テスト結果のサマリーテーブル（テスト数・Pass/Fail・カバレッジ・ステータス） | build-and-test-summary.md |
| 7. レビュー承認 | Mob | テスト指示書のレビュー → Operations（デプロイ）への遷移承認 | 承認 / フィードバック |

---

## テストサマリーテンプレート（AI-DLC準拠）

```javascript
# Build and Test Summary

## Build Status
- Build Tool: [ツール名]
- Build Status: [Success/Failed]
- Build Time: [所要時間]

## Test Execution Summary

| テスト種別 | 総数 | Pass | Fail | カバレッジ | ステータス |
|-----------|------|------|------|-----------|----------|
| Unit      |      |      |      |           |          |
| Integration|     |      |      |           |          |
| Performance|     |      |      |           |          |
| Security  |      |      |      |           | N/A      |
| E2E       |      |      |      |           | N/A      |

## Overall: [Ready / Not Ready] for Operations
```

---

## 権限モデル（AI-DLC reviewerロール準拠）

| 権限 | 値 | 理由 |
| --- | --- | --- |
| bash | true（読み取り系のみ） | テスト実行・ビルド確認に必要 |
| edit | false | レビュアーはコードを直接修正しない |
| write | false | テスト指示書のみ出力（コード修正はcoding_agentが行う） |

---

## 環境別実現

| 環境 | レビュー | テスト指示書 | 成果物 |
| --- | --- | --- | --- |
| Notion | PJ配下にレビューコメントページ | テスト指示書ページを生成 | Documents配下 |
| Claude Code | aidlc-docs/construction/build-and-test/ に指示書 | CLIでテスト実行確認 | テスト結果ログ |
| Cursor | Agent Modeでレビュー | テスト指示をインラインコメント | テスト結果レポート |

---

**作成日:** 2026-04-08

**AI-DLC参照:** `aidlc-workflows/construction/build-and-test.md`

**ステータス:** Active