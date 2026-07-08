---
name: spec-story-starter
description: 議論・議事録・選定された施策を起点に、対象リポジトリの実構造にgroundした「エンジニア向け Story（User Story + Acceptance Criteria）と Spec（技術仕様）」をSubagentで収束生成する。target_repoで対象コードベースを、backlog_db_urlで起票先バックログを選べる汎用スキル。抽象的な打ち手を実装可能な仕様へ絞り込む収束フェーズの実行に使う。
---

# spec-story-starter — Feature Story & Spec Starter（汎用・Subagent収束型）

議論／議事録／選定済み施策を起点に、**対象リポジトリの実構造にgroundした Story + Spec** を生成し、指定バックログに起票（またはローカル出力）する。特定ツール連携の専用版スキル（v1.1）を、任意リポジトリ・任意バックログに向けられる汎用スキルへ翻案したもの。

**収束の中核:** 抽象的な施策（「補充リマインドをやる」）を、複数Subagentで「既存コードのどこに何を実装するか」まで**絞り込む**。発散（広げる）の対に位置する収束（実装可能な1形に落とす）フェーズを担う。

## When to Use

- 発散・選定フェーズで決まった施策を、エンジニアに渡せる仕様に落としたいとき
- Chat/議事録の機能議論を、Story（受け入れ基準付き）とSpec（技術仕様）に一気に構造化したいとき
- 既存の簡素なStoryを、対象リポジトリの実装文脈で詳細化したいとき

## 入力インターフェース

| 入力 | 必須 | 説明 |
|------|------|------|
| `source` | ✅ | 起点。選定ドキュメント／議事録ページ／Chat議論／既存Story。パス・URL・直近会話のいずれか |
| `feature_label` | ✅ | 機能名（例: `補充リマインド配信`） |
| `target_repo` | ⭕ | **仕様をgroundする対象リポジトリのパス**。指定するとそのコード構造を読んで実装箇所を特定。未指定＝カレントリポ or repo探索スキップ（構造非依存の一般Specになる） |
| `backlog_db_url` | ⭕ | **起票先バックログDB**（Notion DB URL / ローカルbacklogパス）。指定時はそこにStory行を起票。未指定＝ローカル `<出力先>/Story.md` に出力 |
| `spec_output` | ⭕ | Spec出力先（ローカルファイルパス / Specs DB URL）。未指定＝`<出力先>/Spec.md` |
| `detail_level` | ⭕ | `lean` / `standard`(既定) / `deep`。Story/Spec同一粒度 |

出力先が未指定の場合は `Flow/[YYYYMM]/[YYYY-MM-DD]/[feature_label]/` を既定とする。

## 処理フロー（Subagent収束）

```
source ──▶ P1 要旨抽出
                │
                ▼
        P2 repo探索(Subagent①) ── target_repoの構造・接続点・既存パターンを地図化
                │  (target_repo未指定ならスキップ)
                ▼
        P3 Story骨子 + Spec章立て 提案 ──▶ P4 Mob CP(停止・承認)
                                                │ OK
                                                ▼
        P5 並列収束: Story起草(Subagent②) ∥ Spec起草(Subagent③)  ← ともにP2の地図をground情報として受領
                                                │
                                                ▼
        P6 整合レビュー(Subagent④ / maker≠checker) ── Story⇔Spec整合・repo実現可能性
                                                │
                                                ▼
        P7 出力/起票(backlog_db_url or ローカル) ─▶ P8 Verification ─▶ P9 完了報告
```

### Phase 1: 要旨抽出

`source` から抽出: **課題(Why)** / **背景** / **成功条件(Acceptance想定)** を3〜5行に要約。selectされた施策なら「なぜこの施策か」の根拠も拾う。

### Phase 2: repo探索（Subagent①・target_repo指定時）

`target_repo` を Agent tool（Subagent, tools: Read/Glob/Grep）で探索させ、以下を含む **grounding map** を返させる:

- feature が触るレイヤ/ファイル（entities / repositories / services / components / infra 等）
- 追加すべき箇所（新規ファイル vs 既存拡張）と、その根拠となる既存パターン
- 依存する外部クライアント（例: LINE/メール/決済クライアント）
- 命名・構造の既存規約（新Specがそれに従うため）

**プロンプト骨子:** 「このリポジトリで機能『[feature_label]』を実装するなら、どのファイルに何を足すか。既存の構造・命名規約に沿って、touch pointsをファイルパス付きで列挙。要旨: [P1]」

target_repo未指定時はP2をスキップし、構造非依存の一般Specとして続行（その旨をP4で明示）。

### Phase 3: Story骨子 + Spec章立て 提案

- **Story骨子:** `As a / I want / So that` + Acceptance Criteria 3〜5個
- **Spec章立て:** 概要 / 対象ユーザーストーリー / 画面 or API / データモデル / インタラクション / バリデーション・エラーケース / **実装箇所（P2の grounding mapを反映：どのファイルに何を足すか）** / ガードレール

### Phase 4: Mob Checkpoint — 骨子承認（停止）

🚨 必ず停止し応答を待つ。骨子（Story + Spec章立て + 実装箇所サマリ）を提示し、🙋承認待ちブロック（OK / 修正 / 差し戻し）を出す。target_repo未指定ならその旨も明示。

### Phase 5: 並列収束（Subagent② ∥ ③）

承認後、**2つのSubagentを並列**で走らせる（Agent tool・同時2発）:

- **Subagent② Story起草:** User Story + Acceptance Criteria（チェックボックス形式）+ 背景/期待効果。detail_levelに従う
- **Subagent③ Spec起草:** P3章立てを本文化。**P2の grounding mapを必ず入力に含め**、「実装箇所」章は実ファイルパスで書く。detail_levelに従う

両Subagentに同じ grounding map と骨子を渡し、記述粒度・用語を揃えるよう指示する（収束＝1つの整合した仕様へ）。

### Phase 6: 整合レビュー（Subagent④ / maker≠checker）

起草した Story と Spec **のみ**を、作成文脈を渡さない独立Subagentに検証させる:

- Story⇔Spec の整合（AC と Spec の対応、粒度の一致）
- target_repo に対する**実現可能性**（存在しないファイル/構造を前提にしていないか）
- 欠落（バリデーション・エラーケース・非機能）
- 出力: P0-P3 フラットリスト or 「No findings」

P0/P1は修正してP5成果物に反映（必要ならP5の該当Subagentを再実行）。

### Phase 7: 出力・起票

- **`backlog_db_url` 指定あり:**
  - Notion DB URL → notion-cli / nsync で Story行を起票（Feature=feature_label / Status=Backlog / Priority / 本文=Story）。Spec は `spec_output`（Specs DB or ローカル）へ。両者を相互リンク
  - ローカルbacklogパス → その backlog.yaml / ディレクトリに Story を追記・作成
- **`backlog_db_url` 指定なし:** `<出力先>/Story.md` と `<出力先>/Spec.md` を作成し、相互に相対リンク

いずれも Story本文の冒頭に対応Spec参照、Spec冒頭に対応Story参照を置く。

### Phase 8: Verification

Story/Spec が存在・双方向リンク成立・（target_repo指定時）実装箇所が実在ファイルを指すこと・AC が検証可能な粒度か、を確認しチェックリスト出力。

### Phase 9: 完了報告（Next Action Protocol）

成果物パス（Story/Spec）＋起票先＋レビュー結果を報告。Next Action: A=Story段階分け（Tier化）/ B=デザイン下書き / C=別Feature起票。

## Subagent役割まとめ（収束の見せ場）

| # | Subagent | 入力 | 出力 | tools |
|---|----------|------|------|-------|
| ① | repo探索 | target_repo, 要旨 | grounding map（touch points） | Read/Glob/Grep |
| ② | Story起草 | 骨子, grounding map | Story本文 | Read/Write |
| ③ | Spec起草 | 章立て, grounding map | Spec本文 | Read/Write |
| ④ | 整合レビュー | Story+Spec（文脈なし） | P0-P3 findings | Read/Glob/Grep |

②③を並列 → ④で収束、という流れが「複数の視点を1つの実装可能な仕様に絞り込む」収束フェーズの体現になる。

## ガードレール

- **Mob CP（P4）は必ず停止**。承認なしにP5へ進まない
- Spec の「実装箇所」は target_repo に実在するパスのみを指す（探索結果に無い構造を捏造しない）
- レビュー（P6）は作成文脈を渡さない独立Subagentで行う（maker≠checker）
- `.env`・秘密情報を生成/参照しない。target_repo に書き込まない（読むだけ）
- backlog_db_url へ起票する前に、同名Story重複を確認（存在時はsuffix提案）

## 使用例

```
/spec-story-starter
source: @T004_施策選定_意思決定.md
feature_label: 補充リマインド配信
target_repo: examples/kotonoha/store
backlog_db_url: （未指定=ローカルStory.md/Spec.md出力）
detail_level: standard
```

```
/spec-story-starter
source: @議事録_XXX
feature_label: 条件分岐ノード
target_repo: <your-repo>/path/to/product-repo
backlog_db_url: https://notion.so/.../ProductBacklog-DB
```

---
**作成日:** 2026-07-08 ｜ **由来:** 特定ツール連携の専用版スキル（v1.1）の汎用・ローカル・Subagent収束型翻案
