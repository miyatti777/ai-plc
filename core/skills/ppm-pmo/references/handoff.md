# 案件別要求と読戻し

`handoffs.json`トップレベル：schema_version=`handoff-1`、portfolio_id、decision_id、requests配列。JSON正本のローカル読戻し専用。外部APIの変更/自動適用はない。

各requestの必須項目：
- portfolio_id、decision_id：トップと一致
- project_id、request_id、revision：非空文字列。同じ組の重複禁止。新版はrevisionを変更。
- target_path：利用者の明示した案件正本。相対パスはhandoffs.jsonの親から解決。
- pointer：`/priority`等JSON pointer。配列添字は0起点。キー内`/`は`~1`、`~`は`~0`。
- expected_before、expected_after：異なるJSON値。
- before_sha256：要求作成時に実際に読んだ元正本のSHA256。
- 任意の説明やowner等は要求の内容に含まれる。confirmation/receipt以外すべてのフィールドを内容hashに束縛。
- confirmation：actor、authority、at、request_sha256。確認者がこの内容と権限を明示した証跡。存在しなければ案のまま。
- receipt：actor、at、request_sha256、after_sha256。案件担当の実行記録。PMOが架空の実行記録を作らない。

`request_sha256`はスクリプト `readback.request_hash(request)` で生成。確認/実行記録を含まない要求JSONをキー順・UTF-8・indent2・末尾改行で正規化したSHA256。hashを埋めることは承認ではない。確認者/権限/日時は利用者の明示証跡からのみ記入。

```python
import sys
sys.path.insert(0, '<SKILL_DIR>/scripts')
from readback import request_hash
# request は正本から作成した要求。hash提示→明示確認→confirmationを記録。
content_hash = request_hash(request)
```

要求台帳を保持し、同一project_id/request_id/revisionの再登場は過去hashと照合する。異なるならconflictとして実行しない。ヘルパーは一回の入力の重複・confirmation/receiptとのhash不一致を検出するが、過去台帳を自動探索しない。過去の確認内容を新版にコピーしない。

照合結果：期待before+元hash一致→unapplied。beforeだが版違い、期待外の値、receiptとのhash不一致→conflict。期待afterでも実行記録なし→evidence_missing。正本取得不能→evidence_missing。内容版に結び付いた確認なし→needs_review。正しい確認+receipt+実正本期待値が揃う場合のみverified。全件verifiedなら全体verified、一部だけならpartial。実行記録は暗号署名ではなく、確認者/権限の正当性は人が確認する。

Markdown等は手動照合し、元資料の場所/見出し/版、要求hash、確認証跡、案件担当の実行記録、取得した実際の値、判定と理由を`readback_manual.md`に記録。取得しないまま反映済みにしない。
