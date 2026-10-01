---
name: 03-construction
description: ai_plc_construction - AI-PLC Stage 3。Agent 定義が要るタスク（RUL_plc_adaptive §6）に対して実行可能なスキル定義と実行計画を生成する。
---

# AI-PLC Stage 3: Construction

Backlogの各タスクに対して実行可能なAgent定義を生成するステージ。既存テンプレート（templates/agents/TPL_*）とタスク固有コンテキストを組み合わせる。

**共通規約:** 命名は RUL_plc_system §6 / 完了報告は RUL_plc_session §7 / Phase遷移通知は §8 / Mob CP出力は §9 に従う。

**呼ぶ条件:** RUL_plc_adaptive §6 の条件に当たるときだけ通す。生成するのは backlog の `construction.tasks` のタスクだけ（Layer 単位の条件＝complex・platform_builder・`construction_mode: always` のときは、Inception が command のある全タスクをそこに書いている）。

**自動完走モード:** セッション中に RUL_plc_session §10 を指す /goal があるときは §10 に従い、Mob Checkpoint・Next Action・タスク選択で待たずに進める（無ければ本 SKILL のとおり止まる）。

## 入力

| 入力 | 必須 | 説明 |
| --- | --- | --- |
| Backlog | ✅ | Stage 2で生成されたbacklog.yaml |
| Agent Template Library | ⭕ | templates/agents/ 配下のTPL_* |
| Existing Agents | ⭕ | 過去に生成された再利用可能なAgent定義群 |
| Task | ⭕ | 指定時はそのタスクのみ生成（未指定=一括生成モード） |

## 実行フロー

### Phase 1: Backlog読み込み + ティア判定

backlog.yamlを読み込み、各タスクのcommand / command_template_ref を確認し、typeからAgent定義ティアを自動判定する（ユーザー指定優先）:

- **Lite**（design / research / content / planning）: Goal + Input + Output + Guardrails の4セクション。Execution FlowとInstructionsはテンプレートから暗黙適用し、Guardrails内に独立レビュー契約を必ず含める
- **Full**（implementation / validation / complex / coding）: 全6セクション（Goal / Input / Output / Execution Flow / Guardrails / Agent Instructions）

commandフィールドがないタスクはスキップする。

### Phase 2: Template探索

3段階で探索する: ①templates/agents/のTPL_* ②既存Agents/の過去定義 ③ドメイン知識テンプレート。テンプレートが見つかれば必ずコピーして使用する。

コーディングPJではTPL_coding_agent / TPL_review_agentが選択され、生成AgentのFlow内に機能設計→Code Gen→Build & Testが組み込まれる（特別フェーズは不要。SubLayerは通常どおり4ステージを再帰展開）。

### Phase 3: 生成計画 + Agent一括生成

1. 各タスクに最適なテンプレートを特定し、ティアに応じたAgent定義を生成して `Agents/` に配置する
2. Task未指定時は `construction.tasks` のタスクを一括生成（Mob CPは1回のみ）。Task指定時は単体生成
3. Agent定義はHITL統合型（Autonomous Phase + Mob Checkpoint交互）を標準構造とし（delegable: true のタスクは4項のとおり Autonomous-only）、実行可能な詳細度で書く
4. **Subagent互換frontmatterを全AGTに付与する**: `name`（kebab-case）/ `description` / `tools`（最小権限。reviewer系はWrite/Edit除外）/ `delegable`（backlog の `delegable` の値を写す。backlog が正。true のタスクは Mob Checkpoint を挟まない Autonomous-only で生成する）。Guardrailsに「変更禁止ファイル」欄（backlog.yaml / context.yaml / intent.yaml / sqlite / rules / SKILL等）を必ず含める。返り値規約は 04-operation Phase 4 に従う — AGT本文はそのままAgent toolのpromptに渡せる自己完結指示書にする
5. **独立レビュー契約:** 04-operation Phase 5.5 に従う（Guardrails には『独立レビュー: 04-operation Phase 5.5 に従う』の1行だけ書く）。生成した AGT のパスは backlog の該当タスクの `command_template_ref` に書く
6. 生成中にスコープ外タスク（別チーム作業の前提・別システムでの実装要求・スコープ外の改善点）を発見したら、Self-Describing Task構造（RUL_plc_system §9）でチケット化し「外部DBに書き出しますか？」と確認→承認後push
7. 結果をユーザーに提示する:

```
【発見されたテンプレート・参考Agent】[一覧]
【生成対象Agent】
✅ [TaskID]: AGT_[タスク名] — ティア / 参考: [テンプレート名] / Goal: [概要]
⏭️ [TaskID]: [タスク名]（commandなし → スキップ）
```

### Phase 4: Mob Checkpoint — 生成結果確認（停止）

ここで必ず停止し、承認を待つ: 生成Agent一覧（ティア・参考TPL・Goal概要）を提示し、🙋承認待ちブロック（OK / 修正: [指示] / 差し戻し）を出力。修正指示があれば反映して再提示する。

### Phase 5: Mob Checkpoint — 次ステージ提案（停止）

RUL_plc_session §7 の4パートを出力して停止する。Next Action: A=/04-operation でP0タスク実行（⭐推奨） / B=タスク一覧・Agent定義確認（表記は §7.4「実行形式は環境の正」）。

## Agent定義の標準構造

| セクション | 内容 |
| --- | --- |
| Goal | このAgentが達成すること（成功基準） |
| Input | 必要な入力データ・コンテキスト |
| Output | 生成される成果物（完了判定基準） |
| Execution Flow | Phase構造（Autonomous + Mob Checkpoint） |
| Guardrails | 各Phaseの品質保証条件 + type別の独立レビュー契約 |
| Agent Instructions | Stage 4実行時のAI指示 |

全ティア共通でfrontmatter（name / description / tools / delegable）を付与する（Phase 3の4項参照）。

## 出力

Agents/ 配下のAgent定義群 → Stage 4: SKL_plc_04_operation へ。Exit条件: `construction.tasks` の全タスクに Agent 定義が存在すること。

---
**作成日:** 2026-04-07 ｜ **更新日:** 2026-10-01 ｜ **バージョン:** 2.3（冒頭に自動完走モードの1行〔RUL_plc_session §10〕／Construction は要るときだけ通し、生成対象は backlog の construction.tasks・delegable は backlog の値を写す・独立レビュー契約は 04-operation Phase 5.5 に一本化〔RUL_plc_adaptive §6〕）｜ 2.2（全AGTへ独立レビュー契約を埋め込み、`delegable`とreviewer起動を分離。2.1: AGT-Subagent互換化: frontmatter必須化・変更禁止欄・返り値規約）
