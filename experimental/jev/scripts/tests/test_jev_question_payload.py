"""Regression: every fixed question the scripts send reaches the HTTP body unchanged.

Why: mocking ask() hides what happens inside it. ask() replaces instruction-like lines (jev_client._INSTR_RE) in the
state AND in the question text with "[指示文を除去]" before sending, so a question that happens to contain e.g.
"answer no" was sent empty while every mocked test passed. Here the real ask() (redact + sanitize) runs and only
route() and _post() are replaced, so the body is checked exactly as it would leave the machine.

Covered paths (one request each): jev_bt_monitor 5.5b / 6b / prompt, jev_prompt_hook (UserPromptSubmit JSON),
jev_coverage_check, aiplc_status_audit --jev (jev_hint), jev_regression_rank and jev_client --check.
When a question text is changed, these tests fail if the new text would be altered before sending.
No network: urllib is blocked and _post is a local recorder. Fictional data only.
"""
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

try:
    import yaml  # noqa: F401  (the scripts need pyyaml; without it these tests are skipped, not errors)
except ImportError:
    raise unittest.SkipTest("pyyaml が無い（pip install pyyaml）")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import aiplc_status_audit as audit  # noqa: E402
import jev_bt_monitor as mon  # noqa: E402
import jev_client  # noqa: E402
import jev_coverage_check as cov  # noqa: E402
import jev_prompt_hook as hook  # noqa: E402
import jev_regression_rank as rank_mod  # noqa: E402
import jev_test_support as jts  # noqa: E402

GOAL = "図書館の本を予約できるアプリを作る"
CRITERIA = ["利用者が本を予約できる", "予約を取り消せる"]
ACCEPTANCE = "予約画面に本の題名と受け取り日が表示される"
UTTERANCE = "受け取りは窓口ではなく宅配にすることになりました。前提が変わります"


def setUpModule():
    jts.isolate()  # fictional extra word list; never the real local file


def tearDownModule():
    jts.restore()


def fixed_texts():
    """(name, text) for every fixed text the scripts put into a request. Add new question constants here."""
    out = [(f"jev_bt_monitor.Q[{k}]", v) for k, v in mon.Q.items()]
    out += [("jev_coverage_check.QUESTION", cov.QUESTION.format(c=c)) for c in CRITERIA]
    out += [("jev_coverage_check NONE choice", "どのタスクもこの成功条件を満たさない")]
    out += [("aiplc_status_audit.JEV_QUESTION", audit.JEV_QUESTION)]
    out += [(f"aiplc_status_audit.JEV_CHOICES[{k}]", v) for k, v in audit.JEV_CHOICES.items()]
    out += [("jev_regression_rank.QUESTION", rank_mod.QUESTION.format(c=ACCEPTANCE))]
    out += [("jev_client.CHECK_QUESTION", jev_client.CHECK_QUESTION), ("jev_client.CHECK_STATE", jev_client.CHECK_STATE)]
    return out


def _strings(v):
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for x in v.values():
            yield from _strings(x)
    elif isinstance(v, list):
        for x in v:
            yield from _strings(x)


class Recorder:
    """Stands in for jev_client._post: keeps a deep copy of each body and answers with numbers only."""

    def __init__(self):
        self.bodies = []

    def __call__(self, url, key, body, timeout, retries):
        self.bodies.append(copy.deepcopy(body))
        answers = {}
        for q, spec in body["questions"].items():
            if spec.get("type") == "choice":
                first = next(iter(spec.get("criteria") or {"x": ""}))
                answers[q] = {"choice": first, "probabilities": {first: 0.9}}
            else:
                answers[q] = {"noul": 0.1}
        return {"answers": answers, "model": "test-model", "usage": {"cost": 0}}, 1.0, None


def _fake_route(with_source=False):
    r = ("http://127.0.0.1:9/v1/systemone", "dummy-key", "test-model", "openrouter")
    return r + ("env",) if with_source else r


def _no_network(*a, **k):
    raise AssertionError("network access in an offline test")


class QuestionPayloadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.rec = Recorder()
        self.passed = []  # (state, questions) handed to ask() by the script, before sanitize
        real_ask = jev_client.ask

        def spy(state, questions, *a, **k):
            self.passed.append((state, copy.deepcopy(questions)))
            return real_ask(state, questions, *a, **k)
        self.spy = spy
        self.log = base / "log.jsonl"
        env = {k: v for k, v in os.environ.items() if k != "JEV_DISABLE"}
        for p in (mock.patch.dict(os.environ, env, clear=True),
                  mock.patch.object(jev_client, "route", side_effect=_fake_route),
                  mock.patch.object(jev_client, "_post", side_effect=self.rec),
                  mock.patch.object(jev_client, "LOG_PATH", self.log),
                  mock.patch.object(jev_client.urllib.request, "urlopen", side_effect=_no_network),
                  mock.patch.object(mon, "COUNTS_STATE_PATH", base / "counts.json"),
                  mock.patch.object(hook, "MARKER_PATH", base / "sessions.json")):
            p.start()
            self.addCleanup(p.stop)
        self.root = base
        self.layer = base / "Flow" / "202601" / "2026-01-01" / "demo-layer"
        self.layer.mkdir(parents=True)
        intent = {"scope_id": "L-0000-1", "jev_monitor": True,
                  "goal": {"description": GOAL, "success_criteria": CRITERIA}}
        backlog = {"tasks": [
            {"id": "T001", "name": "予約画面を作る", "status": "completed", "description": "予約の画面",
             "result": "予約画面を作成し、本の題名と受け取り日を表示した"},
            {"id": "T002", "name": "取り消し機能", "status": "pending", "description": "予約の取り消し"}]}
        (self.layer / "intent.yaml").write_text(yaml.safe_dump(intent, allow_unicode=True), encoding="utf-8")
        (self.layer / "backlog.yaml").write_text(yaml.safe_dump(backlog, allow_unicode=True), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    # ------------------------------------------------------------------ helpers
    def assert_sent_unchanged(self, expected_questions, n=1):
        """One request per call; its question block equals what the script built (and the constants)."""
        self.assertEqual(len(self.rec.bodies), n, "number of requests")
        body = self.rec.bodies[-1]
        raw = json.dumps(body, ensure_ascii=False)
        self.assertNotIn(jev_client.INSTR_PLACEHOLDER, raw)
        self.assertEqual(body["questions"], expected_questions)
        if self.passed:
            state, questions = self.passed[-1]
            self.assertEqual(body["questions"], questions, "sanitize changed the question block")
            self.assertEqual(body["state"], state, "sanitize changed the (fictional, clean) state")
        for s in _strings(body["questions"]):
            self.assertEqual(jev_client.sanitize(s), (s, 0))
        if self.log.exists():
            last = json.loads(self.log.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(last["action"], "answered")
            self.assertEqual(last["sanitized"]["removed_lines"], 0)
        return body

    # ------------------------------------------------------------------ fixed texts alone
    def test_every_fixed_text_passes_sanitize_and_redact(self):
        for name, text in fixed_texts():
            with self.subTest(name=name):
                self.assertEqual(jev_client.sanitize(text), (text, 0))
                self.assertEqual(jev_client.redact(text), (True, None))

    def test_fixed_texts_pass_this_checkouts_do_not_send_list(self):
        """The real list of this checkout (local file / $JEV_REDACT_EXTRA when present) must not stop a question."""
        try:
            jev_client.load_redact_patterns()
            if jev_client._REDACT_ERROR:
                self.skipTest("local do-not-send file has an error (see --redact-status)")
            for name, text in fixed_texts():
                with self.subTest(name=name):
                    self.assertTrue(jev_client.redact(text)[0])
        finally:
            jts.isolate()

    def test_the_detector_sees_the_old_wording(self):
        """Guard for the guard: the wording that used to be stripped is still caught by sanitize()."""
        self.assertEqual(jev_client.sanitize("If there is no user utterance, answer no.")[1], 1)

    # ------------------------------------------------------------------ each sending path
    def test_bt_monitor_phases(self):
        for i, (phase, kw) in enumerate([("5.5b", {"task": "T001", "report": "予約画面を作成した"}),
                                         ("6b", {}),
                                         ("prompt", {"utterance": UTTERANCE})], 1):
            with self.subTest(phase=phase):
                out, rec = mon.monitor(self.layer, phase, ask=self.spy, **kw)
                qid = mon.PHASE_Q[phase]
                self.assert_sent_unchanged({qid: {"type": "noul", "instructions": mon.Q[qid]}}, n=i)
                self.assertEqual(rec["sanitized"]["removed_lines"], 0)

    def test_prompt_hook_user_prompt_submit(self):
        base = {"session_id": "sess-0001", "transcript_path": str(self.root / "t.jsonl"), "cwd": str(self.root),
                "permission_mode": "default", "hook_event_name": "UserPromptSubmit"}
        rel = self.layer.relative_to(self.root)
        self.assertEqual(hook.handle({**base, "prompt": f"/04-operation-jev Layer: {rel}"}, ask=self.spy), "")
        self.assertEqual(self.rec.bodies, [])  # activation itself sends nothing
        hook.handle({**base, "prompt": UTTERANCE}, ask=self.spy)
        body = self.assert_sent_unchanged({"user_signal": {"type": "noul", "instructions": mon.Q["user_signal"]}})
        self.assertIn(UTTERANCE, body["state"])

    def test_coverage_check(self):
        lines, rec = cov.check(self.layer, ask=self.spy)
        self.assertEqual(rec["action"], "answered")
        sent = self.assert_sent_unchanged(self.passed[-1][1])["questions"]
        self.assertEqual([q["instructions"] for q in sent.values()], [cov.QUESTION.format(c=c) for c in CRITERIA])
        for q in sent.values():
            self.assertEqual(q["criteria"][cov.NONE], "どのタスクもこの成功条件を満たさない")

    def test_status_audit_stale_hint(self):
        tasks = [{"id": "T001", "name": "予約画面を作る", "status": "completed", "completed_at": "2026-01-02",
                  "result": "予約画面を作成した"}, {"id": "T002", "name": "取り消し機能", "status": "pending"}]
        layer = SimpleNamespace(intent={"goal": {"description": GOAL}}, raw_tasks=tasks, tasks=tasks,
                                terminal=1, open=1)
        c = {"confidential": False, "jev_opt_in": True, "scope_id": "L-0000-1", "days_since_touch": 40}
        j = audit.jev_hint(c, layer, self.spy)
        self.assertEqual((j["status"], j["sent"]), ("answered", True))
        self.assert_sent_unchanged({"status": {"type": "choice", "instructions": audit.JEV_QUESTION,
                                               "criteria": dict(audit.JEV_CHOICES)}})

    def test_regression_rank(self):
        with mock.patch.object(jev_client, "ask", side_effect=self.spy):
            res = rank_mod.rank([{"id": "R1", "state": "予約画面: 題名と受け取り日を表示", "criterion": ACCEPTANCE}])
        self.assertEqual(res[0]["action"], "answered")
        self.assert_sent_unchanged({"satisfies": {"type": "noul",
                                                  "instructions": rank_mod.QUESTION.format(c=ACCEPTANCE)}})

    def test_check_connection(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(jev_client.check(), 0)
        body = self.assert_sent_unchanged({"ok": {"type": "noul", "instructions": jev_client.CHECK_QUESTION}})
        self.assertEqual(body["state"], jev_client.CHECK_STATE)

    # ------------------------------------------------------------------ JEV_DISABLE is shown as disabled
    def test_disabled_is_reported_as_disabled(self):
        with mock.patch.dict(os.environ, {"JEV_DISABLE": "1"}), \
                mock.patch.object(jev_client, "route", return_value=None):
            rec = jev_client.ask("本文", {"q": {"type": "noul", "instructions": "Is this a test?"}}, "bt_monitor")
            self.assertEqual(rec["action"], "skipped(unavailable:disabled)")
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(jev_client.check(), 1)
            self.assertIn("JEV_DISABLE=1", buf.getvalue())
        self.assertEqual(self.rec.bodies, [])


if __name__ == "__main__":
    unittest.main()
