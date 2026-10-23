---
name: plc-auto
description: この会話のAI-PLC Layerを自動完走（RUL_plc_session §10）で最後まで進める。Codexは利用可能なGoal継続経路（明示forceは同一ターン実行にも対応）、Claude Code は状態ファイル＋Stop hook（.claude/skills/plc-auto/scripts/plc_auto.py）で続ける。利用者が /plc-auto・$plc-auto（clear・status を含む）またはAI-PLC自動完走の開始を明示したときに使う。
---

# AI-PLC 自動完走（Claude Code・Codex 共通）

利用者が `/plc-auto`（Claude Code）または `$plc-auto`（Codex）を実行したら、この会話で扱う Layer の自動完走を始め、同じターンで Stage の実行に進む。`/goal` 文の表示だけで終わらない。Skill の作成・編集・説明・プレビュー依頼では開始しない。

本人が対象/Goal を指定して「権限委譲・人への承認要求なし・最後まで実行」と直接指示した場合も明示 force の開始とする（過去の報告や引用、改修依頼は除く）。force の契約は RUL_plc_session §10.1 と [force-contract.md](references/force-contract.md)（force 中は各 Skill/§9.1 の待機より委譲を優先し、代替不能なら理由を報告して終了する。承認要求で待機に戻さない）。

引数: `$ARGUMENTS`（Claude Code。Codex は呼び出し文の残り）

| 引数 | すること |
| --- | --- |
| `force` / `--force` + LayerまたはGoal | 明示workflow-force。§10.1と[追加契約](references/force-contract.md)を読み、本人指示由来のwrite_setを固定する。通常autoの開始と区別する |
| `clear [Layer]` | 止める（CC: `python3 .claude/skills/plc-auto/scripts/plc_auto.py clear`／Codex: nativeは管理手順、inlineは同一実行の自動選択を終了してexecution_contractへcleared記録）。結果を1行で伝えて止まる |
| `status [Layer]` | 状態を見る（CC: `python3 .claude/skills/plc-auto/scripts/plc_auto.py status`／Codex: 公開されたGoal読取手順、無ければexecution_contractのruntime/終了記録とbacklog。保存記録からactiveと推定しない）。要点を伝えて止まる |
| Layer パス（`Flow/...`） | そのパスを対象にする |
| それ以外の文 | 新しい Goal として /01-collection から |
| 空 | この会話の直近の Stage 実行・Layer の話題から決める |

status/clear/force は先頭の独立引数だけを操作名・モードとして読み、残りを対象 Layer にする。自然文は上記の本人による直接の委譲指示として解釈し、文章/引用内のforceという語だけでは発火しない。引数から取り除いた残りでLayer/Goalを解決する。追加契約の記録だけでは再開せず、同じactive Goal/sessionまたは今回本人が明示したinline実行の範囲を確認する。

## 1. 共通: 対象と前提

開始/再開で [outcome-delivery.md](../ai-plc/references/outcome-delivery.md) の「止まった後に続ける」に従い、現在 Intent の原要求/明示変更・既存成果/未達・次操作を復元する。

**有効実行を先に照合:** 本人が一括実行を承認した範囲は [execution-record.md](references/execution-record.md) の共通判定で照合し、保存ログだけを現在の許可とみなさない。

1. リポジトリの `AGENTS.md`（Codex）／`CLAUDE.md`（CC）と、`.claude/rules/ai-plc-system.md`・`ai-plc-session.md`・`ai-plc-adaptive.md`、実行する Stage の正本を読む。アダプターだけ読んで Stage の処理を推測しない。
2. 対象 Layer を決める。明示パスを優先し、無ければ直近に Stage を実行した Layer か直前に話題にした Layer。任意の inflight 案件を拾わない。候補が複数で決められなければ行頭に `⛔ 自動完走を停止: 対象の Layer を決められない` を出して止まる。
3. intent.yaml が `workflow_depth: complex` か `mode: platform_builder` なら開始せず、行頭に `⛔ 自動完走を停止: complex / platform_builder は対象外` を出して止まる。
4. 全タスクcompleted（運用タスクを除く）なら既存成果/AC/Phase7の確認と報告までにし、Goal開始・新タスク/デモ・完了後のNext Actionを実行しない。force時は追加契約に従いexecution_contractと本人指示を記録し、通常autoと区別する。開始したら backlog.yaml の既存 `refactoring_log` 形式で `[auto-approved] plc-auto 開始（<CC Stop hook | Codex native-existing/native-created | Codex inline>）` を1行書く（Goal からは Layer ができた時点で）。実行記録であり、将来の会話の承認根拠にはしない。利用者が `/goal` を入力したと偽って記録しない。

## 1.5 重い自動実行の記録

重い自動実行だけ RUL_plc_session §7.6 に従い `backlog.execution_budget` を読み戻す（記録の形・持越し・終了条件は [execution-record.md](references/execution-record.md)）。回数の上限（修正2回・独立レビュー1回・stopped 1回）は 04-operation の既定。軽い作業には足さない。CC の turns 初期化や Codex の新規 Goal で既消費・実期限をリセットせず、上限到達後は本人の具体的な変更なしに再開しない。

## 2. 実行環境で分ける

| 環境 | 続け方 |
| --- | --- |
| Claude Code（hook 登録済み） | §2.1 |
| Claude Code（hook 未登録・別リポジトリ） | 状態ファイルを作らない。「hook 未登録のため /plc-auto で続けられない」と1行伝え、RUL_plc_session §10 の /goal（Layer があれば短い版、無ければ Goal から版、§10 の無い環境は自己完結版）を1行出して止まる。/goal は利用者が打つ |
| Codex | §2.2 |

### 2.1 Claude Code — Stop hook

CC の組み込み `/goal` はスキルから設定できないため、状態ファイル `.claude/db/plc_auto_state.json` を active にし、Stop hook（`.claude/skills/plc-auto/scripts/plc_auto.py hook`）がターン終了のたびにコードで判定して続ける: 行頭の `⛔ 自動完走を停止` で停止／backlog の全タスク（運用タスクを除く）が completed・deferred・blocked かつ応答に「Phase 7」で達成／上限 60 ターンで終了／それ以外は次のターンへ。

**hook の確認（開始の前に毎回）:** `.claude/settings.json` の `hooks.Stop` に `.claude/skills/plc-auto/scripts/plc_auto.py" hook` を含むコマンドがあり、`.claude/skills/plc-auto/scripts/plc_auto.py` が存在すること。無ければ §2 表の2行目に従う（settings.json は書き換えない — 登録は人がする）。登録する設定:

```json
"hooks": { "Stop": [ { "hooks": [ { "type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/skills/plc-auto/scripts/plc_auto.py\" hook" } ] } ] }
```

1. 状態を作る（パスはリポジトリ相対）。forceは下のstartに `--mode workflow-force` を追加する（CLIの `--force` も同義、既存状態の置換ではない）。forceは有効な `--session` を必須とする。環境から取得できなければ開始せず原因を示す（任意の最初のhookへ束縛しない）。本人指示で許可されたLayer外ファイルは `--write-path <絶対パス>` を各々追加し、execution_contractと一致を確認する。これは書込許可の執行器ではなく状態記録であり、各ツール前の契約判定を省かない:
   - Layer がある: `python3 .claude/skills/plc-auto/scripts/plc_auto.py start --layer <Layerパス> --session ${CLAUDE_SESSION_ID}`
   - Goal から: `python3 .claude/skills/plc-auto/scripts/plc_auto.py start --goal "<Goal>" --session ${CLAUDE_SESSION_ID}` → Layer ができたら `python3 .claude/skills/plc-auto/scripts/plc_auto.py set-layer <Layerパス>`
   - `[NG] 既に active` なら上書きせず、`/plc-auto clear` してから打ち直すよう伝えて止まる。
2. 「自動完走を開始した（Layer・上限 60 ターン・止めるのは `/plc-auto clear`）」と1行伝え、同じターンで Stage を進める。始める位置は §10 の開始列（短い版）。
   共通v2実行をCCで継続する場合は、現在の許可/実行を照合したJSONを上のstartへ `--execution-request <実在JSON>` で渡す。startとhookは共通コード判定に従い、一式のscope_tasksだけを追跡し、期限切れ/停止/版不一致で次の工程を起動しない。
3. 状態の操作は `.claude/skills/plc-auto/scripts/plc_auto.py` だけで行い、状態ファイルを手で書き換えない。Esc で割り込むと hook は動かず待機になる。完全に止めるのは `/plc-auto clear`。hook の設定は新しいセッションから読まれることがあり、続かなければ新しいセッションで打ち直すよう伝える。

### 2.2 Codex — 実行許可とGoal継続を分ける

`.agents/skills/ai-plc/references/codex-runtime.md` の「Codex の実行許可と Goal 継続の経路」節を正本とする（経路表・codex_route.py・inline・終端処理はそこ。「自動完走モードとCodexのGoal」節は共通規定）。要点: Stage 名は同名の `$skill` に読み替える／公開されている tool schema から Goal の読取・作成・終端能力を確認し、公開されない名前を推測して呼ばない／同じ対象・同じ force 条件の active Goal が確認できれば既存 Goal の継続（native-existing）、無ければ作成（native-create）、作成手段が無ければ本人の今回指示だけで有効な同一ターン実行（codex-inline。終了後は自動再開しない）／経路判断は `python3 .claude/skills/plc-auto/scripts/codex_route.py`／停止能力の不在は内部情報として扱い、本人が停止方法を聞いたときだけ答える／paused・別対象・別モードの Goal・対象未確定は停止し inline で回避しない。

## 3. 共通: 進め方・止まり方

- この Skill の明示実行で開始した自動完走（CC: 状態ファイルが active／Codex: native Goalと継続が確認済み、または今回明示したforceのcodex-inline実行中）の間だけ、RUL_plc_session §10 の Mob Checkpoint・Next Action・タスク選択の自動承認を適用する。自動で進める範囲・保留・停止・自動承認ログは §10 のとおり（この Skill で足さない・緩めない）。他の Stage の既定動作は変えない。
- `pipeline_variant: jev` でも本体版を使う。Jev 実験版を解凍せず、opt-in を代筆せず、凍結中の会話監視を起動しない。
- Stage 正本が求める検証・独立レビュー・BT 判定・Propagation・ステータス点検を行う。保留した作業や未確認 AC を検証済み完了と扱わない。`deferred`・`blocked` はタスク完了と区別し、理由・残件・再開条件を報告する。
- 止まるときは行頭に単独で `⛔ 自動完走を停止: <理由>`（説明文で引用しない — CC の hook が停止と判定する）。残件・再開方法（同じ `/plc-auto <Layerパス>`／`$plc-auto` を打ち直す）と、自動完走の実際の状態を示す。Codexの定型報告には停止能力の注意を添えず、§2.2「停止能力の通知」に従う。
- forceでは終了時にcomplete/partial/stopを区別し、停止後にactive Goalが残っても自動判断を続けない。通常の中断/応答終了後の同じ残作業は、現在の本人継続指示又はforce再指定を§2.2/共通判定へ照合し、対象/版/残量/実期限/禁止/競合が成立する範囲で再開する。取消/打切り/実期限到達の停止を単なる継続指示で解除せず、本人の具体的な変更指示が必要な条件は保持する。
- 完了時は成果物の存在・検証結果・Phase 7 チェックリスト・自動承認ログと保留事項を示す。
