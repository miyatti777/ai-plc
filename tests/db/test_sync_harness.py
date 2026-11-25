"""Non-destructive regression harness for ``.claude/db/sync.py``.

Every sync command in this module is redirected to a temporary SQLite database
and a fake Notion API.  A per-test fingerprint guard fails the suite if the
production database changes for any reason.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
import sqlite3
import tempfile
import unittest
import urllib.error
import warnings
from collections import deque
from contextlib import closing
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
DB_DIR = REPO_ROOT / "core" / "db"
PRODUCTION_DB = DB_DIR / "ai_plc.db"
# 公開版の sync.py は Notion の DB の ID を環境変数から読む。試験では架空の ID を使う（Notion には送らない）
os.environ.setdefault("AI_PLC_PROJECTS_DB_ID", "11111111-1111-4111-8111-111111111111")
os.environ.setdefault("AI_PLC_TASKS_DB_ID", "22222222-2222-4222-8222-222222222222")
FIXED_NOW = "2026-07-10T12:34:56Z"
FIXED_NOTION_EDITED = "2026-07-10T12:34:57.000Z"


def file_fingerprint(path: Path) -> tuple[int, int, str]:
    """Return size, nanosecond mtime, and SHA-256 without opening SQLite (None when absent)."""
    if not path.exists():  # 公開版のリポジトリには ai_plc.db が無い。現れたら差として検出される
        return None
    stat = path.stat()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return stat.st_size, stat.st_mtime_ns, digest


def load_module(path: Path, name: str):
    """Load a repository script without adding its directory to ``sys.path``."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeNotionAPI:
    """Deterministic callable with response queues, call logs, and failures."""

    def __init__(self, responses=None, *, fail_on_call=None, failure=None):
        self.responses = deque(
            response if isinstance(response, BaseException) else copy.deepcopy(response)
            for response in (responses or [])
        )
        self.fail_on_call = fail_on_call
        self.failure = failure or RuntimeError("injected Notion API failure")
        self.calls = []

    def __call__(self, method, path, body=None, retries=3):
        self.calls.append(
            {
                "method": method,
                "path": path,
                "body": copy.deepcopy(body),
                "retries": retries,
            }
        )
        if self.fail_on_call == len(self.calls):
            raise self.failure
        if not self.responses:
            raise AssertionError(
                f"unexpected API call without a queued response: {method} {path}"
            )
        response = self.responses.popleft()
        if isinstance(response, BaseException):
            raise response
        return copy.deepcopy(response)


class SyncHarnessTest(unittest.TestCase):
    """Run sync behavior against disposable resources only."""

    def setUp(self):
        self.production_before = file_fingerprint(PRODUCTION_DB)
        self.addCleanup(self._assert_production_db_unchanged)

        self.temp_dir = tempfile.TemporaryDirectory(prefix="ai-plc-sync-test-")
        self.addCleanup(self.temp_dir.cleanup)
        self.test_db = Path(self.temp_dir.name) / "ai_plc_test.db"

        init_db = load_module(DB_DIR / "init_db.py", f"ai_plc_init_test_{id(self)}")
        with (
            closing(sqlite3.connect(self.test_db)) as conn,
            contextlib.redirect_stdout(io.StringIO()),
            warnings.catch_warnings(),
        ):
            warnings.simplefilter("ignore", DeprecationWarning)
            init_db.create_schema(conn)

        self.sync = load_module(DB_DIR / "sync.py", f"ai_plc_sync_test_{id(self)}")
        self.fake_api = FakeNotionAPI()
        self.sync.DB_PATH = str(self.test_db)
        self.sync.TOKEN = "dummy-test-token"
        self.sync.RATE_LIMIT_DELAY = 0
        self.sync._now_iso = lambda: FIXED_NOW
        self.real_api_call = self.sync._api_call
        self.sync._api_call = self.fake_api

        # Track connections so an injected exception cannot leak a handle.
        real_get_conn = self.sync._get_conn
        self.opened_connections = []

        def tracked_get_conn():
            conn = real_get_conn()
            self.opened_connections.append(conn)
            return conn

        self.sync._get_conn = tracked_get_conn
        self.addCleanup(self._close_tracked_connections)

        # If a future refactor bypasses _api_call, fail instead of using a socket.
        self.network_guard = mock.patch.object(
            self.sync.urllib.request,
            "urlopen",
            side_effect=AssertionError("network access is forbidden in sync tests"),
        )
        self.network_guard.start()
        self.addCleanup(self.network_guard.stop)

    def _assert_production_db_unchanged(self):
        self.assertEqual(
            self.production_before,
            file_fingerprint(PRODUCTION_DB),
            "production .claude/db/ai_plc.db changed during an isolated test",
        )

    def _close_tracked_connections(self):
        for conn in self.opened_connections:
            conn.close()
        self.opened_connections.clear()

    def _install_fake_api(self, responses=None, *, fail_on_call=None, failure=None):
        self.fake_api = FakeNotionAPI(
            responses, fail_on_call=fail_on_call, failure=failure
        )
        self.sync._api_call = self.fake_api
        return self.fake_api

    def _database_response(self, schema):
        return {
            "properties": {
                name: {"id": f"property-{index}", "type": property_type}
                for index, (name, property_type) in enumerate(schema.items(), start=1)
            },
            "last_edited_time": FIXED_NOTION_EDITED,
        }

    def _valid_schema_responses(self):
        return [
            self._database_response(self.sync.PROJECTS_NOTION_SCHEMA),
            self._database_response(self.sync.TASKS_NOTION_SCHEMA),
        ]

    @staticmethod
    def _empty_query_response():
        return {"results": [], "has_more": False, "next_cursor": None}

    def _valid_reconciliation_responses(self, project_pages=None, task_pages=None):
        project_query = self._empty_query_response()
        project_query["results"] = copy.deepcopy(project_pages or [])
        task_query = self._empty_query_response()
        task_query["results"] = copy.deepcopy(task_pages or [])
        return [project_query, task_query]

    def _valid_absence_revalidation_responses(
        self, project_pages=None, task_pages=None
    ):
        return self._valid_reconciliation_responses(project_pages, task_pages)

    def _install_sync_api(
        self,
        responses=None,
        *,
        project_pages=None,
        task_pages=None,
        revalidation_project_pages=None,
        revalidation_task_pages=None,
        fail_on_mutation=None,
        failure=None,
    ):
        queued = (
            self._valid_schema_responses()
            + self._valid_reconciliation_responses(project_pages, task_pages)
            + self._valid_absence_revalidation_responses(
                revalidation_project_pages, revalidation_task_pages
            )
            + list(responses or [])
        )
        fail_on_call = None
        if fail_on_mutation is not None:
            fail_on_call = (
                len(self._valid_schema_responses())
                + len(self._valid_reconciliation_responses())
                + len(self._valid_absence_revalidation_responses())
                + fail_on_mutation
            )
        return self._install_fake_api(
            queued, fail_on_call=fail_on_call, failure=failure
        )

    @staticmethod
    def _mutation_calls(api):
        return [
            call for call in api.calls
            if call["method"] in {"PATCH", "DELETE"}
            or (call["method"] == "POST" and call["path"] == "/v1/pages")
        ]

    def _connect(self):
        conn = sqlite3.connect(self.test_db)
        conn.row_factory = sqlite3.Row
        return conn

    def _insert_project(self, scope_id="L-TEST-PROJECT", notion_page_id=None):
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO projects
                    (notion_page_id, scope_id, name, goal, status, mode, depth, system,
                     last_sync_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    notion_page_id,
                    scope_id,
                    "Temporary Project",
                    "Isolated fixture",
                    "active",
                    "direct",
                    "standard",
                    "AI-PLC",
                    "2026-07-09T10:00:00Z",
                    "2026-07-01T00:00:00Z",
                    "2026-07-09T09:00:00Z",
                ),
            )
            conn.commit()

    def _insert_task(self, task_id="T-TEST", scope_id="L-TEST-PROJECT"):
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO tasks
                    (task_id, scope_id, name, status, type, priority,
                     last_sync_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    scope_id,
                    "Temporary Task",
                    "未着手",
                    "implementation",
                    "P1",
                    "2026-07-09T10:00:00Z",
                    "2026-07-01T00:00:00Z",
                    "2026-07-09T09:00:00Z",
                ),
            )
            conn.commit()

    def _run_push(self, *, dry_run=False):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.sync.cmd_push(dry_run=dry_run)
        return output.getvalue()

    def _run_status(self, *, audit=False):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.sync.cmd_status(audit=audit)
        return output.getvalue()

    def _page_response(self, parent_id, *, archived=False, in_trash=False):
        return {
            "id": "linked-page",
            "archived": archived,
            "in_trash": in_trash,
            "parent": {"type": "database_id", "database_id": parent_id},
            "last_edited_time": FIXED_NOTION_EDITED,
        }

    @staticmethod
    def _plain_text(value):
        return [{"plain_text": value}] if value is not None else []

    def _project_page(
        self, page_id, scope_id, name, *, parent_scope=None, edited=FIXED_NOTION_EDITED
    ):
        return {
            "id": page_id,
            "last_edited_time": edited,
            "parent": {
                "type": "database_id",
                "database_id": self.sync.PROJECTS_DB_ID,
            },
            "properties": {
                "PJ名": {"title": self._plain_text(name)},
                "Scope ID": {"rich_text": self._plain_text(scope_id)},
                "親Scope": {"rich_text": self._plain_text(parent_scope)},
            },
        }

    def _task_page(
        self, page_id, scope_id, task_id, name, *, edited=FIXED_NOTION_EDITED
    ):
        return {
            "id": page_id,
            "last_edited_time": edited,
            "parent": {
                "type": "database_id",
                "database_id": self.sync.TASKS_DB_ID,
            },
            "properties": {
                "タスク名": {"title": self._plain_text(name)},
                "Scope ID": {"rich_text": self._plain_text(scope_id)},
                "Task ID": {"rich_text": self._plain_text(task_id)},
            },
        }

    def _run_preflight_report(self, page_responses=None):
        api = self._install_fake_api(
            self._valid_schema_responses() + list(page_responses or [])
        )
        with closing(self._connect()) as conn:
            report = self.sync.run_preflight(conn)
        return report, api

    def test_project_missing_notion_id_is_created_despite_last_sync(self):
        self._insert_project()
        self._install_sync_api()

        output = self._run_push(dry_run=True)
        status = self._run_status()

        self.assertIn("[CREATE] L-TEST-PROJECT", output)
        self.assertIn("Projects: 1 total, 1 dirty, 1 new", status)
        self.assertEqual(4, len(self.fake_api.calls))
        self.assertEqual([], self._mutation_calls(self.fake_api))

    def test_task_missing_notion_id_is_created_despite_last_sync(self):
        self._insert_task()
        self._install_sync_api()

        output = self._run_push(dry_run=True)
        status = self._run_status()

        self.assertIn("[CREATE] L-TEST-PROJECT/T-TEST", output)
        self.assertIn("Tasks: 1 total, 1 dirty, 1 new", status)
        self.assertEqual(4, len(self.fake_api.calls))
        self.assertEqual([], self._mutation_calls(self.fake_api))

    def test_fake_push_updates_only_temporary_database(self):
        self._insert_project()
        self._insert_task()
        operation_now = "2099-01-01T00:00:00Z"
        self.sync._now_iso = lambda: operation_now
        self._install_sync_api(
            [
                {"id": "fake-notion-page-1", "last_edited_time": FIXED_NOTION_EDITED},
                {"id": "fake-notion-page-2", "last_edited_time": FIXED_NOTION_EDITED},
            ]
        )

        output = self._run_push()

        self.assertEqual(8, len(self.fake_api.calls))
        project_call, task_call = self._mutation_calls(self.fake_api)
        self.assertEqual(("POST", "/v1/pages"), (project_call["method"], project_call["path"]))
        self.assertEqual(("POST", "/v1/pages"), (task_call["method"], task_call["path"]))
        self.assertEqual(
            {"database_id": self.sync.PROJECTS_DB_ID}, project_call["body"]["parent"]
        )
        self.assertEqual(
            {"database_id": self.sync.TASKS_DB_ID}, task_call["body"]["parent"]
        )
        self.assertEqual(
            {
                "PJ名", "Goal", "Scope ID", "ステータス", "モード", "深度",
                "システム", "親Scope", "トップページ", "開始日", "期限",
                "Sync UID", "Workspace ID", "Ownership Epoch", "Identity Version",
            },
            set(project_call["body"]["properties"]),
        )
        self.assertEqual(
            {
                "タスク名", "Task ID", "Scope ID", "ステータス", "タイプ",
                "優先度", "見積(日)", "成果物", "完了日",
                "Project Sync UID", "Workspace ID", "Project Ownership Epoch",
                "Identity Version",
            },
            set(task_call["body"]["properties"]),
        )
        self.assertIn("fake-notion-page-1", output)
        self.assertIn("fake-notion-page-2", output)
        with closing(self._connect()) as conn:
            project = conn.execute(
                "SELECT notion_page_id, last_sync_at, notion_last_edited FROM projects"
            ).fetchone()
            task = conn.execute(
                "SELECT notion_page_id, last_sync_at, notion_last_edited FROM tasks"
            ).fetchone()
        self.assertEqual(
            ("fake-notion-page-1", operation_now, FIXED_NOTION_EDITED), tuple(project)
        )
        self.assertEqual(
            ("fake-notion-page-2", operation_now, FIXED_NOTION_EDITED), tuple(task)
        )

    def test_multiple_creates_use_per_operation_baselines_and_only_real_edit_patches(self):
        self._insert_project()
        self._insert_task()
        with closing(self._connect()) as conn:
            conn.executescript("""
                DROP TRIGGER trg_projects_updated;
                DROP TRIGGER trg_tasks_updated;
                CREATE TRIGGER trg_projects_updated
                AFTER UPDATE ON projects
                WHEN OLD.last_sync_at IS NEW.last_sync_at
                BEGIN
                    UPDATE projects SET updated_at = '2099-01-01T00:00:01Z'
                    WHERE id = NEW.id;
                END;
                CREATE TRIGGER trg_tasks_updated
                AFTER UPDATE ON tasks
                WHEN OLD.last_sync_at IS NEW.last_sync_at
                BEGIN
                    UPDATE tasks SET updated_at = '2099-01-01T00:00:03Z'
                    WHERE id = NEW.id;
                END;
            """)
            conn.commit()
        api = self._install_sync_api([
            {"id": "multi-create-project", "last_edited_time": FIXED_NOTION_EDITED},
            {"id": "multi-create-task", "last_edited_time": FIXED_NOTION_EDITED},
        ])
        plan = self.sync.build_push_plan()
        operation_times = iter([
            "2099-01-01T00:00:00Z",
            "2099-01-01T00:00:02Z",
            "2099-01-01T00:00:04Z",
        ])
        self.sync._now_iso = lambda: next(operation_times)

        result = self.sync.execute_push_plan(plan)

        self.assertEqual(0, result)
        self.assertEqual(2, len(self._mutation_calls(api)))
        with closing(self._connect()) as conn:
            project = conn.execute(
                "SELECT updated_at, last_sync_at FROM projects"
            ).fetchone()
            task = conn.execute(
                "SELECT updated_at, last_sync_at FROM tasks"
            ).fetchone()
        self.assertEqual(
            ("2099-01-01T00:00:01Z", "2099-01-01T00:00:02Z"), tuple(project)
        )
        self.assertEqual(
            ("2099-01-01T00:00:03Z", "2099-01-01T00:00:04Z"), tuple(task)
        )

        self.sync._now_iso = lambda: "2099-01-01T00:00:10Z"
        self._install_fake_api(self._valid_reconciliation_responses())
        clean_plan = self.sync.build_push_plan(skip_preflight=True)
        self.assertEqual([], clean_plan["operations"])

        with closing(self._connect()) as conn:
            conn.executescript("""
                DROP TRIGGER trg_projects_updated;
                CREATE TRIGGER trg_projects_updated
                AFTER UPDATE ON projects
                WHEN OLD.last_sync_at IS NEW.last_sync_at
                BEGIN
                    UPDATE projects SET updated_at = '2099-01-01T00:00:05Z'
                    WHERE id = NEW.id;
                END;
            """)
            conn.execute("UPDATE projects SET goal='Real local edit'")
            conn.commit()
        project_page = self._project_page(
            "multi-create-project", "L-TEST-PROJECT", "Temporary Project"
        )
        patch_api = self._install_fake_api(
            self._valid_reconciliation_responses(project_pages=[project_page])
            + [{"id": "multi-create-project", "last_edited_time": FIXED_NOTION_EDITED}]
        )
        edit_plan = self.sync.build_push_plan(skip_preflight=True)
        self.assertEqual(1, edit_plan["summary"]["patch_remote"])
        self.assertEqual("project", edit_plan["operations"][0]["entity"])
        self.assertEqual(0, self.sync.execute_push_plan(edit_plan))
        self.assertEqual(1, len(self._mutation_calls(patch_api)))

        self._install_fake_api(self._valid_reconciliation_responses())
        rerun_plan = self.sync.build_push_plan(skip_preflight=True)
        self.assertEqual([], rerun_plan["operations"])

    def test_phase_b_cas_preserves_concurrent_local_edit_and_old_baseline(self):
        self._insert_project(notion_page_id="linked-page")
        with closing(self._connect()) as conn:
            conn.executescript("""
                DROP TRIGGER trg_projects_updated;
                CREATE TRIGGER trg_projects_updated
                AFTER UPDATE ON projects
                WHEN OLD.last_sync_at IS NEW.last_sync_at
                BEGIN
                    UPDATE projects SET updated_at = '2099-01-01T00:00:05Z'
                    WHERE id = NEW.id;
                END;
            """)
            conn.execute("UPDATE projects SET goal='Planned local edit'")
            old_baseline = conn.execute(
                "SELECT last_sync_at FROM projects"
            ).fetchone()[0]
            conn.commit()
        project_page = self._project_page(
            "linked-page", "L-TEST-PROJECT", "Temporary Project"
        )
        api = self._install_fake_api(
            self._valid_reconciliation_responses(project_pages=[project_page])
            + [{"id": "linked-page", "last_edited_time": FIXED_NOTION_EDITED}]
        )
        plan = self.sync.build_push_plan(skip_preflight=True)
        self.sync._now_iso = lambda: "2099-01-01T00:00:10Z"

        def inject_concurrent_edit(point, operation, response=None):
            if point != "before_phase_b_commit":
                return
            with closing(self._connect()) as concurrent:
                concurrent.execute("UPDATE projects SET goal=?", ("Concurrent local edit",))
                concurrent.commit()

        self.sync._push_failure_hook = inject_concurrent_edit
        result = self.sync.execute_push_plan(plan)

        self.assertEqual(4, result)
        self.assertEqual(1, len(self._mutation_calls(api)))
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT goal, updated_at, last_sync_at FROM projects"
            ).fetchone()
        self.assertEqual(
            ("Concurrent local edit", "2099-01-01T00:00:05Z", old_baseline),
            tuple(row),
        )

    def test_fixed_clock_updates_push_metadata(self):
        self._insert_project()
        self._install_sync_api(
            [{"id": "fixed-clock-page", "last_edited_time": FIXED_NOTION_EDITED}]
        )

        self._run_push()

        with closing(self._connect()) as conn:
            value = conn.execute(
                "SELECT value FROM _metadata WHERE key='last_push_at'"
            ).fetchone()[0]
        self.assertEqual(FIXED_NOW, value)

    def test_failure_injection_aborts_without_persisting_created_id(self):
        self._insert_project()
        failing_api = self._install_sync_api(fail_on_mutation=1)

        with contextlib.redirect_stdout(io.StringIO()):
            result = self.sync.cmd_push()

        self.assertEqual(4, result)
        self.assertEqual(7, len(failing_api.calls))
        self.assertEqual(1, len(self._mutation_calls(failing_api)))
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT notion_page_id, last_sync_at FROM projects"
            ).fetchone()
            last_push = conn.execute(
                "SELECT value FROM _metadata WHERE key='last_push_at'"
            ).fetchone()
        self.assertEqual((None, "2026-07-09T10:00:00Z"), tuple(row))
        self.assertIsNone(last_push)

    def test_keyboard_interrupt_rolls_back_and_harness_closes_connection(self):
        self._insert_project()
        interrupted_api = self._install_sync_api(
            fail_on_mutation=1, failure=KeyboardInterrupt()
        )

        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                self.sync.cmd_push()

        interrupted_conn = self.opened_connections[0]
        self._close_tracked_connections()
        self.assertEqual(7, len(interrupted_api.calls))
        self.assertEqual(1, len(self._mutation_calls(interrupted_api)))
        with self.assertRaises(sqlite3.ProgrammingError):
            interrupted_conn.execute("SELECT 1")
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT notion_page_id, last_sync_at FROM projects"
            ).fetchone()
            last_push = conn.execute(
                "SELECT value FROM _metadata WHERE key='last_push_at'"
            ).fetchone()
        self.assertEqual((None, "2026-07-09T10:00:00Z"), tuple(row))
        self.assertIsNone(last_push)

    def test_partial_success_rollback_can_be_replayed_deterministically(self):
        self._insert_project()
        operation_now = "2099-01-01T00:00:00Z"
        self.sync._now_iso = lambda: operation_now
        first_attempt = self._install_sync_api(
            [{"id": "remote-project-from-first-attempt", "last_edited_time": FIXED_NOTION_EDITED}],
        )

        def fail_after_remote(point, operation, response=None):
            if point == "after_remote_mutation":
                raise RuntimeError("injected after remote success")

        self.sync._push_failure_hook = fail_after_remote

        with contextlib.redirect_stdout(io.StringIO()):
            result = self.sync.cmd_push()

        self.assertEqual(4, result)
        with closing(self._connect()) as conn:
            project_id = conn.execute("SELECT notion_page_id FROM projects").fetchone()[0]
            pending = conn.execute(
                "SELECT COUNT(*) FROM _metadata WHERE key LIKE 'pending_push:%'"
            ).fetchone()[0]
        self.assertIsNone(project_id)
        self.assertEqual(1, pending)

        second_attempt = self._install_fake_api(
            self._valid_schema_responses()
            + self._valid_reconciliation_responses()
        )
        self.sync._push_failure_hook = lambda *args, **kwargs: None
        result = self.sync.cmd_push()

        first_mutations = self._mutation_calls(first_attempt)
        second_mutations = self._mutation_calls(second_attempt)
        self.assertEqual(0, result)
        self.assertEqual(1, len(first_mutations))
        self.assertEqual(0, len(second_mutations))
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT notion_page_id, last_sync_at FROM projects"
            ).fetchone()
            pending = conn.execute(
                "SELECT COUNT(*) FROM _metadata WHERE key LIKE 'pending_push:%'"
            ).fetchone()[0]
        self.assertEqual(("remote-project-from-first-attempt", operation_now), tuple(row))
        self.assertEqual(0, pending)

    def test_push_plan_artifact_round_trip_and_expected_id(self):
        self._insert_project()
        self._install_sync_api()
        plan = self.sync.build_push_plan()
        artifact = Path(self.temp_dir.name) / "push-plan.json"

        self.sync.write_push_plan(plan, artifact)
        loaded = self.sync.load_push_plan(artifact)

        self.assertEqual(plan, loaded)
        self.assertTrue(self.sync.validate_push_plan(
            loaded, expected_plan_id=plan["plan_id"]
        ))
        self.assertFalse(self.sync.validate_push_plan(
            loaded, expected_plan_id="0" * 64
        ))

    def test_dry_run_and_execute_consume_the_same_push_plan(self):
        self._insert_project()
        api = self._install_sync_api([
            {"id": "same-plan-page", "last_edited_time": FIXED_NOTION_EDITED}
        ])

        plan = self.sync.build_push_plan()
        calls_after_build = len(api.calls)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            dry_result = self.sync.cmd_push(dry_run=True, plan=plan)
            execute_result = self.sync.cmd_push(
                plan=plan, expected_plan_id=plan["plan_id"]
            )

        self.assertEqual((0, 0), (dry_result, execute_result))
        self.assertEqual(1, plan["summary"]["create_remote"])
        self.assertIn(plan["plan_id"], output.getvalue())
        self.assertEqual(0, len(self._mutation_calls(api)) - 1)
        self.assertGreater(len(api.calls), calls_after_build)

    def test_tampered_push_plan_is_rejected_before_mutation(self):
        self._insert_project()
        api = self._install_sync_api()
        plan = self.sync.build_push_plan()
        plan["operations"][0]["stable_key"] = ["TAMPERED"]

        result = self.sync.cmd_push(plan=plan, expected_plan_id=plan["plan_id"])

        self.assertEqual(2, result)
        self.assertEqual([], self._mutation_calls(api))

    def test_existing_create_claim_blocks_concurrent_post(self):
        self._insert_project()
        api = self._install_sync_api()
        plan = self.sync.build_push_plan()
        operation = plan["operations"][0]
        pending = {
            "entity": operation["entity"],
            "stable_key": operation["stable_key"],
            "fingerprint": operation["expected_local_fingerprint"],
            "plan_id": plan["plan_id"],
            "claimed_by_pid": 999999,
            "claimed_at": FIXED_NOW,
        }
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO _metadata(key, value) VALUES (?, ?)",
                ("pending_push:%s" % operation["operation_id"],
                 self.sync.json.dumps(pending)),
            )
            conn.commit()

        pending_key = "pending_push:%s" % operation["operation_id"]
        self.sync.ACTIVE_PUSH_CLAIMS.add(pending_key)
        self.addCleanup(self.sync.ACTIVE_PUSH_CLAIMS.discard, pending_key)
        result = self.sync.execute_push_plan(plan)

        self.assertEqual(4, result)
        self.assertEqual([], self._mutation_calls(api))

    def test_live_other_process_claim_blocks_concurrent_post(self):
        self._insert_project()
        api = self._install_sync_api()
        plan = self.sync.build_push_plan()
        operation = plan["operations"][0]
        pending = {
            "entity": operation["entity"],
            "stable_key": operation["stable_key"],
            "fingerprint": operation["expected_local_fingerprint"],
            "plan_id": plan["plan_id"],
            "claimed_by_pid": 424242,
            "claimed_at": FIXED_NOW,
        }
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO _metadata(key, value) VALUES (?, ?)",
                ("pending_push:%s" % operation["operation_id"],
                 self.sync.json.dumps(pending)),
            )
            conn.commit()

        with mock.patch.object(self.sync, "_pid_is_alive", return_value=True):
            result = self.sync.execute_push_plan(plan)

        self.assertEqual(4, result)
        self.assertEqual([], self._mutation_calls(api))

    def test_expired_claim_is_not_blocked_by_reused_live_pid(self):
        self._insert_project()
        api = self._install_sync_api([
            {"id": "lease-recovery-page", "last_edited_time": FIXED_NOTION_EDITED}
        ])
        plan = self.sync.build_push_plan()
        operation = plan["operations"][0]
        pending = {
            "entity": operation["entity"],
            "stable_key": operation["stable_key"],
            "fingerprint": operation["expected_local_fingerprint"],
            "plan_id": plan["plan_id"],
            "claimed_by_pid": 424242,
            "claimed_at": "2026-07-10T12:00:00Z",
            "process_identity": "old process start",
        }
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO _metadata(key, value) VALUES (?, ?)",
                ("pending_push:%s" % operation["operation_id"],
                 self.sync.json.dumps(pending)),
            )
            conn.commit()

        with mock.patch.object(
            self.sync, "_process_identity", return_value="new process start"
        ):
            result = self.sync.execute_push_plan(plan)

        self.assertEqual(0, result)
        self.assertEqual(1, len(self._mutation_calls(api)))

    def test_same_process_identity_keeps_claim_beyond_lease(self):
        self._insert_project()
        api = self._install_sync_api()
        plan = self.sync.build_push_plan()
        operation = plan["operations"][0]
        pending = {
            "entity": operation["entity"],
            "stable_key": operation["stable_key"],
            "fingerprint": operation["expected_local_fingerprint"],
            "plan_id": plan["plan_id"],
            "claimed_by_pid": 424242,
            "claimed_at": "2026-07-10T12:00:00Z",
            "process_identity": "same process start",
        }
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO _metadata(key, value) VALUES (?, ?)",
                ("pending_push:%s" % operation["operation_id"],
                 self.sync.json.dumps(pending)),
            )
            conn.commit()

        with mock.patch.object(
            self.sync, "_process_identity", return_value="same process start"
        ):
            result = self.sync.execute_push_plan(plan)

        self.assertEqual(4, result)
        self.assertEqual([], self._mutation_calls(api))

    def test_identity_lookup_failure_uses_fresh_live_pid_fallback(self):
        self._insert_project()
        api = self._install_sync_api()
        plan = self.sync.build_push_plan()
        operation = plan["operations"][0]
        pending = {
            "entity": operation["entity"],
            "stable_key": operation["stable_key"],
            "fingerprint": operation["expected_local_fingerprint"],
            "plan_id": plan["plan_id"],
            "claimed_by_pid": 424242,
            "claimed_at": FIXED_NOW,
            "process_identity": "stored process start",
        }
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO _metadata(key, value) VALUES (?, ?)",
                ("pending_push:%s" % operation["operation_id"],
                 self.sync.json.dumps(pending)),
            )
            conn.commit()

        with (
            mock.patch.object(self.sync, "_process_identity", return_value=None),
            mock.patch.object(self.sync, "_pid_is_alive", return_value=True),
        ):
            result = self.sync.execute_push_plan(plan)

        self.assertEqual(4, result)
        self.assertEqual([], self._mutation_calls(api))

    def test_stale_claim_without_page_id_can_be_replanned(self):
        self._insert_project()
        api = self._install_sync_api([
            {"id": "replanned-page", "last_edited_time": FIXED_NOTION_EDITED}
        ])
        plan = self.sync.build_push_plan()
        operation = plan["operations"][0]
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO _metadata(key, value) VALUES (?, ?)",
                ("pending_push:%s" % operation["operation_id"], "{}"),
            )
            conn.commit()

        result = self.sync.execute_push_plan(plan)

        self.assertEqual(0, result)
        self.assertEqual(1, len(self._mutation_calls(api)))

    def test_pending_remote_id_requires_current_fingerprint_match(self):
        self._insert_project()
        self._install_sync_api()
        plan = self.sync.build_push_plan()
        operation = plan["operations"][0]
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO _metadata(key, value) VALUES (?, ?)",
                ("pending_push:%s" % operation["operation_id"], self.sync.json.dumps({
                    "entity": "project", "stable_key": operation["stable_key"],
                    "fingerprint": "different", "remote_page_id": "old-page",
                })),
            )
            conn.commit()

        rebuilt = self.sync.build_push_plan(skip_preflight=True)

        self.assertEqual("create_remote", rebuilt["operations"][0]["action"])

    def test_second_push_has_zero_create_calls_and_zero_row_delta(self):
        self._insert_project()
        self.sync._now_iso = lambda: "2099-01-01T00:00:00Z"
        first = self._install_sync_api([
            {"id": "idempotent-page", "last_edited_time": FIXED_NOTION_EDITED}
        ])
        first_result = self.sync.cmd_push()
        with closing(self._connect()) as conn:
            rows_after_first = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]

        second = self._install_fake_api(
            self._valid_schema_responses()
            + [self._page_response(self.sync.PROJECTS_DB_ID)]
        )
        second_result = self.sync.cmd_push()
        with closing(self._connect()) as conn:
            rows_after_second = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]

        self.assertEqual((0, 0), (first_result, second_result))
        self.assertEqual(1, len(self._mutation_calls(first)))
        self.assertEqual(0, len(self._mutation_calls(second)))
        self.assertEqual(0, rows_after_second - rows_after_first)

    def test_preflight_valid_schema_and_no_links_passes(self):
        self._install_sync_api()

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = self.sync.cmd_preflight()

        self.assertEqual(0, result)
        self.assertIn("Preflight: PASS", output.getvalue())
        self.assertEqual(
            [
                ("GET", f"/v1/databases/{self.sync.PROJECTS_DB_ID}"),
                ("GET", f"/v1/databases/{self.sync.TASKS_DB_ID}"),
            ],
            [(call["method"], call["path"]) for call in self.fake_api.calls],
        )
        self.assertEqual([], self._mutation_calls(self.fake_api))

    def test_preflight_classifies_valid_not_found_wrong_parent_and_trashed(self):
        cases = (
            (
                "valid",
                "valid",
                self._page_response(self.sync.PROJECTS_DB_ID),
                "pass",
            ),
            (
                "not_found",
                "not_found",
                urllib.error.HTTPError(
                    "https://api.notion.test/page", 404, "not found", {}, None
                ),
                "blocked",
            ),
            (
                "wrong_parent",
                "wrong_parent",
                self._page_response("00000000-0000-0000-0000-000000000000"),
                "blocked",
            ),
            (
                "trashed",
                "trashed",
                self._page_response(self.sync.PROJECTS_DB_ID, in_trash=True),
                "blocked",
            ),
            (
                "http_503",
                None,
                urllib.error.HTTPError(
                    "https://api.notion.test/page", 503, "unavailable", {}, None
                ),
                "blocked",
            ),
            (
                "network_error",
                None,
                urllib.error.URLError("temporary outage"),
                "blocked",
            ),
        )

        for label, expected_state, page_response, expected_status in cases:
            with self.subTest(label=label):
                with closing(self._connect()) as conn:
                    conn.execute("DELETE FROM projects")
                    conn.commit()
                self._insert_project(notion_page_id="linked-page")
                report, api = self._run_preflight_report([page_response])

                self.assertEqual(expected_status, report["status"])
                self.assertEqual(
                    expected_state, report["links"]["projects"][0]["state"]
                )
                self.assertEqual([], self._mutation_calls(api))

    def test_schema_mismatch_blocks_push_before_page_mutation(self):
        self._insert_project()
        invalid_projects = self._database_response(self.sync.PROJECTS_NOTION_SCHEMA)
        del invalid_projects["properties"]["Scope ID"]
        api = self._install_fake_api(
            [
                invalid_projects,
                self._database_response(self.sync.TASKS_NOTION_SCHEMA),
            ]
        )

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = self.sync.cmd_push()

        self.assertEqual(3, result)
        self.assertIn("SCHEMA_MISMATCH", output.getvalue())
        self.assertEqual([], self._mutation_calls(api))
        with closing(self._connect()) as conn:
            page_id = conn.execute(
                "SELECT notion_page_id FROM projects"
            ).fetchone()[0]
            last_push = conn.execute(
                "SELECT value FROM _metadata WHERE key='last_push_at'"
            ).fetchone()
        self.assertIsNone(page_id)
        self.assertIsNone(last_push)

    def test_schema_mismatch_blocks_pull_and_sync_before_mutation(self):
        invalid_projects = self._database_response(self.sync.PROJECTS_NOTION_SCHEMA)
        invalid_projects["properties"]["Scope ID"]["type"] = "title"

        for command in (self.sync.cmd_pull, self.sync.cmd_sync):
            with self.subTest(command=command.__name__):
                api = self._install_fake_api(
                    [
                        invalid_projects,
                        self._database_response(self.sync.TASKS_NOTION_SCHEMA),
                    ]
                )
                with contextlib.redirect_stdout(io.StringIO()):
                    result = command()

                self.assertEqual(3, result)
                self.assertEqual([], self._mutation_calls(api))
                self.assertTrue(all(call["method"] == "GET" for call in api.calls))

    def test_local_schema_mismatch_blocks_preflight(self):
        with closing(self._connect()) as conn:
            conn.execute("DROP TABLE tasks")
            conn.commit()
        api = self._install_sync_api()

        with closing(self._connect()) as conn:
            report = self.sync.run_preflight(conn)

        self.assertEqual("blocked", report["status"])
        self.assertIn(
            "LOCAL_SCHEMA_MISMATCH",
            {finding["code"] for finding in report["findings"]},
        )
        self.assertEqual([], self._mutation_calls(api))

    def test_missing_local_database_returns_preflight_exit_three(self):
        missing_path = Path(self.temp_dir.name) / "missing.db"
        self.sync.DB_PATH = str(missing_path)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = self.sync.cmd_push()

        self.assertEqual(3, result)
        self.assertIn("LOCAL_DB_UNAVAILABLE", output.getvalue())
        self.assertEqual([], self.fake_api.calls)

    def test_corrupt_local_database_returns_preflight_exit_three(self):
        corrupt_path = Path(self.temp_dir.name) / "corrupt.db"
        corrupt_path.write_bytes(b"this is not sqlite")
        self.sync.DB_PATH = str(corrupt_path)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = self.sync.cmd_preflight()

        self.assertEqual(3, result)
        self.assertIn("LOCAL_SCHEMA_ERROR", output.getvalue())
        self.assertEqual([], self.fake_api.calls)

    def test_blocked_preflight_does_not_change_sqlite_journal_mode(self):
        with closing(self._connect()) as conn:
            before = conn.execute("PRAGMA journal_mode").fetchone()[0]
        invalid_projects = self._database_response(self.sync.PROJECTS_NOTION_SCHEMA)
        del invalid_projects["properties"]["Scope ID"]
        self._install_fake_api(
            [invalid_projects, self._database_response(self.sync.TASKS_NOTION_SCHEMA)]
        )

        with contextlib.redirect_stdout(io.StringIO()):
            result = self.sync.cmd_preflight()

        with closing(self._connect()) as conn:
            after = conn.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(3, result)
        self.assertEqual(before, after)

    def test_push_dry_run_does_not_change_sqlite_journal_mode(self):
        self._insert_project()
        self._install_sync_api()
        with closing(self._connect()) as conn:
            before = conn.execute("PRAGMA journal_mode").fetchone()[0]

        self._run_push(dry_run=True)

        with closing(self._connect()) as conn:
            after = conn.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(before, after)

    def test_local_status_preserves_output_without_api_calls(self):
        self._insert_project()
        api = self._install_fake_api()
        before = file_fingerprint(self.test_db)

        output = self._run_status()
        after = file_fingerprint(self.test_db)

        self.assertIn("=== AI-PLC DB Sync Status ===", output)
        self.assertIn("Projects: 1 total, 1 dirty, 1 new", output)
        self.assertEqual([], api.calls)
        self.assertEqual(before, after)

    def test_status_audit_counts_dirty_missing_and_stale_pull(self):
        self._insert_project()
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO _metadata(key, value) VALUES ('last_pull_at', ?)",
                ("2026-07-08T00:00:00Z",),
            )
            conn.commit()
        api = self._install_sync_api()
        before = file_fingerprint(self.test_db)

        output = self._run_status(audit=True)
        after = file_fingerprint(self.test_db)

        self.assertIn("dirty=1", output)
        self.assertIn("missing_id=1", output)
        self.assertIn("[WARN] LAST_PULL_STALE", output)
        self.assertEqual([], self._mutation_calls(api))
        self.assertEqual(before, after)

    def test_status_audit_counts_stale_link(self):
        self._insert_project(notion_page_id="stale-page")
        api = self._install_fake_api(
            self._valid_schema_responses()
            + [urllib.error.HTTPError(
                "https://api.notion.test/page", 404, "not found", {}, None
            )]
            + self._valid_reconciliation_responses()
        )

        output = self._run_status(audit=True)

        self.assertIn("stale_link=1", output)
        self.assertIn("create_remote=1", output)
        self.assertEqual([], self._mutation_calls(api))

    def test_status_audit_counts_collision_and_duplicate(self):
        cases = (
            ([self._project_page(
                "collision-page", "L-TEST-PROJECT", "Different Project"
            )], "collision=1", 2),
            ([
                self._project_page("duplicate-1", "L-TEST-PROJECT", "Temporary Project"),
                self._project_page("duplicate-2", "L-TEST-PROJECT", "Temporary Project"),
            ], "duplicate=1", 2),
        )
        for pages, expected, exit_code in cases:
            with self.subTest(expected=expected):
                self._insert_project(scope_id=expected)
                # Use the fixture's stable key for this isolated row.
                with closing(self._connect()) as conn:
                    conn.execute(
                        "UPDATE projects SET scope_id='L-TEST-PROJECT' WHERE scope_id=?",
                        (expected,),
                    )
                    conn.commit()
                api = self._install_sync_api(project_pages=pages)
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = self.sync.cmd_status(audit=True)
                self.assertEqual(exit_code, result)
                self.assertIn(expected, output.getvalue())
                self.assertEqual([], self._mutation_calls(api))
                with closing(self._connect()) as conn:
                    conn.execute("DELETE FROM projects")
                    conn.commit()

    def test_status_audit_schema_error_returns_three(self):
        broken = self._database_response(self.sync.PROJECTS_NOTION_SCHEMA)
        del broken["properties"]["Scope ID"]
        api = self._install_fake_api([
            broken, self._database_response(self.sync.TASKS_NOTION_SCHEMA)
        ])
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            result = self.sync.cmd_status(audit=True)

        self.assertEqual(3, result)
        self.assertIn("schema_error=1", output.getvalue())
        self.assertEqual([], self._mutation_calls(api))

    def test_status_audit_local_schema_error_returns_three(self):
        with closing(self._connect()) as conn:
            conn.execute("DROP TABLE tasks")
            conn.commit()
        self._install_fake_api()
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            result = self.sync.cmd_status(audit=True)

        self.assertEqual(3, result)
        self.assertIn("LOCAL_SCHEMA_MISMATCH", output.getvalue())
        self.assertIn("schema_error=1", output.getvalue())

    def test_last_pull_warning_normalizes_naive_and_future_timestamps(self):
        self.assertEqual(
            "LAST_PULL_STALE",
            self.sync._last_pull_warning(
                "2026-07-08T00:00:00", now="2026-07-10T12:00:00Z"
            ),
        )
        self.assertEqual(
            "LAST_PULL_FUTURE",
            self.sync._last_pull_warning(
                "2026-07-11T00:00:00Z", now="2026-07-10T12:00:00Z"
            ),
        )

    def test_post_verify_failure_returns_five(self):
        self._insert_project()
        api = self._install_sync_api([
            {"id": "verify-page", "last_edited_time": FIXED_NOTION_EDITED}
        ])
        failed = {
            "operation_id": "project:L-TEST-PROJECT",
            "status": "failed",
            "findings": ["INJECTED_POST_VERIFY_MISMATCH"],
        }
        output = io.StringIO()
        with mock.patch.object(
            self.sync, "_post_verify_operation", return_value=failed
        ), contextlib.redirect_stdout(output):
            result = self.sync.cmd_push()

        self.assertEqual(5, result)
        self.assertIn("POST-VERIFY FAILED", output.getvalue())
        self.assertIn("INJECTED_POST_VERIFY_MISMATCH", output.getvalue())
        self.assertEqual(1, len(self._mutation_calls(api)))

    def test_pull_dry_run_does_not_change_sqlite_journal_mode(self):
        empty_query = {"results": [], "has_more": False, "next_cursor": None}
        self._install_fake_api(
            self._valid_schema_responses() + [empty_query, empty_query]
        )
        with closing(self._connect()) as conn:
            before = conn.execute("PRAGMA journal_mode").fetchone()[0]

        with contextlib.redirect_stdout(io.StringIO()):
            result = self.sync.cmd_pull(dry_run=True)

        with closing(self._connect()) as conn:
            after = conn.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(0, result)
        self.assertEqual(before, after)
        self.assertEqual([], self._mutation_calls(self.fake_api))

    def test_project_reconciliation_matrix(self):
        local = {
            "id": 1,
            "notion_page_id": None,
            "scope_id": "L-IDENTITY",
            "name": " Cafe\u0301 ",
            "parent_scope": " PARENT ",
        }
        compatible = self._project_page(
            "project-compatible", "L-IDENTITY", "Café", parent_scope="PARENT"
        )
        name_collision = self._project_page(
            "project-name-collision", "L-IDENTITY", "Different", parent_scope="PARENT"
        )
        parent_collision = self._project_page(
            "project-parent-collision", "L-IDENTITY", "Café", parent_scope="OTHER"
        )
        cases = (
            ("not_found", [], "not_found", "none", 0),
            ("attach", [compatible], "attach", "unique_compatible", 2),
            ("name_collision", [name_collision], "collision", "unique_incompatible", 2),
            ("parent_collision", [parent_collision], "collision", "unique_incompatible", 2),
            ("duplicate", [compatible, name_collision], "duplicate", "multiple", 2),
        )

        for label, pages, classification, match_state, exit_code in cases:
            with self.subTest(label=label):
                report = self.sync.build_reconciliation_report(
                    {"project": [local], "task": []},
                    {"project": pages, "task": []},
                )
                item = next(
                    item for item in report["items"]
                    if item["local_row_id"] == local["id"]
                )
                self.assertEqual(classification, item["classification"])
                self.assertEqual(match_state, item["match_state"])
                self.assertEqual(exit_code, report["exit_code"])
                if classification == "duplicate":
                    self.assertEqual(
                        {"project-compatible", "project-name-collision"},
                        {candidate["page_id"] for candidate in item["candidates"]},
                    )

    def test_task_reconciliation_matrix(self):
        local = {
            "id": 2,
            "notion_page_id": None,
            "scope_id": "L-TASK",
            "task_id": "T004",
            "name": " Task Name ",
        }
        compatible = self._task_page(
            "task-compatible", "L-TASK", "T004", "Task Name"
        )
        collision = self._task_page(
            "task-collision", "L-TASK", "T004", "Different Task"
        )
        cases = (
            ("not_found", [], "not_found", 0),
            ("attach", [compatible], "attach", 2),
            ("collision", [collision], "collision", 2),
            ("duplicate", [compatible, collision], "duplicate", 2),
        )

        for label, pages, classification, exit_code in cases:
            with self.subTest(label=label):
                report = self.sync.build_reconciliation_report(
                    {"project": [], "task": [local]},
                    {"project": [], "task": pages},
                )
                item = next(
                    item for item in report["items"]
                    if item["local_row_id"] == local["id"]
                )
                self.assertEqual(classification, item["classification"])
                self.assertEqual(exit_code, report["exit_code"])

    def test_attach_candidate_already_linked_to_other_local_is_collision(self):
        linked = {
            "id": 10,
            "notion_page_id": "shared-page",
            "scope_id": "L-OLD",
            "name": "Old Project",
            "parent_scope": None,
        }
        missing = {
            "id": 11,
            "notion_page_id": None,
            "scope_id": "L-NEW",
            "name": "New Project",
            "parent_scope": None,
        }
        candidate = self._project_page("shared-page", "L-NEW", "New Project")

        report = self.sync.build_reconciliation_report(
            {"project": [linked, missing], "task": []},
            {"project": [candidate], "task": []},
        )

        item = next(item for item in report["items"] if item["local_row_id"] == 11)
        self.assertEqual("collision", item["classification"])
        self.assertEqual("candidate_already_linked_local", item["reason"])
        self.assertEqual(10, item["linked_local_row_id"])
        self.assertEqual(2, report["exit_code"])

    def test_invalid_duplicate_and_remote_only_stable_keys(self):
        invalid_project = {
            "id": 1, "notion_page_id": None, "scope_id": "UNKNOWN",
            "name": "Invalid", "parent_scope": None,
        }
        invalid_task = {
            "id": 2, "notion_page_id": None, "scope_id": "L-VALID",
            "task_id": "T000", "name": "Invalid Task",
        }
        duplicate_a = {
            "id": 3, "notion_page_id": None, "scope_id": "L-DUP",
            "name": "Duplicate", "parent_scope": None,
        }
        duplicate_b = dict(duplicate_a, id=4)
        report = self.sync.build_reconciliation_report(
            {
                "project": [invalid_project, duplicate_a, duplicate_b],
                "task": [invalid_task],
            },
            {"project": [], "task": []},
        )

        self.assertEqual(3, report["exit_code"])
        self.assertEqual(
            {"INVALID_STABLE_KEY", "LOCAL_DUPLICATE_KEY"},
            {finding["code"] for finding in report["findings"]},
        )
        self.assertEqual(4, report["summary"]["invalid"])

        remote_only = self.sync.build_reconciliation_report(
            {"project": [], "task": []},
            {
                "project": [self._project_page("remote-only", "L-REMOTE", "Remote")],
                "task": [],
            },
        )
        self.assertEqual(0, remote_only["exit_code"])
        self.assertEqual(1, remote_only["summary"]["remote_only"])
        self.assertEqual("skip", remote_only["items"][0]["action"])

        remote_duplicate = self.sync.build_reconciliation_report(
            {"project": [], "task": []},
            {
                "project": [
                    self._project_page("remote-dup-1", "L-REMOTE-DUP", "Remote"),
                    self._project_page("remote-dup-2", "L-REMOTE-DUP", "Remote"),
                ],
                "task": [],
            },
        )
        self.assertEqual(2, remote_duplicate["exit_code"])
        self.assertEqual(1, remote_duplicate["summary"]["duplicate"])
        self.assertEqual(
            {"remote-dup-1", "remote-dup-2"},
            {
                candidate["page_id"]
                for candidate in remote_duplicate["items"][0]["candidates"]
            },
        )

        linked_duplicate = self.sync.build_reconciliation_report(
            {
                "project": [
                    dict(duplicate_a, id=20, notion_page_id="linked-1"),
                    dict(duplicate_a, id=21, notion_page_id="linked-2"),
                ],
                "task": [],
            },
            {"project": [], "task": []},
        )
        self.assertEqual(3, linked_duplicate["exit_code"])
        self.assertIn(
            "LOCAL_DUPLICATE_KEY",
            {finding["code"] for finding in linked_duplicate["findings"]},
        )

    def test_push_blocks_attach_collision_and_duplicate_without_mutation(self):
        cases = (
            (
                "attach",
                [self._project_page("attach-page", "L-TEST-PROJECT", "Temporary Project")],
            ),
            (
                "collision",
                [self._project_page("collision-page", "L-TEST-PROJECT", "Other Project")],
            ),
            (
                "duplicate",
                [
                    self._project_page("duplicate-1", "L-TEST-PROJECT", "Temporary Project"),
                    self._project_page("duplicate-2", "L-TEST-PROJECT", "Temporary Project"),
                ],
            ),
        )

        for classification, project_pages in cases:
            with self.subTest(classification=classification):
                with closing(self._connect()) as conn:
                    conn.execute("DELETE FROM projects")
                    conn.commit()
                self._insert_project()
                api = self._install_sync_api(project_pages=project_pages)
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = self.sync.cmd_push()

                self.assertEqual(2, result)
                self.assertIn("[%s]" % classification.upper(), output.getvalue())
                for page in project_pages:
                    self.assertIn("id=%s" % page["id"], output.getvalue())
                    self.assertIn(FIXED_NOTION_EDITED, output.getvalue())
                    self.assertIn(self.sync.PROJECTS_DB_ID, output.getvalue())
                self.assertEqual([], self._mutation_calls(api))
                with closing(self._connect()) as conn:
                    page_id = conn.execute(
                        "SELECT notion_page_id FROM projects"
                    ).fetchone()[0]
                self.assertIsNone(page_id)

    def test_stale_link_reconciles_before_safe_create(self):
        self._insert_project(notion_page_id="stale-page")
        replacement = {
            "id": "replacement-page",
            "last_edited_time": FIXED_NOTION_EDITED,
        }
        api = self._install_fake_api(
            self._valid_schema_responses()
            + [
                urllib.error.HTTPError(
                    "https://api.notion.test/page", 404, "not found", {}, None
                )
            ]
            + self._valid_reconciliation_responses()
            + self._valid_absence_revalidation_responses()
            + [replacement]
        )

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = self.sync.cmd_push()

        self.assertEqual(0, result)
        self.assertIn("[RECONCILE] LINK_NOT_FOUND", output.getvalue())
        self.assertIn("[CREATE] L-TEST-PROJECT", output.getvalue())
        mutations = self._mutation_calls(api)
        self.assertEqual(1, len(mutations))
        self.assertEqual(("POST", "/v1/pages"), (
            mutations[0]["method"], mutations[0]["path"],
        ))
        with closing(self._connect()) as conn:
            page_id = conn.execute(
                "SELECT notion_page_id FROM projects"
            ).fetchone()[0]
        self.assertEqual("replacement-page", page_id)

    def test_stale_link_attach_candidate_stops_without_mutation(self):
        self._insert_project(notion_page_id="stale-page")
        candidate = self._project_page(
            "existing-page", "L-TEST-PROJECT", "Temporary Project"
        )
        api = self._install_fake_api(
            self._valid_schema_responses()
            + [
                urllib.error.HTTPError(
                    "https://api.notion.test/page", 404, "not found", {}, None
                )
            ]
            + self._valid_reconciliation_responses(project_pages=[candidate])
        )

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = self.sync.cmd_push()

        self.assertEqual(2, result)
        self.assertIn("[ATTACH]", output.getvalue())
        self.assertEqual([], self._mutation_calls(api))
        with closing(self._connect()) as conn:
            page_id = conn.execute(
                "SELECT notion_page_id FROM projects"
            ).fetchone()[0]
        self.assertEqual("stale-page", page_id)

    def test_candidate_appearing_before_create_fails_absence_cas(self):
        self._insert_project()
        late_candidate = self._project_page(
            "late-candidate", "L-TEST-PROJECT", "Temporary Project"
        )
        api = self._install_sync_api(
            revalidation_project_pages=[late_candidate]
        )

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = self.sync.cmd_push()

        self.assertEqual(2, result)
        self.assertIn("Create Absence Revalidation", output.getvalue())
        self.assertIn("[ATTACH]", output.getvalue())
        self.assertIn("id=late-candidate", output.getvalue())
        self.assertEqual([], self._mutation_calls(api))
        with closing(self._connect()) as conn:
            page_id = conn.execute(
                "SELECT notion_page_id FROM projects"
            ).fetchone()[0]
        self.assertIsNone(page_id)

    def test_dirty_linked_push_queries_reconciliation_for_remote_duplicates(self):
        self._insert_project(notion_page_id="linked-page")
        with closing(self._connect()) as conn:
            conn.execute("UPDATE projects SET name=? WHERE scope_id=?", (
                "Locally Updated", "L-TEST-PROJECT",
            ))
            conn.commit()
        api = self._install_fake_api(
            self._valid_schema_responses()
            + [self._page_response(self.sync.PROJECTS_DB_ID)]
            + self._valid_reconciliation_responses(project_pages=[
                self._project_page(
                    "linked-page", "L-TEST-PROJECT", "Locally Updated"
                )
            ])
        )

        output = self._run_push(dry_run=True)

        self.assertIn("[PATCH] L-TEST-PROJECT", output)
        self.assertEqual(2, sum("/query" in call["path"] for call in api.calls))
        self.assertEqual([], self._mutation_calls(api))

    def test_measured_scope_collision_fixtures(self):
        fixtures = (
            ("L-HIST-A", "合成の案件A", ["合成のタスクA"], "collision"),
            ("L-HIST-B", "synthetic_b", ["合成のタスクB"], "collision"),
            ("L-HIST-C", "合成の案件C", ["合成のタスクC"], "collision"),
            ("L-HIST-D-SG1", "合成の調査", ["合成の調査", "合成の調査"], "duplicate"),
        )
        totals = {"collision": 0, "duplicate": 0}

        for scope_id, local_name, remote_names, expected in fixtures:
            local = {
                "id": 1,
                "notion_page_id": None,
                "scope_id": scope_id,
                "name": local_name,
                "parent_scope": None,
            }
            pages = [
                self._project_page(f"{scope_id}-{index}", scope_id, name)
                for index, name in enumerate(remote_names, start=1)
            ]
            report = self.sync.build_reconciliation_report(
                {"project": [local], "task": []},
                {"project": pages, "task": []},
            )
            item = next(item for item in report["items"] if item["local_row_id"] == 1)
            self.assertEqual(expected, item["classification"])
            totals[expected] += 1

        self.assertEqual({"collision": 3, "duplicate": 1}, totals)

    def test_http_404_is_fail_fast_without_retry(self):
        error = urllib.error.HTTPError(
            "https://api.notion.test/page", 404, "not found", {}, None
        )
        with mock.patch.object(
            self.sync.urllib.request, "urlopen", side_effect=error
        ) as urlopen:
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(urllib.error.HTTPError):
                    self.real_api_call("GET", "/v1/pages/missing", retries=3)

        self.assertEqual(1, urlopen.call_count)

    def test_pull_guard_blocks_same_scope_different_page(self):
        self._insert_project()
        candidate = self._project_page(
            "other-page", "L-TEST-PROJECT", "Temporary Project"
        )
        with closing(self._connect()) as conn:
            report = self.sync.build_pull_guard(
                conn, {"project": [candidate], "task": []}
            )

        self.assertEqual(2, report["exit_code"])
        self.assertEqual(1, report["summary"]["conflict"])
        self.assertIn(
            "STABLE_KEY_PAGE_COLLISION",
            {finding["code"] for finding in report["findings"]},
        )

    def test_pull_guard_blocks_both_dirty_and_compares_utc_instants(self):
        self._insert_project(notion_page_id="linked-page")
        page = self._project_page(
            "linked-page", "L-TEST-PROJECT", "Temporary Project",
            edited="2026-07-10T10:00:00.000Z",
        )
        with closing(self._connect()) as conn:
            conn.execute("""
                UPDATE projects SET updated_at=?, last_sync_at=?, notion_last_edited=?
            """, (
                "2026-07-10T09:30:00+00:00", "2026-07-10T09:00:00Z",
                "2026-07-10T09:00:00.000+00:00",
            ))
            conn.commit()
            report = self.sync.build_pull_guard(
                conn, {"project": [page], "task": []}
            )
        self.assertEqual(2, report["exit_code"])
        self.assertIn("BOTH_DIRTY", {f["code"] for f in report["findings"]})
        self.assertFalse(self.sync._instant_gt(
            "2026-07-10T10:00:00.000Z", "2026-07-10T10:00:00+00:00"
        ))

    def test_sync_stops_before_push_when_pull_guard_blocks(self):
        self._insert_project()
        candidate = self._project_page(
            "other-page", "L-TEST-PROJECT", "Temporary Project"
        )
        api = self._install_fake_api(
            self._valid_schema_responses()
            + self._valid_reconciliation_responses(project_pages=[candidate])
        )

        with contextlib.redirect_stdout(io.StringIO()):
            result = self.sync.cmd_sync()

        self.assertEqual(2, result)
        self.assertEqual([], self._mutation_calls(api))
        self.assertEqual(4, len(api.calls))

    def test_pull_revalidates_under_write_lock_before_mutation(self):
        candidate = self._project_page(
            "remote-only-page", "L-REMOTE", "Remote Only"
        )
        api = self._install_fake_api(
            self._valid_schema_responses()
            + self._valid_reconciliation_responses(project_pages=[candidate])
        )
        real_guard = self.sync.build_pull_guard
        blocked = {
            "status": "blocked", "exit_code": 2,
            "findings": [{"code": "LATE_CONFLICT", "message": "late local edit"}],
            "summary": {"insert_local": 0, "patch_local": 0, "no_op": 0,
                        "conflict": 1, "duplicate": 0, "invalid": 0,
                        "orphan": 0},
        }
        with mock.patch.object(
            self.sync, "build_pull_guard", side_effect=[
                mock.DEFAULT, blocked
            ], wraps=real_guard,
        ) as guard:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = self.sync.cmd_pull()

        self.assertEqual(2, result)
        self.assertEqual(2, guard.call_count)
        self.assertIn("Pull Revalidation", output.getvalue())
        self.assertEqual([], self._mutation_calls(api))
        with closing(self._connect()) as conn:
            self.assertEqual(0, conn.execute(
                "SELECT COUNT(*) FROM projects"
            ).fetchone()[0])

    @staticmethod
    def _urlopen_json_response(payload):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(payload).encode("utf-8")
        return response

    def test_retry_attempts_for_429_5xx_network_and_create(self):
        success = self._urlopen_json_response({"ok": True})
        cases = (
            (urllib.error.HTTPError("u", 429, "rate", {"Retry-After": "0"}, None), 2),
            (urllib.error.HTTPError("u", 503, "temporary", {}, None), 2),
            (urllib.error.URLError("temporary"), 2),
        )
        for failure, expected in cases:
            with self.subTest(failure=type(failure).__name__):
                with (
                    mock.patch.object(
                        self.sync.urllib.request, "urlopen",
                        side_effect=[failure, success],
                    ) as urlopen,
                    mock.patch.object(self.sync.time, "sleep"),
                ):
                    result = self.real_api_call("GET", "/v1/test", retries=3)
                self.assertEqual({"ok": True}, result)
                self.assertEqual(expected, urlopen.call_count)

        with (
            mock.patch.object(
                self.sync.urllib.request, "urlopen",
                side_effect=urllib.error.URLError("uncertain"),
            ) as urlopen,
            mock.patch.object(self.sync.time, "sleep"),
        ):
            with self.assertRaises(urllib.error.URLError):
                self.real_api_call("POST", "/v1/pages", {"x": 1}, retries=3)
        self.assertEqual(1, urlopen.call_count)

    def test_fake_api_queues_responses_and_records_immutable_calls(self):
        queued = {"id": "queued-page", "last_edited_time": "queued-time"}
        api = FakeNotionAPI([queued])
        body = {"properties": {"name": "before"}}

        response = api("POST", "/v1/pages", body)
        body["properties"]["name"] = "after"
        response["id"] = "mutated"

        self.assertEqual("before", api.calls[0]["body"]["properties"]["name"])
        self.assertEqual("queued-page", queued["id"])
        with self.assertRaisesRegex(AssertionError, "unexpected API call"):
            api("GET", "/v1/unexpected")

    def test_t011_unrelated_findings_are_audit_only_and_create_two(self):
        self._insert_project()
        self._insert_task()
        with closing(self._connect()) as conn:
            selected = {
                "project": [dict(conn.execute("SELECT * FROM projects").fetchone())],
                "task": [dict(conn.execute("SELECT * FROM tasks").fetchone())],
            }
        local_records = {
            "project": selected["project"] + [{
                "id": 999, "scope_id": "", "name": "Unrelated invalid",
                "notion_page_id": None,
            }],
            "task": selected["task"],
        }
        remote_projects = [
            self._project_page("invalid-%d" % index, "", "Invalid")
            for index in range(7)
        ]
        for group in range(10):
            remote_projects.extend([
                self._project_page("dup-%d-a" % group, "L-DUP-%d" % group, "Dup"),
                self._project_page("dup-%d-b" % group, "L-DUP-%d" % group, "Dup"),
            ])
        remote_projects.extend(
            self._project_page("remote-%d" % index, "L-REMOTE-%d" % index, "Remote")
            for index in range(194)
        )
        report = self.sync.build_reconciliation_report(
            local_records, {"project": remote_projects, "task": []}
        )
        projection = self.sync.project_reconciliation_for_push(report, selected)

        self.assertEqual(8, projection["raw_summary"]["invalid"])
        self.assertEqual(10, projection["raw_summary"]["duplicate"])
        self.assertEqual(194, projection["raw_summary"]["remote_only"])
        self.assertEqual(0, projection["blocking"]["exit_code"])
        self.assertEqual(8, projection["audit_only"]["summary"]["invalid"])
        self.assertEqual(10, projection["audit_only"]["summary"]["duplicate"])
        self.assertEqual(194, projection["audit_only"]["summary"]["remote_only"])

        with mock.patch.object(self.sync, "run_reconciliation", return_value=report):
            plan = self.sync.build_push_plan(skip_preflight=True)
        self.assertEqual(0, plan["exit_code"])
        self.assertEqual(2, plan["summary"]["create_remote"])
        self.assertTrue(self.sync.validate_push_plan(plan))

    def test_t011_selected_remote_duplicate_blocks_once(self):
        local = {
            "id": 1, "scope_id": "L-SELECTED", "name": "Selected",
            "parent_scope": None, "notion_page_id": None,
        }
        report = self.sync.build_reconciliation_report(
            {"project": [local], "task": []},
            {"project": [
                self._project_page("selected-a", "L-SELECTED", "Selected"),
                self._project_page("selected-b", "L-SELECTED", "Selected"),
            ], "task": []},
        )
        projection = self.sync.project_reconciliation_for_push(
            report, {"project": [local], "task": []}
        )
        duplicate_findings = [
            finding for finding in report["findings"]
            if finding["code"] == "REMOTE_DUPLICATE_KEY"
        ]
        duplicate_item = next(
            item for item in report["items"]
            if item["classification"] == "duplicate"
        )
        self.assertEqual(1, len(duplicate_findings))
        self.assertEqual(
            duplicate_findings[0]["finding_id"],
            duplicate_item["duplicate_finding_id"],
        )
        self.assertEqual(1, projection["blocking"]["summary"]["duplicate"])
        self.assertEqual(2, projection["blocking"]["exit_code"])

    def test_t011_linked_selected_duplicate_and_self_page_contract(self):
        local = {
            "id": 1, "scope_id": "L-LINKED", "name": "Linked",
            "parent_scope": None, "notion_page_id": "owned-page",
        }
        duplicate = self.sync.build_reconciliation_report(
            {"project": [local], "task": []},
            {"project": [
                self._project_page("owned-page", "L-LINKED", "Linked"),
                self._project_page("extra-page", "L-LINKED", "Linked"),
            ], "task": []},
            target_row_ids={"project": [1], "task": []},
        )
        projection = self.sync.project_reconciliation_for_push(
            duplicate, {"project": [local], "task": []}
        )
        self.assertEqual(1, projection["blocking"]["summary"]["duplicate"])
        self.assertEqual(2, projection["blocking"]["exit_code"])

        self_owned = self.sync.build_reconciliation_report(
            {"project": [local], "task": []},
            {"project": [
                self._project_page("owned-page", "L-LINKED", "Linked")
            ], "task": []},
            target_row_ids={"project": [1], "task": []},
        )
        own_projection = self.sync.project_reconciliation_for_push(
            self_owned, {"project": [local], "task": []}
        )
        self.assertEqual([], self_owned["items"])
        self.assertEqual(0, own_projection["blocking"]["exit_code"])

    def test_t011_selected_invalid_and_clean_dependency_collision_block(self):
        invalid_task = {
            "id": 2, "scope_id": "L-VALID", "task_id": "T000",
            "name": "Invalid Task", "notion_page_id": None,
        }
        invalid_report = self.sync.build_reconciliation_report(
            {"project": [], "task": [invalid_task]},
            {"project": [], "task": []},
        )
        invalid_projection = self.sync.project_reconciliation_for_push(
            invalid_report, {"project": [], "task": [invalid_task]}
        )
        self.assertEqual(1, invalid_projection["blocking"]["summary"]["invalid"])
        self.assertEqual(3, invalid_projection["blocking"]["exit_code"])

        clean_project = {
            "id": 1, "scope_id": "L-DEPENDENCY", "name": "Expected Project",
            "parent_scope": None, "notion_page_id": "old-page",
        }
        selected_task = {
            "id": 2, "scope_id": "L-DEPENDENCY", "task_id": "T011",
            "name": "Selected Task", "notion_page_id": "task-page",
        }
        dependency_report = self.sync.build_reconciliation_report(
            {"project": [clean_project], "task": [selected_task]},
            {"project": [
                self._project_page("other-page", "L-DEPENDENCY", "Other Project")
            ], "task": []},
            reachable_stable_keys={"project": [["L-DEPENDENCY"]], "task": []},
        )
        dependency_projection = self.sync.project_reconciliation_for_push(
            dependency_report, {"project": [], "task": [selected_task]}
        )
        self.assertEqual(1, dependency_projection["blocking"]["summary"]["collision"])
        self.assertEqual(2, dependency_projection["blocking"]["exit_code"])

    def test_t011_unknown_reachability_blocks_push(self):
        report = self.sync.build_reconciliation_report(
            {"project": [], "task": []},
            {"project": [{}], "task": []},
        )
        projection = self.sync.project_reconciliation_for_push(
            report, {"project": [], "task": []}
        )
        self.assertEqual(1, projection["blocking"]["summary"]["unknown_reachability"])
        self.assertEqual(3, projection["blocking"]["exit_code"])

    def test_t011_invalid_remote_at_selected_linked_page_is_blocking(self):
        local = {
            "id": 1, "scope_id": "L-LINKED", "name": "Linked",
            "parent_scope": None, "notion_page_id": "owned-page",
        }
        malformed = self._project_page("owned-page", "", "Malformed")
        report = self.sync.build_reconciliation_report(
            {"project": [local], "task": []},
            {"project": [malformed], "task": []},
            target_row_ids={"project": [1], "task": []},
        )
        projection = self.sync.project_reconciliation_for_push(
            report, {"project": [local], "task": []}
        )
        self.assertEqual(1, projection["blocking"]["summary"]["invalid"])
        self.assertEqual(3, projection["blocking"]["exit_code"])

    def test_t011_audit_identity_changes_digest_and_plan_id(self):
        selected = {"project": [], "task": []}
        first = self.sync.build_reconciliation_report(
            {"project": [], "task": []},
            {"project": [self._project_page("page-a", "L-A", "A")], "task": []},
        )
        second = self.sync.build_reconciliation_report(
            {"project": [], "task": []},
            {"project": [self._project_page("page-b", "L-B", "B")], "task": []},
        )
        first_projection = self.sync.project_reconciliation_for_push(first, selected)
        second_projection = self.sync.project_reconciliation_for_push(second, selected)
        self.assertNotEqual(
            first_projection["audit_only"]["projection_digest"],
            second_projection["audit_only"]["projection_digest"],
        )
        base = {
            "direction": "push", "preflight": {}, "source_snapshot": {},
            "operations": [],
        }
        self.assertNotEqual(
            self.sync._push_plan_id(dict(base, reconciliation=first_projection)),
            self.sync._push_plan_id(dict(base, reconciliation=second_projection)),
        )

    def test_t011_authorization_requires_same_plan_all_ops_and_approver(self):
        projection = {
            "blocking": {"exit_code": 0},
            "authorization_required": {"operation_ids": ["project:L-A"]},
            "audit_only": {"projection_digest": "digest"},
        }
        plan = {
            "plan_id": "", "direction": "push", "preflight": {},
            "source_snapshot": {}, "reconciliation": projection,
            "operations": [{"operation_id": "project:L-A", "action": "attach_candidate"}],
        }
        plan["plan_id"] = self.sync._push_plan_id(plan)
        valid = {"plan_id": plan["plan_id"], "operation_ids": ["project:L-A"],
                 "approved_by": "reviewer"}
        self.assertTrue(self.sync.validate_plan_authorization(plan, valid))
        self.assertFalse(self.sync.validate_plan_authorization(
            plan, dict(valid, plan_id="wrong")
        ))
        self.assertFalse(self.sync.validate_plan_authorization(
            plan, dict(valid, operation_ids=[])
        ))
        self.assertFalse(self.sync.validate_plan_authorization(
            plan, dict(valid, approved_by="")
        ))

    def test_t011_valid_authorization_executes_attach_link_only(self):
        self._insert_project()
        with closing(self._connect()) as conn:
            row = dict(conn.execute("SELECT * FROM projects").fetchone())
        operation = {
            "operation_id": "project:L-TEST-PROJECT",
            "entity": "project", "stable_key": ["L-TEST-PROJECT"],
            "action": "attach_candidate", "local_row_id": row["id"],
            "remote_page_ids": ["approved-page"], "remote_candidates": [],
            "link_state": "missing", "expected_local_updated_at": row["updated_at"],
            "expected_local_fingerprint": self.sync._mapped_fingerprint("project", row),
            "mutable_properties": self.sync._project_to_notion_props(row),
        }
        projection = {
            "blocking": {"exit_code": 0, "summary": {}},
            "authorization_required": {
                "operation_ids": [operation["operation_id"]], "summary": {"attach": 1}
            },
            "audit_only": {"projection_digest": "digest", "summary": {}},
        }
        plan = {
            "plan_id": "", "generated_at": FIXED_NOW, "direction": "push",
            "preflight": {"status": "pass", "findings": []},
            "source_snapshot": {}, "operations": [operation],
            "summary": {"attach_candidate": 1}, "reconciliation": projection,
            "exit_code": 2,
        }
        plan["plan_id"] = self.sync._push_plan_id(plan)
        authorization = {
            "plan_id": plan["plan_id"], "operation_ids": [operation["operation_id"]],
            "approved_by": "reviewer",
        }
        result = self.sync.execute_push_plan(plan, authorization=authorization)
        with closing(self._connect()) as conn:
            linked = conn.execute(
                "SELECT notion_page_id, last_sync_at FROM projects WHERE id=?", (row["id"],)
            ).fetchone()
        self.assertEqual(0, result)
        self.assertEqual(("approved-page", row["last_sync_at"]), tuple(linked))
        self.assertEqual([], self._mutation_calls(self.fake_api))

    def test_t011_execute_revalidation_stops_new_dependency_collision(self):
        self._insert_task(scope_id="L-DEPENDENCY")
        with closing(self._connect()) as conn:
            row = dict(conn.execute("SELECT * FROM tasks").fetchone())
        operation = {
            "operation_id": "task:L-DEPENDENCY/T-TEST", "entity": "task",
            "stable_key": ["L-DEPENDENCY", "T-TEST"], "action": "create_remote",
            "local_row_id": row["id"], "remote_page_ids": [],
            "remote_candidates": [], "link_state": "missing",
            "expected_local_updated_at": row["updated_at"],
            "expected_local_fingerprint": self.sync._mapped_fingerprint("task", row),
            "mutable_properties": self.sync._task_to_notion_props(row),
        }
        projection = {
            "blocking": {"exit_code": 0, "summary": {}},
            "authorization_required": {"operation_ids": [], "summary": {}},
            "audit_only": {"projection_digest": "before", "summary": {}},
        }
        plan = {
            "plan_id": "", "generated_at": FIXED_NOW, "direction": "push",
            "preflight": {"status": "pass", "findings": []},
            "source_snapshot": {}, "operations": [operation],
            "summary": {"create_remote": 1}, "reconciliation": projection,
            "exit_code": 0,
        }
        plan["plan_id"] = self.sync._push_plan_id(plan)
        dependency = {
            "id": 100, "scope_id": "L-DEPENDENCY", "name": "Expected",
            "parent_scope": None, "notion_page_id": "old-page",
        }
        fresh = self.sync.build_reconciliation_report(
            {"project": [dependency], "task": [row]},
            {"project": [
                self._project_page("other-page", "L-DEPENDENCY", "Other")
            ], "task": []},
            target_row_ids={"project": [], "task": [row["id"]]},
            reachable_stable_keys={"project": [["L-DEPENDENCY"]],
                                   "task": [["L-DEPENDENCY", "T-TEST"]]},
        )
        with mock.patch.object(self.sync, "run_reconciliation", return_value=fresh):
            result = self.sync.execute_push_plan(plan)
        self.assertEqual(2, result)
        self.assertEqual([], self._mutation_calls(self.fake_api))

    def test_t011_dependency_attach_is_an_authorized_plan_operation(self):
        self._insert_project(
            scope_id="L-DEPENDENCY", notion_page_id="old-project-page"
        )
        self._insert_task(scope_id="L-DEPENDENCY")
        with closing(self._connect()) as conn:
            local_records = {
                "project": [dict(conn.execute("SELECT * FROM projects").fetchone())],
                "task": [dict(conn.execute("SELECT * FROM tasks").fetchone())],
            }
        report = self.sync.build_reconciliation_report(
            local_records,
            {"project": [
                self._project_page(
                    "compatible-project-page", "L-DEPENDENCY", "Temporary Project"
                )
            ], "task": []},
            reachable_stable_keys={"project": [["L-DEPENDENCY"]],
                                   "task": [["L-DEPENDENCY", "T-TEST"]]},
        )
        with mock.patch.object(self.sync, "run_reconciliation", return_value=report):
            plan = self.sync.build_push_plan(skip_preflight=True)
        attach = [op for op in plan["operations"] if op["action"] == "attach_candidate"]
        self.assertEqual(1, len(attach))
        self.assertEqual("project", attach[0]["entity"])
        self.assertEqual(
            [attach[0]["operation_id"]],
            plan["reconciliation"]["authorization_required"]["operation_ids"],
        )
        self.assertEqual(2, plan["exit_code"])

    def _run_cli_with_stubbed_handlers(self, argv, return_code=91):
        calls = []

        def stub(name):
            def handler(*args, **kwargs):
                calls.append((name, args, kwargs))
                return return_code
            return handler

        handlers = (
            "cmd_pull", "cmd_push", "cmd_sync", "cmd_status",
            "cmd_preflight", "cmd_reconcile",
        )
        output = io.StringIO()
        with contextlib.ExitStack() as stack:
            for name in handlers:
                stack.enter_context(mock.patch.object(self.sync, name, stub(name)))
            stack.enter_context(mock.patch.object(
                self.sync.sys, "argv", ["sync.py", *argv]
            ))
            stack.enter_context(contextlib.redirect_stdout(output))
            result = self.sync.main()
        return result, calls, output.getvalue()

    def test_t018_root_and_subcommand_help_are_non_executing(self):
        cases = [
            (["--help"], None),
            *[([command, "--help"], command) for command in (
                "pull", "push", "sync", "status", "preflight", "reconcile"
            )],
        ]
        for argv, command in cases:
            with self.subTest(argv=argv):
                database_before = file_fingerprint(self.test_db)
                result, calls, output = self._run_cli_with_stubbed_handlers(argv)
                self.assertEqual(0, result)
                self.assertEqual([], calls)
                self.assertEqual([], self.fake_api.calls)
                self.assertEqual(database_before, file_fingerprint(self.test_db))
                self.assertIn("Usage:", output)
                if command:
                    self.assertIn(command, output)

    def test_t018_invalid_cli_is_rejected_before_handler_or_mutation(self):
        plan_out = Path(self.temp_dir.name) / "must-not-exist.json"
        cases = [
            ["push", "--unknown", "--plan-out", str(plan_out)],
            ["push", "--plan"],
            ["push", "--plan", "-x", "--plan-id", "abc"],
            ["push", "--dry-run", "--dry-run"],
            ["status", "--dry-run"],
            ["pull", "--audit"],
            ["preflight", "extra"],
            ["push", "--plan-id", "abc"],
            ["push", "--help", "--dry-run"],
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                database_before = file_fingerprint(self.test_db)
                result, calls, output = self._run_cli_with_stubbed_handlers(argv)
                self.assertEqual(64, result)
                self.assertEqual([], calls)
                self.assertEqual([], self.fake_api.calls)
                self.assertEqual(database_before, file_fingerprint(self.test_db))
                self.assertFalse(plan_out.exists())
                self.assertIn("ERROR:", output)

    def test_t018_valid_cli_preserves_handler_arguments(self):
        cases = [
            (["pull"], "cmd_pull", {"dry_run": False}),
            (["pull", "--dry-run"], "cmd_pull", {"dry_run": True}),
            (["push", "--dry-run", "--plan-out", "plan.json"], "cmd_push", {
                "dry_run": True, "plan_path": None, "expected_plan_id": None,
                "plan_out": "plan.json", "authorization_path": None,
                "scope_id": None,
            }),
            (["push", "--plan", "plan.json", "--plan-id", "abc",
              "--authorization", "auth.json"], "cmd_push", {
                "dry_run": False, "plan_path": "plan.json",
                "expected_plan_id": "abc", "plan_out": None,
                "authorization_path": "auth.json", "scope_id": None,
            }),
            (["sync", "--dry-run"], "cmd_sync", {"dry_run": True}),
            (["status", "--audit"], "cmd_status", {"audit": True}),
            (["preflight"], "cmd_preflight", {}),
            (["reconcile"], "cmd_reconcile", {}),
        ]
        for argv, handler, expected_kwargs in cases:
            with self.subTest(argv=argv):
                result, calls, _ = self._run_cli_with_stubbed_handlers(argv)
                self.assertEqual(91, result)
                self.assertEqual([(handler, (), expected_kwargs)], calls)
                self.assertEqual([], self.fake_api.calls)

    def test_t019_scoped_plan_excludes_other_scope_operations_and_blockers(self):
        self._insert_project(scope_id="L-TARGET")
        self._insert_task(task_id="T001", scope_id="L-TARGET")
        self._insert_project(scope_id="L-OTHER-COLLISION")
        self._insert_project(scope_id="L-OTHER-PENDING")
        with closing(self._connect()) as conn:
            pending_row = dict(conn.execute(
                "SELECT * FROM projects WHERE scope_id=?", ("L-OTHER-PENDING",)
            ).fetchone())
            conn.execute(
                "INSERT INTO _metadata (key, value) VALUES (?, ?)",
                (
                    "pending_push:project:L-OTHER-PENDING",
                    self.sync.json.dumps({
                        "entity": "project",
                        "stable_key": ["L-OTHER-PENDING"],
                        "fingerprint": self.sync._mapped_fingerprint(
                            "project", pending_row
                        ),
                        "remote_page_id": "other-pending-page",
                    }),
                ),
            )
            conn.commit()
        api = self._install_fake_api(self._valid_reconciliation_responses(
            project_pages=[
                self._project_page(
                    "other-collision-page", "L-OTHER-COLLISION", "Incompatible"
                ),
                self._project_page(
                    "other-duplicate-a", "L-OTHER-DUPLICATE", "Duplicate"
                ),
                self._project_page(
                    "other-duplicate-b", "L-OTHER-DUPLICATE", "Duplicate"
                ),
            ],
        ))

        plan = self.sync.build_push_plan(
            scope_id="  L-TARGET  ", skip_preflight=True
        )

        self.assertEqual({"scope_id": "L-TARGET"}, plan["selector"])
        self.assertEqual(0, plan["exit_code"])
        self.assertEqual(2, len(plan["operations"]))
        self.assertTrue(all(
            operation["stable_key"][0] == "L-TARGET"
            for operation in plan["operations"]
        ))
        self.assertEqual(0, plan["reconciliation"]["blocking"]["exit_code"])
        self.assertGreaterEqual(
            plan["reconciliation"]["audit_only"]["summary"]["duplicate"], 1
        )
        self.assertEqual([], self._mutation_calls(api))

    def test_t019_scoped_preflight_reads_only_target_links(self):
        self._insert_project(scope_id="L-TARGET", notion_page_id="target-link")
        self._insert_project(scope_id="L-OTHER", notion_page_id="other-link")
        api = self._install_fake_api(
            self._valid_schema_responses()
            + [self._page_response(self.sync.PROJECTS_DB_ID)]
        )
        with closing(self._connect()) as conn:
            report = self.sync.run_preflight(conn, scope_id="L-TARGET")

        self.assertEqual("pass", report["status"])
        self.assertEqual(1, len(report["links"]["projects"]))
        self.assertEqual(3, len(api.calls))
        self.assertEqual([], self._mutation_calls(api))

    def test_t019_target_scope_collision_remains_blocking(self):
        self._insert_project(scope_id="L-TARGET")
        api = self._install_fake_api(self._valid_reconciliation_responses(
            project_pages=[
                self._project_page(
                    "target-collision-page", "L-TARGET", "Incompatible"
                )
            ],
        ))
        plan = self.sync.build_push_plan(scope_id="L-TARGET", skip_preflight=True)

        self.assertEqual(2, plan["exit_code"])
        self.assertEqual(
            1, plan["reconciliation"]["blocking"]["summary"]["collision"]
        )
        self.assertEqual([], self._mutation_calls(api))

    def test_t019_scope_selector_replay_and_operation_escape_fail_closed(self):
        self._insert_project(scope_id="L-TARGET")
        self._install_fake_api(self._valid_reconciliation_responses())
        plan = self.sync.build_push_plan(scope_id="L-TARGET", skip_preflight=True)
        self.assertTrue(self.sync.validate_push_plan(plan))
        selector_tamper = copy.deepcopy(plan)
        selector_tamper["selector"] = {"scope_id": "L-OTHER"}
        selector_tamper["plan_id"] = self.sync._push_plan_id(selector_tamper)
        self.assertNotEqual(plan["plan_id"], selector_tamper["plan_id"])

        database_before = file_fingerprint(self.test_db)
        self.assertEqual(2, self.sync.cmd_push(
            dry_run=True, plan=plan, expected_plan_id=plan["plan_id"],
            scope_id="L-OTHER",
        ))
        self.assertEqual(2, self.sync.cmd_push(
            dry_run=True, plan=plan, expected_plan_id=plan["plan_id"]
        ))
        self.assertEqual(database_before, file_fingerprint(self.test_db))

        escaped = copy.deepcopy(plan)
        escaped["operations"][0]["stable_key"][0] = "L-OTHER"
        escaped["plan_id"] = self.sync._push_plan_id(escaped)
        with mock.patch.object(
            self.sync, "_open_write_conn",
            side_effect=AssertionError("write connection must not open"),
        ):
            self.assertEqual(2, self.sync.execute_push_plan(
                escaped, scope_id="L-TARGET"
            ))

        self._insert_project(scope_id="L-OTHER")
        with closing(self._connect()) as conn:
            other_id = conn.execute(
                "SELECT id FROM projects WHERE scope_id=?", ("L-OTHER",)
            ).fetchone()[0]
        database_after_fixture = file_fingerprint(self.test_db)
        row_escape = copy.deepcopy(plan)
        row_escape["operations"][0]["local_row_id"] = other_id
        row_escape["plan_id"] = self.sync._push_plan_id(row_escape)
        with mock.patch.object(
            self.sync, "_open_write_conn",
            side_effect=AssertionError("write connection must not open"),
        ):
            self.assertEqual(2, self.sync.execute_push_plan(
                row_escape, scope_id="L-TARGET"
            ))
        self.assertEqual(database_after_fixture, file_fingerprint(self.test_db))
        self.assertEqual([], self._mutation_calls(self.fake_api))

    def test_t019_unknown_scope_stops_before_notion_read(self):
        plan = self.sync.build_push_plan(scope_id="L-UNKNOWN")
        self.assertEqual(3, plan["exit_code"])
        self.assertEqual([], plan["operations"])
        self.assertEqual({"scope_id": "L-UNKNOWN"}, plan["selector"])
        self.assertEqual([], self.fake_api.calls)

    def test_t019_scope_lookup_schema_error_fails_closed(self):
        with closing(self._connect()) as conn:
            conn.execute("DROP TABLE projects")
            conn.commit()
        plan = self.sync.build_push_plan(scope_id="L-TARGET")

        self.assertEqual(3, plan["exit_code"])
        self.assertEqual("LOCAL_SCHEMA_ERROR", plan["preflight"]["findings"][0]["code"])
        self.assertEqual([], self.fake_api.calls)

    def test_t019_global_plan_and_cli_remain_backward_compatible(self):
        self._insert_project(scope_id="L-FIRST")
        self._insert_project(scope_id="L-SECOND")
        self._install_fake_api(self._valid_reconciliation_responses())
        plan = self.sync.build_push_plan(skip_preflight=True)

        self.assertNotIn("selector", plan)
        self.assertEqual(2, len(plan["operations"]))
        self.assertTrue(self.sync.validate_push_plan(plan))
        result, calls, _ = self._run_cli_with_stubbed_handlers(
            ["push", "--scope", "L-TARGET", "--dry-run"]
        )
        self.assertEqual(91, result)
        self.assertEqual("L-TARGET", calls[0][2]["scope_id"])

    def test_t019_scoped_execute_reruns_to_zero_despite_other_dirty(self):
        self._insert_project(scope_id="L-TARGET")
        self._insert_task(task_id="T001", scope_id="L-TARGET")
        self._insert_project(scope_id="L-OTHER")
        api = self._install_fake_api(
            self._valid_reconciliation_responses()
            + self._valid_absence_revalidation_responses()
            + [
                {"id": "target-project-page", "last_edited_time": FIXED_NOTION_EDITED},
                {"id": "target-task-page", "last_edited_time": FIXED_NOTION_EDITED},
            ]
            + self._valid_reconciliation_responses()
        )
        plan = self.sync.build_push_plan(scope_id="L-TARGET", skip_preflight=True)
        self.assertEqual(0, self.sync.execute_push_plan(
            plan, scope_id="L-TARGET"
        ))
        rerun = self.sync.build_push_plan(scope_id="L-TARGET", skip_preflight=True)

        self.assertEqual(0, rerun["exit_code"])
        self.assertEqual([], rerun["operations"])
        self.assertEqual(2, len(self._mutation_calls(api)))

    def test_t019_empty_scope_is_cli_usage_error(self):
        result, calls, output = self._run_cli_with_stubbed_handlers(
            ["push", "--scope", "   "]
        )
        self.assertEqual(64, result)
        self.assertEqual([], calls)
        self.assertIn("ERROR:", output)


if __name__ == "__main__":
    unittest.main()
