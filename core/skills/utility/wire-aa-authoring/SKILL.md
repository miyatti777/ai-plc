---
name: wire-aa-authoring
description: Story/Spec と対象リポジトリを起点に、画面UIの「現状」と「変更後」を ASCII Art（AA）ワイヤフレームで描き、Storyに設計決定ログを追記する。target_repoのcomponentを調査して実装状況にground。抽象仕様を"見える画面"まで収束させる可視化フェーズに使う。特定ツール連携の専用版スキルのローカル/汎用翻案。
---

# wire-aa-authoring — WireAA Authoring（汎用・Subagent・ASCII Art）

Story/Spec を起点に、対象リポジトリの component を調査し、画面UIの **現状 → 変更後** を **ASCII Art ワイヤフレーム**（コードブロック）で描く。仕様（文字）を「画面（図）」まで収束させ、エンジニアが実装イメージを掴める状態にする。

**位置づけ:** `spec-story-starter`（施策→Story/Spec）の**次段**。Spec の UI をワイヤフレームで具体化する収束の到達点。

## When to Use

- Story/Spec は出来たが、UIの「現状と変更後」を目に見える形で示したいとき
- 画面変更を伴う機能で、実装前に導線・レイアウトの合意を取りたいとき
- 仕様を、エンジニアが実装着手できる粒度（どのcomponentをどう変えるか＋AA図）まで落としたいとき

## 入力インターフェース

| 入力 | 必須 | 説明 |
|------|------|------|
| `story` | ✅ | 対象Story（パス/参照）。Spec併記があれば一緒に読む |
| `spec` | ⭕ | 対応Spec（未指定ならstoryから辿る/推定） |
| `target_repo` | ⭕ | component調査対象リポジトリのパス。未指定=カレント |
| `screens` | ⭕ | 対象画面（例: `NotificationSettings, MyPage`）。未指定=SpecとStoryから推定 |
| `tier` | ⭕ | `lite`（現状/変更後AA + AC のみ）/ `full`（+ フロー + エラー + 実装参考）。既定 full |
| `update_story` | ⭕ | 既定 true。Storyに概要AA＋設計決定ログを追記 |

## 処理フロー（Subagent収束）

```
story/spec ──▶ P0 Load
                 │
                 ▼
        P1 component調査(Subagent①) ── target_repoの対象画面component・既存UI構造・状態管理を調べ、
                 │                       「既存実装済み/部分/未実装」を判定
                 ▼
        P2 対象画面の特定 + 現状UI把握 ──▶ Mob CP1(停止・対象画面と方針の確認)
                                             │ OK
                                             ▼
        P3 AAワイヤフレーム作図(Subagent②) ── 現状AA / 変更後AA を対で描く（コードブロック）
                                             │
                                             ▼
        Mob CP2 設計論点(決定項目/選択肢/推奨/根拠) ── 停止
                                             │ 決定
                                             ▼
        P4 wire_aaファイル出力 ─▶ P5 Story更新(概要AA+決定ログ) ─▶ P6 Verification ─▶ 完了報告
```

### Phase 0: Load

`story`（+`spec`）を読み、対象機能・画面・AC・変更意図を把握する。

### Phase 1: component調査（Subagent①）

`target_repo` を Subagent（Read/Glob/Grep）で調査し返させる:

- 対象画面の component ファイル（例: `src/components/NotificationSettings.tsx`）と現状の構造
- 使っている状態管理（stores）・呼ぶservice/API
- 「既存実装済み / 部分実装 / 未実装」の判定
- 変更時に触るファイル（component / store / service）

**プロンプト骨子:** 「target_repoで画面『[screen]』の現状UI構造を調べて。component/store/呼ぶserviceをファイルパス付きで。機能『[feature]』を足すならどのcomponentをどう変えるか。」

### Phase 2: 対象画面特定 + 現状UI把握 → Mob CP1（停止）

対象画面と、現状UIの理解（Subagent①の結果）を提示し、作図対象と方針を確認する。🙋承認待ち。

> 📷 キャプチャは使わない（ローカル）。現状UIはcomponentコードから再構成する。

### Phase 3: AAワイヤフレーム作図（Subagent②）

対象画面ごとに **現状AA** と **変更後AA** を対で描く（下記記法）。full時はフロー(mermaid)・AC・エラー・実装参考も。

### Phase 4/5/6/Mob CP2: 決定・出力・Story更新・検証

- **Mob CP2:** 設計論点を「決定項目 / 選択肢 / 推奨 / 根拠」の4カラム表で提示し停止
- **P4:** `<出力先>/wire_aa/[画面名]_wire_aa.md` を作成（現状UI / BE実装状況 / 変更仕様 / フロー / AC / エラー / 実装参考 ＋ 現状AA・変更後AA）
- **P5（update_story）:** Story本文に (1)「対応方針」直下へ**概要AA（現状→変更後の簡潔版）** (2)「設計決定ログ」セクションを追記
- **P6 Verification:** 各wire_aaに現状/変更後AAが描かれ、実装参考パスが target_repo に実在し、Story⇔wire_aa整合、をチェックリスト出力

## AA（ASCII Art）ワイヤフレーム記法

等幅テキストで画面レイアウトを描く。**現状と変更後を必ず対で**並べる。コードブロックで整列を保つ。

```
+----------------------------------+
| 画面見出し                [ 保存 ] |
| +------------------------------+ |
| | ● LINE で受け取る            | |  <- トグル（現状: 個別設定なし）
| | ○ メールで受け取る           | |
| +------------------------------+ |
|          [ 変更を保存 ]          |
+----------------------------------+
```

記法のコツ: (1) `+ - |` で枠線 (2) `[ ... ]` でボタン/入力 (3) `● ○` でトグル/ラジオ (4) `<- <= ↑` で注釈 (5) `★`/`（新規）` で状態 (6) 現状↔変更後を対で。

## ガードレール

- **Mob CP1/CP2 は必ず停止**（走り抜け禁止）
- **現状/変更後のAAワイヤフレームは省略不可**（このスキルの本質。文字記述だけで済ませない）
- 実装参考は target_repo に実在するファイルパスのみ（存在しない構造を捏造しない）
- target_repo は読むだけ（書き込まない）。`.env`・秘密は扱わない
- component調査は2〜3クエリに絞る（過剰探索しない）

## 使用例

`spec-story-starter` が起票した Story/Spec を入力に、その画面をワイヤフレーム化する（収束チェーンの次段）:

```
/wire-aa-authoring
story: <spec-story-starterが起票したStoryのパス（例: examples/kotonoha/backlog/stories/ST-KTN-NNN_*.md）>
spec:  <対応Specのパス>
target_repo: examples/kotonoha/store
screens: NotificationSettings, MyPage
tier: full
```

> ⚠️ story/spec は前段（spec-story-starter）でライブ生成される。事前に用意しない。既存の backlog Story（例: `examples/kotonoha/backlog/stories/ST-KTN-002_*`）を対象に単体実行することも可。

---
**作成日:** 2026-07-08 ｜ **由来:** 特定ツール連携の専用版スキル（v1.1）の汎用・ローカル・Subagent翻案。次段: spec-story-starter → wire-aa-authoring で収束チェーン完成
