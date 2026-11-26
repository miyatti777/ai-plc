# 3層の定義（ポートフォリオ層・プロジェクト層・ワークパッケージ層）

> 🏷️ **Type:** reference / **Context:** 仕事の情報を置く3つの段の定義。RUL_plc_system §3・§6 から参照する。層の名前・役割・語の書き分けの正本

仕事の情報は3つの段（層）に置く。名前は PMBOK の並び（ポートフォリオ＞プログラム＞プロジェクト＞ワークパッケージ）から取った。仕組みの名前 AI-PLC は変えず、2段目の中身を指す。

| 段 | 名前（英語） | 仕組み・コマンドの接頭辞 | ひとことで |
| --- | --- | --- | --- |
| 1段目 | **ポートフォリオ層**（portfolio tier） | `ppm-`（プロジェクトポートフォリオマネジメント〔PPM〕） | 全体統括。何が動いているかを人とオーケストレーターが共有し、下へ振り、下から要約を受ける |
| 2段目 | **プロジェクト層**（project tier） | AI-PLC（`0N-<stage>`・`plc-`） | 現場統括。1つの Goal を1つの案件（Layer）として進め、成果物と検証を残す |
| 3段目 | **ワークパッケージ層**（work package tier） | `pm-`（AIPM の箱の操作） | 本当の現場。方式（AIPM など）の箱の中で、論点・仮説・ToDo・WBS などを細かく持つ |

- **公開版に入っているポートフォリオ層のスキル:** 案件をまたいで見る7つ — `ppm-audit`（点検。スクリプトは Jev 実験版にある。無ければスキップ）・`ppm-registry`・`ppm-someday`・`ppm-viewer`・`ppm-pmo`（複数案件の PMO。週次の整理・依存・資源の競合・判断メモ・決定の反映の照合）・`ppm-scan`（指定した範囲の Notion・Slack から案件の候補を1回だけ集める）・`ppm-collection`（依頼に似た既存の案件を探し、行き先を勧める。読み取り専用）
- **任意で使える日次の入口:** 入口の `/ppm`（依頼の目的から行き先を1つ選ぶ）と、`ppm-plan`（翌日の WillDo を組む）・`ppm-status`（状況確認。読むだけ）・`ppm-todo`（TODO の一覧の見直し）・`ppm-capture`（差し込みの振り分け）・`ppm-update`（終わった仕事を WillDo に反映）・`ppm-close`（終業の振り返りと翌日の準備）・`ppm-inflight`（Layer から進行中の候補を洗い出す。読むだけ）。TODO の一覧（既定は `todo/todo.md`）と、日付フォルダの WillDo・日記を使う人のためのもので、置き場と見出しの名前は `.ai-plc/config.yaml` の `ppm:` で替えられる（設定と書式は `.claude/skills/ppm/README.md`）。**使わなくても Stage（01〜04）の動きは変わらない。** 別の TODO 管理を使う人は、今までどおりそちらで人の予定と残作業を扱う
- **担い手と場所を呼び分ける。** 担い手は **オーケストレーター**（Claude Code の親セッション・Codex・Cursor など、Stage やスキルを動かす実行環境）、場所は **ポートフォリオ層**
- 外に出すときは単独の「AI-PPM」ではなく「AI-PLC の PPM スキル」と書く
- 層の外にあって全員が読むもの: 仕組みの正本（`.claude/rules`・`.claude/skills`・`.claude/commands`・`AGENTS.md`・`CLAUDE.md`）、横断の知見（`.claude/wiki/`）、本人専用のもの（native memory など）

## 1. 各層の役割と持つもの

| | ポートフォリオ層 | プロジェクト層 | ワークパッケージ層 |
| --- | --- | --- | --- |
| **役割** | 仕事を下へ振り、下から結果を**引き継いで要約する**。細かい ToDo を全部並べる場所ではない | 1つの Goal を1つの案件として Collection〜Operation で進め、成果物と検証を残す | 案件の中で、方式に沿った文書と一覧を細かく持つ |
| **持つもの** | Registry ビューア（画面）、いつかやる（Registry の S-）、点検の結果。人が今かかえている案件の一覧と1日の予定は、あなたの TODO 管理（同梱の日次の入口を使うなら、TODO の一覧〔案件1行〕・日付フォルダの WillDo と日記） | Layer の `intent.yaml`・`context.yaml`・`backlog.yaml`・`Context/`・`Documents/`・`Agents/`・`sublayers/`、Registry の projects（Layer の写し）、Stock（`Stock/programs/` の確定版） | AIPM の箱（新しい箱は Layer の直下の `Sheets/`、それより前の形は `Documents/aipm_project/`。文書・工程記録・一覧〔論点 I・仮説 H・ToDo D・WBS W・ロードマップ M。sheets_v1 は `Sheets/` の直下、それより前の形は `registers/`〕・nested_v1 だけ箱の中の `Stock/`） |
| **正本** | 中身の正本は下の層にある（全部を見る場所ではない）。TODO の一覧は案件1行の写しで、案件の状態の正本ではない | 案件の Goal・status は `intent.yaml`、Task は `backlog.yaml` が唯一の正。Registry の projects はその写し。Stock は**箱や Flow から抜き出して合わせたプロジェクト層の正本**（確定版・年月つき） | 論点・ToDo などは箱の一覧が正（TODO 管理へ書き写さない）。nested_v1 の箱の中の `Stock/` は検査に通った同じ版 |
| **書く人・入口** | 人、オーケストレーター。`/ppm-someday`・`/ppm-registry`、点検の反映は `/ppm-audit` の承認行だけ（`/ppm-pmo`・`/ppm-scan` は自分の出力のファイルだけを書く）。日次の入口を使うなら、TODO の一覧は `/ppm-todo` の承認行だけ、WillDo は `/ppm-plan`・`/ppm-update`・`/ppm-close`、日記は `/ppm-capture`（どれも本人の OK の後） | 各案件の実行スレッド。`/01-collection`〜`/04-operation`・`/plc-backfill`・`/plc-lifecycle`。Registry の projects は Phase 7 で更新 | 人の確定の後に `/pm-issue`・`/pm-todo`・`/pm-hypothesis`、aipm-guided、04-operation Phase 6（WBS の完了候補） |
| **読む人** | 人と全オーケストレーター（`/ppm-viewer`・`/ppm-registry`・`/ppm-collection`・`/ppm-pmo`。日次の入口を使うなら `/ppm-status`・`/ppm-inflight`） | その案件の担当、plc-brief・plc-consult・plc-next、ポートフォリオ層の集計（ppm-audit） | その案件の担当、`/pm-today` |

## 2. 上下の受け渡し

| 向き | 渡すもの |
| --- | --- |
| ポートフォリオ層 → プロジェクト層 | 依頼、新しい案件（/01-collection）、いつかやるからの起動 |
| プロジェクト層 → ポートフォリオ層 | Registry の状態（Phase 7）、完了報告、点検で見つかった食い違い。どれも要約で、Task の中身は渡さない |
| プロジェクト層 → ワークパッケージ層 | 方式の選択（intent の addons）、箱の初期化（mode_init）、Task の wbs_id・issue_id |
| ワークパッケージ層 → プロジェクト層 | WBS の完了候補（backlog の完了の証拠）、validate の issues_summary、箱の archive → Stock |
| ポートフォリオ層 → 人 | 要約・選択肢・質問 |

期限を過ぎた箱の ToDo や期限の近い論点は、その案件の `/pm-today` で見る。日次の入口の `/ppm-plan` を使うなら、TODO の一覧の進行中に載っている案件のうち箱に ToDo のシートがあるものから、「期限を過ぎた ToDo」と「7日以内が期限の論点」が翌日の WillDo の「TODOから」の欄の候補に上がる（`/pm-today` と同じ選び方。人の言葉の1行に書き直して載せ、論点・ToDo は TODO の一覧へ書き写さない。一覧に載っていない案件は件数だけ示す）。`/ppm-plan` を使わなければ、箱の期限は `/pm-today` だけで見る。

## 3. データの流れとしての読み方（例え）

| 段 | データの言葉 | 中身 | 置き場 |
| --- | --- | --- | --- |
| 素材 | 生の素材（ソース） | 集めた文脈・会議メモ・資料 | Layer の `Context/` など |
| ワークパッケージ層 | 加工した構造（例えではウェアハウス） | 論点・仮説・ToDo・WBS・ロードマップの一覧、ペルソナ・ストーリー | AIPM の箱 |
| プロジェクト層 | 抜き出して合わせた確定版（例えではマート） | 案件ごとの確定版 | Stock、Layer の intent・backlog |
| ポートフォリオ層 | 束ねて見る・振る | 全体の一覧 | Registry の画面・いつかやる（日次の入口を使うなら TODO の一覧・WillDo） |

例えは読み方の助けで、層の名前ではない（データ分析の用語と混ざらないよう、名前には PMBOK の語を使う）。

## 4. 語の書き分け

| まぎらわしい組 | 書き分け |
| --- | --- |
| 層 ／ Layer ／ tier | **層**＝3つの段。仕組みの語 **Layer**＝案件（intent.yaml の単位）。英語で段を書くときは **tier**（portfolio tier など）にして Layer と分ける。Agent 定義の Lite・Full は「定義の型」と呼ぶ（旧称ティア。tier と重ならないように呼び直した） |
| プロジェクト層 ／ 案件 ／ 業務プロジェクト | **プロジェクト層**＝2段目の名前。**案件**＝その中の1件（Layer・scope_id）。**業務プロジェクト**＝業務のまとまり（任意の業務Project の表〔RUL_plc_system §3〕。既定では読まない）。「プロジェクト」を単独で使うのは層の名前の中だけ |
| ポートフォリオ層 ／ プログラム | **プログラム**＝Registry の programs（顧客・事業ごとのまとまり。ポートフォリオ層の中の単位） |
| ワークパッケージ層 ／ 箱 ／ WBS の行 | **箱**＝AIPM の入れ物。箱の中の **WBS の行**（W）は「ワークパッケージ」と呼ばない |
| Stock の意味 | ①`Stock/programs/` の確定版は**プロジェクト層の正本**。②古い形（nested_v1）の箱の中の `Documents/aipm_project/Stock/` は**ワークパッケージ層の中の版**で、①とは別。新しい形（sheets_v1・box_root_v1）の箱は中に Stock を持たず、archive で写す（写す先は `.ai-plc/config.yaml` の `aipm_archive` で決める。公開版の既定は Layer の中。aipm-guided の「保存先の設定」） |
| PPM ／ `ppm-` ／ `pm-` | **PPM** はプロジェクトポートフォリオマネジメント（初出でこう書き、プロダクト・ポートフォリオ・マネジメントと区別する）。**`ppm-`**＝ポートフォリオ層、**`pm-`**＝ワークパッケージ層の AIPM の箱の操作。1文字の差なので命名表（RUL_plc_system §6）で並べて示している |

## 5. 日本語の呼び名の対応表

人に話す語と仕組みの語の対応。新しく書くものから従い、過去の記録は一括で書き換えない。

| 概念 | 人に話す語（日本語） | 仕組みの語（英語・ファイル） | 使わない・限る語 |
| --- | --- | --- | --- |
| 1段目・2段目・3段目 | **ポートフォリオ層・プロジェクト層・ワークパッケージ層** | portfolio tier・project tier・work package tier | Layer（段の意味で） |
| 動かす担い手 | **オーケストレーター** | Claude Code・Codex・Cursor など | — |
| 1つの Goal を進める単位 | **案件** | **Layer**（intent.yaml・scope_id） | PJ・プロジェクト・レイヤー（使わない）、Scope（`scope_id` の欄の名前だけ） |
| 登録簿に載る案件の行 | 案件の登録 | Registry の project | 「Project」単独 |
| 業務のまとまり | **業務プロジェクト** | business project | — |
| AIPM の Project | **AIPM の箱**（ワークパッケージ層の入れ物） | Sheets（sheets_v1）・aipm_project（それより前の形） | 「プロジェクト」 |
| AIPM の一覧 | 箱の一覧（論点・仮説・ToDo・WBS・ロードマップ） | registers | 「一覧」単独 |
| Layer の作業 | **タスク** | Task（backlog・T001） | — |
| 箱の中の作業 | **箱の ToDo** | ToDo（D1） | 「TODO」 |
| Stage | **段階（Stage）** | 0N-<stage> | 「工程」（AIPM の文書の作業の段に譲る） |
| 点検 | **点検** | audit（`/ppm-audit`） | 監査 |
| いつかやる | **いつかやる** | someday（S-。`/ppm-someday`） | ストック |
| 登録簿 | **登録簿（Registry）** | ai_plc.db（`/ppm-registry`。持ち主はプロジェクト層、読むのはポートフォリオ層） | DB 単独 |
| 正本 | **正本** | — | 正・定位置・canonical |
| 成果物の置き場 | 成果物 | Documents | Artifact Store |
| 集めた文脈 | 集めた文脈 | Context・context.yaml | Context Store |
| 確定版の置き場 | Stock | Stock/ | 古い形の箱の中の Stock は「箱の確定版」（§4） |
| Agent 定義の Lite・Full | **定義の型** | Lite・Full | ティア（旧称。tier と重なる） |

---
**作成日:** 2026-10-23 ｜ **更新日:** 2026-11-26（任意で使える日次の入口〔/ppm と ppm-plan・ppm-status・ppm-todo・ppm-capture・ppm-update・ppm-close・ppm-inflight〕を足した）／2026-11-25（公開版向けに、個人の運用を外した） ｜ **ステータス:** Active
