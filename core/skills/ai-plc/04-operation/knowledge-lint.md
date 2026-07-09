# Knowledge Lint（04-operation Phase 8 — イベント駆動主/手動発動）

> 発動: イベント駆動（主・状態ベース）/ カレンダー駆動（従）/ 手動指示。通常のタスク実行フローには含めない。
> チェック項目の定義: RUL_plc_system §10

## トリガー（cron前提にしない3択）

1. **イベント駆動（主・推奨）** — 状態ベースで自然発火。以下でOperation Phase 7が1行提案:
   - 概念ページが +5 増えた / CONTRADICTION open が 2件以上たまった
   - **判定の基準点(baseline):** 「+5」は **log.md の直近 `lint` エントリに記録した概念ページ数**との差分で判定する（下記フロー5でページ総数を必ず件数サマリに残す）。lint実績ゼロ（初回）は即発火可。CONTRADICTION openは index.md の⚠️ / log.md の `contradiction` エントリから数える（§12）
2. **カレンダー駆動（従）** — 月初に `/04-operation Knowledge Lint` を手動起動。月をまたいだ初回Propagation時にAIが「今月まだLint未実行」と1行リマインド
3. **schedule / cron（任意・opt-in）** — 定期実行したい場合のみ設定（強制しない）

「月次」の時間ベースは忘れられる（実績0が証拠）。状態ベースを主にする。

## 実行フロー

1. wiki の `index.md` を読み込み、全ページを走査する（概念ページ=直下 / sources/ / queries/ の3層。索引漏れページの検出も含む）
2. 6項目のLintチェックを実行:
   - 🔴 **矛盾検出** — `> ⚠️ CONTRADICTION:` フラグ（Status: open）のあるページを特定し、既存知見との不整合を検証
   - 🟡 **孤立ページ** — 他トピックからのバックリンクがないページ
   - 🟡 **引用なし** — 「Source:」記載がない事実主張
   - 🟡 **非ASCIIファイル名** — wiki配下のファイル（概念ページ=直下 / sources/ / queries/）で非ASCIIファイル名を検出。`git -c core.quotepath=false ls-files .claude/wiki | grep -P '[^\x00-\x7F]'`（quotepath既定onだと8進エスケープ表示で取りこぼすため `core.quotepath=false` 必須）。ASCIIスラッグ規約（wiki.md）違反。表示名は本文H1で保持し、ファイルはリネーム提案
   - 🔵 **未説明概念** — 他ページで言及されるが専用トピックがない概念
   - 🔵 **欠落相互参照** — 関連すべきトピック間のリンク欠落
3. レポートを `wiki/lint-report-YYYY-MM.md` に出力:

```markdown
# Knowledge Lint Report - YYYY-MM

## 🔴 Errors（要対応）
- CONTRADICTION: [トピック] — [内容]
## 🟡 Warnings（推奨対応)
- ORPHAN / NO_SOURCE / NON_ASCII_FILENAME: [トピック] — [内容]
## 🔵 Info（改善提案）
- UNDEFINED / MISSING_LINK: [内容]
## 📊 Summary
- Total pages（概念ページ数を明記=次回baseline） / 🔴 / 🟡 / 🔵 の件数
- 推奨アクション: [最優先3件]
- 知識ギャップを埋めるために読むべき3記事（Karpathy方式）
```

4. 🔴があればオーナーに通知する
5. `log.md` に `| YYYY-MM-DD | lint | wiki全体 | 概念ページ N枚 / 🔴x 🟡y 🔵z |` を追加する（**概念ページ数を必ず記録** — 次回イベント駆動「+5」判定のbaselineになる）

## 発見問題の後処理（レポート出して終わりにしない）

- 🔴 Errors（CONTRADICTION等）→ その場で解決 or backlogにP1タスク化
- 🟡 Warnings（孤立/引用なし/非ASCII名）→ レポート列挙、次のingest時に「ついで直し」
- 🔵 Info → 記録のみ（読むべき3記事は次の学習の入口）

## 規模連動の発動基準（過剰防止）

- 概念ページ < 10: 軽量Lint（矛盾検出+孤立のみ、Info省略可）
- 概念ページ ≥ 10: フル6項目
