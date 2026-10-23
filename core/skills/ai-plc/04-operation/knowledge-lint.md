# Knowledge Lint（軽量=04-operation Phase 7 で月1回必須／フル=Phase 8 手動）

> 軽量3項目は Phase 7 の Wiki波及の中で月1回必ず実行（RUL_plc_system §10）。フル6項目は手動指示のときだけ。
> チェック項目の定義: このファイル（RUL_plc_system §10 は発動の概要だけ）

## 軽量Lint（Phase 7・月1回）

概念ページ＝`.claude/wiki/` 直下の .md から log.md・wiki.md・index.md・README.md を除いたもの。

1. 今月の lint 行が log.md にあれば「今月実施済み」で終わる（`grep '| lint |' log.md` の最終月）
2. 無ければ次を調べる:
   - 🔴 open 矛盾: 概念ページに `grep -nE '^[[:space:]]*>.*Status: open'`（字下げ・別行の Status も拾う）。当たった行の Date から経過日数を出す。数え漏れの確認に `grep -n -A3 'CONTRADICTION'` の後ろ3行の Status も見る
   - 🟡 非ASCIIファイル名: `find .claude/wiki -type f | LC_ALL=C grep '[^ -~]'`（git 未登録のページも見る）
   - 🟡 Last Updated 欠落: 概念ページのうち `grep -qE '\*\*Last Updated:\*\*|^last_updated:'` が当たらないもの（コールアウトか YAML のどちらかがあれば可）
   - 60KB（61,440 B）超の概念ページ: `find .claude/wiki -maxdepth 1 -name '*.md' -size +60k` から log.md・wiki.md・index.md を除いた名前を1行出す（移さない。移すかは下の「節の退避」）
3. log.md に `| YYYY-MM-DD | lint | 軽量 | 概念ページ N枚 / 🔴x 🟡y |` を1行足す。🔴は Phase 7 の出力で知らせ、6日以上 open のものは**いつかやるストック（`/plc-someday`、Registry の planned・S-ID）に「wiki 矛盾の解決: [ページ名]」として登録**するか、登録しない理由を1行書く（実行中の Layer の backlog には入れない。Layer の Goal と無関係なため）
4. schedule / cron は任意（opt-in）のまま

## 節の退避（フルLint か手動の整理のとき。Phase 7 では行わない）

移すのは、節単位の被引用を数えたページで、**Flow の全期間の Context で被引用 0 の節**だけ。被引用のある節・被引用を数えていないページ・PJ 別でない節（「矛盾・未解決」「関連トピック」など）は移さない。移した節は `[slug]-archive.md` に入れ、元ページに見出しを1行ずつ残す。

**被引用の数え方（固定）:** ①対象ファイルは `grep -rlE "<slug>" --include=*.md Flow | grep "/Context/"`（数えている Layer 自身と `Documents/trials/` の複製は除く） ②そのファイルに節名か節見出しの L 番号（例 `L-1234-5`。後ろに `-数字` が続くものは別番号）があれば、その節を引いたと数える ③パスや slug だけで節が分からない引用のファイル数が、ページの節（`## ` 見出し）の数を上回るページは「数えていない」扱いにして移さない

## フルLint（手動）

1. wiki の `index.md` を読み込み、全ページを走査する（概念ページ=直下 / sources/ / queries/ の3層。索引漏れページの検出も含む）
2. 6項目のLintチェックを実行:
   - 🔴 **矛盾検出** — 概念ページの `> ⚠️ CONTRADICTION:` フラグ（Status: open）を数え元にする（RUL_plc_system §12。log は印だけ）。既存知見との不整合を検証
   - 🟡 **孤立ページ** — 他トピックからのバックリンクがないページ
   - 🟡 **引用なし** — 「Source:」記載がない事実主張
   - 🟡 **非ASCIIファイル名** — `find .claude/wiki -type f | LC_ALL=C grep '[^ -~]'`（軽量と同じ。`grep -P` は macOS の BSD grep に無いので使わない）。ASCIIスラッグ規約（wiki.md）違反。表示名は本文H1で保持し、ファイルはリネーム提案
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
- Total pages / 🔴 / 🟡 / 🔵 の件数
- 推奨アクション: [最優先3件]
- 知識ギャップを埋めるために読むべき3記事（Karpathy方式）
```

4. 🔴があればオーナーに通知する
5. `log.md` に `| YYYY-MM-DD | lint | フル | 概念ページ N枚 / 🔴x 🟡y 🔵z |` を追加する（概念ページ数は記録するが、発動の判定には使わない）。過去の ingest を数えるときは見出し形式 `^## 20..-..-.. ingest` と表の行 `^\| 20..-..-.. \| ingest \|` の両方を数える

## 発見問題の後処理（レポート出して終わりにしない）

- 🔴 Errors（CONTRADICTION等）→ その場で解決 or いつかやるストック（`/plc-someday`）に「wiki 矛盾の解決: [ページ名]」で登録（軽量Lint と同じ起票先）
- 🟡 Warnings（孤立/引用なし/非ASCII名）→ レポート列挙、次のingest時に「ついで直し」
- 🔵 Info → 記録のみ（読むべき3記事は次の学習の入口）

---
**更新日:** 2026-09-30 ｜ 軽量Lint（Phase 7・月1回必須）と節の退避を追加、状態ベースのトリガーと規模連動の発動基準を削除
