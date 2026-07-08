> 🏷️ **Type:** template (agent generation) — 量産実行・パターン適用系タスクのAgent定義生成用。/04-operation の Platform Builder（platform-builder.md Phase 9-11）で使用

このテンプレートは Phase 9（Production Skill自動生成）で生成される。元のLayerの実行結果から変数化ポイントを抽出し、パラメータ化されたテンプレートとして保存する。

## Agent定義の標準構造

- Goal: 「[Production Skill]を使い、[Variables]を指定するだけで[Artifact]を量産する」
- Input: Production Skill（Phase 9で生成済み）、Variables（Parameter Storeから取得）、Input Data（任意）
- Output: 量産された成果物、Database更新（ステータス・プロパティ）、Evalデータ（品質評価）
- frontmatter（必須）: name（kebab-case）/ description / tools（最小権限）/ delegable（FlowにMob CPを含むならfalse）を先頭に付与（03-construction v2.1）

## Execution Flow（量産実行型）

| Phase | タイプ | アクション | 出力 |
| --- | --- | --- | --- |
| 1. 変数検証 | Autonomous | 必須変数の確認・デフォルト値適用 | 検証済み変数 |
| 2. 実行計画 | Mob | 実行フロー表示・推定所要時間・承認 | 承認済み計画 |
| 3. Runtime Execution | Autonomous | Production SkillのPhase構造に従い実行 | 成果物 |
| 4. Eval Output | Autonomous | 実行結果の記録・品質評価 | Evalデータ |
| 5. 継続判定 | Mob | 次のアイテムを処理するか判定 | 継続 / 完了 |

継続の場合はPhase 1に戻り、変数を更新して繰り返す。

## 変数定義テンプレート

```yaml
variables:
  variable_1:
    name: "[name]"
    type: "string | number | date"
    description: "[説明]"
    example: "[例]"
    required: true | false
    default: "[デフォルト値]"
```

## Guardrails

- 必須変数が全て揃っていることを確認してから実行
- 元のLayerと同じDB構造・ワークフローを使用（型の再現性）
- 各実行結果をEvalデータとして記録
- 品質問題があれば即座に停止して報告

## 起動形式

/04-operation で platform-builder.md の Phase 10 を実行してください

```yaml
Variables:
  target_person: "山田太郎"
  theme: "AIプロダクト開発の極意"
  deadline: "2026-05-01"
```
