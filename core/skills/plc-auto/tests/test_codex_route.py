import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("codex_route", Path(__file__).parents[1] / "scripts/codex_route.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class RouteTests(unittest.TestCase):
    def route(self, **kwargs):
        return mod.select_route(**kwargs)["route"]

    def test_force_without_goal_tools_runs_inline(self):
        self.assertEqual(self.route(force=True), "codex_inline")

    def test_read_api_is_used_before_fallback(self):
        self.assertEqual(self.route(force=True, can_get=True), "inspect")

    def test_existing_goal_does_not_need_create_tool(self):
        self.assertEqual(self.route(force=True, goal_state="active_same", native_continuation=True), "native_existing")

    def test_goal_creation_requires_observed_state(self):
        self.assertEqual(self.route(force=True, can_create=True), "codex_inline")
        self.assertEqual(self.route(force=True, can_create=True, goal_state="none"), "native_create")

    def test_terminal_controls_are_not_proof_of_active_goal(self):
        self.assertEqual(self.route(force=True, goal_state="unknown"), "codex_inline")

    def test_confirmed_goal_without_driver_does_not_claim_native_continuation(self):
        self.assertEqual(self.route(force=True, goal_state="active_same"), "codex_inline")

    def test_normal_auto_still_returns_prompt_when_native_missing(self):
        self.assertEqual(self.route(), "prompt_only")

    def test_denial_error_pause_conflict_never_fall_back(self):
        self.assertEqual(self.route(force=True, access_denied=True), "stop")
        for state in ("error", "paused", "other", "active_unbound"):
            self.assertEqual(self.route(force=True, goal_state=state), "stop")

    def test_finished_layer_never_creates_demo_or_goal(self):
        self.assertEqual(self.route(force=True, work_remaining=False, can_create=True, goal_state="none"), "report_only")

    def test_normal_native_creation_is_preserved(self):
        self.assertEqual(self.route(goal_state="complete", can_create=True), "native_create")

    def test_complete_capability_does_not_require_stop_goal_or_create(self):
        self.assertEqual(mod.select_finish(result="complete", goal_state="active_same", can_complete=True)["route"], "native_complete")

    def test_partial_cannot_complete_native_goal(self):
        self.assertEqual(mod.select_finish(result="partial", goal_state="active_same", can_complete=True)["route"], "record_terminal_once")

    def test_block_requires_observed_active_goal_and_schema_condition(self):
        self.assertEqual(mod.select_finish(result="stopped", goal_state="active_same", can_block=True)["route"], "record_terminal_once")
        self.assertEqual(mod.select_finish(result="stopped", goal_state="active_same", can_block=True, block_allowed=True)["route"], "native_block")

    def test_end_tools_alone_do_not_prove_target(self):
        self.assertEqual(mod.select_finish(result="complete", can_complete=True)["route"], "record_terminal_once")

    def test_no_tools_record_once_and_never_repeat_verification(self):
        self.assertEqual(mod.select_finish(result="complete")["route"], "record_terminal_once")
        self.assertEqual(mod.select_finish(result="complete", already_reported=True)["route"], "no_op")

    def test_newly_exposed_end_tool_can_finish_without_rechecking_layer(self):
        self.assertEqual(mod.select_finish(result="complete", goal_state="active_same", can_complete=True, already_reported=True)["route"], "native_complete")

    def test_end_failure_or_target_conflict_never_retries(self):
        self.assertEqual(mod.select_finish(result="complete", goal_state="active_same", can_complete=True, finish_failed=True)["route"], "finish_stop")
        for state in ("error", "paused", "other", "active_unbound"):
            self.assertEqual(mod.select_finish(result="complete", goal_state=state, can_complete=True)["route"], "finish_stop")


if __name__ == "__main__":
    unittest.main()
