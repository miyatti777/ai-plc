# サンプル: コトノハストア（AI-PLC 発散→収束→仕様化を試す）

> 🏷️ **Project:** コトノハストア（架空デモ） / **Type:** memo / **Context:** AI-PLC公開リポの「その場で試せる」練習用サンプル一式

架空のD2Cライフスタイル雑貨EC「**株式会社コトノハ**」を題材に、AI-PLCの
**発散（施策を広げる）→ 収束（Story+Specに絞る）→ 仕様化（ワイヤフレーム）** を
自分の手で一周体験できるサンプルです。登場する社名・人物・数値はすべて架空です。

## 同梱物

| フォルダ | 中身 | 役割 |
| --- | --- | --- |
| `context/` | 会社概要・今QuarterのOKR・コンテキスト収集MTG議事録・現状データ/ベンチマーク（4本） | 発散の入力。ここから施策を考える |
| `kotonoha-store/` | 対象ECアプリのDDD骨格（entities→repositories→services→components→stores + infra stub） | 収束の接地先。「どのファイルに実装するか」を指せる構造 |
| `kotonoha-backlog/` | プロダクトバックログ `board.md` ＋ 既存Story 3本（ST-KTN-001〜003）＋ `TEMPLATE_story.md` | Storyの置き場所と書式。あなたが作るStoryはここに増える |

### このサンプルに「答え」は入っていません

発散の結論となる本命施策の **完成済みStory / Spec / ワイヤフレームは意図的に同梱していません**。
参加者がその場で生成する体験にするためです。提供するのは
**事業コンテキスト・対象repo・既存backlog（3 story）・施策の"入口"まで**。
③まで走らせると、あなたのbacklogに新しいStoryとSpec、ワイヤフレームが生まれます。

---

## 試す3ステップ

前提: このリポジトリを開いた状態で、AI-PLC のスキル（スラッシュコマンド）を使います。
以下のコピペ用プロンプトは `examples/kotonoha/` を基準にした相対パスで書いてあります。

### ① 発散 — 事業コンテキストとOKRから施策を広げて選ぶ

`context/` を読み込ませ、OKRに効く施策を発散 → 加重スコア等で1本に絞ります。
（AI-PLCの Collection/Inception を使ってもよいし、まず素の対話で発散してもOK）

コピペ例:

```
examples/kotonoha/context/ の4ファイル（会社概要・OKR・議事録・現状データ）を読んで、
今QuarterのObjective「リピート起点でLTVを底上げ」とKR1〜3に効く施策を5〜8個 発散して。
そのうえで、効果 / 実現コスト / 撤退容易性で加重スコアを付けて最有力の1本を選定して。
選定理由と、狙うKR・想定KPIツリー上の位置づけも添えて。
```

### ② 収束 — 選んだ施策を Story + Spec 化する（/spec-story-starter）

選定した施策を、対象リポジトリ `kotonoha-store` の実構造にgroundしたエンジニア向け
**Story + Spec** に収束させます。Storyは `kotonoha-backlog/stories/` に、
既存の `TEMPLATE_story.md` と `board.md` の書式に沿って追加されます。

コピペ例:

```
/spec-story-starter
入力: ①で選定した施策（施策名と選定メモ）
target_repo: examples/kotonoha/kotonoha-store
backlog: examples/kotonoha/kotonoha-backlog（board.md に1行追加し、stories/ に ST-KTN-004 を新規作成）
選定の根拠は examples/kotonoha/context/ を参照。実装参考ファイルは kotonoha-store の実構造から特定して。
```

### ③ 仕様化 — 画面のワイヤフレームを描く（/wire-aa-authoring）

②で作ったStory/Specと `kotonoha-store` を起点に、対象画面の
**現状 → 変更後** をASCIIアートのワイヤフレームで描き、Storyに設計決定ログを追記します。

コピペ例:

```
/wire-aa-authoring
Story: examples/kotonoha/kotonoha-backlog/stories/ST-KTN-004_<②で付けたfeature名>.md
target_repo: examples/kotonoha/kotonoha-store
対象画面は Story/Spec と kotonoha-store/src/components から特定して、
現状→変更後のASCIIワイヤフレームを作成し、Storyに設計決定ログを追記して。
```

---

## 一周し終えたら

- `kotonoha-backlog/board.md` に新しいStory行が増え、`stories/` にStoryファイル、
  必要ならSpec・`wire_aa/` のワイヤフレームが生成されているはずです。
- 別の施策を選び直して②③をやり直すと、収束の当たり外れを比較できます。
- 既存Story（ST-KTN-001〜003）は書式と粒度の参考として残してあります。
