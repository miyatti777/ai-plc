#!/usr/bin/env python3
"""Select a Codex execution route from observed capabilities; never mutate Goal or Layer."""
import argparse
import json


def select_route(*, force=False, goal_state="unknown", can_get=False,
                 can_create=False, native_continuation=False,
                 access_denied=False, work_remaining=True):
    if access_denied or goal_state in {"error", "paused", "other", "active_unbound"}:
        return {"route": "stop", "reason": "Goal拒否/読取失敗/paused/対象不一致はfallbackで越えない"}
    if not work_remaining:
        return {"route": "report_only", "reason": "新タスク/新NextActionを実行しない。既存成果の確認と報告だけ"}
    if goal_state == "unknown" and can_get:
        return {"route": "inspect", "reason": "公開された読取ツールでGoalの対象と状態を確認"}
    if goal_state == "active_same" and native_continuation:
        return {"route": "native_existing", "reason": "同じ対象/force条件のactive Goalと継続経路を確認済み。作成不要"}
    if goal_state in {"none", "complete"} and can_create:
        return {"route": "native_create", "reason": "作成ツールの成功後にのみ設定を報告"}
    if force:
        return {"route": "codex_inline", "reason": "本人の明示forceに基づく現在ターンの実行。native設定/背景継続は未設定"}
    return {"route": "prompt_only", "reason": "通常autoの既定fallbackを保持。forceを自動補完しない"}


def select_finish(*, result, goal_state="unknown", can_complete=False,
                  can_block=False, block_allowed=False, already_reported=False,
                  finish_failed=False):
    """result is the verified entire Goal result, not merely terminal Layer tasks."""
    if finish_failed or goal_state in {"error", "paused", "other", "active_unbound"}:
        return {"route": "finish_stop", "reason": "拒否/失敗/不一致を別toolやfallbackで越えず再試行しない"}
    if goal_state == "active_same":
        if result == "complete" and can_complete:
            return {"route": "native_complete", "reason": "全Goal達成を検証済み。現在schemaの正式complete能力を使う"}
        if result != "complete" and can_block and block_allowed:
            return {"route": "native_block", "reason": "現在schemaのblocked条件を満たす場合だけ正式block能力を使う"}
    if already_reported:
        return {"route": "no_op", "reason": "終端記録済み。新しい条件/本人指示なしに再検算や同じ終了報告を繰り返さない"}
    return {"route": "record_terminal_once", "reason": "ローカル終了とnative未操作/未確認を一度記録。Goal終了を偽らず追加作業をしない"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--force", action="store_true")
    p.add_argument("--goal-state", choices=["unknown", "none", "complete", "active_same", "active_unbound", "paused", "other", "error"], default="unknown")
    p.add_argument("--can-get", action="store_true")
    p.add_argument("--can-create", action="store_true")
    p.add_argument("--native-continuation", action="store_true")
    p.add_argument("--access-denied", action="store_true")
    p.add_argument("--no-work-remaining", action="store_true")
    p.add_argument("--finish-result", choices=["complete", "partial", "stopped"])
    p.add_argument("--can-complete", action="store_true")
    p.add_argument("--can-block", action="store_true")
    p.add_argument("--block-allowed", action="store_true")
    p.add_argument("--already-reported", action="store_true")
    p.add_argument("--finish-failed", action="store_true")
    a = p.parse_args()
    if a.finish_result:
        result = select_finish(result=a.finish_result, goal_state=a.goal_state,
                               can_complete=a.can_complete, can_block=a.can_block,
                               block_allowed=a.block_allowed, already_reported=a.already_reported,
                               finish_failed=a.finish_failed or a.access_denied)
    else:
        result = select_route(force=a.force, goal_state=a.goal_state, can_get=a.can_get,
                              can_create=a.can_create, native_continuation=a.native_continuation,
                              access_denied=a.access_denied, work_remaining=not a.no_work_remaining)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
