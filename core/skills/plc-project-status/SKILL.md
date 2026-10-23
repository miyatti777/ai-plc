---
name: plc-project-status
description: ProjectをGoal未達のまま意図的に中止（cancelled）し、理由と本人判断を残す。中止済みProjectの再計画後の再開も扱う。TaskのcancelledはRe-Inceptionで扱う。
---

# Projectの中止と再開

> 2026-10-06: 本番CHECK移行と全行保全を検証済み。Viewerは閲覧専用、中止/再開はこの正式CLIで行う。

共通ルール `.claude/rules/ai-plc-system.md` §21 と session §9.1を読む。既存の対象Layerを継続し、機能実装の承認を実案件の中止承認とみなさない。

1. 対象Layerをraw編集しているAgent/エディタを止める。公式CLI/点検writerは共通advisory lockを使うが非協調writerを強制停止しない。完了実績が並行更新される状態で中止/復旧を実行しない。対象intent/backlogとRegistryを読み、Scopeの一致、元Goal/AC、未達、保持成果、残Task、動いている処理/子Layerを確認する。中止対象と範囲が本人指示で既に明示なら聞き直さない。子やTaskは自動中止しない。動くnative Goalは別操作で、止めたと偽らない。
2. Layerの `Documents/project-cancellation-decision.yaml` に判断案を作る。必須は `reason`（未達理由を含める）、`decided_at`（timezone付きISO時刻）、`approved_by`、`approval_ref`（本人指示の日時/文言/参照）、`retained_artifacts`（Layer基準の既存パスのlist。全体なら `['.']`）。任意は `replacement_scope_id`（存在する別Project）、`reconsider_when`（再検討条件）。本人の承認を代筆しない。Taskは元の状態/実績を保持する。
3. `python3 .claude/db/project_lifecycle.py cancel --layer <Layer> --decision <判断yaml>` で予定を確認する。対象版、未達、保持成果、置換先/再検討条件、外部同期保留を示し、中止の本人指示が不足するときだけsession §9.1の質問UIで承認を得る。
4. 承認範囲だけ `cancel ... --yes` を実行。Layer status/summary、監査event、理由を読み戻し、`python3 .claude/ai-plc-jev/scripts/aiplc_status_audit.py --brief --layer <Layer>` を行う。cancelledは成功/AC達成を意味せず completed・完了率分子へ足さない。
5. 再開は元Goal/AC/未達/依存/保持成果/残Taskを再確認し、Re-Collection/Re-Inceptionの必要な差分を本人許可の範囲で計画ファイルに残す。再開判断yamlの必須欄は reason/decided_at/approved_by/approval_ref と `replan_ref`（Layer基準の実在する再計画ファイル）。`reopen --layer <Layer> --decision <判断yaml>` をプレビュー後、明示された再開指示の範囲で `--yes`。activeに戻し中止履歴は保持する。異なるGoalなら新ProjectをCollectionで作りreplacementとして関連づける。

`PROJECT_LIFECYCLE_MIGRATION_REQUIRED` は本スキルで勝手にmigrationせず、下記公式migration手順と承認範囲を確認する。その他のBLOCKEDは理由を示して止める。journalが残れば `recover --layer <Layer>` でDBevent有無に基づく復旧予定を確認し `--yes`。並行変更がある場合は復旧しない。原本削除/全DBの古いbackupによる巻戻しはしない。

## スキーマ移行（機能拡張/移行を本人が依頼した場合だけ）

- `python3 .claude/db/project_lifecycle.py migrate` は予定だけ。
- 合成fixtureで全行/制約/index/trigger/sequence/TaskFROZEN保全とfailure rollbackを通す。
- `migrate --backup <存在しないbackupパス> --yes` はSQLite backupを作成してBEGIN IMMEDIATE内でprojectsのstatus CHECKだけを拡張し、監査表を追加。Task/metadata/既存状態は無変更。FK依存など未対応はBLOCKEDで停止する。
- backupは機密扱いで同期ツリー外に保持する。失敗時は自動rollbackし、backupは復旧証拠として残す。backup検証や復元試験はコピー先で行う。実DBに戻すには移行後の他変更が無いことを確認し別途本人承認が必要。

## 外部境界

cancelledの外部Notion Schema/選択肢/判断metadata同期は未対応・別承認。sync.pyは `PROJECT_CANCELLED_EXTERNAL_SYNC_UNSUPPORTED` で停止し別statusへ変換しない。公開OSS、送信済みsnapshot、git commit/pushはこの操作に含まれない。Task側のcancelled/dropped/deferred仕様は変更しない。
