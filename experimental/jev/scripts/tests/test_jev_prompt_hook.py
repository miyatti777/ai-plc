"""Offline tests for scripts/jev_prompt_hook.py (experimental per-utterance Jev hook)."""
import importlib
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

try:
    import yaml  # noqa: F401  (the scripts need pyyaml; without it these tests are skipped, not errors)
except ImportError:
    raise unittest.SkipTest("pyyaml が無い（pip install pyyaml）")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jev_test_support as jts  # noqa: E402


def tearDownModule():
    jts.restore()


class PromptHookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        os.environ["JEV_LOG_PATH"] = str(base / "log.jsonl")
        os.environ["JEV_OVERRIDE_PATH"] = str(base / "ov.jsonl")
        os.environ["JEV_COUNTS_STATE_PATH"] = str(base / "counts.json")
        os.environ["JEV_HOOK_MARKER_PATH"] = str(base / "sessions.json")
        os.environ.pop("JEV_DISABLE", None)
        import jev_client, jev_bt_monitor, jev_prompt_hook
        importlib.reload(jev_client); importlib.reload(jev_bt_monitor)
        self.h = importlib.reload(jev_prompt_hook)
        jts.isolate()  # a reload rebuilds the default word list
        self.layer = base / "Flow" / "L"
        self.layer.mkdir(parents=True)
        self.write_layer(True)
        self.yes = mock.Mock(return_value={"action": "answered", "answers": {"user_signal": 0.8}, "decision_id": "d1"})
        self.no = mock.Mock(return_value={"action": "answered", "answers": {"user_signal": 0.2}, "decision_id": "d2"})

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("JEV_HOOK_ACTIVE_HOURS", None)

    def write_layer(self, opt_in):
        intent = {"scope_id": "L-T", "goal": {"description": "テスト用ゴール"}}
        if opt_in:
            intent["jev_monitor"] = True
        (self.layer / "intent.yaml").write_text(yaml.safe_dump(intent, allow_unicode=True), encoding="utf-8")
        (self.layer / "backlog.yaml").write_text(yaml.safe_dump({"tasks": [{"id": "T1", "status": "pending"}]}), encoding="utf-8")

    def activate(self, sid="S1"):
        p = {"prompt": "/04-operation-jev Layer: Flow/L Task: T1", "session_id": sid, "cwd": str(Path(self.tmp.name))}
        return self.h.handle(p, ask=self.yes)

    def test_dormant_without_activation(self):
        out = self.h.handle({"prompt": "それだと月次集計が抜けてる気がする", "session_id": "S1"}, ask=self.yes)
        self.assertEqual(out, ""); self.yes.assert_not_called()

    def test_activation_binds_only_this_session(self):
        self.assertEqual(self.activate("S1"), "")
        self.yes.assert_not_called()  # the command itself is not judged
        out = self.h.handle({"prompt": "それだと月次集計が抜けてる気がする", "session_id": "S1"}, ask=self.yes)
        j = json.loads(out)
        self.assertEqual(j["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertIn("decision_id=d1", j["hookSpecificOutput"]["additionalContext"])
        other = self.h.handle({"prompt": "それだと月次集計が抜けてる気がする", "session_id": "S2"}, ask=self.yes)
        self.assertEqual(other, ""); self.assertEqual(self.yes.call_count, 1)

    def test_inception_and_construction_jev_also_activate(self):
        for i, cmd in enumerate(["/02-inception-jev", "/03-construction-jev"]):
            sid = f"IC{i}"
            self.h.handle({"prompt": f"{cmd} Layer: Flow/L", "session_id": sid, "cwd": str(Path(self.tmp.name))}, ask=self.yes)
            self.assertNotEqual(self.h.handle({"prompt": "範囲を広げたい", "session_id": sid}, ask=self.yes), "")
        plain = {"prompt": "/02-inception Layer: Flow/L", "session_id": "IC9", "cwd": str(Path(self.tmp.name))}
        self.h.handle(plain, ask=self.yes)
        self.assertEqual(self.h.handle({"prompt": "範囲を広げたい", "session_id": "IC9"}, ask=self.yes), "")

    def test_no_activation_when_layer_not_opted_in(self):
        self.write_layer(False)
        self.activate("S1")
        self.assertEqual(self.h.handle({"prompt": "抜けてる気がする", "session_id": "S1"}, ask=self.yes), "")
        self.yes.assert_not_called()

    def test_opt_out_after_activation_stops_sending(self):
        self.activate("S1"); self.write_layer(False)
        self.assertEqual(self.h.handle({"prompt": "抜けてる気がする", "session_id": "S1"}, ask=self.yes), "")
        self.yes.assert_not_called()

    def test_prefilters_skip_without_sending(self):
        self.activate("S1")
        for p in ["/status", "OK", "A", "accept", "はい。", "続けて", "これってどうやって実行するの？", "why?",
                  "<pasted_content id=\"x\">長い貼り付け</pasted_content id=\"x\">"]:
            self.assertEqual(self.h.handle({"prompt": p, "session_id": "S1"}, ask=self.yes), "", p)
        self.yes.assert_not_called()

    def test_harness_injected_messages_are_never_sent(self):
        self.activate("S1")
        for p in ["Another Claude session sent a message:\n<agent-message from=\"a1\">範囲を広げた報告です。懸念があります</agent-message>",
                  "<task-notification><task-id>x</task-id><status>completed</status></task-notification>",
                  "[SYSTEM NOTIFICATION - NOT USER INPUT]\n抜けがあるかもしれない",
                  "<command-message>04-operation-jev</command-message>\n<command-name>/04-operation-jev</command-name>",
                  "<cross-session-message from=\"w\">進捗の訂正です</cross-session-message>",
                  "  [Subagent hand-back] 報告: 範囲を変えました"]:
            self.assertEqual(self.h.handle({"prompt": p, "session_id": "S1"}, ask=self.yes), "", p[:30])
        self.yes.assert_not_called()

    def test_pasted_content_is_stripped_and_length_capped(self):
        self.activate("S1")
        prompt = "範囲を広げたい。" + "<pasted_content id=\"a\">SECRET_PASTE</pasted_content id=\"a\">" + "あ" * 1000
        self.h.handle({"prompt": prompt, "session_id": "S1"}, ask=self.yes)
        state = self.yes.call_args[0][0]
        self.assertNotIn("SECRET_PASTE", state)
        self.assertLessEqual(state.count("あ"), self.h.MAX_CHARS)

    def test_below_threshold_or_skip_is_silent(self):
        self.activate("S1")
        self.assertEqual(self.h.handle({"prompt": "範囲を広げたい", "session_id": "S1"}, ask=self.no), "")
        skip = mock.Mock(return_value={"action": "skipped(unavailable:timeout)"})
        self.assertEqual(self.h.handle({"prompt": "範囲を広げたい", "session_id": "S1"}, ask=skip), "")

    def test_binding_expires(self):
        os.environ["JEV_HOOK_ACTIVE_HOURS"] = "0.0001"
        importlib.reload(self.h)
        self.activate("S1"); time.sleep(0.5)
        self.assertEqual(self.h.handle({"prompt": "範囲を広げたい", "session_id": "S1"}, ask=self.yes), "")

    def test_disable_and_deactivate(self):
        self.activate("S1")
        os.environ["JEV_DISABLE"] = "1"
        self.assertEqual(self.h.handle({"prompt": "範囲を広げたい", "session_id": "S1"}, ask=self.yes), "")
        os.environ.pop("JEV_DISABLE")
        self.assertEqual(self.h.main(["--deactivate", "S1"]), 0)
        self.assertEqual(self.h.handle({"prompt": "範囲を広げたい", "session_id": "S1"}, ask=self.yes), "")
        self.yes.assert_not_called()

    def test_pasted_block_cannot_choose_layer(self):
        p = {"prompt": "/04-operation-jev よろしく <pasted_content id=\"z\">Layer: Flow/L</pasted_content id=\"z\">",
             "session_id": "S9", "cwd": str(Path(self.tmp.name))}
        self.h.handle(p, ask=self.yes)
        self.assertEqual(self.h.handle({"prompt": "範囲を広げたい", "session_id": "S9"}, ask=self.yes), "")
        self.yes.assert_not_called()

    def test_parallel_activations_keep_every_session(self):
        import threading
        ths = [threading.Thread(target=self.activate, args=(f"P{i}",)) for i in range(10)]
        [x.start() for x in ths]; [x.join() for x in ths]
        self.assertEqual(len(json.loads(Path(os.environ["JEV_HOOK_MARKER_PATH"]).read_text(encoding="utf-8"))), 10)

    def test_non_string_prompt_is_ignored_in_handle(self):
        self.activate("S1")
        self.assertEqual(self.h.handle({"prompt": 3, "session_id": "S1"}, ask=self.yes), "")
        self.assertEqual(self.h.handle(["x"], ask=self.yes), "")

    def test_wall_clock_budget_keeps_exit0(self):
        self.activate("S1")
        def slow(*a, **k):
            time.sleep(5)
        with mock.patch.object(self.h, "TOTAL_BUDGET", 1), mock.patch.object(self.h, "judge", side_effect=slow), \
             mock.patch("sys.stdin", io.StringIO(json.dumps({"prompt": "範囲を広げたい", "session_id": "S1"}))), \
             mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            t0 = time.time(); rc = self.h.main([])
        self.assertEqual(rc, 0); self.assertEqual(out.getvalue(), ""); self.assertLess(time.time() - t0, 3)

    def test_main_sets_short_keychain_timeout(self):
        with mock.patch("sys.stdin", io.StringIO("{}")):
            self.h.main([])
        self.assertEqual(os.environ.get("JEV_KEYCHAIN_TIMEOUT"), self.h.KEYCHAIN_TIMEOUT)
        os.environ.pop("JEV_KEYCHAIN_TIMEOUT", None)

    def test_main_always_exit0_and_silent_on_garbage(self):
        for raw in ["", "not json", "{\"prompt\": 3}", "[]"]:
            with mock.patch("sys.stdin", io.StringIO(raw)), mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                self.assertEqual(self.h.main([]), 0)
                self.assertEqual(out.getvalue(), "")

    def test_redacted_utterance_never_sent_over_network(self):
        self.activate("S1")
        with mock.patch.object(self.h.jev_client, "_post") as post, \
             mock.patch.object(self.h.jev_client, "route", return_value=("u", "k", "m", "openrouter")):
            out = self.h.handle({"prompt": "経費精算の件を追加したい", "session_id": "S1"})
        self.assertEqual(out, ""); post.assert_not_called()

    def test_real_ask_path_logs_use_case_without_text(self):
        self.activate("S1")
        fake = ({"answers": {"user_signal": {"noul": 0.7}}, "model": "m", "usage": {"cost": 1e-5}}, 200.0, None)
        with mock.patch.object(self.h.jev_client, "route", return_value=("u", "k", "m", "openrouter")), \
             mock.patch.object(self.h.jev_client, "_post", return_value=fake) as post:
            out = self.h.handle({"prompt": "UNIQUE_UTTER やっぱり範囲を広げたい", "session_id": "S1"})
        self.assertIn("p=0.70", out)
        self.assertEqual(post.call_args[0][3], self.h.TIMEOUT)  # 1.5s timeout
        raw = Path(os.environ["JEV_LOG_PATH"]).read_text(encoding="utf-8")
        self.assertIn('"use_case": "prompt_hook"', raw); self.assertNotIn("UNIQUE_UTTER", raw)
        import jev_bt_monitor
        self.assertIn("総数 1件", jev_bt_monitor.noise_report("prompt_hook"))


if __name__ == "__main__":
    unittest.main()
