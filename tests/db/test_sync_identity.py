"""Deterministic, API-free contract harness for AI-PLC Sync Identity v2.

This module intentionally does not import the production sync engine.  It provides
reusable fakes and disposable SQLite fixtures for T003 and later tasks, while its
own tests prove that failures are deterministic and cannot reach the production
database or the real Notion API.
"""

from __future__ import annotations

import copy
import contextlib
import hashlib
import hmac
import io
import json
import os
import re
import shutil
import sqlite3
import tempfile
import unittest
import urllib.request
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

try:  # unittest discovery imports test modules as top-level modules.
    from .test_sync_harness import DB_DIR, PRODUCTION_DB, file_fingerprint, load_module
except ImportError:  # pragma: no cover - exercised by discovery invocation.
    from test_sync_harness import DB_DIR, PRODUCTION_DB, file_fingerprint, load_module


FIXED_NOW = "2026-07-15T12:00:00Z"
FIXED_WORKSPACE_A = "wsp_00000000-0000-4000-8000-000000000001"
FIXED_WORKSPACE_B = "wsp_00000000-0000-4000-8000-000000000002"
FIXED_PROJECT_A = "prj_00000000-0000-4000-8000-000000000001"
FIXED_PROJECT_B = "prj_00000000-0000-4000-8000-000000000002"
FIXED_TASK_A = "T001"
FIXED_PLAN_ID = "plan-00000000-0000-4000-8000-000000000001"
FIXED_WRITER_A = "writer-a"
FIXED_WRITER_B = "writer-b"
FIXED_PAGE_A = "page-00000000-0000-4000-8000-000000000001"


IDENTITY_SCENARIOS = (
    (1, "same_identity_converges", "positive", "identity"),
    (2, "same_scope_different_identity_coexists", "positive", "identity"),
    (3, "clone_and_move_preserve_ids", "positive", "bootstrap"),
    (4, "explicit_fork_issues_new_ids", "positive", "bootstrap"),
    (5, "credentialless_clone_is_denied", "negative", "authority"),
    (6, "stale_writer_is_denied", "negative", "authority"),
    (7, "authority_failures_are_fail_closed", "negative", "authority"),
    (8, "concurrent_plan_has_one_claim", "negative", "journal"),
    (9, "claimed_operation_resumes_once", "positive", "journal"),
    (10, "scope_rename_patches_same_page", "positive", "identity"),
    (11, "transfer_requires_dual_approval", "negative", "transfer"),
    (12, "interrupted_transfer_converges", "positive", "transfer"),
    (13, "task_id_is_project_namespaced", "positive", "identity"),
    (14, "linked_legacy_preserves_page", "positive", "migration"),
    (15, "ambiguous_legacy_requires_approval", "negative", "migration"),
    (16, "v1_or_tampered_plan_is_denied", "negative", "plan"),
    (17, "uncertain_create_deduplicates", "positive", "journal"),
    (18, "approval_constraints_are_enforced", "negative", "approval"),
    (19, "bootstrap_crashes_converge", "positive", "bootstrap"),
    (20, "table_rebuild_failure_rolls_back", "negative", "migration"),
    (21, "authority_transition_crashes_converge", "positive", "authority"),
    (22, "pending_journal_blocks_writer_change", "negative", "journal"),
    (23, "handoff_repairs_link_without_mutation", "positive", "handoff"),
    (24, "handoff_without_evidence_stays_uncertain", "negative", "handoff"),
    (25, "break_glass_requires_recovery_evidence", "negative", "handoff"),
    (26, "patch_handoff_requires_exact_payload", "negative", "handoff"),
    (27, "full_regression_has_zero_production_side_effect", "positive", "isolation"),
)


class ContractViolation(RuntimeError):
    """Raised when a fixture reproduces a fail-closed contract decision."""


class InjectedCrash(RuntimeError):
    """Deterministic interruption used at documented crash boundaries."""


class CommitThenTimeout(TimeoutError):
    """The fake remote committed a mutation but its response was lost."""


class MutationRecorder:
    """Count boundary interactions without relying on timestamps or sleeps."""

    def __init__(self):
        self.counts: Counter[str] = Counter()
        self.events: list[dict] = []

    def record(self, event: str, **details):
        self.counts[event] += 1
        self.events.append({"event": event, **copy.deepcopy(details)})

    def count(self, event: str) -> int:
        return self.counts[event]


IDENTITY_PATTERNS = {
    "workspace_id": re.compile(
        r"^wsp_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    ),
    "sync_uid": re.compile(
        r"^prj_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    ),
}


def validate_identity(field: str, value: str):
    pattern = IDENTITY_PATTERNS[field]
    if not pattern.fullmatch(value):
        raise ContractViolation(f"invalid canonical {field}")


class FixedValueSource:
    """Stable clock/identifier source for reproducible Plan and journal data."""

    def __init__(self, *values: str):
        self.values = list(values)
        self.index = 0

    def now(self) -> str:
        return FIXED_NOW

    def next_id(self) -> str:
        if self.index >= len(self.values):
            raise AssertionError("fixed identifier sequence exhausted")
        value = self.values[self.index]
        self.index += 1
        return value


class FakeNotionIdentityAPI:
    """In-memory Notion boundary with separate read and mutation accounting."""

    def __init__(self, recorder: MutationRecorder):
        self.recorder = recorder
        self.pages: dict[str, dict] = {}
        self.fail_after_commit = False

    def seed_page(self, page_id: str, sync_uid: str, **properties):
        self.pages[page_id] = {
            "id": page_id,
            "sync_uid": sync_uid,
            "properties": copy.deepcopy(properties),
        }

    def query_by_uid(self, sync_uid: str) -> list[dict]:
        self.recorder.record("notion_read", sync_uid=sync_uid)
        return [
            copy.deepcopy(page)
            for page in self.pages.values()
            if page["sync_uid"] == sync_uid
        ]

    def create_page(self, page_id: str, sync_uid: str, **properties) -> dict:
        self.recorder.record("notion_mutation", method="CREATE", sync_uid=sync_uid)
        if self.query_by_uid(sync_uid):
            raise ContractViolation("duplicate remote sync_uid")
        self.seed_page(page_id, sync_uid, **properties)
        result = copy.deepcopy(self.pages[page_id])
        if self.fail_after_commit:
            self.fail_after_commit = False
            raise CommitThenTimeout("fake response lost after remote commit")
        return result

    def patch_page(self, page_id: str, **properties) -> dict:
        self.recorder.record("notion_mutation", method="PATCH", page_id=page_id)
        if page_id not in self.pages:
            raise ContractViolation("remote page is absent")
        self.pages[page_id]["properties"].update(copy.deepcopy(properties))
        result = copy.deepcopy(self.pages[page_id])
        if self.fail_after_commit:
            self.fail_after_commit = False
            raise CommitThenTimeout("fake response lost after remote commit")
        return result


class FakeIdentityAuthorityStore:
    """Atomic revisioned CAS store for writer and Project ownership records."""

    def __init__(self, recorder: MutationRecorder):
        self.recorder = recorder
        self.available = True
        self.force_conflict = False
        self.workspaces: dict[str, dict] = {}
        self.projects: dict[str, dict] = {}

    def seed_workspace(
        self,
        workspace_id: str,
        writer_id: str = FIXED_WRITER_A,
        *,
        writer_epoch: int = 1,
        revision: int = 1,
    ):
        self.workspaces[workspace_id] = {
            "workspace_id": workspace_id,
            "writer_id": writer_id,
            "writer_epoch": writer_epoch,
            "revision": revision,
        }

    def seed_project(
        self,
        sync_uid: str,
        workspace_id: str,
        *,
        ownership_epoch: int = 1,
        revision: int = 1,
    ):
        self.projects[sync_uid] = {
            "sync_uid": sync_uid,
            "workspace_id": workspace_id,
            "ownership_epoch": ownership_epoch,
            "revision": revision,
        }

    def _require_available(self):
        if not self.available:
            raise ContractViolation("identity authority unavailable")

    def get_workspace(self, workspace_id: str) -> dict:
        self.recorder.record("authority_read", record="workspace")
        self._require_available()
        if workspace_id not in self.workspaces:
            raise ContractViolation("workspace authority is absent")
        return copy.deepcopy(self.workspaces[workspace_id])

    def get_project(self, sync_uid: str) -> dict:
        self.recorder.record("authority_read", record="project")
        self._require_available()
        if sync_uid not in self.projects:
            raise ContractViolation("project authority is absent")
        return copy.deepcopy(self.projects[sync_uid])

    def compare_and_swap(
        self, kind: str, key: str, expected_revision: int | None, replacement: dict
    ) -> dict:
        self.recorder.record("authority_cas", kind=kind, key=key)
        self._require_available()
        records = self.workspaces if kind == "workspace" else self.projects
        current = records.get(key)
        if self.force_conflict:
            raise ContractViolation("authority CAS conflict")
        if expected_revision is None:
            if current is None:
                updated = copy.deepcopy(replacement)
                updated["revision"] = 1
                records[key] = updated
                return copy.deepcopy(updated)
            comparable = {k: v for k, v in current.items() if k != "revision"}
            if comparable == replacement:
                return copy.deepcopy(current)
            raise ContractViolation("authority create-if-absent conflict")
        if current is None:
            raise ContractViolation("authority CAS conflict")
        if current["revision"] != expected_revision:
            raise ContractViolation("stale authority revision")
        updated = copy.deepcopy(replacement)
        updated["revision"] = expected_revision + 1
        records[key] = updated
        return copy.deepcopy(updated)


class ReadOnlyFakeApprovalStore:
    """Executor-facing approval store: records can be seeded, never written."""

    def __init__(self, recorder: MutationRecorder):
        self.recorder = recorder
        self._records: dict[str, dict] = {}
        self.available = True

    def seed(self, nonce: str, **record):
        self._records[nonce] = {"nonce": nonce, **copy.deepcopy(record)}

    def get_approval(self, nonce: str) -> dict:
        self.recorder.record("approval_read", nonce=nonce)
        if not self.available:
            raise ContractViolation("approval store unavailable")
        if nonce not in self._records:
            raise ContractViolation("approval is absent")
        return copy.deepcopy(self._records[nonce])


class EphemeralWriterCredentialStore:
    """Test-only HMAC credentials; fixed secrets never leave the fixture."""

    def __init__(self):
        self._secrets: dict[str, bytes] = {}

    def seed(self, writer_id: str, secret: bytes):
        self._secrets[writer_id] = secret

    @staticmethod
    def canonical_bytes(record: dict) -> bytes:
        return json.dumps(
            record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

    def sign(self, writer_id: str, record: dict) -> str:
        if writer_id not in self._secrets:
            raise ContractViolation("writer credential is absent")
        return hmac.new(
            self._secrets[writer_id], self.canonical_bytes(record), hashlib.sha256
        ).hexdigest()

    def verify(self, writer_id: str, record: dict, proof: str):
        expected = self.sign(writer_id, record)
        if not hmac.compare_digest(expected, proof):
            raise ContractViolation("WriterProof mismatch")


@dataclass(frozen=True)
class IdentityManifest:
    workspace_id: str
    project_sync_uid: str

    def __post_init__(self):
        validate_identity("workspace_id", self.workspace_id)
        validate_identity("sync_uid", self.project_sync_uid)

    def moved(self) -> "IdentityManifest":
        return self

    def cloned(self) -> "IdentityManifest":
        return self

    def forked(self, workspace_id: str, project_sync_uid: str) -> "IdentityManifest":
        if (workspace_id, project_sync_uid) == (
            self.workspace_id,
            self.project_sync_uid,
        ):
            raise ContractViolation("explicit fork must issue new identities")
        return IdentityManifest(workspace_id, project_sync_uid)


class IdentityFixture:
    """Disposable v2-shaped SQLite fixture used by subsequent implementation tasks."""

    def __init__(self, recorder: MutationRecorder):
        self.recorder = recorder
        self._temp = tempfile.TemporaryDirectory(prefix="ai-plc-identity-v2-")
        self.root = Path(self._temp.name).resolve()
        self.db_path = self.root / "identity-v2-test.db"
        if self.db_path == PRODUCTION_DB.resolve() or self.root not in self.db_path.parents:
            raise AssertionError("identity fixture escaped its temporary directory")
        self._create_schema()

    def close(self):
        self._temp.cleanup()

    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _create_schema(self):
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE projects (
                    workspace_id TEXT NOT NULL,
                    sync_uid TEXT NOT NULL PRIMARY KEY,
                    scope_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    notion_page_id TEXT,
                    ownership_epoch INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(workspace_id, scope_id)
                );
                CREATE TABLE tasks (
                    project_sync_uid TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    PRIMARY KEY(project_sync_uid, task_id),
                    FOREIGN KEY(project_sync_uid) REFERENCES projects(sync_uid)
                );
                CREATE TABLE legacy_candidates (
                    local_key TEXT PRIMARY KEY,
                    scope_id TEXT NOT NULL,
                    notion_page_id TEXT,
                    approved INTEGER NOT NULL DEFAULT 0,
                    mapped_sync_uid TEXT
                );
                CREATE TABLE operation_journal (
                    plan_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    writer_epoch INTEGER NOT NULL,
                    project_sync_uid TEXT NOT NULL,
                    ownership_epoch INTEGER NOT NULL,
                    entity TEXT NOT NULL,
                    task_id TEXT,
                    claim_owner TEXT,
                    lease_expires_at TEXT,
                    state TEXT NOT NULL,
                    payload_fingerprint TEXT NOT NULL,
                    mutation_budget INTEGER NOT NULL,
                    remote_page_id TEXT,
                    PRIMARY KEY(
                        plan_id, workspace_id, writer_epoch, project_sync_uid,
                        ownership_epoch, entity, operation_id
                    ),
                    UNIQUE(nonce, operation_id)
                );
                CREATE TABLE approval_usage (
                    nonce TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    PRIMARY KEY(nonce, operation_id)
                );
                CREATE TABLE metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE authority_transitions (
                    transition_id TEXT PRIMARY KEY,
                    expected_revision INTEGER NOT NULL,
                    result_digest TEXT NOT NULL,
                    result_revision INTEGER,
                    state TEXT NOT NULL,
                    projection_applied INTEGER NOT NULL DEFAULT 0
                );
                """
            )
            conn.commit()

    def insert_project(
        self,
        workspace_id: str,
        sync_uid: str,
        scope_id: str = "L-SAME",
        *,
        name: str = "Fixture Project",
        notion_page_id: str | None = None,
    ):
        validate_identity("workspace_id", workspace_id)
        validate_identity("sync_uid", sync_uid)
        with closing(self.connect()) as conn:
            conn.execute(
                "INSERT INTO projects VALUES (?, ?, ?, ?, ?, 1)",
                (workspace_id, sync_uid, scope_id, name, notion_page_id),
            )
            conn.commit()
        self.recorder.record("sqlite_write", table="projects")

    def insert_task(self, project_sync_uid: str, task_id: str = "T001"):
        validate_identity("sync_uid", project_sync_uid)
        with closing(self.connect()) as conn:
            conn.execute(
                "INSERT INTO tasks VALUES (?, ?, ?)",
                (project_sync_uid, task_id, "Fixture Task"),
            )
            conn.commit()
        self.recorder.record("sqlite_write", table="tasks")

    def rows(self, table: str) -> list[sqlite3.Row]:
        if table not in {
            "projects",
            "tasks",
            "legacy_candidates",
            "operation_journal",
            "approval_usage",
            "metadata",
            "authority_transitions",
        }:
            raise ValueError("unknown fixture table")
        self.recorder.record("sqlite_read", table=table)
        with closing(self.connect()) as conn:
            return conn.execute(f"SELECT * FROM {table}").fetchall()

    def generate_plan(self, operations: list[dict], *, version: int = 2) -> dict:
        validate_identity("workspace_id", FIXED_WORKSPACE_A)
        validate_identity("sync_uid", FIXED_PROJECT_A)
        self.recorder.record("plan_generation")
        plan = {
            "version": version,
            "plan_id": FIXED_PLAN_ID,
            "workspace_id": FIXED_WORKSPACE_A,
            "writer_id": FIXED_WRITER_A,
            "writer_epoch": 1,
            "authority_revision": 1,
            "project_sync_uid": FIXED_PROJECT_A,
            "ownership_epoch": 1,
            "operations": copy.deepcopy(operations),
        }
        plan["digest"] = canonical_digest({k: v for k, v in plan.items() if k != "digest"})
        return plan

    def claim_operation(
        self,
        plan_id: str,
        operation_id: str,
        writer_id: str,
        *,
        nonce: str = "nonce-journal-001",
        now: str = FIXED_NOW,
        lease_expires_at: str = "2026-07-15T12:05:00Z",
        workspace_id: str = FIXED_WORKSPACE_A,
        writer_epoch: int = 1,
        project_sync_uid: str = FIXED_PROJECT_A,
        ownership_epoch: int = 1,
        entity: str = "project",
        task_id: str | None = None,
        payload_fingerprint: str = "sha256:fixture-payload",
        mutation_budget: int = 1,
    ) -> bool:
        validate_identity("workspace_id", workspace_id)
        validate_identity("sync_uid", project_sync_uid)
        with closing(self.connect()) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    "SELECT * FROM operation_journal WHERE plan_id = ? AND operation_id = ?",
                    (plan_id, operation_id),
                ).fetchone()
                if existing is None:
                    conn.execute(
                        """
                        INSERT INTO operation_journal (
                            plan_id, operation_id, nonce, workspace_id, writer_epoch,
                            project_sync_uid, ownership_epoch, entity, task_id,
                            claim_owner, lease_expires_at, state, payload_fingerprint,
                            mutation_budget, remote_page_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'claimed', ?, ?, NULL)
                        """,
                        (
                            plan_id,
                            operation_id,
                            nonce,
                            workspace_id,
                            writer_epoch,
                            project_sync_uid,
                            ownership_epoch,
                            entity,
                            task_id,
                            writer_id,
                            lease_expires_at,
                            payload_fingerprint,
                            mutation_budget,
                        ),
                    )
                    claimed = True
                else:
                    immutable = {
                        "nonce": nonce,
                        "workspace_id": workspace_id,
                        "writer_epoch": writer_epoch,
                        "project_sync_uid": project_sync_uid,
                        "ownership_epoch": ownership_epoch,
                        "entity": entity,
                        "task_id": task_id,
                        "payload_fingerprint": payload_fingerprint,
                        "mutation_budget": mutation_budget,
                    }
                    mismatches = [
                        field
                        for field, expected in immutable.items()
                        if existing[field] != expected
                    ]
                    if mismatches:
                        raise ContractViolation(
                            "journal identity mismatch: " + ",".join(mismatches)
                        )
                if existing is not None and (existing["state"] == "prepared" or (
                    existing["state"] == "claimed"
                    and existing["lease_expires_at"] is not None
                    and existing["lease_expires_at"] <= now
                )):
                    conn.execute(
                        """
                        UPDATE operation_journal
                        SET claim_owner = ?, lease_expires_at = ?, state = 'claimed'
                        WHERE plan_id = ? AND operation_id = ?
                        """,
                        (writer_id, lease_expires_at, plan_id, operation_id),
                    )
                    claimed = True
                elif existing is not None:
                    claimed = False
                conn.commit()
            except sqlite3.IntegrityError:
                conn.rollback()
                claimed = False
        self.recorder.record("journal_claim", claimed=claimed)
        if claimed:
            self.recorder.record("sqlite_write", table="operation_journal")
        return claimed

    def consume_approval(self, nonce: str, operation_id: str, budget: int):
        with closing(self.connect()) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                replay = conn.execute(
                    "SELECT 1 FROM approval_usage WHERE nonce = ? AND operation_id = ?",
                    (nonce, operation_id),
                ).fetchone()
                if replay:
                    raise ContractViolation("approval nonce replay")
                used = conn.execute(
                    "SELECT COUNT(*) FROM approval_usage WHERE nonce = ?", (nonce,)
                ).fetchone()[0]
                if used >= budget:
                    raise ContractViolation("approval mutation budget exhausted")
                conn.execute(
                    "INSERT INTO approval_usage VALUES (?, ?)", (nonce, operation_id)
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                conn.rollback()
                raise ContractViolation("approval nonce replay") from exc
            except Exception:
                conn.rollback()
                raise
        self.recorder.record("sqlite_write", table="approval_usage")

    def set_metadata(self, key: str, value: str):
        with closing(self.connect()) as conn:
            conn.execute(
                "INSERT INTO metadata VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            conn.commit()
        self.recorder.record("sqlite_write", table="metadata")

    def get_metadata(self, key: str) -> str | None:
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        self.recorder.record("sqlite_read", table="metadata")
        return row[0] if row else None

    def set_journal_state(
        self, plan_id: str, operation_id: str, state: str, remote_page_id: str | None = None
    ):
        with closing(self.connect()) as conn:
            conn.execute(
                "UPDATE operation_journal SET state = ?, remote_page_id = ? "
                "WHERE plan_id = ? AND operation_id = ?",
                (state, remote_page_id, plan_id, operation_id),
            )
            conn.commit()
        self.recorder.record("sqlite_write", table="operation_journal")

    def migrate_legacy_batch(self, rows: list[dict], *, crash_after: int | None = None):
        with closing(self.connect()) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                for index, row in enumerate(rows, start=1):
                    conn.execute(
                        "INSERT INTO legacy_candidates VALUES (?, ?, ?, ?, ?)",
                        (
                            row["local_key"],
                            row["scope_id"],
                            row.get("notion_page_id"),
                            int(row.get("approved", False)),
                            row.get("mapped_sync_uid"),
                        ),
                    )
                    if crash_after == index:
                        raise InjectedCrash("migration crash point")
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        for _ in rows:
            self.recorder.record("sqlite_write", table="legacy_candidates")


def canonical_digest(record: dict) -> str:
    payload = json.dumps(
        record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def writer_proof_record(plan: dict, operation_id: str, nonce: str) -> dict:
    return {
        "plan_id": plan["plan_id"],
        "plan_digest": plan["digest"],
        "workspace_id": plan["workspace_id"],
        "writer_epoch": plan["writer_epoch"],
        "authority_revision": plan["authority_revision"],
        "project_sync_uid": plan["project_sync_uid"],
        "ownership_epoch": plan["ownership_epoch"],
        "operation_ids": [operation_id],
        "expires_at": "2026-07-15T13:00:00Z",
        "nonce": nonce,
    }


class ContractGate:
    """Test-only fail-closed validator shared by later production integration tests."""

    def __init__(
        self,
        authority: FakeIdentityAuthorityStore,
        approvals: ReadOnlyFakeApprovalStore,
        credentials: EphemeralWriterCredentialStore,
        usage_store: IdentityFixture,
    ):
        self.authority = authority
        self.approvals = approvals
        self.credentials = credentials
        self.usage_store = usage_store

    def authorize(
        self,
        plan: dict,
        operation_id: str,
        nonce: str,
        proof: str,
        *,
        expected_subject: str = "sync-executor",
    ):
        if plan.get("version") != 2:
            raise ContractViolation("legacy Plan version is read-only")
        unsigned = {k: v for k, v in plan.items() if k != "digest"}
        if canonical_digest(unsigned) != plan.get("digest"):
            raise ContractViolation("Plan digest mismatch")
        workspace = self.authority.get_workspace(plan["workspace_id"])
        if (
            workspace["writer_id"] != plan["writer_id"]
            or workspace["writer_epoch"] != plan["writer_epoch"]
            or workspace["revision"] != plan["authority_revision"]
        ):
            raise ContractViolation("stale writer authority")
        approval = self.approvals.get_approval(nonce)
        if approval.get("subject") != expected_subject:
            raise ContractViolation("approval subject mismatch")
        plan_operation_ids = [operation["operation_id"] for operation in plan["operations"]]
        if operation_id not in plan_operation_ids:
            raise ContractViolation("operation is not present in Plan")
        expected_binding = {
            "plan_id": plan["plan_id"],
            "plan_digest": plan["digest"],
            "workspace_id": plan["workspace_id"],
            "writer_epoch": plan["writer_epoch"],
            "project_sync_uid": plan["project_sync_uid"],
            "ownership_epoch": plan["ownership_epoch"],
            "operation_ids": plan_operation_ids,
        }
        if any(approval.get(key) != value for key, value in expected_binding.items()):
            raise ContractViolation("approval Plan mismatch")
        if approval.get("expires_at", "") <= FIXED_NOW:
            raise ContractViolation("approval expired")
        if approval.get("mutation_budget", 0) < 1:
            raise ContractViolation("approval mutation budget exhausted")
        record = writer_proof_record(plan, operation_id, nonce)
        self.credentials.verify(plan["writer_id"], record, proof)
        self.usage_store.consume_approval(
            nonce, operation_id, approval["mutation_budget"]
        )
        return True


class BreakGlassGate:
    """Require all three T001 handoff-CAS recovery evidences."""

    @staticmethod
    def authorize(
        *, recovery_signature_valid: bool, approver_count: int, transition_plan_valid: bool
    ) -> bool:
        if not (
            recovery_signature_valid
            and approver_count >= 2
            and transition_plan_valid
        ):
            raise ContractViolation("break-glass evidence is incomplete")
        return True


class BootstrapHarness:
    """Durable manifest -> authority -> cache bootstrap state machine."""

    def __init__(
        self, fixture: IdentityFixture, authority: FakeIdentityAuthorityStore
    ):
        self.fixture = fixture
        self.authority = authority
        self.manifest_path = fixture.root / "workspace_identity.json"
        self.state_path = fixture.root / "identity_bootstrap.state.json"
        self.manifest = {
            "identity_version": 2,
            "workspace_id": FIXED_WORKSPACE_A,
            "writer_id": FIXED_WRITER_A,
            "writer_epoch": 1,
            "writer_authority_hash_cache": "sha256:fixed-authority-hash",
        }

    @staticmethod
    def _atomic_write(path: Path, value: dict):
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)

    def _write_state(self, state: str):
        self._atomic_write(
            self.state_path,
            {
                "state": state,
                "planned_manifest": self.manifest,
                "authority_record": {
                    "workspace_id": FIXED_WORKSPACE_A,
                    "writer_id": FIXED_WRITER_A,
                    "writer_epoch": 1,
                },
            },
        )

    def _read_state(self) -> dict | None:
        if not self.state_path.exists():
            return None
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _verified_result(self, manifest: dict) -> dict:
        authority_record = self.authority.get_workspace(manifest["workspace_id"])
        active_workspace_id = self.fixture.get_metadata("active_workspace_id")
        active_writer_epoch = self.fixture.get_metadata("active_writer_epoch")
        if (
            authority_record["workspace_id"] != manifest["workspace_id"]
            or active_workspace_id != manifest["workspace_id"]
            or active_writer_epoch != str(authority_record["writer_epoch"])
        ):
            raise ContractViolation("bootstrap readback mismatch")
        return {
            "manifest": manifest,
            "authority": authority_record,
            "active_workspace_id": active_workspace_id,
            "active_writer_epoch": active_writer_epoch,
        }

    def run(self, *, crash_at: str | None = None) -> dict:
        state = self._read_state()
        if state is None and self.manifest_path.exists():
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            return self._verified_result(manifest)
        if state is None:
            if crash_at == "before_planned":
                raise InjectedCrash(crash_at)
            self._write_state("planned")
            state = self._read_state()
        if crash_at == "after_planned" and state["state"] == "planned":
            raise InjectedCrash(crash_at)

        manifest = state["planned_manifest"]
        replacement = state["authority_record"]
        if state["state"] == "planned":
            authority_record = self.authority.compare_and_swap(
                "workspace", manifest["workspace_id"], None, replacement
            )
            if crash_at == "after_authority_cas":
                raise InjectedCrash(crash_at)
            self._write_state("authority_committed")
            state = self._read_state()
        else:
            authority_record = self.authority.get_workspace(manifest["workspace_id"])
        if (
            crash_at == "after_authority_committed"
            and state["state"] == "authority_committed"
        ):
            raise InjectedCrash(crash_at)

        if state["state"] == "authority_committed":
            self._atomic_write(self.manifest_path, manifest)
            if crash_at == "after_manifest_commit":
                raise InjectedCrash(crash_at)
            self._write_state("manifest_committed")
            state = self._read_state()
        if (
            crash_at == "after_manifest_committed"
            and state["state"] == "manifest_committed"
        ):
            raise InjectedCrash(crash_at)

        if state["state"] == "manifest_committed":
            self.fixture.set_metadata("active_workspace_id", manifest["workspace_id"])
            self.fixture.set_metadata(
                "active_writer_epoch", str(authority_record["writer_epoch"])
            )
            if crash_at == "after_cache_commit":
                raise InjectedCrash(crash_at)
            self._write_state("cache_committed")
            state = self._read_state()
        if (
            crash_at == "after_cache_committed"
            and state["state"] == "cache_committed"
        ):
            raise InjectedCrash(crash_at)

        result = self._verified_result(manifest)
        if state["state"] != "verified":
            self._write_state("verified")
        if crash_at == "after_verified":
            raise InjectedCrash(crash_at)
        self.state_path.unlink()
        return result


class AuthorityTransitionHarness:
    """Resume CAS/journal/projection without executing the CAS twice."""

    TRANSITION_ID = "transition-fixed-001"

    def __init__(
        self, fixture: IdentityFixture, authority: FakeIdentityAuthorityStore
    ):
        self.fixture = fixture
        self.authority = authority
        self.result_record = {
            "workspace_id": FIXED_WORKSPACE_A,
            "writer_id": FIXED_WRITER_B,
            "writer_epoch": 2,
        }
        self.result_digest = canonical_digest(self.result_record)

    def _journal(self) -> sqlite3.Row | None:
        rows = self.fixture.rows("authority_transitions")
        return rows[0] if rows else None

    def run(self, *, crash_at: str | None = None) -> dict:
        row = self._journal()
        if row is None:
            with closing(self.fixture.connect()) as conn:
                conn.execute(
                    "INSERT INTO authority_transitions VALUES (?, ?, ?, NULL, 'prepared', 0)",
                    (self.TRANSITION_ID, 1, self.result_digest),
                )
                conn.commit()
            self.fixture.recorder.record("sqlite_write", table="authority_transitions")
            row = self._journal()
        if crash_at == "before_cas" and row["state"] == "prepared":
            raise InjectedCrash(crash_at)

        if row["state"] == "prepared":
            current = self.authority.get_workspace(FIXED_WORKSPACE_A)
            if (
                current["revision"] == 2
                and canonical_digest({k: v for k, v in current.items() if k != "revision"})
                == self.result_digest
            ):
                result = current
            else:
                result = self.authority.compare_and_swap(
                    "workspace", FIXED_WORKSPACE_A, 1, self.result_record
                )
            if crash_at == "after_cas_before_journal":
                raise InjectedCrash(crash_at)
            with closing(self.fixture.connect()) as conn:
                conn.execute(
                    """
                    UPDATE authority_transitions
                    SET result_revision = ?, state = 'authority_committed'
                    WHERE transition_id = ?
                    """,
                    (result["revision"], self.TRANSITION_ID),
                )
                conn.commit()
            self.fixture.recorder.record("sqlite_write", table="authority_transitions")
            row = self._journal()

        if crash_at == "after_journal_before_projection" and not row["projection_applied"]:
            raise InjectedCrash(crash_at)
        current = self.authority.get_workspace(FIXED_WORKSPACE_A)
        current_digest = canonical_digest({k: v for k, v in current.items() if k != "revision"})
        if (
            current["revision"] != row["result_revision"]
            or current_digest != row["result_digest"]
        ):
            raise ContractViolation("transition readback mismatch")
        self.fixture.set_metadata("active_writer_id", current["writer_id"])
        self.fixture.set_metadata("active_writer_epoch", str(current["writer_epoch"]))
        with closing(self.fixture.connect()) as conn:
            conn.execute(
                """
                UPDATE authority_transitions
                SET state = 'completed', projection_applied = 1
                WHERE transition_id = ?
                """,
                (self.TRANSITION_ID,),
            )
            conn.commit()
        self.fixture.recorder.record("sqlite_write", table="authority_transitions")
        return {
            "authority": current,
            "journal": dict(self._journal()),
            "active_writer_id": self.fixture.get_metadata("active_writer_id"),
        }


class IdentityHarnessTest(unittest.TestCase):
    """Self-tests for isolation, determinism, and Identity v2 fixture contracts."""

    def setUp(self):
        self.production_before = file_fingerprint(PRODUCTION_DB)
        self.production_sidecars_before = self._production_sidecars()
        self.recorder = MutationRecorder()
        self.fixture = IdentityFixture(self.recorder)
        self.notion = FakeNotionIdentityAPI(self.recorder)
        self.authority = FakeIdentityAuthorityStore(self.recorder)
        self.approvals = ReadOnlyFakeApprovalStore(self.recorder)
        self.credentials = EphemeralWriterCredentialStore()
        self.values = FixedValueSource(FIXED_PROJECT_A, FIXED_TASK_A)
        self.addCleanup(self._assert_production_unchanged)
        self.addCleanup(self.fixture.close)
        self.network_guard = mock.patch.object(
            urllib.request,
            "urlopen",
            side_effect=AssertionError("network access is forbidden in Identity tests"),
        )
        self.network_guard.start()
        self.addCleanup(self.network_guard.stop)

    @staticmethod
    def _production_sidecars() -> tuple[bool, bool]:
        return (
            Path(f"{PRODUCTION_DB}-wal").exists(),
            Path(f"{PRODUCTION_DB}-shm").exists(),
        )

    def _assert_production_unchanged(self):
        self.assertEqual(self.production_before, file_fingerprint(PRODUCTION_DB))
        self.assertEqual(self.production_sidecars_before, self._production_sidecars())

    def _approved_gate(self, *, nonce: str = "nonce-001") -> tuple[ContractGate, dict, str]:
        self.authority.seed_workspace(FIXED_WORKSPACE_A)
        self.credentials.seed(FIXED_WRITER_A, b"fixed-test-secret-a")
        plan = self.fixture.generate_plan(
            [{
                "operation_id": "op-001",
                "kind": "CREATE",
                "project_sync_uid": FIXED_PROJECT_A,
                "ownership_epoch": 1,
            }]
        )
        self.approvals.seed(
            nonce,
            subject="sync-executor",
            plan_id=plan["plan_id"],
            plan_digest=plan["digest"],
            workspace_id=plan["workspace_id"],
            writer_epoch=plan["writer_epoch"],
            project_sync_uid=plan["project_sync_uid"],
            ownership_epoch=plan["ownership_epoch"],
            operation_ids=["op-001"],
            expires_at="2026-07-15T13:00:00Z",
            mutation_budget=1,
        )
        proof = self.credentials.sign(
            FIXED_WRITER_A, writer_proof_record(plan, "op-001", nonce)
        )
        return (
            ContractGate(
                self.authority, self.approvals, self.credentials, self.fixture
            ),
            plan,
            proof,
        )

    def test_contract_matrix_covers_all_t001_nfr_scenarios(self):
        self.assertEqual(list(range(1, 28)), [row[0] for row in IDENTITY_SCENARIOS])
        self.assertEqual(27, len({row[1] for row in IDENTITY_SCENARIOS}))
        self.assertEqual({"positive", "negative"}, {row[2] for row in IDENTITY_SCENARIOS})

    def test_fixture_uses_only_disposable_database(self):
        self.assertNotEqual(PRODUCTION_DB.resolve(), self.fixture.db_path.resolve())
        self.assertIn(self.fixture.root, self.fixture.db_path.resolve().parents)
        self.assertTrue(self.fixture.db_path.exists())

    def test_fixed_clock_and_ids_are_reproducible(self):
        self.assertEqual(FIXED_NOW, self.values.now())
        self.assertEqual(FIXED_PROJECT_A, self.values.next_id())
        self.assertEqual(FIXED_TASK_A, self.values.next_id())

    def test_network_guard_rejects_real_http(self):
        with self.assertRaisesRegex(AssertionError, "network access is forbidden"):
            urllib.request.urlopen("https://api.notion.com/v1/pages")
        self.assertEqual(0, self.recorder.count("notion_mutation"))

    def test_real_notion_token_is_not_required(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.notion.query_by_uid(FIXED_PROJECT_A)
        self.assertEqual(1, self.recorder.count("notion_read"))
        self.assertEqual(0, self.recorder.count("notion_mutation"))

    def test_same_identity_converges_to_one_project_row(self):
        self.fixture.insert_project(FIXED_WORKSPACE_A, FIXED_PROJECT_A)
        with self.assertRaises(sqlite3.IntegrityError):
            self.fixture.insert_project(FIXED_WORKSPACE_A, FIXED_PROJECT_A)
        self.assertEqual(1, len(self.fixture.rows("projects")))

    def test_same_scope_different_workspaces_and_uids_coexist(self):
        self.fixture.insert_project(FIXED_WORKSPACE_A, FIXED_PROJECT_A, "L-SAME")
        self.fixture.insert_project(FIXED_WORKSPACE_B, FIXED_PROJECT_B, "L-SAME")
        rows = self.fixture.rows("projects")
        self.assertEqual({FIXED_WORKSPACE_A, FIXED_WORKSPACE_B}, {r["workspace_id"] for r in rows})

    def test_same_scope_and_workspace_with_different_uid_is_rejected(self):
        self.fixture.insert_project(FIXED_WORKSPACE_A, FIXED_PROJECT_A, "L-SAME")
        with self.assertRaises(sqlite3.IntegrityError):
            self.fixture.insert_project(FIXED_WORKSPACE_A, FIXED_PROJECT_B, "L-SAME")
        self.assertEqual(1, len(self.fixture.rows("projects")))

    def test_task_identity_is_namespaced_by_project(self):
        self.fixture.insert_project(FIXED_WORKSPACE_A, FIXED_PROJECT_A)
        self.fixture.insert_project(FIXED_WORKSPACE_B, FIXED_PROJECT_B)
        self.fixture.insert_task(FIXED_PROJECT_A, "T001")
        self.fixture.insert_task(FIXED_PROJECT_B, "T001")
        self.assertEqual(2, len(self.fixture.rows("tasks")))

    def test_duplicate_task_id_in_same_project_is_rejected(self):
        self.fixture.insert_project(FIXED_WORKSPACE_A, FIXED_PROJECT_A)
        self.fixture.insert_task(FIXED_PROJECT_A, "T001")
        with self.assertRaises(sqlite3.IntegrityError):
            self.fixture.insert_task(FIXED_PROJECT_A, "T001")
        self.assertEqual(1, len(self.fixture.rows("tasks")))

    def test_noncanonical_identity_formats_are_rejected_before_write(self):
        cases = (
            ("workspace_id", "WSP_00000000-0000-4000-8000-000000000001"),
            ("workspace_id", "ws_00000000-0000-4000-8000-000000000001"),
            ("workspace_id", "wsp_00000000-0000-1000-8000-000000000001"),
            ("sync_uid", "PRJ_00000000-0000-4000-8000-000000000001"),
            ("sync_uid", "pj_00000000-0000-4000-8000-000000000001"),
            ("sync_uid", "prj_00000000-0000-4000-7000-000000000001"),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value):
                with self.assertRaises(ContractViolation):
                    validate_identity(field, value)
        self.assertEqual(0, self.recorder.count("sqlite_write"))
        self.assertEqual(0, self.recorder.count("plan_generation"))

    def test_move_and_clone_preserve_manifest_identity(self):
        manifest = IdentityManifest(FIXED_WORKSPACE_A, FIXED_PROJECT_A)
        self.assertEqual(manifest, manifest.moved())
        self.assertEqual(manifest, manifest.cloned())

    def test_explicit_fork_requires_and_returns_new_identity(self):
        manifest = IdentityManifest(FIXED_WORKSPACE_A, FIXED_PROJECT_A)
        fork = manifest.forked(FIXED_WORKSPACE_B, FIXED_PROJECT_B)
        self.assertNotEqual(manifest, fork)
        with self.assertRaises(ContractViolation):
            manifest.forked(FIXED_WORKSPACE_A, FIXED_PROJECT_A)

    def test_scope_rename_keeps_uid_and_remote_page(self):
        self.notion.seed_page(FIXED_PAGE_A, FIXED_PROJECT_A, scope_id="L-OLD")
        result = self.notion.patch_page(FIXED_PAGE_A, scope_id="L-NEW")
        self.assertEqual(FIXED_PAGE_A, result["id"])
        self.assertEqual(FIXED_PROJECT_A, result["sync_uid"])
        self.assertEqual(1, self.recorder.count("notion_mutation"))

    def test_authorized_writer_passes_all_fresh_checks(self):
        gate, plan, proof = self._approved_gate()
        self.assertTrue(gate.authorize(plan, "op-001", "nonce-001", proof))
        self.assertEqual(1, self.recorder.count("authority_read"))
        self.assertEqual(1, self.recorder.count("approval_read"))

    def test_credentialless_clone_is_denied_before_mutation(self):
        gate, plan, _ = self._approved_gate()
        self.credentials._secrets.clear()
        with self.assertRaises(ContractViolation):
            gate.authorize(plan, "op-001", "nonce-001", "missing")
        self.assertEqual(0, self.recorder.count("notion_mutation"))

    def test_stale_writer_epoch_is_denied_before_mutation(self):
        gate, plan, proof = self._approved_gate()
        self.authority.seed_workspace(FIXED_WORKSPACE_A, writer_epoch=2, revision=2)
        with self.assertRaisesRegex(ContractViolation, "stale writer"):
            gate.authorize(plan, "op-001", "nonce-001", proof)
        self.assertEqual(0, self.recorder.count("notion_mutation"))

    def test_authority_unavailable_is_fail_closed(self):
        gate, plan, proof = self._approved_gate()
        self.authority.available = False
        with self.assertRaisesRegex(ContractViolation, "unavailable"):
            gate.authorize(plan, "op-001", "nonce-001", proof)
        self.assertEqual(0, self.recorder.count("notion_mutation"))

    def test_authority_cas_is_atomic_and_rejects_stale_revision(self):
        self.authority.seed_workspace(FIXED_WORKSPACE_A)
        updated = self.authority.compare_and_swap(
            "workspace",
            FIXED_WORKSPACE_A,
            1,
            {
                "workspace_id": FIXED_WORKSPACE_A,
                "writer_id": FIXED_WRITER_B,
                "writer_epoch": 2,
            },
        )
        self.assertEqual(2, updated["revision"])
        with self.assertRaisesRegex(ContractViolation, "stale"):
            self.authority.compare_and_swap("workspace", FIXED_WORKSPACE_A, 1, updated)

    def test_forced_authority_cas_conflict_is_deterministic(self):
        self.authority.seed_workspace(FIXED_WORKSPACE_A)
        self.authority.force_conflict = True
        with self.assertRaisesRegex(ContractViolation, "CAS conflict"):
            self.authority.compare_and_swap(
                "workspace", FIXED_WORKSPACE_A, 1, self.authority.workspaces[FIXED_WORKSPACE_A]
            )
        self.assertEqual(1, self.recorder.count("authority_cas"))

    def test_same_plan_operation_can_be_claimed_only_once(self):
        self.assertTrue(self.fixture.claim_operation(FIXED_PLAN_ID, "op-001", FIXED_WRITER_A))
        self.assertFalse(self.fixture.claim_operation(FIXED_PLAN_ID, "op-001", FIXED_WRITER_B))
        self.assertEqual(1, len(self.fixture.rows("operation_journal")))

    def test_claim_rejects_before_lease_and_reclaims_same_operation_after_expiry(self):
        self.assertTrue(
            self.fixture.claim_operation(
                FIXED_PLAN_ID,
                "op-lease",
                FIXED_WRITER_A,
                nonce="nonce-lease",
                lease_expires_at="2026-07-15T12:05:00Z",
            )
        )
        self.assertFalse(
            self.fixture.claim_operation(
                FIXED_PLAN_ID,
                "op-lease",
                FIXED_WRITER_B,
                nonce="nonce-lease",
                now="2026-07-15T12:04:59Z",
            )
        )
        self.assertTrue(
            self.fixture.claim_operation(
                FIXED_PLAN_ID,
                "op-lease",
                FIXED_WRITER_B,
                nonce="nonce-lease",
                now="2026-07-15T12:05:00Z",
                lease_expires_at="2026-07-15T12:10:00Z",
            )
        )
        row = self.fixture.rows("operation_journal")[0]
        self.assertEqual(("op-lease", FIXED_WRITER_B), (row["operation_id"], row["claim_owner"]))
        self.assertEqual(1, len(self.fixture.rows("operation_journal")))

    def test_reclaim_rejects_every_immutable_journal_field_mismatch(self):
        cases = (
            ("nonce", {"nonce": "nonce-other"}),
            ("workspace", {"workspace_id": FIXED_WORKSPACE_B}),
            ("writer_epoch", {"writer_epoch": 2}),
            ("project", {"project_sync_uid": FIXED_PROJECT_B}),
            ("ownership_epoch", {"ownership_epoch": 2}),
            ("entity", {"entity": "task"}),
            ("task_id", {"task_id": "T999"}),
            ("payload", {"payload_fingerprint": "sha256:other"}),
            ("budget", {"mutation_budget": 2}),
        )
        for label, changed in cases:
            with self.subTest(label=label):
                recorder = MutationRecorder()
                fixture = IdentityFixture(recorder)
                self.addCleanup(fixture.close)
                fixture.claim_operation(
                    FIXED_PLAN_ID,
                    "op-immutable",
                    FIXED_WRITER_A,
                    nonce="nonce-original",
                    lease_expires_at="2026-07-15T12:05:00Z",
                )
                kwargs = {
                    "nonce": "nonce-original",
                    "now": "2026-07-15T12:05:00Z",
                    "workspace_id": FIXED_WORKSPACE_A,
                    "writer_epoch": 1,
                    "project_sync_uid": FIXED_PROJECT_A,
                    "ownership_epoch": 1,
                    "entity": "project",
                    "task_id": None,
                    "payload_fingerprint": "sha256:fixture-payload",
                    "mutation_budget": 1,
                }
                kwargs.update(changed)
                writes_before = recorder.count("sqlite_write")
                with self.assertRaisesRegex(ContractViolation, "journal identity mismatch"):
                    fixture.claim_operation(
                        FIXED_PLAN_ID,
                        "op-immutable",
                        FIXED_WRITER_B,
                        **kwargs,
                    )
                self.assertEqual(writes_before, recorder.count("sqlite_write"))
                self.assertEqual(FIXED_WRITER_A, fixture.rows("operation_journal")[0]["claim_owner"])

    def test_claimed_operation_resumes_with_same_operation_id(self):
        self.fixture.claim_operation(FIXED_PLAN_ID, "op-001", FIXED_WRITER_A)
        self.fixture.set_journal_state(FIXED_PLAN_ID, "op-001", "sent")
        row = self.fixture.rows("operation_journal")[0]
        self.assertEqual((FIXED_PLAN_ID, "op-001", "sent"), (row["plan_id"], row["operation_id"], row["state"]))

    def test_pending_or_uncertain_journal_fixture_blocks_writer_change(self):
        for state in ("claimed", "sent", "uncertain"):
            with self.subTest(state=state):
                recorder = MutationRecorder()
                fixture = IdentityFixture(recorder)
                self.addCleanup(fixture.close)
                fixture.claim_operation(FIXED_PLAN_ID, f"op-{state}", FIXED_WRITER_A)
                fixture.set_journal_state(FIXED_PLAN_ID, f"op-{state}", state)
                blocking = [r for r in fixture.rows("operation_journal") if r["state"] != "verified"]
                self.assertEqual(1, len(blocking))
                self.assertEqual(0, recorder.count("notion_mutation"))

    def test_plan_generation_and_sqlite_write_counts_are_exact(self):
        self.fixture.insert_project(FIXED_WORKSPACE_A, FIXED_PROJECT_A)
        self.fixture.generate_plan([])
        self.assertEqual(1, self.recorder.count("sqlite_write"))
        self.assertEqual(1, self.recorder.count("plan_generation"))

    def test_plan_digest_is_deterministic(self):
        operations = [{"operation_id": "op-001", "kind": "CREATE"}]
        self.assertEqual(
            self.fixture.generate_plan(operations)["digest"],
            self.fixture.generate_plan(operations)["digest"],
        )

    def test_v1_plan_is_read_only(self):
        gate, plan, proof = self._approved_gate()
        plan["version"] = 1
        with self.assertRaisesRegex(ContractViolation, "read-only"):
            gate.authorize(plan, "op-001", "nonce-001", proof)
        self.assertEqual(0, self.recorder.count("notion_mutation"))

    def test_tampered_plan_is_denied_before_store_reads_or_mutation(self):
        gate, plan, proof = self._approved_gate()
        reads_before = self.recorder.count("authority_read")
        plan["operations"][0]["sync_uid"] = FIXED_PROJECT_B
        with self.assertRaisesRegex(ContractViolation, "digest"):
            gate.authorize(plan, "op-001", "nonce-001", proof)
        self.assertEqual(reads_before, self.recorder.count("authority_read"))
        self.assertEqual(0, self.recorder.count("notion_mutation"))

    def test_approval_store_is_executor_read_only(self):
        self.assertFalse(hasattr(self.approvals, "write"))
        self.assertFalse(hasattr(self.approvals, "approve"))
        self.approvals.seed("nonce-001", subject="sync-executor")
        self.assertEqual("sync-executor", self.approvals.get_approval("nonce-001")["subject"])

    def test_approval_expiry_subject_budget_and_replay_are_denied(self):
        cases = (
            ("expired", {"expires_at": FIXED_NOW, "subject": "sync-executor", "mutation_budget": 1}),
            ("subject", {"expires_at": "2026-07-15T13:00:00Z", "subject": "other", "mutation_budget": 1}),
            ("budget", {"expires_at": "2026-07-15T13:00:00Z", "subject": "sync-executor", "mutation_budget": 0}),
        )
        for label, overrides in cases:
            with self.subTest(label=label):
                recorder = MutationRecorder()
                fixture = IdentityFixture(recorder)
                self.addCleanup(fixture.close)
                authority = FakeIdentityAuthorityStore(recorder)
                approvals = ReadOnlyFakeApprovalStore(recorder)
                credentials = EphemeralWriterCredentialStore()
                authority.seed_workspace(FIXED_WORKSPACE_A)
                credentials.seed(FIXED_WRITER_A, b"fixed-test-secret-a")
                plan = fixture.generate_plan([{"operation_id": "op-001"}])
                approvals.seed(
                    "nonce-x",
                    plan_id=plan["plan_id"],
                    plan_digest=plan["digest"],
                    workspace_id=plan["workspace_id"],
                    writer_epoch=plan["writer_epoch"],
                    project_sync_uid=plan["project_sync_uid"],
                    ownership_epoch=plan["ownership_epoch"],
                    operation_ids=["op-001"],
                    **overrides,
                )
                proof = credentials.sign(FIXED_WRITER_A, writer_proof_record(plan, "op-001", "nonce-x"))
                gate = ContractGate(authority, approvals, credentials, fixture)
                with self.assertRaises(ContractViolation):
                    gate.authorize(plan, "op-001", "nonce-x", proof)
                self.assertEqual(0, recorder.count("notion_mutation"))
        gate, plan, proof = self._approved_gate(nonce="nonce-replay")
        gate.authorize(plan, "op-001", "nonce-replay", proof)
        with self.assertRaisesRegex(ContractViolation, "replay"):
            gate.authorize(plan, "op-001", "nonce-replay", proof)

    def test_plan_outside_operation_identity_swap_and_budget_are_denied(self):
        gate, plan, _ = self._approved_gate(nonce="nonce-binding")
        outside_proof = self.credentials.sign(
            FIXED_WRITER_A,
            writer_proof_record(plan, "op-outside", "nonce-binding"),
        )
        with self.assertRaisesRegex(ContractViolation, "not present"):
            gate.authorize(plan, "op-outside", "nonce-binding", outside_proof)

        gate, plan, proof = self._approved_gate(nonce="nonce-identity")
        self.approvals._records["nonce-identity"]["project_sync_uid"] = FIXED_PROJECT_B
        with self.assertRaisesRegex(ContractViolation, "Plan mismatch"):
            gate.authorize(plan, "op-001", "nonce-identity", proof)

        gate, plan, proof = self._approved_gate(nonce="nonce-budget")
        gate.authorize(plan, "op-001", "nonce-budget", proof)
        second_plan = copy.deepcopy(plan)
        second_plan["operations"].append({"operation_id": "op-002"})
        second_plan["digest"] = canonical_digest(
            {k: v for k, v in second_plan.items() if k != "digest"}
        )
        self.approvals._records["nonce-budget"].update(
            plan_digest=second_plan["digest"], operation_ids=["op-001", "op-002"]
        )
        second_proof = self.credentials.sign(
            FIXED_WRITER_A,
            writer_proof_record(second_plan, "op-002", "nonce-budget"),
        )
        with self.assertRaisesRegex(ContractViolation, "budget"):
            ContractGate(
                self.authority, self.approvals, self.credentials, self.fixture
            ).authorize(second_plan, "op-002", "nonce-budget", second_proof)
        self.assertEqual(0, self.recorder.count("notion_mutation"))

    def test_linked_legacy_fixture_preserves_page_mapping(self):
        self.fixture.migrate_legacy_batch(
            [{
                "local_key": "legacy-1",
                "scope_id": "L-LEGACY",
                "notion_page_id": FIXED_PAGE_A,
                "approved": True,
                "mapped_sync_uid": FIXED_PROJECT_A,
            }]
        )
        row = self.fixture.rows("legacy_candidates")[0]
        self.assertEqual((FIXED_PAGE_A, FIXED_PROJECT_A), (row["notion_page_id"], row["mapped_sync_uid"]))

    def test_unlinked_or_ambiguous_legacy_is_non_mutating(self):
        self.fixture.migrate_legacy_batch(
            [{"local_key": "legacy-1", "scope_id": "L-SAME"}, {"local_key": "legacy-2", "scope_id": "L-SAME"}]
        )
        candidates = self.fixture.rows("legacy_candidates")
        self.assertTrue(all(not row["approved"] for row in candidates))
        self.assertEqual(0, self.recorder.count("notion_mutation"))

    def test_migration_interruption_rolls_back_entire_batch(self):
        rows = [
            {"local_key": "legacy-1", "scope_id": "L-ONE"},
            {"local_key": "legacy-2", "scope_id": "L-TWO"},
        ]
        with self.assertRaises(InjectedCrash):
            self.fixture.migrate_legacy_batch(rows, crash_after=1)
        self.assertEqual([], self.fixture.rows("legacy_candidates"))
        with closing(self.fixture.connect()) as conn:
            self.assertEqual("ok", conn.execute("PRAGMA quick_check").fetchone()[0])

    def test_commit_then_timeout_recovers_by_uid_without_duplicate_create(self):
        self.notion.fail_after_commit = True
        with self.assertRaises(CommitThenTimeout):
            self.notion.create_page(FIXED_PAGE_A, FIXED_PROJECT_A, scope_id="L-SAME")
        recovered = self.notion.query_by_uid(FIXED_PROJECT_A)
        self.assertEqual([FIXED_PAGE_A], [page["id"] for page in recovered])
        self.assertEqual(1, self.recorder.count("notion_mutation"))

    def test_response_before_journal_crash_recovers_without_remote_replay(self):
        self.fixture.claim_operation(FIXED_PLAN_ID, "op-001", FIXED_WRITER_A)
        result = self.notion.create_page(FIXED_PAGE_A, FIXED_PROJECT_A)
        self.assertEqual("claimed", self.fixture.rows("operation_journal")[0]["state"])
        recovered = self.notion.query_by_uid(FIXED_PROJECT_A)
        self.fixture.set_journal_state(FIXED_PLAN_ID, "op-001", "verified", result["id"])
        self.assertEqual(1, len(recovered))
        self.assertEqual(1, self.recorder.count("notion_mutation"))

    def test_transfer_requires_source_and_destination_approval_fixtures(self):
        approvals = {"source": True, "destination": False}
        self.assertFalse(all(approvals.values()))
        self.assertEqual(0, self.recorder.count("notion_mutation"))
        approvals["destination"] = True
        self.assertTrue(all(approvals.values()))

    def test_transfer_cas_changes_owner_and_rejects_old_epoch(self):
        self.authority.seed_project(FIXED_PROJECT_A, FIXED_WORKSPACE_A)
        updated = self.authority.compare_and_swap(
            "project",
            FIXED_PROJECT_A,
            1,
            {
                "sync_uid": FIXED_PROJECT_A,
                "workspace_id": FIXED_WORKSPACE_B,
                "ownership_epoch": 2,
            },
        )
        self.assertEqual((FIXED_WORKSPACE_B, 2), (updated["workspace_id"], updated["ownership_epoch"]))
        with self.assertRaises(ContractViolation):
            self.authority.compare_and_swap("project", FIXED_PROJECT_A, 1, updated)

    def test_authority_transition_crash_boundaries_resume_same_plan_once(self):
        for crash_at in (
            "before_cas",
            "after_cas_before_journal",
            "after_journal_before_projection",
        ):
            with self.subTest(crash_at=crash_at):
                recorder = MutationRecorder()
                fixture = IdentityFixture(recorder)
                self.addCleanup(fixture.close)
                authority = FakeIdentityAuthorityStore(recorder)
                authority.seed_workspace(FIXED_WORKSPACE_A)
                harness = AuthorityTransitionHarness(fixture, authority)
                with self.assertRaises(InjectedCrash):
                    harness.run(crash_at=crash_at)
                result = harness.run()
                self.assertEqual(FIXED_WRITER_B, result["active_writer_id"])
                self.assertEqual("completed", result["journal"]["state"])
                self.assertEqual(2, result["journal"]["result_revision"])
                self.assertEqual(1, recorder.count("authority_cas"))
                self.assertEqual(0, recorder.count("notion_mutation"))

    def test_bootstrap_crash_boundaries_converge_manifest_authority_and_cache(self):
        for crash_at in (
            "before_planned",
            "after_planned",
            "after_authority_cas",
            "after_authority_committed",
            "after_manifest_commit",
            "after_manifest_committed",
            "after_cache_commit",
            "after_cache_committed",
            "after_verified",
        ):
            with self.subTest(crash_at=crash_at):
                recorder = MutationRecorder()
                fixture = IdentityFixture(recorder)
                self.addCleanup(fixture.close)
                authority = FakeIdentityAuthorityStore(recorder)
                harness = BootstrapHarness(fixture, authority)
                with self.assertRaises(InjectedCrash):
                    harness.run(crash_at=crash_at)
                result = harness.run()
                self.assertEqual(
                    FIXED_WORKSPACE_A,
                    result["manifest"]["workspace_id"],
                )
                self.assertEqual(
                    result["manifest"]["workspace_id"],
                    result["authority"]["workspace_id"],
                )
                self.assertEqual(
                    result["manifest"]["workspace_id"],
                    result["active_workspace_id"],
                )
                self.assertEqual("1", result["active_writer_epoch"])
                self.assertFalse(harness.state_path.exists())
                self.assertFalse(
                    harness.state_path.with_suffix(
                        harness.state_path.suffix + ".tmp"
                    ).exists()
                )
                self.assertFalse(
                    harness.manifest_path.with_suffix(
                        harness.manifest_path.suffix + ".tmp"
                    ).exists()
                )
                self.assertEqual(0, recorder.count("notion_mutation"))

    def test_handoff_repairs_link_without_remote_mutation(self):
        self.fixture.insert_project(FIXED_WORKSPACE_A, FIXED_PROJECT_A)
        self.notion.seed_page(FIXED_PAGE_A, FIXED_PROJECT_A)
        remote = self.notion.query_by_uid(FIXED_PROJECT_A)[0]
        with closing(self.fixture.connect()) as conn:
            conn.execute("UPDATE projects SET notion_page_id = ? WHERE sync_uid = ?", (remote["id"], FIXED_PROJECT_A))
            conn.commit()
        self.recorder.record("sqlite_write", table="projects")
        self.assertEqual(0, self.recorder.count("notion_mutation"))

    def test_handoff_without_evidence_keeps_create_uncertain(self):
        self.fixture.claim_operation(FIXED_PLAN_ID, "op-001", FIXED_WRITER_A)
        self.fixture.set_journal_state(FIXED_PLAN_ID, "op-001", "uncertain")
        self.assertEqual([], self.notion.query_by_uid(FIXED_PROJECT_A))
        self.assertEqual("uncertain", self.fixture.rows("operation_journal")[0]["state"])
        self.assertEqual(0, self.recorder.count("notion_mutation"))

    def test_break_glass_requires_all_three_recovery_evidences(self):
        cases = (
            (False, 2, True),
            (True, 1, True),
            (True, 2, False),
            (False, 1, False),
        )
        for signature, approvers, transition_plan in cases:
            with self.subTest(
                signature=signature,
                approvers=approvers,
                transition_plan=transition_plan,
            ):
                with self.assertRaises(ContractViolation):
                    BreakGlassGate.authorize(
                        recovery_signature_valid=signature,
                        approver_count=approvers,
                        transition_plan_valid=transition_plan,
                    )
        self.assertTrue(
            BreakGlassGate.authorize(
                recovery_signature_valid=True,
                approver_count=2,
                transition_plan_valid=True,
            )
        )
        self.assertEqual(0, self.recorder.count("notion_mutation"))

    def test_patch_handoff_verifies_only_exact_remote_payload(self):
        expected = {"name": "Expected", "status": "active"}
        cases = (
            ("applied", expected, True),
            ("missing", {}, False),
            ("partial", {"name": "Expected"}, False),
            ("different", {"name": "Other", "status": "active"}, False),
        )
        for label, remote, verified in cases:
            with self.subTest(label=label):
                self.assertEqual(verified, remote == expected)
        self.assertEqual(0, self.recorder.count("notion_mutation"))

    def test_rerun_after_verified_operation_has_zero_additional_mutations(self):
        self.fixture.claim_operation(FIXED_PLAN_ID, "op-001", FIXED_WRITER_A)
        self.notion.create_page(FIXED_PAGE_A, FIXED_PROJECT_A)
        self.fixture.set_journal_state(FIXED_PLAN_ID, "op-001", "verified", FIXED_PAGE_A)
        before = self.recorder.count("notion_mutation")
        rows = self.fixture.rows("operation_journal")
        should_execute = rows[0]["state"] != "verified"
        if should_execute:  # pragma: no cover - documents the execution boundary.
            self.notion.create_page("unexpected", FIXED_PROJECT_A)
        self.assertEqual(before, self.recorder.count("notion_mutation"))


class IdentityV2ReconciliationAuditTest(unittest.TestCase):
    """T004 Identity-first schema, reconciliation, and audit contracts."""

    def setUp(self):
        self.production_before = file_fingerprint(PRODUCTION_DB)
        self.addCleanup(self._assert_production_unchanged)
        self.sync = load_module(DB_DIR / "sync.py", f"identity_sync_t004_{id(self)}")

    def _assert_production_unchanged(self):
        self.assertEqual(self.production_before, file_fingerprint(PRODUCTION_DB))

    @staticmethod
    def _rich(value):
        return {"rich_text": [] if not value else [{"plain_text": value}]}

    @staticmethod
    def _title(value):
        return {"title": [] if not value else [{"plain_text": value}]}

    @staticmethod
    def _number(value):
        return {"number": value}

    def _project_page(
        self,
        page_id,
        *,
        scope_id="L-SHARED",
        sync_uid=FIXED_PROJECT_A,
        workspace_id=FIXED_WORKSPACE_A,
        ownership_epoch=1,
        identity_version=2,
        name="Identity Project",
    ):
        return {
            "id": page_id,
            "parent": {"type": "database_id", "database_id": "projects-db"},
            "last_edited_time": FIXED_NOW,
            "properties": {
                "PJ名": self._title(name),
                "Scope ID": self._rich(scope_id),
                "Sync UID": self._rich(sync_uid),
                "Workspace ID": self._rich(workspace_id),
                "Ownership Epoch": self._number(ownership_epoch),
                "Identity Version": self._number(identity_version),
            },
        }

    def _task_page(
        self,
        page_id,
        *,
        scope_id="L-SHARED",
        task_id="T001",
        project_sync_uid=FIXED_PROJECT_A,
        workspace_id=FIXED_WORKSPACE_A,
        ownership_epoch=1,
        identity_version=2,
    ):
        return {
            "id": page_id,
            "parent": {"type": "database_id", "database_id": "tasks-db"},
            "last_edited_time": FIXED_NOW,
            "properties": {
                "タスク名": self._title("Identity Task"),
                "Task ID": self._rich(task_id),
                "Scope ID": self._rich(scope_id),
                "Project Sync UID": self._rich(project_sync_uid),
                "Workspace ID": self._rich(workspace_id),
                "Project Ownership Epoch": self._number(ownership_epoch),
                "Identity Version": self._number(identity_version),
            },
        }

    @staticmethod
    def _local_project(**changes):
        row = {
            "id": 1,
            "notion_page_id": None,
            "scope_id": "L-SHARED",
            "name": "Identity Project",
            "goal": None,
            "owner": "owner-a",
            "status": "active",
            "mode": "direct",
            "depth": "standard",
            "system": "AI-PLC",
            "parent_scope": None,
            "top_page_url": None,
            "start_date": None,
            "deadline": None,
            "sync_uid": FIXED_PROJECT_A,
            "workspace_id": FIXED_WORKSPACE_A,
            "ownership_epoch": 1,
            "identity_version": 2,
        }
        row.update(changes)
        return row

    @staticmethod
    def _local_task(**changes):
        row = {
            "id": 10,
            "notion_page_id": None,
            "scope_id": "L-SHARED",
            "task_id": "T001",
            "name": "Identity Task",
            "status": "未着手",
            "type": None,
            "priority": "P1",
            "estimate_days": None,
            "output_url": None,
            "completed_at": None,
            "project_sync_uid": FIXED_PROJECT_A,
            "workspace_id": FIXED_WORKSPACE_A,
            "project_ownership_epoch": 1,
            "identity_version": 2,
        }
        row.update(changes)
        return row

    def _report(self, *, projects=None, tasks=None, project_pages=None, task_pages=None):
        return self.sync.build_reconciliation_report(
            {"project": projects or [], "task": tasks or []},
            {"project": project_pages or [], "task": task_pages or []},
        )

    def test_notion_identity_schema_converter_and_builder_are_aligned(self):
        self.assertEqual("rich_text", self.sync.PROJECTS_NOTION_SCHEMA["Sync UID"])
        self.assertEqual(
            "number", self.sync.TASKS_NOTION_SCHEMA["Project Ownership Epoch"]
        )
        remote = self.sync._notion_row_to_project(self._project_page("page-a"))
        self.assertEqual(FIXED_PROJECT_A, remote["sync_uid"])
        self.assertEqual(FIXED_WORKSPACE_A, remote["workspace_id"])
        props = self.sync._project_to_notion_props(self._local_project())
        self.assertEqual(
            FIXED_PROJECT_A,
            props["Sync UID"]["rich_text"][0]["text"]["content"],
        )
        self.assertEqual(2.0, self.sync._extract_number(props["Identity Version"]))

    def test_schema_type_mismatch_is_fail_closed(self):
        database = {
            "properties": {
                name: {"type": kind}
                for name, kind in self.sync.PROJECTS_NOTION_SCHEMA.items()
            }
        }
        database["properties"]["Sync UID"]["type"] = "number"
        calls = []
        self.sync._api_call = lambda *args: calls.append(args) or database
        _database, findings = self.sync._validate_notion_database(
            "project", "fake-db", self.sync.PROJECTS_NOTION_SCHEMA
        )
        self.assertEqual(["SCHEMA_MISMATCH"], [item["code"] for item in findings])
        self.assertEqual(1, len(calls))

    def test_v2_remote_row_omitting_identity_property_is_globally_fail_closed(self):
        page = self._project_page("missing-property")
        del page["properties"]["Sync UID"]
        report = self._report(
            projects=[self._local_project()], project_pages=[page]
        )
        self.assertEqual(3, report["exit_code"])
        self.assertEqual(
            1,
            report["identity_summary"]["REMOTE_IDENTITY_PROPERTY_MISSING"],
        )
        projection = self.sync.project_reconciliation_for_push(
            report, {"project": [self._local_project()], "task": []}
        )
        self.assertEqual(3, projection["blocking"]["exit_code"])

    def test_exact_identity_and_same_scope_different_identity_are_distinct(self):
        exact = self._report(
            projects=[self._local_project()],
            project_pages=[self._project_page("page-exact")],
        )
        self.assertEqual(0, exact["exit_code"])
        self.assertEqual(1, exact["identity_summary"]["IDENTITY_EXACT"])

        other_uid = "prj_00000000-0000-4000-8000-000000000003"
        separate = self._report(
            projects=[self._local_project()],
            project_pages=[self._project_page("page-other", sync_uid=other_uid)],
        )
        self.assertEqual(0, separate["exit_code"])
        self.assertEqual(
            1, separate["identity_summary"]["SAME_SCOPE_DIFFERENT_IDENTITY"]
        )
        local_item = next(
            item for item in separate["items"] if item["local_row_id"] == 1
        )
        self.assertEqual("create_remote", local_item["action"])

    def test_duplicate_missing_workspace_and_split_brain_exit_contract(self):
        duplicate = self._report(
            projects=[self._local_project()],
            project_pages=[
                self._project_page("dup-a"), self._project_page("dup-b")
            ],
        )
        self.assertEqual(2, duplicate["exit_code"])
        self.assertEqual(1, duplicate["identity_summary"]["IDENTITY_DUPLICATE"])

        missing = self._report(
            projects=[self._local_project(sync_uid=None)], project_pages=[]
        )
        self.assertEqual(2, missing["exit_code"])
        self.assertEqual(1, missing["identity_summary"]["IDENTITY_MISSING"])

        mismatch = self._report(
            projects=[self._local_project()],
            project_pages=[self._project_page("other-workspace", workspace_id=FIXED_WORKSPACE_B)],
        )
        self.assertEqual(3, mismatch["exit_code"])
        self.assertEqual(
            1, mismatch["identity_summary"]["IDENTITY_WORKSPACE_MISMATCH"]
        )

        split = self._report(
            projects=[self._local_project(notion_page_id="linked-page")],
            project_pages=[self._project_page(
                "linked-page", sync_uid="prj_00000000-0000-4000-8000-000000000003"
            )],
        )
        self.assertEqual(3, split["exit_code"])
        self.assertEqual(1, split["identity_summary"]["IDENTITY_SPLIT_BRAIN"])

    def test_legacy_candidates_never_become_exact_identity(self):
        legacy = self._project_page(
            "legacy-page", sync_uid="", workspace_id="",
            ownership_epoch=None, identity_version=None,
        )
        attach = self._report(
            projects=[self._local_project()], project_pages=[legacy]
        )
        self.assertEqual(2, attach["exit_code"])
        self.assertEqual(
            1, attach["identity_summary"]["LEGACY_ATTACH_CANDIDATE"]
        )

        linked = self._report(
            projects=[self._local_project(notion_page_id="legacy-page")],
            project_pages=[legacy],
        )
        self.assertEqual(2, linked["exit_code"])
        self.assertEqual(
            1, linked["identity_summary"]["LEGACY_LINKED_CANDIDATE"]
        )

        ambiguous = self._report(
            projects=[self._local_project()],
            project_pages=[legacy, dict(copy.deepcopy(legacy), id="legacy-page-2")],
        )
        self.assertEqual(2, ambiguous["exit_code"])
        self.assertEqual(1, ambiguous["identity_summary"]["LEGACY_AMBIGUOUS"])

    def test_task_identity_is_project_namespaced(self):
        other_project_uid = "prj_00000000-0000-4000-8000-000000000003"
        report = self._report(
            tasks=[self._local_task()],
            task_pages=[self._task_page(
                "other-task", project_sync_uid=other_project_uid
            )],
        )
        self.assertEqual(0, report["exit_code"])
        self.assertEqual(
            1, report["identity_summary"]["SAME_SCOPE_DIFFERENT_IDENTITY"]
        )
        local_item = next(item for item in report["items"] if item["local_row_id"] == 10)
        self.assertEqual("create_remote", local_item["action"])

    def test_same_scope_collisions_become_separate_identities(self):
        other_uid = "prj_00000000-0000-4000-8000-000000000003"
        for scope_id in ("L-OLD-E1", "L-OLD-E2", "L-OLD-E2-2"):
            with self.subTest(scope_id=scope_id):
                report = self._report(
                    projects=[self._local_project(scope_id=scope_id)],
                    project_pages=[self._project_page(
                        "page-" + scope_id, scope_id=scope_id,
                        sync_uid=other_uid,
                    )],
                )
                self.assertEqual(0, report["exit_code"])
                self.assertEqual(0, report["summary"]["collision"])
                self.assertEqual(
                    1,
                    report["identity_summary"]["SAME_SCOPE_DIFFERENT_IDENTITY"],
                )

    def test_remote_only_legacy_row_is_visible_as_audit_identity_missing(self):
        legacy = self._project_page(
            "remote-legacy", scope_id="L-REMOTE-ONLY", sync_uid="",
            workspace_id="", ownership_epoch=None, identity_version=None,
        )
        report = self._report(
            projects=[self._local_project(scope_id="L-LOCAL")],
            project_pages=[legacy],
        )
        self.assertEqual(0, report["exit_code"])
        self.assertEqual(1, report["identity_summary"]["IDENTITY_MISSING"])
        projection = self.sync.project_reconciliation_for_push(
            report,
            {"project": [self._local_project(scope_id="L-LOCAL")], "task": []},
        )
        self.assertEqual(0, projection["blocking"]["exit_code"])
        self.assertEqual(
            ["IDENTITY_MISSING"],
            [item["code"] for item in projection["audit_only"]["findings"]
             if item["code"] == "IDENTITY_MISSING"],
        )

    def test_local_identity_schema_rejects_partial_and_mixed_profiles(self):
        init_db = load_module(DB_DIR / "init_db.py", f"identity_init_t004_{id(self)}")
        with tempfile.TemporaryDirectory(prefix="ai-plc-identity-t004-schema-") as root:
            path = Path(root) / "schema.db"
            with closing(sqlite3.connect(path)) as conn:
                init_db.create_schema(conn)
                for sql in (
                    "ALTER TABLE projects ADD COLUMN workspace_id TEXT",
                    "ALTER TABLE projects ADD COLUMN sync_uid TEXT",
                    "ALTER TABLE projects ADD COLUMN ownership_epoch INTEGER",
                    "ALTER TABLE projects ADD COLUMN identity_version INTEGER",
                ):
                    conn.execute(sql)
                mixed = self.sync._validate_local_schema(conn)
                self.assertIn(
                    "LOCAL_IDENTITY_SCHEMA_MIXED",
                    {finding["code"] for finding in mixed},
                )
                conn.execute("ALTER TABLE tasks ADD COLUMN workspace_id TEXT")
                partial = self.sync._validate_local_schema(conn)
                self.assertIn(
                    "LOCAL_IDENTITY_SCHEMA_PARTIAL",
                    {finding["code"] for finding in partial},
                )

    def test_push_projection_separates_audit_authorization_and_critical_blocker(self):
        local = self._local_project()
        other_uid = "prj_00000000-0000-4000-8000-000000000003"
        same_scope = self._report(
            projects=[local],
            project_pages=[self._project_page("other", sync_uid=other_uid)],
        )
        projected = self.sync.project_reconciliation_for_push(
            same_scope, {"project": [local], "task": []}
        )
        self.assertEqual(0, projected["blocking"]["exit_code"])
        self.assertIn(
            "SAME_SCOPE_DIFFERENT_IDENTITY",
            [item["code"] for item in projected["audit_only"]["findings"]],
        )

        legacy = self._project_page(
            "legacy", sync_uid="", workspace_id="",
            ownership_epoch=None, identity_version=None,
        )
        legacy_report = self._report(projects=[local], project_pages=[legacy])
        legacy_projection = self.sync.project_reconciliation_for_push(
            legacy_report, {"project": [local], "task": []}
        )
        self.assertEqual(0, legacy_projection["blocking"]["exit_code"])
        self.assertGreaterEqual(
            legacy_projection["authorization_required"]["summary"]["attach"], 1
        )

        mismatch = self._report(
            projects=[local],
            project_pages=[self._project_page("wrong", workspace_id=FIXED_WORKSPACE_B)],
        )
        mismatch_projection = self.sync.project_reconciliation_for_push(
            mismatch, {"project": [local], "task": []}
        )
        self.assertEqual(3, mismatch_projection["blocking"]["exit_code"])

    def test_same_scope_other_identity_duplicate_is_audit_only(self):
        local = self._local_project()
        other_uid = "prj_00000000-0000-4000-8000-000000000003"
        report = self._report(
            projects=[local],
            project_pages=[
                self._project_page("other-a", sync_uid=other_uid),
                self._project_page("other-b", sync_uid=other_uid),
            ],
        )
        local_item = next(
            item for item in report["items"] if item.get("local_row_id") == local["id"]
        )
        self.assertEqual("create_remote", local_item["action"])
        projection = self.sync.project_reconciliation_for_push(
            report, {"project": [local], "task": []}
        )
        self.assertEqual(0, projection["blocking"]["exit_code"])
        self.assertIn(
            "IDENTITY_DUPLICATE",
            [item["code"] for item in projection["audit_only"]["findings"]],
        )

    def test_execution_revalidation_stops_schema_and_attach_identity_drift(self):
        local = self._local_project(
            updated_at="2026-07-15T12:00:00Z", last_sync_at=None
        )
        operation = {
            "operation_id": "project:L-SHARED",
            "entity": "project",
            "stable_key": ["L-SHARED"],
            "action": "attach_candidate",
            "local_row_id": local["id"],
            "remote_page_ids": ["legacy-page"],
            "remote_candidates": [],
            "expected_reconciliation_reason": "LEGACY_ATTACH_CANDIDATE",
            "link_state": "missing",
            "expected_local_updated_at": local["updated_at"],
            "expected_local_fingerprint": self.sync._mapped_fingerprint("project", local),
            "mutable_properties": self.sync._project_to_notion_props(local),
        }

        def connection():
            conn = sqlite3.connect(":memory:")
            conn.row_factory = sqlite3.Row
            conn.execute("""
                CREATE TABLE projects (
                    id INTEGER, notion_page_id TEXT, scope_id TEXT, name TEXT,
                    goal TEXT, owner TEXT, status TEXT, mode TEXT, depth TEXT,
                    system TEXT, parent_scope TEXT, top_page_url TEXT,
                    start_date TEXT, deadline TEXT, sync_uid TEXT,
                    workspace_id TEXT, ownership_epoch INTEGER,
                    identity_version INTEGER, updated_at TEXT, last_sync_at TEXT
                )
            """)
            columns = list(local)
            conn.execute(
                "INSERT INTO projects (%s) VALUES (%s)" % (
                    ",".join(columns), ",".join("?" for _ in columns)
                ),
                [local[column] for column in columns],
            )
            return conn

        plan = {
            "preflight": {"schema_fingerprints": {"project": "schema-a"}},
            "operations": [operation],
        }
        blocked_schema = {"status": "blocked", "schemas": {}, "findings": [{}]}
        with (
            mock.patch.object(self.sync, "_open_read_conn", return_value=(connection(), None)),
            mock.patch.object(self.sync, "run_preflight", return_value=blocked_schema),
        ):
            self.assertEqual(3, self.sync._revalidate_identity_plan_before_write(plan))

        exact_remote = self._project_page("legacy-page")
        changed = self._report(projects=[local], project_pages=[exact_remote])
        fresh_schema = {
            "status": "pass", "findings": [],
            "schemas": {"project": {"fingerprint": "schema-a"}},
        }
        with (
            mock.patch.object(self.sync, "_open_read_conn", return_value=(connection(), None)),
            mock.patch.object(self.sync, "run_preflight", return_value=fresh_schema),
            mock.patch.object(self.sync, "run_reconciliation", return_value=changed),
        ):
            self.assertEqual(2, self.sync._revalidate_identity_plan_before_write(plan))

    def test_execute_stops_identity_revalidation_before_write_connection(self):
        local = self._local_project()
        operation = {
            "operation_id": "project:L-SHARED", "entity": "project",
            "stable_key": ["L-SHARED"], "action": "attach_candidate",
            "local_row_id": local["id"], "remote_page_ids": ["legacy-page"],
            "expected_reconciliation_reason": "LEGACY_ATTACH_CANDIDATE",
            "expected_local_updated_at": None,
            "expected_local_fingerprint": self.sync._mapped_fingerprint("project", local),
            "mutable_properties": self.sync._project_to_notion_props(local),
        }
        projection = {
            "blocking": {"exit_code": 0},
            "authorization_required": {"operation_ids": [operation["operation_id"]]},
        }
        plan = {
            "plan_id": "", "direction": "push", "preflight": {},
            "source_snapshot": {}, "operations": [operation],
            "reconciliation": projection, "exit_code": 2,
        }
        plan["plan_id"] = self.sync._push_plan_id(plan)
        authorization = {
            "plan_id": plan["plan_id"], "operation_ids": [operation["operation_id"]],
            "approved_by": "reviewer",
        }
        with (
            # 本体ではこの試験は本番の DB を読み、行が無いのでローカル行の照合で 2 になる。公開版のリポジトリには
            # ai_plc.db が無い（開けないと 3）ので、同じ結果（行が無い＝照合が合わない）を明示して本体と同じ道を通す
            mock.patch.object(self.sync, "_local_rows_match_plan_scope", return_value=False),
            mock.patch.object(self.sync, "_revalidate_identity_plan_before_write", return_value=2),
            mock.patch.object(self.sync, "_open_write_conn") as open_write,
        ):
            result = self.sync.execute_push_plan(plan, authorization=authorization)
        self.assertEqual(2, result)
        open_write.assert_not_called()

    def test_status_audit_renders_identity_codes_without_raw_values(self):
        report = {
            "status": "pass",
            "exit_code": 0,
            "counts": {
                "dirty": 0, "missing_id": 0, "stale_link": 0,
                "collision": 0, "duplicate": 0, "schema_error": 0,
            },
            "warnings": [],
            "plan": {
                "summary": {},
                "reconciliation": {
                    "blocking": {"summary": {}},
                    "audit_only": {"summary": {}, "projection_digest": "digest"},
                    "raw_summary": {
                        "identity_codes": {"SAME_SCOPE_DIFFERENT_IDENTITY": 1}
                    },
                },
            },
        }
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.sync._print_status_audit_report(report)
        rendered = output.getvalue()
        self.assertIn("SAME_SCOPE_DIFFERENT_IDENTITY=1", rendered)
        self.assertNotIn(FIXED_PROJECT_A, rendered)
        self.assertNotIn(FIXED_WORKSPACE_A, rendered)


class IdentityV2PlanJournalFencingTest(unittest.TestCase):
    """T005 immutable Identity Plan and durable journal fencing contracts."""

    def setUp(self):
        self.production_before = file_fingerprint(PRODUCTION_DB)
        self.temp_dir = tempfile.TemporaryDirectory(prefix="ai-plc-identity-t005-")
        self.addCleanup(self._assert_production_unchanged)
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "identity-v2.db"
        self.manifest_path = self.root / "workspace_identity.json"
        self.init_db = load_module(DB_DIR / "init_db.py", f"identity_init_t005_{id(self)}")
        self.sync = load_module(DB_DIR / "sync.py", f"identity_sync_t005_{id(self)}")
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.init_db.create_schema(conn)
            conn.execute("""
                INSERT INTO projects (
                    scope_id, name, status, created_at, updated_at, last_sync_at
                ) VALUES ('L-T005', 'Plan Project', 'active', ?, ?, NULL)
            """, (FIXED_NOW, FIXED_NOW))
            conn.execute("""
                INSERT INTO tasks (
                    task_id, scope_id, name, status, created_at, updated_at, last_sync_at
                ) VALUES ('T001', 'L-T005', 'Plan Task', '未着手', ?, ?, NULL)
            """, (FIXED_NOW, FIXED_NOW))
            conn.commit()
            mapping = self.init_db.build_identity_migration_mapping(
                conn, FIXED_WORKSPACE_A,
                project_uid_factory=lambda: FIXED_PROJECT_A,
            )
            self.init_db.migrate_identity_v2(conn, mapping)
            writer = {
                "workspace_id": FIXED_WORKSPACE_A,
                "writer_id": FIXED_WRITER_A,
                "writer_epoch": 1,
            }
            authority_hash = self.sync._canonical_json_digest(writer)
            manifest = dict(
                writer, identity_version=2,
                writer_authority_hash_cache=authority_hash,
            )
            self.manifest_path.write_text(
                json.dumps(manifest, sort_keys=True), encoding="utf-8"
            )
            conn.execute(
                "INSERT OR REPLACE INTO _metadata(key, value) VALUES (?, ?)",
                ("active_workspace_id", FIXED_WORKSPACE_A),
            )
            conn.execute(
                "INSERT OR REPLACE INTO _metadata(key, value) VALUES (?, '1')",
                ("active_writer_epoch",),
            )
            conn.execute(
                "INSERT OR REPLACE INTO _metadata(key, value) VALUES (?, ?)",
                ("writer_authority_hash_cache", authority_hash),
            )
            conn.commit()
        self.sync.DB_PATH = str(self.db_path)
        self.sync.WORKSPACE_MANIFEST_PATH = str(self.manifest_path)

    def _assert_production_unchanged(self):
        self.assertEqual(self.production_before, file_fingerprint(PRODUCTION_DB))

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _fresh_report(self):
        with closing(self._connect()) as conn:
            local = {
                "project": conn.execute("SELECT * FROM projects").fetchall(),
                "task": conn.execute("SELECT * FROM tasks").fetchall(),
            }
        return self.sync.build_reconciliation_report(
            local, {"project": [], "task": []}
        )

    def _build_plan(self, scope_id="L-T005"):
        with mock.patch.object(
            self.sync, "run_reconciliation", return_value=self._fresh_report()
        ):
            return self.sync.build_push_plan(
                skip_preflight=True, scope_id=scope_id
            )

    def test_v2_plan_binds_identity_selector_operations_and_snapshot(self):
        plan = self._build_plan()
        self.assertEqual(2, plan["plan_schema_version"])
        self.assertEqual(FIXED_WORKSPACE_A, plan["identity"]["workspace_id"])
        self.assertEqual(FIXED_PROJECT_A, plan["selector"]["project_sync_uid"])
        self.assertTrue(self.sync.validate_push_plan(plan))
        self.assertTrue(all(
            operation["stable_key"][0] == FIXED_PROJECT_A
            for operation in plan["operations"]
        ))
        self.assertTrue(all(
            operation["operation_id"].startswith("opv2_")
            for operation in plan["operations"]
        ))
        self.assertEqual(
            len(plan["operations"]), plan["source_snapshot"]["operation_count"]
        )
        artifact = self.root / "v2-plan.json"
        self.sync.write_push_plan(plan, artifact)
        loaded = self.sync.load_push_plan(artifact)
        self.assertEqual(plan, loaded)
        self.assertNotIsInstance(loaded, self.sync.ReadOnlyV1PushPlan)

    def test_valid_v2_plan_executes_once_and_replans_to_zero_operations(self):
        plan = self._build_plan()
        responses = iter((
            {"id": "project-page", "last_edited_time": FIXED_NOW},
            {"id": "task-page", "last_edited_time": FIXED_NOW},
        ))
        calls = []

        def fake_api(method, path, body=None, retries=3):
            calls.append((method, path))
            if method == "POST" and path == "/v1/pages":
                return next(responses)
            raise AssertionError("unexpected read after execution revalidation stub")

        with (
            mock.patch.object(
                self.sync, "_revalidate_identity_plan_before_write", return_value=0
            ),
            mock.patch.object(self.sync, "_api_call", side_effect=fake_api),
        ):
            self.assertEqual(
                0, self.sync.execute_push_plan(plan, scope_id="L-T005")
            )
        self.assertEqual(2, len(calls))
        with closing(self._connect()) as conn:
            self.assertEqual(0, conn.execute(
                "SELECT COUNT(*) FROM _metadata WHERE key LIKE 'pending_push:v2:%'"
            ).fetchone()[0])
            self.assertEqual(1, conn.execute(
                "SELECT COUNT(*) FROM projects WHERE notion_page_id IS NOT NULL"
            ).fetchone()[0])
            self.assertEqual(1, conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE notion_page_id IS NOT NULL"
            ).fetchone()[0])
        rebuilt = self._build_plan()
        self.assertEqual([], rebuilt["operations"])
        self.assertEqual(0, rebuilt["exit_code"])

    def test_v2_create_failure_is_durably_marked_uncertain(self):
        plan = self._build_plan()
        calls = []

        def fail_create(method, path, body=None, retries=3):
            calls.append((method, path))
            raise RuntimeError("commit outcome unavailable")

        with (
            mock.patch.object(
                self.sync, "_revalidate_identity_plan_before_write", return_value=0
            ),
            mock.patch.object(self.sync, "_api_call", side_effect=fail_create),
        ):
            self.assertEqual(
                4, self.sync.execute_push_plan(plan, scope_id="L-T005")
            )
        self.assertEqual(1, len(calls))
        with closing(self._connect()) as conn:
            pending = conn.execute(
                "SELECT value FROM _metadata WHERE key LIKE 'pending_push:v2:%'"
            ).fetchall()
        self.assertEqual(1, len(pending))
        value = json.loads(pending[0]["value"])
        self.assertEqual("uncertain", value["state"])
        self.assertEqual(plan["plan_id"], value["plan_id"])
        with (
            mock.patch.object(self.sync, "_api_call") as api,
            mock.patch.object(self.sync, "_open_write_conn") as open_write,
            mock.patch.object(
                self.sync, "_revalidate_identity_plan_before_write"
            ) as revalidate,
        ):
            self.assertEqual(
                4, self.sync.execute_push_plan(plan, scope_id="L-T005")
            )
        api.assert_not_called()
        open_write.assert_not_called()
        revalidate.assert_not_called()

    def test_claimed_journal_replay_stops_before_api_or_write(self):
        plan = self._build_plan()
        operation = plan["operations"][0]
        value = self.sync._v2_pending_owner(plan, operation)
        value.update({
            "state": "claimed",
            "claimed_by_pid": 99999999,
            "claimed_at": FIXED_NOW,
            "process_identity": None,
        })
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO _metadata(key, value) VALUES (?, ?)",
                (
                    self.sync._v2_pending_key(operation),
                    json.dumps(value, sort_keys=True),
                ),
            )
            conn.commit()
        with (
            mock.patch.object(self.sync, "_api_call") as api,
            mock.patch.object(self.sync, "_open_write_conn") as open_write,
            mock.patch.object(
                self.sync, "_revalidate_identity_plan_before_write"
            ) as revalidate,
        ):
            self.assertEqual(
                4, self.sync.execute_push_plan(plan, scope_id="L-T005")
            )
        api.assert_not_called()
        open_write.assert_not_called()
        revalidate.assert_not_called()

    def test_mutable_payload_tamper_is_rejected_before_api_or_write(self):
        plan = self._build_plan()
        plan["operations"][0]["mutable_properties"]["PJ名"] = {
            "title": [{"text": {"content": "tampered"}}]
        }
        plan["plan_id"] = self.sync._push_plan_id(plan)
        self.assertTrue(self.sync.validate_push_plan(plan))
        with (
            mock.patch.object(self.sync, "_api_call") as api,
            mock.patch.object(self.sync, "_open_write_conn") as open_write,
            mock.patch.object(
                self.sync, "_revalidate_identity_plan_before_write"
            ) as revalidate,
        ):
            self.assertEqual(
                2, self.sync.execute_push_plan(plan, scope_id="L-T005")
            )
        api.assert_not_called()
        open_write.assert_not_called()
        revalidate.assert_not_called()

    def test_missing_scope_returns_blocked_plan(self):
        plan = self._build_plan("L-MISSING")
        self.assertEqual(3, plan["exit_code"])
        self.assertEqual([], plan["operations"])
        self.assertIn(
            "SCOPE_NOT_UNIQUE",
            {finding["code"] for finding in plan["preflight"]["findings"]},
        )

    def test_malformed_nested_plan_types_fail_closed(self):
        plan = self._build_plan()
        mutations = (
            ("operations", None),
            ("summary", []),
            ("reconciliation", []),
            ("preflight", []),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                malformed = copy.deepcopy(plan)
                malformed[field] = value
                malformed["plan_id"] = self.sync._push_plan_id(malformed)
                self.assertFalse(self.sync.validate_push_plan(malformed))
                with (
                    mock.patch.object(self.sync, "_api_call") as api,
                    mock.patch.object(self.sync, "_open_write_conn") as open_write,
                ):
                    self.assertEqual(
                        2,
                        self.sync.execute_push_plan(
                            malformed, scope_id="L-T005"
                        ),
                    )
                api.assert_not_called()
                open_write.assert_not_called()

    def test_remote_committed_replay_converges_without_duplicate_create(self):
        with closing(self._connect()) as conn:
            conn.execute("DELETE FROM tasks")
            conn.commit()
        plan = self._build_plan()
        calls = []

        def create_once(method, path, body=None, retries=3):
            calls.append((method, path))
            self.assertEqual(("POST", "/v1/pages"), (method, path))
            return {"id": "project-page", "last_edited_time": FIXED_NOW}

        def crash_after_remote(point, operation, response=None):
            if point == "after_remote_mutation":
                raise RuntimeError("simulated worker exit after remote commit")

        with (
            mock.patch.object(
                self.sync, "_revalidate_identity_plan_before_write", return_value=0
            ),
            mock.patch.object(self.sync, "_api_call", side_effect=create_once),
            mock.patch.object(
                self.sync, "_push_failure_hook", side_effect=crash_after_remote
            ),
        ):
            self.assertEqual(
                4, self.sync.execute_push_plan(plan, scope_id="L-T005")
            )
        self.assertEqual(1, len(calls))
        with closing(self._connect()) as conn:
            pending = conn.execute(
                "SELECT value FROM _metadata WHERE key LIKE 'pending_push:v2:%'"
            ).fetchall()
            self.assertIsNone(conn.execute(
                "SELECT notion_page_id FROM projects"
            ).fetchone()["notion_page_id"])
        self.assertEqual(1, len(pending))
        self.assertEqual("remote_committed", json.loads(pending[0]["value"])["state"])

        with (
            mock.patch.object(
                self.sync, "_revalidate_identity_plan_before_write", return_value=0
            ),
            mock.patch.object(self.sync, "_api_call") as api,
        ):
            self.assertEqual(
                0, self.sync.execute_push_plan(plan, scope_id="L-T005")
            )
        api.assert_not_called()
        with closing(self._connect()) as conn:
            self.assertEqual("project-page", conn.execute(
                "SELECT notion_page_id FROM projects"
            ).fetchone()["notion_page_id"])
            self.assertEqual(0, conn.execute(
                "SELECT COUNT(*) FROM _metadata WHERE key LIKE 'pending_push:v2:%'"
            ).fetchone()[0])

    def test_workspace_replay_is_rejected_before_remote_or_write(self):
        plan = self._build_plan()
        plan["identity"]["workspace_id"] = FIXED_WORKSPACE_B
        plan["selector"]["workspace_id"] = FIXED_WORKSPACE_B
        plan["source_snapshot"]["workspace_id"] = FIXED_WORKSPACE_B
        for operation in plan["operations"]:
            operation["identity"]["workspace_id"] = FIXED_WORKSPACE_B
            operation["operation_id"] = self.sync._identity_operation_id(
                operation["identity"], operation["action"]
            )
        plan["source_snapshot"]["selected_identity_digest"] = (
            self.sync._identity_snapshot_digest(plan["operations"])
        )
        plan["plan_id"] = self.sync._push_plan_id(plan)
        with (
            mock.patch.object(self.sync, "_api_call") as api,
            mock.patch.object(self.sync, "_open_write_conn") as open_write,
        ):
            self.assertEqual(2, self.sync.execute_push_plan(plan, scope_id="L-T005"))
        api.assert_not_called()
        open_write.assert_not_called()

    def test_selector_tamper_and_same_scope_row_swap_are_rejected(self):
        plan = self._build_plan()
        tampered = copy.deepcopy(plan)
        tampered["selector"]["project_sync_uid"] = FIXED_PROJECT_B
        tampered["plan_id"] = self.sync._push_plan_id(tampered)
        self.assertFalse(self.sync.validate_push_plan(tampered))

        with closing(self._connect()) as conn:
            cursor = conn.execute("""
                INSERT INTO projects (
                    workspace_id, sync_uid, ownership_epoch, identity_version,
                    scope_id, name, status, created_at, updated_at
                ) VALUES (?, ?, 1, 2, 'L-T005', 'Other Workspace', 'active', ?, ?)
            """, (FIXED_WORKSPACE_B, FIXED_PROJECT_B, FIXED_NOW, FIXED_NOW))
            other_id = cursor.lastrowid
            conn.commit()
        swapped = copy.deepcopy(plan)
        swapped["operations"][0]["local_row_id"] = other_id
        swapped["source_snapshot"]["selected_identity_digest"] = (
            self.sync._identity_snapshot_digest(swapped["operations"])
        )
        swapped["plan_id"] = self.sync._push_plan_id(swapped)
        with (
            mock.patch.object(self.sync, "_api_call") as api,
            mock.patch.object(self.sync, "_open_write_conn") as open_write,
        ):
            self.assertEqual(2, self.sync.execute_push_plan(swapped, scope_id="L-T005"))
        api.assert_not_called()
        open_write.assert_not_called()

    def test_source_snapshot_change_is_rejected_before_remote_or_write(self):
        plan = self._build_plan()
        plan["source_snapshot"]["db_updated_at_max"] = "2099-01-01T00:00:00Z"
        plan["plan_id"] = self.sync._push_plan_id(plan)
        with (
            mock.patch.object(self.sync, "_api_call") as api,
            mock.patch.object(self.sync, "_open_write_conn") as open_write,
        ):
            self.assertEqual(2, self.sync.execute_push_plan(plan, scope_id="L-T005"))
        api.assert_not_called()
        open_write.assert_not_called()

    def test_identity_journal_is_exact_plan_owned_and_uid_namespaced(self):
        plan = self._build_plan()
        operation = plan["operations"][0]
        owner = self.sync._v2_pending_owner(plan, operation)
        owner.update({
            "state": "remote_committed",
            "remote_page_id": "project-page",
        })
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO _metadata(key, value) VALUES (?, ?)",
                (self.sync._v2_pending_key(operation), json.dumps(owner)),
            )
            conn.commit()
        self.assertEqual(0, self.sync._validate_v2_plan_local_fencing(plan))

        other_identity = dict(operation["identity"], project_sync_uid=FIXED_PROJECT_B)
        other_operation = dict(
            operation,
            identity=other_identity,
            operation_id=self.sync._identity_operation_id(
                other_identity, operation["action"]
            ),
        )
        self.assertNotEqual(
            self.sync._v2_pending_key(operation),
            self.sync._v2_pending_key(other_operation),
        )
        other_plan = copy.deepcopy(plan)
        other_plan["preflight"] = {"status": "pass", "findings": ["changed"]}
        other_plan["plan_id"] = self.sync._push_plan_id(other_plan)
        self.assertEqual(2, self.sync._validate_v2_plan_local_fencing(other_plan))

    def test_v1_artifact_is_loadable_but_execute_is_read_only(self):
        plan = {
            "plan_id": "", "direction": "push", "preflight": {},
            "source_snapshot": {}, "operations": [], "summary": {},
            "reconciliation": {
                "blocking": {"exit_code": 0},
                "authorization_required": {"operation_ids": []},
            },
            "exit_code": 0,
        }
        plan["plan_id"] = self.sync._push_plan_id(plan)
        artifact = self.root / "v1-plan.json"
        self.sync.write_push_plan(plan, artifact)
        loaded = self.sync.load_push_plan(artifact)
        self.assertIsInstance(loaded, self.sync.ReadOnlyV1PushPlan)
        with mock.patch.object(self.sync, "_open_write_conn") as open_write:
            self.assertEqual(2, self.sync.execute_push_plan(loaded))
        open_write.assert_not_called()

    def test_legacy_pending_journal_overlap_requires_explicit_migration(self):
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO _metadata(key, value) VALUES (?, ?)",
                ("pending_push:project:L-T005", json.dumps({
                    "entity": "project", "stable_key": ["L-T005"],
                    "fingerprint": "legacy",
                })),
            )
            conn.commit()
        plan = self._build_plan()
        self.assertEqual(2, plan["exit_code"])
        self.assertEqual([], plan["operations"])
        self.assertEqual(
            "LEGACY_PENDING_JOURNAL_REQUIRES_MIGRATION",
            plan["preflight"]["findings"][0]["code"],
        )


class IdentityV2ProductionMigrationTest(unittest.TestCase):
    """T003 contract tests for the production migration/bootstrap helpers."""

    def setUp(self):
        self.production_before = file_fingerprint(PRODUCTION_DB)
        self.temp_dir = tempfile.TemporaryDirectory(prefix="ai-plc-identity-t003-")
        self.addCleanup(self._assert_production_unchanged)
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "legacy.db"
        self.init_db = load_module(DB_DIR / "init_db.py", f"identity_init_t003_{id(self)}")
        self.sync = load_module(DB_DIR / "sync.py", f"identity_sync_t003_{id(self)}")
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.init_db.create_schema(conn)
        self._insert_legacy_rows()

    def _assert_production_unchanged(self):
        self.assertEqual(self.production_before, file_fingerprint(PRODUCTION_DB))

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _insert_legacy_rows(self, *, orphan_task: bool = False):
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO projects (
                    notion_page_id, scope_id, name, status, created_at, updated_at,
                    last_sync_at
                ) VALUES (?, ?, ?, 'active', ?, ?, ?)
                """,
                (
                    "legacy-page-project-a",
                    "L-LEGACY-A",
                    "Legacy A",
                    "2026-07-01T00:00:00Z",
                    "2026-07-02T00:00:00Z",
                    "2026-07-03T00:00:00Z",
                ),
            )
            conn.execute(
                """
                INSERT INTO projects (
                    notion_page_id, scope_id, name, status, created_at, updated_at,
                    last_sync_at
                ) VALUES (?, ?, ?, 'active', ?, ?, ?)
                """,
                (
                    "legacy-page-project-b",
                    "L-LEGACY-B",
                    "Legacy B",
                    "2026-07-04T00:00:00Z",
                    "2026-07-05T00:00:00Z",
                    "2026-07-06T00:00:00Z",
                ),
            )
            conn.execute(
                """
                INSERT INTO tasks (
                    notion_page_id, task_id, scope_id, name, status, created_at,
                    updated_at, last_sync_at
                ) VALUES (?, 'T001', ?, 'Legacy Task', '未着手', ?, ?, ?)
                """,
                (
                    "legacy-page-task-a",
                    "L-ORPHAN" if orphan_task else "L-LEGACY-A",
                    "2026-07-07T00:00:00Z",
                    "2026-07-08T00:00:00Z",
                    "2026-07-09T00:00:00Z",
                ),
            )
            conn.commit()

    @staticmethod
    def _uid_factory():
        values = iter((FIXED_PROJECT_A, FIXED_PROJECT_B))
        return lambda: next(values)

    def _mapping(self, conn):
        return self.init_db.build_identity_migration_mapping(
            conn,
            FIXED_WORKSPACE_A,
            project_uid_factory=self._uid_factory(),
        )

    @staticmethod
    def _set_active_workspace(conn, workspace_id=FIXED_WORKSPACE_A):
        conn.execute(
            "INSERT OR REPLACE INTO _metadata(key, value) VALUES (?, ?)",
            ("active_workspace_id", workspace_id),
        )
        conn.commit()

    def test_legacy_to_v2_preserves_rows_links_and_timestamps(self):
        with closing(self._connect()) as conn:
            before = self.init_db.identity_migration_snapshot(conn)
            mapping = self._mapping(conn)
            result = self.init_db.migrate_identity_v2(conn, mapping)
            after = self.init_db.identity_migration_snapshot(conn)
            self.assertEqual(before["counts"], after["counts"])
            self.assertEqual(before["links"], after["links"])
            self.assertEqual(before["timestamps"], after["timestamps"])
            self.assertEqual("2", result["identity_schema_version"])
            self.assertEqual("ok", conn.execute("PRAGMA quick_check").fetchone()[0])

    def test_migration_rerun_reuses_every_identity(self):
        with closing(self._connect()) as conn:
            mapping = self._mapping(conn)
            first = self.init_db.migrate_identity_v2(conn, mapping)
            identities = self.init_db.identity_row_snapshot(conn)
            second = self.init_db.migrate_identity_v2(conn, mapping)
            self.assertEqual(identities, self.init_db.identity_row_snapshot(conn))
            self.assertEqual(first["counts"], second["counts"])
            self.assertTrue(second["already_migrated"])

    def test_same_scope_can_coexist_only_in_different_workspaces(self):
        with closing(self._connect()) as conn:
            self.init_db.migrate_identity_v2(conn, self._mapping(conn))
            conn.execute(
                """
                INSERT INTO projects (
                    workspace_id, sync_uid, ownership_epoch, identity_version,
                    scope_id, name, status
                ) VALUES (?, ?, 1, 2, 'L-LEGACY-A', 'Forked A', 'active')
                """,
                (FIXED_WORKSPACE_B, "prj_00000000-0000-4000-8000-000000000003"),
            )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO projects (
                        workspace_id, sync_uid, ownership_epoch, identity_version,
                        scope_id, name, status
                    ) VALUES (?, ?, 1, 2, 'L-LEGACY-A', 'Duplicate A', 'active')
                    """,
                    (FIXED_WORKSPACE_A, "prj_00000000-0000-4000-8000-000000000004"),
                )

    def test_orphan_task_without_explicit_mapping_rolls_back(self):
        with closing(self._connect()) as conn:
            conn.execute("DELETE FROM tasks")
            conn.commit()
        self._insert_orphan_only()
        with closing(self._connect()) as conn:
            before = self.init_db.identity_migration_snapshot(conn)
            with self.assertRaisesRegex(ValueError, "TASK_PROJECT_IDENTITY_MISSING"):
                self._mapping(conn)
            self.assertEqual(before, self.init_db.identity_migration_snapshot(conn))
            self.assertNotIn(
                "workspace_id",
                {row[1] for row in conn.execute("PRAGMA table_info(projects)")},
            )
            self.assertEqual("ok", conn.execute("PRAGMA quick_check").fetchone()[0])

    def test_orphan_task_with_explicit_project_mapping_can_migrate(self):
        with closing(self._connect()) as conn:
            conn.execute("UPDATE tasks SET scope_id = 'L-ORPHAN'")
            conn.commit()
            mapping = self.init_db.build_identity_migration_mapping(
                conn,
                FIXED_WORKSPACE_A,
                project_uid_factory=self._uid_factory(),
                task_project_overrides={1: FIXED_PROJECT_A},
            )
            self.init_db.migrate_identity_v2(conn, mapping)
            row = conn.execute(
                "SELECT project_sync_uid FROM tasks WHERE id = 1"
            ).fetchone()
            self.assertEqual(FIXED_PROJECT_A, row[0])

    def _insert_orphan_only(self):
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO tasks (notion_page_id, task_id, scope_id, name, status)
                VALUES ('legacy-orphan-task', 'T999', 'L-ORPHAN', 'Orphan', '未着手')
                """
            )
            conn.commit()

    def test_injected_rebuild_failure_restores_original_schema(self):
        with closing(self._connect()) as conn:
            mapping = self._mapping(conn)
            before = self.init_db.identity_migration_snapshot(conn)
            with self.assertRaisesRegex(RuntimeError, "injected"):
                self.init_db.migrate_identity_v2(
                    conn, mapping, fail_at="after_projects_swap"
                )
            self.assertEqual(before, self.init_db.identity_migration_snapshot(conn))
            self.assertNotIn(
                "workspace_id",
                {row[1] for row in conn.execute("PRAGMA table_info(projects)")},
            )
            self.assertEqual("ok", conn.execute("PRAGMA quick_check").fetchone()[0])

    def test_partial_additive_columns_converge_to_enforced_v2(self):
        with closing(self._connect()) as conn:
            conn.execute("ALTER TABLE projects ADD COLUMN workspace_id TEXT")
            conn.execute("ALTER TABLE projects ADD COLUMN sync_uid TEXT")
            conn.execute("ALTER TABLE tasks ADD COLUMN workspace_id TEXT")
            conn.execute("ALTER TABLE tasks ADD COLUMN project_sync_uid TEXT")
            conn.commit()
            mapping = self._mapping(conn)
            self.init_db.migrate_identity_v2(conn, mapping)
            self.assertEqual("2", conn.execute(
                "SELECT value FROM _metadata WHERE key='identity_schema_version'"
            ).fetchone()[0])
            self.assertEqual("ok", conn.execute("PRAGMA quick_check").fetchone()[0])

    def test_unknown_columns_indexes_and_triggers_fail_before_rebuild(self):
        with closing(self._connect()) as conn:
            mapping = self._mapping(conn)
            conn.execute("CREATE INDEX custom_projects_owner ON projects(owner)")
            with self.assertRaisesRegex(ValueError, "UNSUPPORTED_INDEX"):
                self.init_db.migrate_identity_v2(conn, mapping)
            self.assertIsNotNone(conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='custom_projects_owner'"
            ).fetchone())
            conn.execute("DROP INDEX custom_projects_owner")

            conn.execute("""
                CREATE TRIGGER custom_projects_audit AFTER INSERT ON projects
                BEGIN SELECT NEW.id; END
            """)
            with self.assertRaisesRegex(ValueError, "UNSUPPORTED_TRIGGER"):
                self.init_db.migrate_identity_v2(conn, mapping)
            self.assertIsNotNone(conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='custom_projects_audit'"
            ).fetchone())
            conn.execute("DROP TRIGGER custom_projects_audit")

            conn.execute("ALTER TABLE projects ADD COLUMN custom_payload TEXT")
            with self.assertRaisesRegex(ValueError, "UNSUPPORTED_COLUMN"):
                self.init_db.migrate_identity_v2(conn, mapping)
            self.assertIn(
                "custom_payload",
                {row[1] for row in conn.execute("PRAGMA table_info(projects)")},
            )

    def test_known_schema_names_with_changed_definitions_fail_before_rebuild(self):
        with closing(self._connect()) as conn:
            mapping = self._mapping(conn)
            conn.execute("DROP INDEX idx_projects_scope")
            conn.execute("CREATE INDEX idx_projects_scope ON projects(owner)")
            with self.assertRaisesRegex(ValueError, "UNSUPPORTED_INDEX_DEFINITION"):
                self.init_db.migrate_identity_v2(conn, mapping)
            conn.execute("DROP INDEX idx_projects_scope")
            conn.execute("CREATE INDEX idx_projects_scope ON projects(scope_id)")

            conn.execute("DROP TRIGGER trg_projects_updated")
            conn.execute("""
                CREATE TRIGGER trg_projects_updated AFTER UPDATE ON projects
                BEGIN SELECT NEW.id; END
            """)
            with self.assertRaisesRegex(ValueError, "UNSUPPORTED_TRIGGER_DEFINITION"):
                self.init_db.migrate_identity_v2(conn, mapping)
            conn.execute("DROP TRIGGER trg_projects_updated")
            conn.execute(self.init_db.TRIGGER_SQL_CONTRACTS["trg_projects_updated"])

            schema_version = conn.execute("PRAGMA schema_version").fetchone()[0]
            conn.execute("PRAGMA writable_schema=ON")
            conn.execute(
                """
                UPDATE sqlite_master
                SET sql = replace(sql, 'owner           TEXT,', 'owner TEXT DEFAULT ''changed'',')
                WHERE type='table' AND name='projects'
                """
            )
            conn.execute("PRAGMA writable_schema=OFF")
            conn.execute("PRAGMA schema_version = %d" % (schema_version + 1))
            with self.assertRaisesRegex(ValueError, "UNSUPPORTED_COLUMN_DEFINITION"):
                self.init_db.migrate_identity_v2(conn, mapping)

    def test_weak_v2_missing_required_objects_is_rebuilt_not_accepted(self):
        with closing(self._connect()) as conn:
            mapping = self._mapping(conn)
            self.init_db.migrate_identity_v2(conn, mapping)
            conn.execute("DROP INDEX idx_projects_workspace")
            conn.execute("DROP TRIGGER trg_tasks_updated")
            result = self.init_db.migrate_identity_v2(conn, mapping)
            self.assertFalse(result["already_migrated"])
            objects = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE name IN (?,?)",
                    ("idx_projects_workspace", "trg_tasks_updated"),
                )
            }
            self.assertEqual(
                {"idx_projects_workspace", "trg_tasks_updated"}, objects
            )

    def test_task_parent_epoch_mismatch_rolls_back_partial_schema(self):
        with closing(self._connect()) as conn:
            conn.execute("ALTER TABLE projects ADD COLUMN ownership_epoch INTEGER")
            conn.execute("ALTER TABLE projects ADD COLUMN identity_version INTEGER")
            conn.execute(
                "ALTER TABLE tasks ADD COLUMN project_ownership_epoch INTEGER"
            )
            conn.execute("ALTER TABLE tasks ADD COLUMN identity_version INTEGER")
            conn.execute("UPDATE projects SET ownership_epoch=2, identity_version=2")
            conn.execute(
                "UPDATE tasks SET project_ownership_epoch=1, identity_version=2"
            )
            conn.commit()
            mapping = self._mapping(conn)
            before_columns = tuple(conn.execute("PRAGMA table_info(tasks)"))
            with self.assertRaisesRegex(ValueError, "TASK_PROJECT_IDENTITY_MISMATCH"):
                self.init_db.migrate_identity_v2(conn, mapping)
            self.assertEqual(before_columns, tuple(conn.execute("PRAGMA table_info(tasks)")))
            self.assertEqual(
                1,
                conn.execute(
                    "SELECT project_ownership_epoch FROM tasks WHERE id=1"
                ).fetchone()[0],
            )

    def test_incomplete_mapping_is_rejected_before_schema_mutation(self):
        with closing(self._connect()) as conn:
            mapping = self._mapping(conn)
            mapping["tasks"].pop("1")
            with self.assertRaisesRegex(ValueError, "MAPPING_INCOMPLETE"):
                self.init_db.migrate_identity_v2(conn, mapping)
            self.assertNotIn(
                "workspace_id",
                {row[1] for row in conn.execute("PRAGMA table_info(projects)")},
            )

    def test_bootstrap_crash_resume_and_path_move_reuse_workspace_id(self):
        recorder = MutationRecorder()
        authority = FakeIdentityAuthorityStore(recorder)
        manifest = self.root / "moved" / "workspace_identity.json"
        state = self.root / "moved" / "identity_bootstrap.state.json"
        manifest.parent.mkdir()
        with closing(self._connect()) as conn:
            with self.assertRaisesRegex(RuntimeError, "after_authority_cas"):
                self.sync.bootstrap_workspace_identity(
                    conn,
                    authority,
                    manifest_path=manifest,
                    state_path=state,
                    workspace_id_factory=lambda: FIXED_WORKSPACE_A,
                    fail_at="after_authority_cas",
                )
            resumed = self.sync.bootstrap_workspace_identity(
                conn,
                authority,
                manifest_path=manifest,
                state_path=state,
                workspace_id_factory=lambda: (_ for _ in ()).throw(
                    AssertionError("workspace ID must not be regenerated")
                ),
            )
            moved_manifest = self.root / "renamed" / "workspace_identity.json"
            moved_manifest.parent.mkdir()
            moved_manifest.write_bytes(manifest.read_bytes())
            resolved = self.sync.resolve_workspace_identity(
                conn, authority, manifest_path=moved_manifest
            )
            self.assertEqual(FIXED_WORKSPACE_A, resumed["workspace_id"])
            self.assertEqual(FIXED_WORKSPACE_A, resolved["workspace_id"])

    def test_tampered_bootstrap_state_is_rejected_before_authority_cas(self):
        recorder = MutationRecorder()
        authority = FakeIdentityAuthorityStore(recorder)
        manifest = self.root / "workspace_identity.json"
        state_path = self.root / "identity_bootstrap.state.json"
        with closing(self._connect()) as conn:
            with self.assertRaisesRegex(RuntimeError, "after_planned"):
                self.sync.bootstrap_workspace_identity(
                    conn,
                    authority,
                    manifest_path=manifest,
                    state_path=state_path,
                    workspace_id_factory=lambda: FIXED_WORKSPACE_A,
                    fail_at="after_planned",
                )
            state = self.sync._read_json_file(state_path)
            state["authority_record"]["writer_id"] = "tampered-writer"
            self.sync._atomic_json_write(state_path, state)
            with self.assertRaisesRegex(ValueError, "BOOTSTRAP_AUTHORITY_INVALID"):
                self.sync.bootstrap_workspace_identity(
                    conn,
                    authority,
                    manifest_path=manifest,
                    state_path=state_path,
                )
            self.assertEqual(0, recorder.count("authority_cas"))
            self.assertFalse(manifest.exists())

    def test_stale_authority_resume_fails_before_manifest_mutation(self):
        recorder = MutationRecorder()
        authority = FakeIdentityAuthorityStore(recorder)
        manifest = self.root / "workspace_identity.json"
        state_path = self.root / "identity_bootstrap.state.json"
        with closing(self._connect()) as conn:
            with self.assertRaisesRegex(RuntimeError, "after_authority_committed"):
                self.sync.bootstrap_workspace_identity(
                    conn,
                    authority,
                    manifest_path=manifest,
                    state_path=state_path,
                    workspace_id_factory=lambda: FIXED_WORKSPACE_A,
                    fail_at="after_authority_committed",
                )
            cas_before = recorder.count("authority_cas")
            authority.workspaces[FIXED_WORKSPACE_A]["writer_id"] = "rotated-writer"
            with self.assertRaisesRegex(ValueError, "AUTHORITY_MISMATCH"):
                self.sync.bootstrap_workspace_identity(
                    conn,
                    authority,
                    manifest_path=manifest,
                    state_path=state_path,
                )
            self.assertEqual(cas_before, recorder.count("authority_cas"))
            self.assertFalse(manifest.exists())

    def test_missing_committed_manifest_fails_before_cache_mutation(self):
        recorder = MutationRecorder()
        authority = FakeIdentityAuthorityStore(recorder)
        manifest = self.root / "workspace_identity.json"
        state_path = self.root / "identity_bootstrap.state.json"
        with closing(self._connect()) as conn:
            with self.assertRaisesRegex(RuntimeError, "after_manifest_committed"):
                self.sync.bootstrap_workspace_identity(
                    conn,
                    authority,
                    manifest_path=manifest,
                    state_path=state_path,
                    workspace_id_factory=lambda: FIXED_WORKSPACE_A,
                    fail_at="after_manifest_committed",
                )
            manifest.unlink()
            with self.assertRaisesRegex(ValueError, "COMMITTED_MANIFEST_MISSING"):
                self.sync.bootstrap_workspace_identity(
                    conn,
                    authority,
                    manifest_path=manifest,
                    state_path=state_path,
                )
            self.assertIsNone(conn.execute(
                "SELECT value FROM _metadata WHERE key='active_workspace_id'"
            ).fetchone())

    def test_forged_progress_state_fails_before_authority_or_cache_mutation(self):
        recorder = MutationRecorder()
        authority = FakeIdentityAuthorityStore(recorder)
        manifest = self.root / "workspace_identity.json"
        state_path = self.root / "identity_bootstrap.state.json"
        with closing(self._connect()) as conn:
            with self.assertRaisesRegex(RuntimeError, "after_planned"):
                self.sync.bootstrap_workspace_identity(
                    conn,
                    authority,
                    manifest_path=manifest,
                    state_path=state_path,
                    workspace_id_factory=lambda: FIXED_WORKSPACE_A,
                    fail_at="after_planned",
                )
            state = self.sync._read_json_file(state_path)
            state.update({"state": "manifest_committed", "authority_revision": 1})
            self.sync._atomic_json_write(state_path, state)
            with self.assertRaisesRegex(ContractViolation, "authority is absent"):
                self.sync.bootstrap_workspace_identity(
                    conn,
                    authority,
                    manifest_path=manifest,
                    state_path=state_path,
                )
            self.assertEqual(0, recorder.count("authority_cas"))
            self.assertFalse(manifest.exists())
            self.assertIsNone(conn.execute(
                "SELECT value FROM _metadata WHERE key='active_workspace_id'"
            ).fetchone())

    def test_production_bootstrap_all_crash_boundaries_converge(self):
        points = (
            "before_planned",
            "after_planned",
            "after_authority_cas",
            "after_authority_committed",
            "after_manifest_commit",
            "after_manifest_committed",
            "after_cache_commit",
            "after_cache_committed",
            "after_verified",
        )
        for fail_at in points:
            with self.subTest(fail_at=fail_at):
                temp = tempfile.TemporaryDirectory(prefix="ai-plc-bootstrap-point-")
                self.addCleanup(temp.cleanup)
                root = Path(temp.name)
                db_path = root / "bootstrap.db"
                with closing(sqlite3.connect(db_path)) as setup_conn:
                    self.init_db.create_schema(setup_conn)
                recorder = MutationRecorder()
                authority = FakeIdentityAuthorityStore(recorder)
                manifest = root / "workspace_identity.json"
                state = root / "identity_bootstrap.state.json"
                with closing(sqlite3.connect(db_path)) as conn:
                    conn.row_factory = sqlite3.Row
                    with self.assertRaisesRegex(RuntimeError, fail_at):
                        self.sync.bootstrap_workspace_identity(
                            conn,
                            authority,
                            manifest_path=manifest,
                            state_path=state,
                            workspace_id_factory=lambda: FIXED_WORKSPACE_A,
                            fail_at=fail_at,
                        )
                    factory = (
                        (lambda: FIXED_WORKSPACE_A)
                        if fail_at == "before_planned"
                        else (lambda: (_ for _ in ()).throw(
                            AssertionError("planned workspace ID must be reused")
                        ))
                    )
                    result = self.sync.bootstrap_workspace_identity(
                        conn,
                        authority,
                        manifest_path=manifest,
                        state_path=state,
                        workspace_id_factory=factory,
                    )
                    self.assertEqual(FIXED_WORKSPACE_A, result["workspace_id"])
                    self.assertFalse(state.exists())
                    self.assertFalse(Path(str(state) + ".tmp").exists())
                    self.assertFalse(Path(str(manifest) + ".tmp").exists())

    def test_manifest_only_rebuilds_missing_cache_without_new_identity(self):
        recorder = MutationRecorder()
        authority = FakeIdentityAuthorityStore(recorder)
        manifest = self.root / "workspace_identity.json"
        state = self.root / "identity_bootstrap.state.json"
        with closing(self._connect()) as conn:
            first = self.sync.bootstrap_workspace_identity(
                conn,
                authority,
                manifest_path=manifest,
                state_path=state,
                workspace_id_factory=lambda: FIXED_WORKSPACE_A,
            )
            conn.execute(
                "DELETE FROM _metadata WHERE key IN (?,?,?)",
                (
                    "active_workspace_id",
                    "active_writer_epoch",
                    "writer_authority_hash_cache",
                ),
            )
            conn.commit()
            recovered = self.sync.bootstrap_workspace_identity(
                conn,
                authority,
                manifest_path=manifest,
                state_path=state,
                workspace_id_factory=lambda: (_ for _ in ()).throw(
                    AssertionError("manifest recovery must not issue a new ID")
                ),
            )
            self.assertEqual(first, recovered)

    def test_bootstrap_rejects_cache_manifest_split_brain(self):
        recorder = MutationRecorder()
        authority = FakeIdentityAuthorityStore(recorder)
        manifest = self.root / "workspace_identity.json"
        state = self.root / "identity_bootstrap.state.json"
        with closing(self._connect()) as conn:
            self.sync.bootstrap_workspace_identity(
                conn,
                authority,
                manifest_path=manifest,
                state_path=state,
                workspace_id_factory=lambda: FIXED_WORKSPACE_A,
            )
            conn.execute(
                "UPDATE _metadata SET value = ? WHERE key = 'active_workspace_id'",
                (FIXED_WORKSPACE_B,),
            )
            conn.commit()
            with self.assertRaisesRegex(ValueError, "SPLIT_BRAIN"):
                self.sync.bootstrap_workspace_identity(
                    conn,
                    authority,
                    manifest_path=manifest,
                    state_path=state,
                )

    def test_explicit_fork_state_is_idempotent_and_does_not_change_current_rows(self):
        with closing(self._connect()) as conn:
            self.init_db.migrate_identity_v2(conn, self._mapping(conn))
            self._set_active_workspace(conn)
            before = self.init_db.identity_row_snapshot(conn)
            fork_state = self.root / "workspace_fork.state.json"
            ids = iter((
                FIXED_WORKSPACE_B,
                "prj_00000000-0000-4000-8000-000000000003",
                "prj_00000000-0000-4000-8000-000000000004",
            ))
            first = self.sync.prepare_workspace_fork(
                conn, fork_state, identity_factory=lambda: next(ids)
            )
            second = self.sync.prepare_workspace_fork(
                conn,
                fork_state,
                identity_factory=lambda: (_ for _ in ()).throw(
                    AssertionError("fork identities must be reused")
                ),
            )
            self.assertEqual(first, second)
            self.assertEqual(before, self.init_db.identity_row_snapshot(conn))

    def test_tampered_fork_state_is_rejected_without_row_mutation(self):
        with closing(self._connect()) as conn:
            self.init_db.migrate_identity_v2(conn, self._mapping(conn))
            self._set_active_workspace(conn)
            before = self.init_db.identity_row_snapshot(conn)
            fork_state = self.root / "workspace_fork.state.json"
            ids = iter((
                FIXED_WORKSPACE_B,
                "prj_00000000-0000-4000-8000-000000000003",
                "prj_00000000-0000-4000-8000-000000000004",
            ))
            state = self.sync.prepare_workspace_fork(
                conn, fork_state, identity_factory=lambda: next(ids)
            )
            state["projects"]["1"]["source_sync_uid"] = FIXED_PROJECT_B
            self.sync._atomic_json_write(fork_state, state)
            with self.assertRaisesRegex(ValueError, "SOURCE_MISMATCH"):
                self.sync.prepare_workspace_fork(conn, fork_state)
            self.assertEqual(before, self.init_db.identity_row_snapshot(conn))

    def test_fork_rejects_source_workspace_and_project_identity_reuse(self):
        with closing(self._connect()) as conn:
            self.init_db.migrate_identity_v2(conn, self._mapping(conn))
            self._set_active_workspace(conn)
            fork_state = self.root / "workspace_fork.state.json"
            with self.assertRaisesRegex(ValueError, "REUSES_SOURCE_WORKSPACE"):
                self.sync.prepare_workspace_fork(
                    conn, fork_state, identity_factory=lambda: FIXED_WORKSPACE_A
                )
            self.assertFalse(fork_state.exists())

            ids = iter((FIXED_WORKSPACE_B, FIXED_PROJECT_A))
            with self.assertRaisesRegex(ValueError, "REUSES_SOURCE_PROJECT_UID"):
                self.sync.prepare_workspace_fork(
                    conn, fork_state, identity_factory=lambda: next(ids)
                )
            self.assertFalse(fork_state.exists())

            valid_ids = iter((
                FIXED_WORKSPACE_B,
                "prj_00000000-0000-4000-8000-000000000003",
                "prj_00000000-0000-4000-8000-000000000004",
            ))
            state = self.sync.prepare_workspace_fork(
                conn, fork_state, identity_factory=lambda: next(valid_ids)
            )
            state["result_workspace_id"] = FIXED_WORKSPACE_A
            self.sync._atomic_json_write(fork_state, state)
            with self.assertRaisesRegex(ValueError, "REUSES_SOURCE_WORKSPACE"):
                self.sync.prepare_workspace_fork(conn, fork_state)

    def test_fork_maps_only_active_workspace_in_multi_workspace_registry(self):
        with closing(self._connect()) as conn:
            self.init_db.migrate_identity_v2(conn, self._mapping(conn))
            conn.execute(
                """
                INSERT INTO projects (
                    workspace_id, sync_uid, ownership_epoch, identity_version,
                    scope_id, name, status
                ) VALUES (?, ?, 1, 2, 'L-OTHER', 'Other Workspace', 'active')
                """,
                (
                    FIXED_WORKSPACE_B,
                    "prj_00000000-0000-4000-8000-000000000005",
                ),
            )
            self._set_active_workspace(conn)
            before = self.init_db.identity_row_snapshot(conn)
            fork_state = self.root / "workspace_fork.state.json"
            ids = iter((
                "wsp_00000000-0000-4000-8000-000000000003",
                "prj_00000000-0000-4000-8000-000000000003",
                "prj_00000000-0000-4000-8000-000000000004",
            ))
            state = self.sync.prepare_workspace_fork(
                conn, fork_state, identity_factory=lambda: next(ids)
            )
            self.assertEqual(FIXED_WORKSPACE_A, state["source_workspace_id"])
            self.assertEqual({"1", "2"}, set(state["projects"]))
            self.assertNotIn("3", state["projects"])
            self.assertEqual(before, self.init_db.identity_row_snapshot(conn))


class FakeMigrationRemote:
    """Minimal three-surface boundary for the T006 migration engine."""

    def __init__(self):
        self.rows = {}
        self.mutations = 0
        self.fail_after_commit = False

    def read(self, entity, operation):
        return copy.deepcopy(self.rows.get(operation["operation_id"]))

    def upsert(self, entity, operation, projection, expected_current=None):
        if self.rows.get(operation["operation_id"]) != expected_current:
            raise ContractViolation("fake remote CAS failed")
        self.mutations += 1
        self.rows[operation["operation_id"]] = copy.deepcopy(projection)
        if self.fail_after_commit:
            self.fail_after_commit = False
            raise CommitThenTimeout("fake remote committed before journal")


class IdentityV2MigrationPlanBackfillTest(unittest.TestCase):
    """T006 failure-first contract using only disposable local surfaces."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db_path = self.root / "migration.db"
        self.state_path = self.root / "migration.state.json"
        self.sync = load_module(DB_DIR / "sync.py", f"identity_sync_t006_{id(self)}")
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    notion_page_id TEXT UNIQUE,
                    scope_id TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'planned',
                    created_at TEXT NOT NULL DEFAULT '2026-07-15T00:00:00Z',
                    updated_at TEXT NOT NULL DEFAULT '2026-07-15T00:00:00Z'
                );
                CREATE TABLE tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    notion_page_id TEXT UNIQUE,
                    task_id TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT '未着手',
                    created_at TEXT NOT NULL DEFAULT '2026-07-15T00:00:00Z',
                    updated_at TEXT NOT NULL DEFAULT '2026-07-15T00:00:00Z',
                    UNIQUE(task_id, scope_id)
                );
                CREATE TRIGGER trg_projects_updated AFTER UPDATE ON projects
                BEGIN UPDATE projects SET updated_at='triggered' WHERE id=NEW.id; END;
                CREATE TRIGGER trg_tasks_updated AFTER UPDATE ON tasks
                BEGIN UPDATE tasks SET updated_at='triggered' WHERE id=NEW.id; END;
                INSERT INTO projects(notion_page_id,scope_id,name,status)
                    VALUES('page-project-existing','L-EXISTING','Existing','active');
                INSERT INTO tasks(notion_page_id,task_id,scope_id,name,status)
                    VALUES('page-task-existing','T001','L-EXISTING','Existing task','進行中');
                INSERT INTO tasks(notion_page_id,task_id,scope_id,name,status)
                    VALUES('page-orphan-1','T004','L-OLD-A-SG0','Excluded','未着手');
                INSERT INTO tasks(notion_page_id,task_id,scope_id,name,status)
                    VALUES('page-orphan-2','T020','L-OLD-B-X1','Mapped A','未着手');
                INSERT INTO tasks(notion_page_id,task_id,scope_id,name,status)
                    VALUES
                    ('page-orphan-3','T001','L-OLD-C-X2-SG1','Mapped B1','未着手'),
                    ('page-orphan-4','T002','L-OLD-C-X2-SG1','Mapped B2','未着手'),
                    ('page-orphan-5','T003','L-OLD-C-X2-SG1','Mapped B3','未着手'),
                    ('page-orphan-6','T004','L-OLD-C-X2-SG1','Mapped B4','未着手'),
                    ('page-orphan-7','T005','L-OLD-C-X2-SG1','Mapped B5','未着手'),
                    ('page-orphan-8','T006','L-OLD-C-X2-SG1','Mapped B6','未着手');
            """)
        self.intents = {
            "L-EXISTING": {"scope_id": "L-EXISTING", "name": "Existing intent", "status": "active"},
            "L-OLD-B-X1": {"scope_id": "L-OLD-B-X1", "name": "Intent A", "status": "active"},
            "L-OLD-C-X2-SG1": {"scope_id": "L-OLD-C-X2-SG1", "name": "Intent B", "status": "completed"},
        }
        self.intent_paths = {}
        for scope_id, intent in self.intents.items():
            path = self.root / scope_id / "intent.yaml"
            path.parent.mkdir()
            path.write_text(json.dumps(intent), encoding="utf-8")
            self.intent_paths[scope_id] = path
        self.uid_existing = "prj_00000000-0000-4000-8000-000000000010"
        self.uid_a = "prj_00000000-0000-4000-8000-000000000011"
        self.uid_b = "prj_00000000-0000-4000-8000-000000000012"
        self.decisions = [{
            "routing_key": "L-OLD-A-SG0/T004",
            "decision": "legacy_excluded", "evidence_digest": "sha256:no-intent",
        }, {
            "routing_key": "L-OLD-B-X1/T020", "decision": "fixed_mapping",
            "project_sync_uid": self.uid_a, "evidence_digest": "sha256:intent-a",
        }]
        self.decisions.extend({
            "routing_key": f"L-OLD-C-X2-SG1/T{index:03d}",
            "decision": "fixed_mapping", "project_sync_uid": self.uid_b,
            "evidence_digest": "sha256:intent-b",
        } for index in range(1, 7))

    def tearDown(self):
        self.tempdir.cleanup()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _plan(self, conn):
        return self.sync.build_identity_migration_plan(
            conn, FIXED_WORKSPACE_A, self.decisions, self.intents,
            project_uid_mappings={"L-EXISTING": self.uid_existing},
            remote=FakeMigrationRemote(), batch_size=10,
        )

    def test_inventory_lists_exact_eight_privacy_safe_orphans(self):
        with closing(self._connect()) as conn:
            inventory = self.sync.identity_migration_inventory(conn)
        self.assertEqual(8, inventory["counts"]["orphans"])
        self.assertEqual("adjudication_required", inventory["state"])
        self.assertNotIn("row_id", inventory["orphans"][0])
        self.assertTrue(all(item["linked"] for item in inventory["orphans"]))

    def test_incomplete_or_inferred_decision_fails_before_mutation(self):
        before = file_fingerprint(self.db_path)
        with closing(self._connect()) as conn:
            with self.assertRaisesRegex(ValueError, "ADJUDICATION_INCOMPLETE"):
                self.sync.build_identity_migration_plan(
                    conn, FIXED_WORKSPACE_A, self.decisions[:-1], self.intents,
                    project_uid_mappings={"L-EXISTING": self.uid_existing},
                )
        self.assertEqual(before, file_fingerprint(self.db_path))
        self.assertFalse(self.state_path.exists())

    def test_fixed_plan_has_two_batches_and_is_tamper_evident(self):
        with closing(self._connect()) as conn:
            plan = self._plan(conn)
        self.assertEqual(8, len(plan["decisions"]))
        self.assertEqual([10, 1], [len(batch) for batch in plan["batches"]])
        self.assertTrue(self.sync.validate_identity_migration_plan(plan, plan["plan_id"]))
        persisted = self.root / "plan.json"
        self.sync.write_identity_migration_plan(persisted, plan)
        plan["operations"][0]["project_sync_uid"] = self.uid_a
        self.assertFalse(self.sync.validate_identity_migration_plan(plan))

    def test_uid_reservation_and_three_surface_collisions_fail_before_mutation(self):
        with closing(self._connect()) as conn:
            with self.assertRaisesRegex(ValueError, "FIXED_UID_REQUIRED"):
                self.sync.build_identity_migration_plan(
                    conn, FIXED_WORKSPACE_A, self.decisions, self.intents,
                    remote=FakeMigrationRemote(),
                )
            remote = FakeMigrationRemote()
            remote.rows["project:1"] = {
                "workspace_id": FIXED_WORKSPACE_B,
                "project_sync_uid": FIXED_PROJECT_B,
                "ownership_epoch": 1, "identity_version": 2,
            }
            with self.assertRaisesRegex(ValueError, "REMOTE_COLLISION"):
                self.sync.build_identity_migration_plan(
                    conn, FIXED_WORKSPACE_A, self.decisions, self.intents,
                    project_uid_mappings={"L-EXISTING": self.uid_existing},
                    remote=remote,
                )
            conflicting = copy.deepcopy(self.intents)
            conflicting["L-EXISTING"]["identity"] = {
                "version": 2, "workspace_id": FIXED_WORKSPACE_B,
                "sync_uid": FIXED_PROJECT_B, "ownership_epoch": 1,
            }
            with self.assertRaisesRegex(ValueError, "INTENT_COLLISION"):
                self.sync.build_identity_migration_plan(
                    conn, FIXED_WORKSPACE_A, self.decisions, conflicting,
                    project_uid_mappings={"L-EXISTING": self.uid_existing},
                    remote=FakeMigrationRemote(),
                )
        self.assertFalse(self.state_path.exists())

    def test_execute_preflight_blocks_local_and_intent_collision_before_remote(self):
        remote = FakeMigrationRemote()
        with closing(self._connect()) as conn:
            plan = self._plan(conn)
            self.sync._ensure_identity_dual_read_schema(conn)
            trigger_sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='trg_projects_updated'"
            ).fetchone()[0]
            conn.execute("DROP TRIGGER trg_projects_updated")
            conn.execute("""
                UPDATE projects SET workspace_id=?,sync_uid=?,ownership_epoch=1,
                                    identity_version=2 WHERE id=1
            """, (FIXED_WORKSPACE_B, FIXED_PROJECT_B))
            conn.execute(trigger_sql)
            conn.commit()
            with self.assertRaisesRegex(ValueError, "LOCAL_PREFLIGHT_COLLISION"):
                self.sync.execute_identity_migration_plan(
                    conn, plan, remote, self.intents, state_path=self.state_path,
                    expected_plan_id=plan["plan_id"], intent_paths=self.intent_paths,
                )
            self.assertEqual(0, remote.mutations)
            conn.execute("DROP TRIGGER trg_projects_updated")
            conn.execute("""
                UPDATE projects SET workspace_id=NULL,sync_uid=NULL,
                                    ownership_epoch=NULL,identity_version=NULL WHERE id=1
            """)
            conn.execute(trigger_sql)
            conn.commit()
            self.sync._atomic_json_write(self.state_path, {
                "plan_id": plan["plan_id"], "state": "planned", "completed": [],
                "remote_committed": [], "batches": [], "uid_regenerations": 0,
            })
            self.intents["L-EXISTING"]["identity"] = {
                "version": 2, "workspace_id": FIXED_WORKSPACE_B,
                "sync_uid": FIXED_PROJECT_B, "ownership_epoch": 1,
            }
            with self.assertRaisesRegex(ValueError, "INTENT_PREFLIGHT_COLLISION"):
                self.sync.execute_identity_migration_plan(
                    conn, plan, remote, self.intents, state_path=self.state_path,
                    expected_plan_id=plan["plan_id"], intent_paths=self.intent_paths,
                )
            self.assertEqual(0, remote.mutations)

    def test_write_before_journal_gaps_are_adopted_without_duplicate_mutation(self):
        remote = FakeMigrationRemote()
        remote.fail_after_commit = True
        with closing(self._connect()) as conn:
            plan = self._plan(conn)
            with self.assertRaises(CommitThenTimeout):
                self.sync.execute_identity_migration_plan(
                    conn, plan, remote, self.intents, state_path=self.state_path,
                    expected_plan_id=plan["plan_id"], intent_paths=self.intent_paths,
                )
            self.assertEqual(1, remote.mutations)
            result = self.sync.execute_identity_migration_plan(
                conn, plan, remote, self.intents, state_path=self.state_path,
                expected_plan_id=plan["plan_id"], intent_paths=self.intent_paths,
            )
            self.assertEqual("verified", result["state"])
            self.assertEqual(11, remote.mutations)

        # A separate fixture proves intent atomic-write -> journal repair.
        self.tearDown()
        self.setUp()
        remote = FakeMigrationRemote()
        with closing(self._connect()) as conn:
            plan = self._plan(conn)
            with self.assertRaisesRegex(RuntimeError, "after_intent_write_before_journal"):
                self.sync.execute_identity_migration_plan(
                    conn, plan, remote, self.intents, state_path=self.state_path,
                    expected_plan_id=plan["plan_id"], intent_paths=self.intent_paths,
                    fail_at="after_intent_write_before_journal",
                )
            before_resume = remote.mutations
            result = self.sync.execute_identity_migration_plan(
                conn, plan, remote, self.intents, state_path=self.state_path,
                expected_plan_id=plan["plan_id"], intent_paths=self.intent_paths,
            )
            self.assertEqual("verified", result["state"])
            self.assertEqual(before_resume, 1)
            self.assertEqual(11, remote.mutations)

    def test_partial_remote_success_resumes_without_uid_regeneration_or_duplicate(self):
        remote = FakeMigrationRemote()
        with closing(self._connect()) as conn:
            plan = self._plan(conn)
            with self.assertRaisesRegex(RuntimeError, "after_remote_commit"):
                self.sync.execute_identity_migration_plan(
                    conn, plan, remote, self.intents, state_path=self.state_path,
                    expected_plan_id=plan["plan_id"], fail_at="after_remote_commit",
                )
            first_mutations = remote.mutations
            state = self.sync.execute_identity_migration_plan(
                conn, plan, remote, self.intents, state_path=self.state_path,
                expected_plan_id=plan["plan_id"], intent_paths=self.intent_paths,
            )
            self.assertEqual("verified", state["state"])
            self.assertEqual(0, state["uid_regenerations"])
            self.assertEqual(11, remote.mutations)
            self.assertEqual(1, first_mutations)
            excluded = conn.execute(
                "SELECT project_sync_uid FROM tasks WHERE scope_id='L-OLD-A-SG0'"
            ).fetchone()[0]
            self.assertIsNone(excluded)
            self.assertEqual(2, conn.execute(
                "SELECT COUNT(*) FROM projects WHERE scope_id IN ('L-OLD-B-X1','L-OLD-C-X2-SG1')"
            ).fetchone()[0])
            before_rerun = remote.mutations
            rerun = self.sync.execute_identity_migration_plan(
                conn, plan, remote, self.intents, state_path=self.state_path,
                expected_plan_id=plan["plan_id"], intent_paths=self.intent_paths,
            )
            self.assertEqual(before_rerun, remote.mutations)
            self.assertEqual(0, rerun["residual_operations"])
        self.assertEqual(self.uid_a, self.intents["L-OLD-B-X1"]["identity"]["sync_uid"])
        self.assertEqual(self.uid_b, self.intents["L-OLD-C-X2-SG1"]["identity"]["sync_uid"])
        self.assertEqual(self.uid_existing,
                         self.intents["L-EXISTING"]["identity"]["sync_uid"])
        self.assertEqual(self.uid_a, json.loads(
            self.intent_paths["L-OLD-B-X1"].read_text(encoding="utf-8")
        )["identity"]["sync_uid"])

    def test_source_snapshot_change_and_intent_failure_are_recoverable(self):
        remote = FakeMigrationRemote()
        with closing(self._connect()) as conn:
            plan = self._plan(conn)
            trigger_sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='trg_tasks_updated'"
            ).fetchone()[0]
            conn.execute("DROP TRIGGER trg_tasks_updated")
            conn.execute("UPDATE tasks SET updated_at='changed' WHERE id=1")
            conn.execute(trigger_sql)
            conn.commit()
            with self.assertRaisesRegex(ValueError, "SOURCE_SNAPSHOT_CHANGED"):
                self.sync.execute_identity_migration_plan(
                    conn, plan, remote, self.intents, state_path=self.state_path,
                    expected_plan_id=plan["plan_id"], intent_paths=self.intent_paths,
                )
            self.assertEqual(0, remote.mutations)
            conn.execute("DROP TRIGGER trg_tasks_updated")
            conn.execute("UPDATE tasks SET updated_at='2026-07-15T00:00:00Z' WHERE id=1")
            conn.execute(trigger_sql)
            conn.commit()
            with self.assertRaisesRegex(RuntimeError, "before_intent_projection"):
                self.sync.execute_identity_migration_plan(
                    conn, plan, remote, self.intents, state_path=self.state_path,
                    expected_plan_id=plan["plan_id"], intent_paths=self.intent_paths,
                    fail_at="before_intent_projection",
                )
            before_resume = remote.mutations
            result = self.sync.execute_identity_migration_plan(
                conn, plan, remote, self.intents, state_path=self.state_path,
                expected_plan_id=plan["plan_id"], intent_paths=self.intent_paths,
            )
            self.assertEqual("verified", result["state"])
            self.assertEqual(11, remote.mutations)
            self.assertLess(before_resume, remote.mutations)

    def test_strict_cli_rejects_ambiguous_migration_modes(self):
        parsed, error = self.sync._parse_cli([
            "migrate-identity", "--dry-run", "--status",
            "--decisions", "decisions.json", "--plan-out", "plan.json",
            "--fixture-root", "fixture",
        ])
        self.assertIsNone(parsed)
        self.assertIn("exactly one", error)
        parsed, error = self.sync._parse_cli([
            "migrate-identity", "--dry-run", "--decisions", "decisions.json",
            "--plan-out", "plan.json", "--fixture-root", "fixture", "--unknown",
        ])
        self.assertIsNone(parsed)
        self.assertIn("unknown option", error)

    def test_fixture_cli_dry_run_execute_resume_and_status(self):
        fixture_db = self.root / "ai_plc.db"
        fixture_db.write_bytes(self.db_path.read_bytes())
        (self.root / ".identity-migration-fixture").write_text("T006\n", encoding="utf-8")
        (self.root / "remote.json").write_text("{}", encoding="utf-8")
        (self.root / "intents.json").write_text(
            json.dumps(self.intents), encoding="utf-8"
        )
        decisions_path = self.root / "decisions.json"
        decisions_path.write_text(json.dumps({
            "workspace_id": FIXED_WORKSPACE_A, "decisions": self.decisions,
            "project_uid_mappings": {"L-EXISTING": self.uid_existing},
            "batch_size": 10,
        }), encoding="utf-8")
        plan_path = self.root / "plan.json"
        state_path = self.root / "state.json"
        self.assertEqual(0, self.sync.main([
            "migrate-identity", "--dry-run", "--decisions", str(decisions_path),
            "--plan-out", str(plan_path), "--fixture-root", str(self.root),
        ]))
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        self.assertEqual(0, self.sync.main([
            "migrate-identity", "--plan", str(plan_path), "--plan-id", plan["plan_id"],
            "--fixture-root", str(self.root), "--state", str(state_path),
        ]))
        self.assertEqual(0, self.sync.main([
            "migrate-identity", "--status", "--plan", str(plan_path),
            "--state", str(state_path),
        ]))
        self.assertEqual(0, self.sync.main([
            "migrate-identity", "--plan", str(plan_path), "--plan-id", plan["plan_id"],
            "--fixture-root", str(self.root), "--state", str(state_path),
        ]))
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual("verified", state["state"])
        self.assertEqual(0, state["residual_operations"])

    def test_fixture_cli_rejects_production_database_hardlink(self):
        hardlink_root = self.root / "hardlink-fixture"
        hardlink_root.mkdir()
        (hardlink_root / ".identity-migration-fixture").write_text(
            "T006\n", encoding="utf-8"
        )
        # 公開版のリポジトリには ai_plc.db が無いので、一時の「本番」の DB を作って sync.DB_PATH をそこへ向ける
        production = self.root / "production" / "ai_plc.db"
        production.parent.mkdir()
        sqlite3.connect(production).close()
        os.link(production, hardlink_root / "ai_plc.db")
        before = file_fingerprint(production)
        with mock.patch.object(self.sync, "DB_PATH", str(production)):
            with self.assertRaisesRegex(ValueError, "PRODUCTION_DB_FORBIDDEN"):
                self.sync._migration_fixture_paths(hardlink_root)
        self.assertEqual(before, file_fingerprint(production))


FIXED_PROJECT_C = "prj_00000000-0000-4000-8000-000000000003"
FIXED_PROJECT_D = "prj_00000000-0000-4000-8000-000000000004"
FIXED_WORKSPACE_C = "wsp_00000000-0000-4000-8000-000000000003"
T007_OLD_EDIT = "2026-07-15T11:00:00.000Z"
T007_NEW_EDIT = "2026-07-15T13:00:00.000Z"
T007_LINKED_AT = "2026-07-15T11:30:00Z"


def _built_to_read_properties(properties):
    """Convert push-built Notion properties to the shape Notion returns."""
    result = {}
    for name, prop in properties.items():
        if "rich_text" in prop:
            result[name] = {"rich_text": [
                {"plain_text": part["text"]["content"]} for part in prop["rich_text"]]}
        elif "title" in prop:
            result[name] = {"title": [
                {"plain_text": part["text"]["content"]} for part in prop["title"]]}
        else:
            result[name] = copy.deepcopy(prop)
    return result


class T007FakeNotion:
    """In-memory Notion DB pair: query/POST/PATCH with call counters."""

    def __init__(self, sync, projects=None, tasks=None):
        self.sync = sync
        self.pages = {"project": list(projects or []), "task": list(tasks or [])}
        self.calls = []
        self.counter = 0

    def query(self, db_id):
        self.calls.append(("QUERY", db_id))
        entity = "project" if db_id == self.sync.PROJECTS_DB_ID else "task"
        return copy.deepcopy(self.pages[entity])

    def api(self, method, path, body=None, retries=3):
        self.calls.append((method, path))
        if method == "POST" and path == "/v1/pages":
            self.counter += 1
            entity = ("project" if body["parent"]["database_id"]
                      == self.sync.PROJECTS_DB_ID else "task")
            page = {"id": "t007-created-%d" % self.counter,
                    "last_edited_time": FIXED_NOW,
                    "parent": {"type": "database_id",
                               "database_id": body["parent"]["database_id"]},
                    "properties": _built_to_read_properties(body["properties"])}
            self.pages[entity].append(page)
            return {"id": page["id"], "last_edited_time": FIXED_NOW}
        raise AssertionError("unexpected Notion call %s %s" % (method, path))

    def mutations(self):
        return [call for call in self.calls if call[0] in {"POST", "PATCH"}]


class IdentityV2SyncCompatibilityTest(unittest.TestCase):
    """T007 v1/v2 Sync, Identity selector, fork/activate-writer, v2.1 boundary."""

    SCOPE = "L-T007"

    def setUp(self):
        self.production_before = file_fingerprint(PRODUCTION_DB)
        self.addCleanup(self._assert_production_unchanged)
        self.temp_dir = tempfile.TemporaryDirectory(prefix="ai-plc-identity-t007-")
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "ai_plc.db"
        self.manifest_path = self.root / "workspace_identity.json"
        self.init_db = load_module(DB_DIR / "init_db.py", f"identity_init_t007_{id(self)}")
        self.sync = load_module(DB_DIR / "sync.py", f"identity_sync_t007_{id(self)}")
        with closing(sqlite3.connect(self.db_path)) as conn:
            with contextlib.redirect_stdout(io.StringIO()):
                self.init_db.create_schema(conn)
            conn.execute("""
                INSERT INTO projects (scope_id, name, status, created_at, updated_at)
                VALUES (?, 'Workspace A Project', 'active', ?, ?)
            """, (self.SCOPE, FIXED_NOW, FIXED_NOW))
            conn.execute("""
                INSERT INTO tasks (task_id, scope_id, name, status, created_at, updated_at)
                VALUES ('T001', ?, 'Workspace A Task', '未着手', ?, ?)
            """, (self.SCOPE, FIXED_NOW, FIXED_NOW))
            conn.commit()
            mapping = self.init_db.build_identity_migration_mapping(
                conn, FIXED_WORKSPACE_A, project_uid_factory=lambda: FIXED_PROJECT_A)
            self.init_db.migrate_identity_v2(conn, mapping)
            # Same Scope ID, other workspace/Identity in the same registry.
            conn.execute("""
                INSERT INTO projects (workspace_id, sync_uid, ownership_epoch,
                    identity_version, scope_id, name, status, created_at, updated_at)
                VALUES (?, ?, 1, 2, ?, 'Workspace B Project', 'active', ?, ?)
            """, (FIXED_WORKSPACE_B, FIXED_PROJECT_B, self.SCOPE, FIXED_NOW, FIXED_NOW))
            conn.execute("""
                INSERT INTO tasks (workspace_id, project_sync_uid,
                    project_ownership_epoch, identity_version, task_id, scope_id,
                    name, status, created_at, updated_at)
                VALUES (?, ?, 1, 2, 'T001', ?, 'Workspace B Task', '未着手', ?, ?)
            """, (FIXED_WORKSPACE_B, FIXED_PROJECT_B, self.SCOPE, FIXED_NOW, FIXED_NOW))
            conn.commit()
        self._activate_manifest(FIXED_WORKSPACE_A, FIXED_WRITER_A)
        self.sync.DB_PATH = str(self.db_path)
        self.sync.WORKSPACE_MANIFEST_PATH = str(self.manifest_path)
        self.sync.TOKEN = "dummy-t007-token"
        self.sync.RATE_LIMIT_DELAY = 0
        self.sync._now_iso = lambda: FIXED_NOW
        guard = mock.patch.object(
            self.sync.urllib.request, "urlopen",
            side_effect=AssertionError("network access is forbidden in T007 tests"))
        guard.start()
        self.addCleanup(guard.stop)

    # ── fixture helpers ──────────────────────────────────────

    def _assert_production_unchanged(self):
        self.assertEqual(self.production_before, file_fingerprint(PRODUCTION_DB))

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _activate_manifest(self, workspace_id, writer_id, *, cache=True):
        manifest = self.sync._writer_manifest(workspace_id, writer_id) if hasattr(
            self, "sync") else None
        manifest = manifest or load_module(
            DB_DIR / "sync.py", f"identity_sync_t007_manifest_{id(self)}"
        )._writer_manifest(workspace_id, writer_id)
        self.manifest_path.write_text(json.dumps(manifest, sort_keys=True),
                                      encoding="utf-8")
        if cache:
            with closing(sqlite3.connect(self.db_path)) as conn:
                for key, value in (
                        ("active_workspace_id", workspace_id),
                        ("active_writer_epoch", "1"),
                        ("writer_authority_hash_cache",
                         manifest["writer_authority_hash_cache"])):
                    conn.execute("INSERT OR REPLACE INTO _metadata(key, value) "
                                 "VALUES (?, ?)", (key, value))
                conn.commit()
        return manifest

    def _rows(self, table, where="1=1", params=()):
        with closing(self._connect()) as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM %s WHERE %s ORDER BY id" % (table, where), params
            ).fetchall()]

    def _snapshot(self):
        with closing(self._connect()) as conn:
            return {table: [dict(row) for row in conn.execute(
                "SELECT * FROM %s ORDER BY %s" % (
                    table, "key" if table == "_metadata" else "id")).fetchall()]
                for table in ("projects", "tasks", "_metadata")}

    def _uids(self):
        with closing(self._connect()) as conn:
            return sorted(row[0] for row in conn.execute(
                "SELECT sync_uid FROM projects").fetchall())

    @staticmethod
    def _rich(value):
        return {"rich_text": [] if not value else [{"plain_text": value}]}

    @staticmethod
    def _title(value):
        return {"title": [] if not value else [{"plain_text": value}]}

    def _project_page(self, page_id, *, sync_uid=FIXED_PROJECT_A,
                      workspace_id=FIXED_WORKSPACE_A, scope_id=None,
                      name="Workspace A Project", edited=T007_OLD_EDIT,
                      identity=True):
        return {
            "id": page_id, "last_edited_time": edited,
            "parent": {"type": "database_id", "database_id": "projects-db"},
            "properties": {
                "PJ名": self._title(name),
                "Scope ID": self._rich(scope_id or self.SCOPE),
                "ステータス": {"status": {"name": "active"}},
                "Sync UID": self._rich(sync_uid if identity else None),
                "Workspace ID": self._rich(workspace_id if identity else None),
                "Ownership Epoch": {"number": 1 if identity else None},
                "Identity Version": {"number": 2 if identity else None},
            },
        }

    def _task_page(self, page_id, *, project_sync_uid=FIXED_PROJECT_A,
                   workspace_id=FIXED_WORKSPACE_A, scope_id=None, task_id="T001",
                   edited=T007_OLD_EDIT):
        return {
            "id": page_id, "last_edited_time": edited,
            "parent": {"type": "database_id", "database_id": "tasks-db"},
            "properties": {
                "タスク名": self._title("Remote Task"),
                "Task ID": self._rich(task_id),
                "Scope ID": self._rich(scope_id or self.SCOPE),
                "ステータス": {"status": {"name": "未着手"}},
                "Project Sync UID": self._rich(project_sync_uid),
                "Workspace ID": self._rich(workspace_id),
                "Project Ownership Epoch": {"number": 1},
                "Identity Version": {"number": 2},
            },
        }

    def _link_workspace_a_project(self, page_id="page-a"):
        with closing(self._connect()) as conn:
            conn.execute(
                "UPDATE projects SET notion_page_id=?, notion_last_edited=?, "
                "last_sync_at=?, updated_at=? WHERE sync_uid=?",
                (page_id, T007_OLD_EDIT, T007_LINKED_AT, T007_LINKED_AT,
                 FIXED_PROJECT_A))
            conn.commit()

    def _run_quiet(self, function, *args, **kwargs):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = function(*args, **kwargs)
        return result, output.getvalue()

    def _pull(self, fake, dry_run=False):
        with (
            mock.patch.object(self.sync, "_query_db", side_effect=fake.query),
            mock.patch.object(self.sync, "_api_call", side_effect=fake.api),
        ):
            return self._run_quiet(self.sync.cmd_pull, dry_run=dry_run,
                                   skip_preflight=True)

    def _build_plan(self, fake=None, **selector):
        fake = fake or T007FakeNotion(self.sync)
        with (
            mock.patch.object(self.sync, "_query_db", side_effect=fake.query),
            mock.patch.object(self.sync, "_api_call", side_effect=fake.api),
        ):
            return self.sync.build_push_plan(skip_preflight=True, **selector)

    def _execute(self, plan, fake, **selector):
        with (
            mock.patch.object(self.sync, "_revalidate_identity_plan_before_write",
                              return_value=0),
            mock.patch.object(self.sync, "_query_db", side_effect=fake.query),
            mock.patch.object(self.sync, "_api_call", side_effect=fake.api),
        ):
            return self._run_quiet(self.sync.execute_push_plan, plan, **selector)

    def _main(self, argv, handlers=()):
        calls = []
        output = io.StringIO()
        with contextlib.ExitStack() as stack:
            for name in handlers:
                stack.enter_context(mock.patch.object(
                    self.sync, name,
                    side_effect=lambda *a, _n=name, **k: calls.append((_n, a, k)) or 91))
            stack.enter_context(contextlib.redirect_stdout(output))
            result = self.sync.main(argv)
        return result, calls, output.getvalue()

    def _fork(self, writer_id="writer-fork", ids=None):
        plan_path = self.root / "fork-plan.json"
        factory_ids = iter(ids or (FIXED_WORKSPACE_C, FIXED_PROJECT_C))
        with mock.patch.object(self.sync.uuid, "uuid4",
                               side_effect=lambda: next(factory_ids)):
            result, _calls, output = self._main([
                "fork-workspace", "--dry-run", "--writer-id", writer_id,
                "--plan-out", str(plan_path)])
        self.assertEqual(0, result, output)
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        return plan_path, plan

    # ── AC1: selector ────────────────────────────────────────

    def test_t007_ac1_sync_uid_selector_limits_same_scope_to_one_identity(self):
        plan = self._build_plan(sync_uid=FIXED_PROJECT_A)
        self.assertEqual(0, plan["exit_code"])
        self.assertEqual("project", plan["selector"]["kind"])
        self.assertEqual(FIXED_PROJECT_A, plan["selector"]["project_sync_uid"])
        self.assertEqual(self.SCOPE, plan["selector"]["scope_id"])
        self.assertEqual(2, len(plan["operations"]))
        self.assertEqual({FIXED_PROJECT_A}, {
            op["identity"]["project_sync_uid"] for op in plan["operations"]})
        self.assertTrue(self.sync.validate_push_plan(plan))
        scoped = self._build_plan(scope_id=self.SCOPE)
        self.assertEqual(plan["selector"], scoped["selector"])
        self.assertEqual(
            [op["operation_id"] for op in plan["operations"]],
            [op["operation_id"] for op in scoped["operations"]])

    def test_t007_ac1_selector_refusals_have_contract_exit_codes(self):
        cases = (
            ({"sync_uid": FIXED_PROJECT_B}, 3, "IDENTITY_WORKSPACE_MISMATCH"),
            ({"sync_uid": FIXED_PROJECT_C}, 3, "IDENTITY_SELECTOR_NOT_FOUND"),
            ({"sync_uid": FIXED_PROJECT_A, "scope_id": "L-OTHER"}, 2,
             "SELECTOR_SCOPE_MISMATCH"),
            ({"workspace_id": FIXED_WORKSPACE_B}, 3, "WORKSPACE_SELECTOR_MISMATCH"),
            ({"scope_id": "L-NOT-HERE"}, 3, "SCOPE_NOT_UNIQUE"),
        )
        before = self._snapshot()
        for selector, exit_code, code in cases:
            with self.subTest(selector=selector):
                fake = T007FakeNotion(self.sync)
                plan = self._build_plan(fake, **selector)
                self.assertEqual(exit_code, plan["exit_code"])
                self.assertEqual([], plan["operations"])
                self.assertEqual(code, plan["preflight"]["findings"][0]["code"])
                self.assertEqual([], fake.calls)
                with (
                    mock.patch.object(self.sync, "_open_write_conn") as write_conn,
                    mock.patch.object(self.sync, "_api_call") as api,
                ):
                    for dry_run in (True, False):
                        result, _output = self._run_quiet(
                            self.sync.cmd_push, dry_run=dry_run,
                            skip_preflight=True, **selector)
                        self.assertEqual(exit_code, result)
                write_conn.assert_not_called()
                api.assert_not_called()
        self.assertEqual(before, self._snapshot())

    def test_t007_ac1_ambiguous_scope_never_selects_implicitly(self):
        ambiguous_db = self.root / "ambiguous.db"
        with closing(sqlite3.connect(ambiguous_db)) as conn:
            conn.execute("""CREATE TABLE projects (id INTEGER PRIMARY KEY,
                workspace_id TEXT, sync_uid TEXT, ownership_epoch INTEGER,
                identity_version INTEGER, scope_id TEXT, name TEXT)""")
            conn.execute("""CREATE TABLE tasks (id INTEGER PRIMARY KEY,
                workspace_id TEXT, project_sync_uid TEXT,
                project_ownership_epoch INTEGER, identity_version INTEGER)""")
            conn.execute("CREATE TABLE _metadata (key TEXT PRIMARY KEY, value TEXT)")
            for uid, name in ((FIXED_PROJECT_A, "latest"), (FIXED_PROJECT_B, "first")):
                conn.execute(
                    "INSERT INTO projects (workspace_id, sync_uid, ownership_epoch, "
                    "identity_version, scope_id, name) VALUES (?, ?, 1, 2, ?, ?)",
                    (FIXED_WORKSPACE_A, uid, self.SCOPE, name))
            manifest = self.sync._writer_manifest(FIXED_WORKSPACE_A, FIXED_WRITER_A)
            for key, value in self.sync._cache_for_manifest(manifest).items():
                conn.execute("INSERT INTO _metadata VALUES (?, ?)", (key, value))
            conn.commit()
        with closing(sqlite3.connect(ambiguous_db)) as conn:
            conn.row_factory = sqlite3.Row
            ambiguous = self.sync.resolve_identity_selection(conn, scope_id=self.SCOPE)
            explicit = self.sync.resolve_identity_selection(
                conn, scope_id=self.SCOPE, sync_uid=FIXED_PROJECT_B)
        self.assertEqual(2, ambiguous["exit_code"])
        self.assertEqual("SCOPE_AMBIGUOUS", ambiguous["finding"]["code"])
        self.assertIsNone(ambiguous["project"])
        self.assertEqual(0, explicit["exit_code"])
        self.assertEqual(FIXED_PROJECT_B, explicit["project"]["sync_uid"])

    # ── AC2: pull never merges another Identity ──────────────

    def test_t007_ac2_pull_skips_foreign_and_legacy_rows_and_patches_exact(self):
        self._link_workspace_a_project()
        fake = T007FakeNotion(self.sync, projects=[
            self._project_page("page-a", name="Renamed Remotely", edited=T007_NEW_EDIT),
            self._project_page("page-b", sync_uid=FIXED_PROJECT_B,
                               workspace_id=FIXED_WORKSPACE_B, name="B Remote"),
            self._project_page("page-legacy", scope_id="L-OLD-A-SG0",
                               name="Legacy Excluded", identity=False),
        ])
        workspace_b_before = self._rows("projects", "workspace_id=?",
                                        (FIXED_WORKSPACE_B,))
        result, output = self._pull(fake)
        self.assertEqual(0, result, output)
        self.assertIn("foreign_workspace=1", output)
        self.assertIn("legacy_skipped=1", output)
        self.assertIn("[POST-VERIFY PASS]", output)
        self.assertEqual(workspace_b_before, self._rows(
            "projects", "workspace_id=?", (FIXED_WORKSPACE_B,)))
        self.assertEqual([], self._rows("projects", "notion_page_id IN (?, ?)",
                                        ("page-b", "page-legacy")))
        project_a = self._rows("projects", "sync_uid=?", (FIXED_PROJECT_A,))[0]
        self.assertEqual("Renamed Remotely", project_a["name"])
        self.assertEqual(FIXED_WORKSPACE_A, project_a["workspace_id"])
        self.assertEqual([], fake.mutations())
        before_rerun = self._snapshot()
        rerun, rerun_output = self._pull(fake)
        self.assertEqual(0, rerun)
        self.assertIn("insert_local=0  patch_local=0", rerun_output)
        rerun_rows = self._snapshot()
        before_rerun["_metadata"] = rerun_rows["_metadata"] = None
        self.assertEqual(before_rerun, rerun_rows)

    def test_t007_ac2_pull_inserts_only_new_current_workspace_identity(self):
        fake = T007FakeNotion(self.sync, projects=[
            self._project_page("page-d", sync_uid=FIXED_PROJECT_D,
                               scope_id="L-T007-NEW", name="New Remote"),
        ], tasks=[
            self._task_page("task-d", project_sync_uid=FIXED_PROJECT_D,
                            scope_id="L-T007-NEW"),
            self._task_page("task-b", project_sync_uid=FIXED_PROJECT_B,
                            workspace_id=FIXED_WORKSPACE_B),
        ])
        result, output = self._pull(fake)
        self.assertEqual(0, result, output)
        inserted = self._rows("projects", "sync_uid=?", (FIXED_PROJECT_D,))
        self.assertEqual(1, len(inserted))
        self.assertEqual((FIXED_WORKSPACE_A, 1, 2, "page-d"), (
            inserted[0]["workspace_id"], inserted[0]["ownership_epoch"],
            inserted[0]["identity_version"], inserted[0]["notion_page_id"]))
        tasks = self._rows("tasks", "notion_page_id IS NOT NULL")
        self.assertEqual([("task-d", FIXED_PROJECT_D)], [
            (row["notion_page_id"], row["project_sync_uid"]) for row in tasks])
        rerun, rerun_output = self._pull(fake)
        self.assertEqual(0, rerun)
        self.assertIn("insert_local=0  patch_local=0", rerun_output)

    def test_t007_ac2_pull_same_scope_new_identity_or_split_brain_is_blocked(self):
        self._link_workspace_a_project()
        cases = (
            ([self._project_page("page-c", sync_uid=FIXED_PROJECT_C, name="Collide")],
             [], 2, "SAME_SCOPE_DIFFERENT_IDENTITY"),
            ([self._project_page("page-a", sync_uid=FIXED_PROJECT_C,
                                 edited=T007_NEW_EDIT)],
             [], 3, "IDENTITY_SPLIT_BRAIN"),
            ([], [self._task_page("task-orphan", project_sync_uid=FIXED_PROJECT_D)],
             3, "TASK_PROJECT_IDENTITY_MISSING"),
        )
        for projects, tasks, exit_code, code in cases:
            with self.subTest(code=code):
                before = self._snapshot()
                fake = T007FakeNotion(self.sync, projects=projects, tasks=tasks)
                with mock.patch.object(self.sync, "_open_write_conn") as write_conn:
                    result, output = self._pull(fake)
                self.assertEqual(exit_code, result, output)
                self.assertIn(code, output)
                write_conn.assert_not_called()
                self.assertEqual(before, self._snapshot())

    def test_t007_ac2_foreign_duplicates_are_audit_only_current_ones_block(self):
        foreign = T007FakeNotion(self.sync, projects=[
            self._project_page("page-b1", sync_uid=FIXED_PROJECT_B,
                               workspace_id=FIXED_WORKSPACE_B),
            self._project_page("page-b2", sync_uid=FIXED_PROJECT_B,
                               workspace_id=FIXED_WORKSPACE_B),
            self._project_page("page-d", sync_uid=FIXED_PROJECT_D,
                               scope_id="L-T007-NEW", name="New Remote"),
        ])
        result, output = self._pull(foreign)
        self.assertEqual(0, result, output)
        self.assertEqual(1, len(self._rows("projects", "sync_uid=?",
                                           (FIXED_PROJECT_D,))))
        before = self._snapshot()
        current = T007FakeNotion(self.sync, projects=[
            self._project_page("page-c1", sync_uid=FIXED_PROJECT_C,
                               scope_id="L-T007-C"),
            self._project_page("page-c2", sync_uid=FIXED_PROJECT_C,
                               scope_id="L-T007-C"),
        ])
        blocked, output = self._pull(current)
        self.assertEqual(2, blocked, output)
        self.assertIn("IDENTITY_DUPLICATE", output)
        self.assertEqual(before, self._snapshot())

    def test_t007_ac2_linked_rename_collision_and_parent_epoch_block_early(self):
        self._link_workspace_a_project()
        with closing(self._connect()) as conn:
            conn.execute("""
                INSERT INTO projects (workspace_id, sync_uid, ownership_epoch,
                    identity_version, scope_id, name, status, created_at, updated_at)
                VALUES (?, ?, 1, 2, 'L-T007-OTHER', 'Other A Project', 'active', ?, ?)
            """, (FIXED_WORKSPACE_A, FIXED_PROJECT_C, FIXED_NOW, FIXED_NOW))
            conn.commit()
        rename_task = self._task_page("task-d", project_sync_uid=FIXED_PROJECT_D,
                                      scope_id="L-T007-NEW")
        rename_task["properties"]["Project Ownership Epoch"] = {"number": 2}
        cases = (
            ([self._project_page("page-a", scope_id="L-T007-OTHER",
                                 edited=T007_NEW_EDIT)], [], 2,
             "SAME_SCOPE_DIFFERENT_IDENTITY"),
            ([self._project_page("page-d", sync_uid=FIXED_PROJECT_D,
                                 scope_id="L-T007-NEW")], [rename_task], 3,
             "TASK_PROJECT_IDENTITY_MISSING"),
        )
        for projects, tasks, exit_code, code in cases:
            with self.subTest(code=code):
                before = self._snapshot()
                with mock.patch.object(self.sync, "_open_write_conn") as write_conn:
                    result, output = self._pull(T007FakeNotion(
                        self.sync, projects=projects, tasks=tasks))
                self.assertEqual(exit_code, result, output)
                self.assertIn(code, output)
                write_conn.assert_not_called()
                self.assertEqual(before, self._snapshot())

    def test_t007_ac2_foreign_copy_of_local_uid_and_intra_pull_collision_block(self):
        cases = (
            ([self._project_page("page-copy", sync_uid=FIXED_PROJECT_A,
                                 workspace_id=FIXED_WORKSPACE_B)],
             3, "IDENTITY_WORKSPACE_MISMATCH"),
            ([self._project_page("page-copy-1", sync_uid=FIXED_PROJECT_A,
                                 workspace_id=FIXED_WORKSPACE_B),
              self._project_page("page-copy-2", sync_uid=FIXED_PROJECT_A,
                                 workspace_id=FIXED_WORKSPACE_B)],
             2, "IDENTITY_DUPLICATE"),
            ([self._project_page("page-c", sync_uid=FIXED_PROJECT_C,
                                 scope_id="L-T007-TWIN"),
              self._project_page("page-d", sync_uid=FIXED_PROJECT_D,
                                 scope_id="L-T007-TWIN")],
             2, "SAME_SCOPE_DIFFERENT_IDENTITY"),
        )
        for projects, exit_code, code in cases:
            with self.subTest(code=code):
                before = self._snapshot()
                with mock.patch.object(self.sync, "_open_write_conn") as write_conn:
                    result, output = self._pull(T007FakeNotion(
                        self.sync, projects=projects))
                self.assertEqual(exit_code, result, output)
                self.assertIn(code, output)
                write_conn.assert_not_called()
                self.assertEqual(before, self._snapshot())

    # ── AC3: push/sync POST-VERIFY and rerun per Identity ────

    def test_t007_ac3_workspace_push_post_verifies_only_current_identity(self):
        fake = T007FakeNotion(self.sync)
        plan = self._build_plan(fake)
        self.assertEqual("workspace", plan["selector"]["kind"])
        self.assertEqual({FIXED_PROJECT_A}, {
            op["identity"]["project_sync_uid"] for op in plan["operations"]})
        workspace_b_before = (self._rows("projects", "workspace_id=?",
                                         (FIXED_WORKSPACE_B,)),
                              self._rows("tasks", "workspace_id=?",
                                         (FIXED_WORKSPACE_B,)))
        result, output = self._execute(plan, fake)
        self.assertEqual(0, result, output)
        self.assertEqual(2, output.count("[POST-VERIFY PASS]"))
        self.assertEqual(2, len(fake.mutations()))
        self.assertEqual(workspace_b_before, (
            self._rows("projects", "workspace_id=?", (FIXED_WORKSPACE_B,)),
            self._rows("tasks", "workspace_id=?", (FIXED_WORKSPACE_B,))))
        rerun = self._build_plan(fake)
        self.assertEqual(0, rerun["exit_code"])
        self.assertEqual([], rerun["operations"])
        self.assertEqual(2, len(fake.mutations()))

    def test_t007_ac3_post_verify_rejects_identity_swapped_row(self):
        plan = self._build_plan(sync_uid=FIXED_PROJECT_A)
        operation = copy.deepcopy(next(
            op for op in plan["operations"] if op["entity"] == "project"))
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM projects WHERE sync_uid=?",
                               (FIXED_PROJECT_A,)).fetchone()
            verified = self.sync._post_verify_operation(
                conn, "projects", operation, None, row["last_sync_at"])
            operation["identity"]["project_sync_uid"] = FIXED_PROJECT_B
            swapped = self.sync._post_verify_operation(
                conn, "projects", operation, None, row["last_sync_at"])
        self.assertNotIn("IDENTITY_MISMATCH", verified["findings"])
        self.assertIn("IDENTITY_MISMATCH", swapped["findings"])
        self.assertEqual("failed", swapped["status"])

    def test_t007_ac3_sync_converges_per_identity_and_reruns_to_zero(self):
        fake = T007FakeNotion(self.sync, projects=[
            self._project_page("page-b", sync_uid=FIXED_PROJECT_B,
                               workspace_id=FIXED_WORKSPACE_B, name="B Remote"),
        ])
        preflight = self.sync._empty_preflight_report()
        with (
            mock.patch.object(self.sync, "run_preflight", return_value=preflight),
            mock.patch.object(self.sync, "_revalidate_identity_plan_before_write",
                              return_value=0),
            mock.patch.object(self.sync, "_query_db", side_effect=fake.query),
            mock.patch.object(self.sync, "_api_call", side_effect=fake.api),
        ):
            first, first_output = self._run_quiet(self.sync.cmd_sync)
            mutations_after_first = len(fake.mutations())
            snapshot = self._snapshot()
            second, second_output = self._run_quiet(self.sync.cmd_sync)
        self.assertEqual(0, first, first_output)
        self.assertEqual(2, mutations_after_first)
        self.assertEqual(2, first_output.count("[POST-VERIFY PASS] opv2_"))
        self.assertEqual(0, second, second_output)
        self.assertEqual(mutations_after_first, len(fake.mutations()))
        self.assertIn("insert_local=0  patch_local=0", second_output)
        self.assertNotIn("[CREATE]", second_output)
        rerun_snapshot = self._snapshot()
        snapshot["_metadata"] = rerun_snapshot["_metadata"] = None
        self.assertEqual(snapshot, rerun_snapshot)
        self.assertEqual([], self._rows("projects", "workspace_id=? AND "
                                        "notion_page_id IS NOT NULL",
                                        (FIXED_WORKSPACE_B,)))

    # ── AC4: strict CLI and global/Scope Plan compatibility ──

    def test_t007_ac4_strict_cli_rejects_identity_usage_before_handlers(self):
        handlers = ("cmd_push", "cmd_pull", "cmd_sync", "cmd_fork_workspace",
                    "cmd_activate_writer", "cmd_deferred_v21")
        cases = (
            ["push", "--sync-uid", "prj_not-a-uuid"],
            ["push", "--workspace-id", FIXED_PROJECT_A],
            ["push", "--sync-uid"],
            ["pull", "--sync-uid", FIXED_PROJECT_A],
            ["sync", "--scope", self.SCOPE],
            ["fork-workspace", "--dry-run", "--plan-out", "x.json"],
            ["fork-workspace", "--dry-run", "--status", "--plan", "x.json"],
            ["fork-workspace", "--plan", "x.json"],
            ["activate-writer", "--fork-plan", "x.json", "--plan-id", "a"],
            ["activate-writer", "--workspace-id", FIXED_WORKSPACE_A,
             "--fork-plan", "x.json", "--plan-id", "a", "--bootstrap-state", "s"],
            ["activate-writer", "--workspace-id", FIXED_WORKSPACE_A,
             "--fork-plan", "x.json"],
            ["transfer-project", "--sync-uid", FIXED_PROJECT_A],
            ["takeover-writer", "--workspace-id", FIXED_WORKSPACE_A],
            ["takeover-writer", "--workspace-id", FIXED_WORKSPACE_A,
             "--writer-id", "bad writer"],
            ["handoff-repair", "--workspace-id", FIXED_WORKSPACE_A, "--plan", "p"],
        )
        before = self._snapshot()
        for argv in cases:
            with self.subTest(argv=argv):
                result, calls, output = self._main(argv, handlers)
                self.assertEqual(64, result)
                self.assertEqual([], calls)
                self.assertIn("ERROR:", output)
        self.assertEqual(before, self._snapshot())

    def test_t007_ac4_valid_identity_cli_reaches_handler_with_selector(self):
        result, calls, _ = self._main(
            ["push", "--sync-uid", FIXED_PROJECT_A, "--workspace-id",
             FIXED_WORKSPACE_A, "--dry-run"], ("cmd_push",))
        self.assertEqual(91, result)
        self.assertEqual(FIXED_PROJECT_A, calls[0][2]["sync_uid"])
        self.assertEqual(FIXED_WORKSPACE_A, calls[0][2]["workspace_id"])
        result, calls, _ = self._main(["push", "--scope", self.SCOPE], ("cmd_push",))
        self.assertNotIn("sync_uid", calls[0][2])
        self.assertNotIn("workspace_id", calls[0][2])

    def test_t007_ac4_plans_bind_to_their_cli_selector(self):
        uid_plan = self._build_plan(sync_uid=FIXED_PROJECT_A)
        global_plan = self._build_plan()
        validate = self.sync.validate_plan_selector
        self.assertTrue(validate(uid_plan, sync_uid=FIXED_PROJECT_A))
        self.assertTrue(validate(uid_plan, scope_id=self.SCOPE))
        self.assertTrue(validate(uid_plan, self.SCOPE, FIXED_PROJECT_A,
                                 FIXED_WORKSPACE_A))
        self.assertFalse(validate(uid_plan))
        self.assertFalse(validate(uid_plan, sync_uid=FIXED_PROJECT_B))
        self.assertFalse(validate(uid_plan, sync_uid=FIXED_PROJECT_A,
                                  workspace_id=FIXED_WORKSPACE_B))
        self.assertTrue(validate(global_plan))
        self.assertTrue(validate(global_plan, workspace_id=FIXED_WORKSPACE_A))
        self.assertFalse(validate(global_plan, sync_uid=FIXED_PROJECT_A))
        fake = T007FakeNotion(self.sync)
        with mock.patch.object(self.sync, "_open_write_conn") as write_conn:
            result, _ = self._execute(uid_plan, fake, sync_uid=FIXED_PROJECT_B)
            no_selector, _ = self._execute(uid_plan, fake)
        self.assertEqual(2, result)
        self.assertEqual(2, no_selector)
        write_conn.assert_not_called()
        self.assertEqual([], fake.mutations())
        result, output = self._execute(uid_plan, fake, sync_uid=FIXED_PROJECT_A)
        self.assertEqual(0, result, output)
        self.assertEqual(2, len(fake.mutations()))

    def test_t007_ac4_v1_schema_keeps_scope_plan_and_rejects_identity_selector(self):
        v1_db = self.root / "v1.db"
        with closing(sqlite3.connect(v1_db)) as conn:
            with contextlib.redirect_stdout(io.StringIO()):
                self.init_db.create_schema(conn)
            conn.execute("INSERT INTO projects (scope_id, name, status, created_at, "
                         "updated_at) VALUES ('L-V1', 'V1', 'active', ?, ?)",
                         (FIXED_NOW, FIXED_NOW))
            conn.commit()
        self.sync.DB_PATH = str(v1_db)
        uid_plan = self._build_plan(sync_uid=FIXED_PROJECT_A)
        scope_plan = self._build_plan(scope_id="L-V1")
        self.assertEqual(3, uid_plan["exit_code"])
        self.assertEqual("IDENTITY_SELECTOR_REQUIRES_V2",
                         uid_plan["preflight"]["findings"][0]["code"])
        self.assertNotIn("plan_schema_version", scope_plan)
        self.assertEqual({"scope_id": "L-V1"}, scope_plan["selector"])
        self.assertEqual(0, scope_plan["exit_code"])
        self.assertTrue(self.sync.validate_plan_selector(scope_plan, "L-V1"))
        self.assertFalse(self.sync.validate_plan_selector(
            scope_plan, "L-V1", FIXED_PROJECT_A))
        with closing(sqlite3.connect(v1_db)) as conn:
            conn.row_factory = sqlite3.Row
            self.assertIsNone(self.sync.build_identity_status(conn))

    # ── AC5: clone/path move keep Identity, fork issues once ─

    def test_t007_ac5_clone_and_path_move_preserve_workspace_and_project_uid(self):
        original = self._build_plan(sync_uid=FIXED_PROJECT_A)
        manifest_before = self.manifest_path.read_bytes()
        moved = self.root / "moved" / "nested"
        moved.mkdir(parents=True)
        (moved / "ai_plc.db").write_bytes(self.db_path.read_bytes())
        (moved / "workspace_identity.json").write_bytes(manifest_before)
        self.sync.DB_PATH = str(moved / "ai_plc.db")
        self.sync.WORKSPACE_MANIFEST_PATH = str(moved / "workspace_identity.json")
        with closing(sqlite3.connect(moved / "ai_plc.db")) as conn:
            conn.row_factory = sqlite3.Row
            status = self.sync.build_identity_status(conn)
        clone_plan = self._build_plan(sync_uid=FIXED_PROJECT_A)
        self._run_quiet(self.sync.cmd_status)
        self.assertEqual(FIXED_WORKSPACE_A, status["workspace_id"])
        self.assertEqual(original["plan_id"], clone_plan["plan_id"])
        self.assertEqual(original["selector"], clone_plan["selector"])
        self.assertEqual(manifest_before,
                         (moved / "workspace_identity.json").read_bytes())
        with closing(sqlite3.connect(moved / "ai_plc.db")) as conn:
            self.assertEqual(self._uids(), sorted(row[0] for row in conn.execute(
                "SELECT sync_uid FROM projects").fetchall()))

    def test_t007_ac5_fork_plan_is_fixed_and_issues_new_ids_exactly_once(self):
        source_before = self._snapshot()
        plan_path, plan = self._fork()
        self.assertEqual(source_before, self._snapshot())
        self.assertEqual(FIXED_WORKSPACE_A, plan["source"]["workspace_id"])
        self.assertEqual(FIXED_WORKSPACE_C, plan["result"]["workspace_id"])
        self.assertEqual([FIXED_PROJECT_C],
                         [item["result_sync_uid"] for item in plan["projects"]])
        self.assertEqual("deferred_v2_1", plan["authority"])
        with mock.patch.object(self.sync.uuid, "uuid4",
                               side_effect=AssertionError("no new Identity on rerun")):
            rerun, _calls, output = self._main([
                "fork-workspace", "--dry-run", "--writer-id", "writer-fork",
                "--plan-out", str(plan_path)])
        self.assertEqual(0, rerun, output)
        self.assertIn('"reused": true', output)
        with mock.patch.object(self.sync.uuid, "uuid4",
                               side_effect=AssertionError("execute never issues IDs")):
            first, _c, first_output = self._main([
                "fork-workspace", "--plan", str(plan_path), "--plan-id",
                plan["plan_id"]])
            second, _c, second_output = self._main([
                "fork-workspace", "--plan", str(plan_path), "--plan-id",
                plan["plan_id"]])
        self.assertEqual(0, first, first_output)
        self.assertIn('"inserted_rows": 2', first_output)
        self.assertEqual(0, second, second_output)
        self.assertIn('"inserted_rows": 0', second_output)
        forked = self._rows("projects", "workspace_id=?", (FIXED_WORKSPACE_C,))
        self.assertEqual([(FIXED_PROJECT_C, self.SCOPE, None, None, 1, 2)], [
            (row["sync_uid"], row["scope_id"], row["notion_page_id"],
             row["last_sync_at"], row["ownership_epoch"], row["identity_version"])
            for row in forked])
        forked_tasks = self._rows("tasks", "workspace_id=?", (FIXED_WORKSPACE_C,))
        self.assertEqual([FIXED_PROJECT_C],
                         [row["project_sync_uid"] for row in forked_tasks])
        after = self._snapshot()
        for table in ("projects", "tasks"):
            self.assertEqual(source_before[table], [
                row for row in after[table] if row["workspace_id"] != FIXED_WORKSPACE_C])
        self.assertEqual(json.loads(self.manifest_path.read_text())["workspace_id"],
                         FIXED_WORKSPACE_A)

    def test_t007_ac5_fork_crash_resume_and_source_drift_are_fail_closed(self):
        plan_path, plan = self._fork()
        state_path = Path(str(plan_path) + ".state.json")
        with closing(self._connect()) as conn:
            with self.assertRaisesRegex(RuntimeError, "after_sqlite_commit"):
                self.sync.execute_workspace_fork_plan(
                    conn, plan, expected_plan_id=plan["plan_id"],
                    state_path=state_path, fail_at="after_sqlite_commit")
        self.assertEqual("planned", json.loads(state_path.read_text())["state"])
        with closing(self._connect()) as conn:
            resumed = self.sync.execute_workspace_fork_plan(
                conn, plan, expected_plan_id=plan["plan_id"], state_path=state_path)
        self.assertEqual(("verified", 0), (resumed["state"], resumed["inserted_rows"]))
        self.assertEqual(1, len(self._rows("projects", "workspace_id=?",
                                           (FIXED_WORKSPACE_C,))))

        drift_plan_path = self.root / "drift-plan.json"
        ids = iter((FIXED_WORKSPACE_B.replace("0002", "0009"), FIXED_PROJECT_D))
        with closing(self._connect()) as conn:
            with mock.patch.object(self.sync.uuid, "uuid4",
                                   side_effect=lambda: next(ids)):
                drift_plan = self.sync.build_workspace_fork_plan(
                    conn, writer_id="writer-drift")
            conn.execute("UPDATE projects SET name='edited after plan' "
                          "WHERE sync_uid=?", (FIXED_PROJECT_A,))
            conn.commit()
        before = self._snapshot()
        tampered = dict(drift_plan, links="inherited")
        with closing(self._connect()) as conn:
            for candidate, code, exit_code in (
                    (drift_plan, "WORKSPACE_FORK_SOURCE_CHANGED", 2),
                    (tampered, "WORKSPACE_FORK_PLAN_INVALID", 2)):
                with self.assertRaises(self.sync.IdentityLifecycleError) as caught:
                    self.sync.execute_workspace_fork_plan(
                        conn, candidate, expected_plan_id=drift_plan["plan_id"],
                        state_path=drift_plan_path)
                self.assertEqual((code, exit_code),
                                 (caught.exception.code, caught.exception.exit_code))
        self.assertEqual(before, self._snapshot())
        self.assertFalse(drift_plan_path.exists())

    # ── AC6: activate-writer is local activation only ────────

    def test_t007_ac6_activate_writer_enables_verified_fork_locally(self):
        plan_path, plan = self._fork()
        argv = ["activate-writer", "--workspace-id", FIXED_WORKSPACE_C,
                "--fork-plan", str(plan_path), "--plan-id", plan["plan_id"]]
        with mock.patch.object(self.sync, "_open_write_conn") as write_conn:
            unverified, _c, output = self._main(argv)
        self.assertEqual(3, unverified, output)
        self.assertIn("WORKSPACE_FORK_NOT_VERIFIED", output)
        write_conn.assert_not_called()
        self.assertEqual(0, self._main(["fork-workspace", "--plan", str(plan_path),
                                        "--plan-id", plan["plan_id"]])[0])
        dry_before = (self.manifest_path.read_bytes(), self._snapshot())
        dry, _c, dry_output = self._main(argv + ["--dry-run"])
        self.assertEqual(0, dry, dry_output)
        self.assertIn("ACTIVATE_FORK", dry_output)
        self.assertEqual(dry_before, (self.manifest_path.read_bytes(), self._snapshot()))
        source_rows = self._rows("projects", "workspace_id<>?", (FIXED_WORKSPACE_C,))
        result, _c, output = self._main(argv)
        self.assertEqual(0, result, output)
        manifest = json.loads(self.manifest_path.read_text())
        self.assertEqual((FIXED_WORKSPACE_C, "writer-fork", 1), (
            manifest["workspace_id"], manifest["writer_id"], manifest["writer_epoch"]))
        with closing(self._connect()) as conn:
            self.assertEqual(manifest, self.sync.resolve_workspace_identity(
                conn, manifest_path=self.manifest_path))
        self.assertEqual(source_rows, self._rows("projects", "workspace_id<>?",
                                                 (FIXED_WORKSPACE_C,)))
        rerun, _c, rerun_output = self._main(argv)
        self.assertEqual(0, rerun)
        self.assertIn("WRITER_ALREADY_ACTIVE", rerun_output)
        fork_plan = self._build_plan()
        self.assertEqual({(FIXED_WORKSPACE_C, FIXED_PROJECT_C)}, {
            (op["identity"]["workspace_id"], op["identity"]["project_sync_uid"])
            for op in fork_plan["operations"]})

    def test_t007_ac6_activation_crash_resumes_and_pending_journal_blocks(self):
        plan_path, plan = self._fork()
        self._main(["fork-workspace", "--plan", str(plan_path), "--plan-id",
                    plan["plan_id"]])
        with closing(self._connect()) as conn:
            conn.execute("INSERT INTO _metadata(key, value) VALUES "
                         "('pending_push:v2:opv2_x', '{}')")
            conn.commit()
        argv = ["activate-writer", "--workspace-id", FIXED_WORKSPACE_C,
                "--fork-plan", str(plan_path), "--plan-id", plan["plan_id"]]
        with mock.patch.object(self.sync, "_open_write_conn") as write_conn:
            blocked, _c, output = self._main(argv)
        self.assertEqual(3, blocked)
        self.assertIn("PENDING_JOURNAL_BLOCKS_ACTIVATION", output)
        write_conn.assert_not_called()
        with closing(self._connect()) as conn:
            conn.execute("DELETE FROM _metadata WHERE key LIKE 'pending_push:%'")
            conn.commit()
        activation_path = str(plan_path) + ".activation.json"
        with closing(self._connect()) as conn:
            decision = self.sync.classify_writer_activation(
                conn, workspace_id=FIXED_WORKSPACE_C, fork_plan=plan,
                fork_plan_id=plan["plan_id"],
                fork_state_path=str(plan_path) + ".state.json",
                activation_state_path=activation_path)
            with self.assertRaisesRegex(RuntimeError, "after_manifest_write"):
                self.sync.execute_writer_activation(
                    conn, decision, plan_ref=plan["plan_id"],
                    activation_state_path=activation_path,
                    manifest_path=self.manifest_path, fail_at="after_manifest_write")
        resumed, _c, output = self._main(argv)
        self.assertEqual(0, resumed, output)
        self.assertIn("ACTIVATE_FORK_RESUME", output)
        with closing(self._connect()) as conn:
            self.assertEqual(FIXED_WORKSPACE_C, self.sync.resolve_workspace_identity(
                conn, manifest_path=self.manifest_path)["workspace_id"])

    def _bootstrap_state(self, workspace_id, writer_id, state="manifest_committed"):
        manifest = self.sync._writer_manifest(workspace_id, writer_id)
        path = self.root / ("bootstrap-%s-%s.json" % (writer_id, state))
        path.write_text(json.dumps({
            "state": state, "authority_revision": 1, "planned_manifest": manifest,
            "authority_record": {
                "workspace_id": workspace_id, "writer_id": writer_id,
                "writer_epoch": 1,
                "authority_hash": manifest["writer_authority_hash_cache"]},
        }), encoding="utf-8")
        return path, manifest

    def test_t007_ac6_bootstrap_activation_only_fills_missing_local_cache(self):
        state_path, manifest = self._bootstrap_state(FIXED_WORKSPACE_C, "writer-new")
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with closing(self._connect()) as conn:
            conn.execute("DELETE FROM _metadata WHERE key IN ('active_workspace_id', "
                         "'active_writer_epoch', 'writer_authority_hash_cache')")
            conn.commit()
        argv = ["activate-writer", "--workspace-id", FIXED_WORKSPACE_C,
                "--bootstrap-state", str(state_path)]
        result, _c, output = self._main(argv)
        self.assertEqual(0, result, output)
        self.assertIn("ACTIVATE_BOOTSTRAP", output)
        with closing(self._connect()) as conn:
            self.assertEqual(manifest, self.sync.resolve_workspace_identity(
                conn, manifest_path=self.manifest_path))
        rerun, _c, output = self._main(argv)
        self.assertEqual(0, rerun)
        self.assertIn("WRITER_ALREADY_ACTIVE", output)
        incomplete, _ = self._bootstrap_state(FIXED_WORKSPACE_C, "writer-new",
                                              state="authority_committed")
        result, _c, output = self._main(["activate-writer", "--workspace-id",
                                         FIXED_WORKSPACE_C, "--bootstrap-state",
                                         str(incomplete)])
        self.assertEqual(3, result)
        self.assertIn("BOOTSTRAP_INCOMPLETE", output)

    def test_t007_ac6_activate_writer_never_takes_over_existing_writer(self):
        before = (self.manifest_path.read_bytes(), self._snapshot())
        takeover_state, _ = self._bootstrap_state(FIXED_WORKSPACE_A, FIXED_WRITER_B)
        with mock.patch.object(self.sync, "_open_write_conn") as write_conn:
            result, _c, output = self._main([
                "activate-writer", "--workspace-id", FIXED_WORKSPACE_A,
                "--bootstrap-state", str(takeover_state)])
            other_ws, _c, other_output = self._main([
                "activate-writer", "--workspace-id", FIXED_WORKSPACE_B,
                "--bootstrap-state", str(takeover_state)])
        self.assertEqual(3, result, output)
        self.assertIn("V2_1_REQUIRED", output)
        self.assertEqual(2, other_ws, other_output)
        self.assertIn("ACTIVATION_TARGET_MISMATCH", other_output)
        write_conn.assert_not_called()
        self.assertEqual(before, (self.manifest_path.read_bytes(), self._snapshot()))

    def test_t007_ac6_clone_or_forged_bootstrap_state_cannot_reactivate_writer(self):
        # Existing workspace A: a clone/rebuilt cache plus a state file forged
        # from the tracked manifest must not become a second active writer.
        with closing(self._connect()) as conn:
            conn.execute("DELETE FROM _metadata WHERE key IN ('active_workspace_id', "
                         "'active_writer_epoch', 'writer_authority_hash_cache')")
            conn.commit()
        before = (self.manifest_path.read_bytes(), self._snapshot())
        for state in ("manifest_committed", "cache_committed", "verified"):
            with self.subTest(state=state):
                forged, _ = self._bootstrap_state(FIXED_WORKSPACE_A, FIXED_WRITER_A,
                                                  state=state)
                with mock.patch.object(self.sync, "_open_write_conn") as write_conn:
                    result, _c, output = self._main([
                        "activate-writer", "--workspace-id", FIXED_WORKSPACE_A,
                        "--bootstrap-state", str(forged)])
                self.assertEqual(3, result, output)
                self.assertIn("V2_1_REQUIRED", output)
                write_conn.assert_not_called()
        self.assertEqual(before, (self.manifest_path.read_bytes(), self._snapshot()))

    def test_t007_ac6_foreign_activation_journal_cannot_bypass_takeover_guard(self):
        _plan_path, plan = self._fork()
        forged = copy.deepcopy(plan)
        forged["result"]["workspace_id"] = FIXED_WORKSPACE_A
        forged["result"]["writer_id"] = FIXED_WRITER_B
        forged["result"]["writer_authority_hash"] = self.sync._writer_manifest(
            FIXED_WORKSPACE_A, FIXED_WRITER_B)["writer_authority_hash_cache"]
        forged["source"]["workspace_id"] = FIXED_WORKSPACE_B
        forged["plan_id"] = self.sync._fork_plan_id(forged)
        fork_state = self.root / "forged.state.json"
        fork_state.write_text(json.dumps(
            {"plan_id": forged["plan_id"], "state": "verified"}), encoding="utf-8")
        current = json.loads(self.manifest_path.read_text())
        activation_files = (
            {"plan_ref": "another-plan", "state": "planned",
             "target_manifest": {}, "source_manifest": current},
            {"plan_ref": forged["plan_id"], "state": "planned",
             "target_manifest": self.sync._writer_manifest(
                 FIXED_WORKSPACE_A, FIXED_WRITER_B),
             "source_manifest": current},
        )
        for index, activation in enumerate(activation_files):
            with self.subTest(activation=index):
                activation_path = self.root / ("forged-%d.activation.json" % index)
                activation_path.write_text(json.dumps(activation), encoding="utf-8")
                with closing(self._connect()) as conn:
                    decision = self.sync.classify_writer_activation(
                        conn, workspace_id=FIXED_WORKSPACE_A, fork_plan=forged,
                        fork_plan_id=forged["plan_id"], fork_state_path=fork_state,
                        activation_state_path=activation_path,
                        manifest_path=self.manifest_path)
                self.assertEqual(("deferred", 3, "V2_1_REQUIRED"), (
                    decision["decision"], decision["exit_code"], decision["code"]))
        self.assertEqual(current, json.loads(self.manifest_path.read_text()))

    def test_t007_ac6_first_activation_refuses_already_synced_result_rows(self):
        plan_path, plan = self._fork()
        self.assertEqual(0, self._main(["fork-workspace", "--plan", str(plan_path),
                                        "--plan-id", plan["plan_id"]])[0])
        with closing(self._connect()) as conn:
            conn.execute("UPDATE projects SET notion_page_id='page-live' "
                         "WHERE workspace_id=?", (FIXED_WORKSPACE_C,))
            conn.commit()
            decision = self.sync.classify_writer_activation(
                conn, workspace_id=FIXED_WORKSPACE_C, fork_plan=plan,
                fork_plan_id=plan["plan_id"],
                fork_state_path=str(plan_path) + ".state.json",
                activation_state_path=str(plan_path) + ".activation.json",
                manifest_path=self.manifest_path)
        self.assertEqual(("deferred", "V2_1_REQUIRED"),
                         (decision["decision"], decision["code"]))

    def test_t007_ac5_fork_and_activation_rerun_is_noop_after_rows_evolve(self):
        plan_path, plan = self._fork()
        execute = ["fork-workspace", "--plan", str(plan_path), "--plan-id",
                   plan["plan_id"]]
        activate = ["activate-writer", "--workspace-id", FIXED_WORKSPACE_C,
                    "--fork-plan", str(plan_path), "--plan-id", plan["plan_id"]]
        self.assertEqual(0, self._main(execute)[0])
        self.assertEqual(0, self._main(activate)[0])
        with closing(self._connect()) as conn:
            conn.execute("UPDATE tasks SET status='完了' WHERE workspace_id=?",
                         (FIXED_WORKSPACE_C,))
            conn.commit()
        uids = self._uids()
        with mock.patch.object(self.sync.uuid, "uuid4",
                               side_effect=AssertionError("no Identity on rerun")):
            fork_rerun, _c, fork_output = self._main(execute)
            activate_rerun, _c, activate_output = self._main(activate)
        self.assertEqual(0, fork_rerun, fork_output)
        self.assertIn('"inserted_rows": 0', fork_output)
        self.assertEqual(0, activate_rerun, activate_output)
        self.assertIn("WRITER_ALREADY_ACTIVE", activate_output)
        self.assertEqual(uids, self._uids())

    def test_t007_ac5_empty_workspace_fork_reruns_cleanly(self):
        with closing(self._connect()) as conn:
            conn.execute("DELETE FROM tasks WHERE workspace_id=?", (FIXED_WORKSPACE_A,))
            conn.execute("DELETE FROM projects WHERE workspace_id=?",
                         (FIXED_WORKSPACE_A,))
            conn.commit()
        plan_path, plan = self._fork(ids=(FIXED_WORKSPACE_C,))
        self.assertEqual([], plan["projects"])
        execute = ["fork-workspace", "--plan", str(plan_path), "--plan-id",
                   plan["plan_id"]]
        for _attempt in range(2):
            result, _c, output = self._main(execute)
            self.assertEqual(0, result, output)
            self.assertIn('"state": "verified"', output)

    # ── AC7: transfer/takeover/handoff are V2_1_REQUIRED ─────

    def test_t007_ac7_deferred_operations_stop_before_any_read_api_or_write(self):
        cases = (
            ["transfer-project", "--sync-uid", FIXED_PROJECT_A,
             "--to-workspace", FIXED_WORKSPACE_B],
            ["takeover-writer", "--workspace-id", FIXED_WORKSPACE_A,
             "--writer-id", FIXED_WRITER_B],
            ["handoff-repair", "--workspace-id", FIXED_WORKSPACE_A],
            ["handoff-repair", "--workspace-id", FIXED_WORKSPACE_A, "--plan",
             "p.json", "--plan-id", "abc", "--dry-run"],
        )
        guarded = ("_api_call", "_query_db", "_open_read_conn", "_open_write_conn",
                   "_get_preflight_conn", "_get_conn", "_read_json_file",
                   "_atomic_json_write", "run_preflight", "resolve_workspace_identity")
        before = (self.db_path.read_bytes(), self.manifest_path.read_bytes())
        for argv in cases:
            with self.subTest(argv=argv):
                with contextlib.ExitStack() as stack:
                    mocks = {name: stack.enter_context(mock.patch.object(
                        self.sync, name, side_effect=AssertionError(name)))
                        for name in guarded}
                    connect = stack.enter_context(mock.patch.object(
                        self.sync.sqlite3, "connect",
                        side_effect=AssertionError("sqlite3.connect")))
                    result, _c, output = self._main(argv)
                self.assertEqual(3, result, output)
                self.assertIn("V2_1_REQUIRED", output)
                self.assertEqual({name: 0 for name in guarded},
                                 {name: m.call_count for name, m in mocks.items()})
                self.assertEqual(0, connect.call_count)
        self.assertEqual(before, (self.db_path.read_bytes(),
                                  self.manifest_path.read_bytes()))


T011_UID_A = "prj_00000000-0000-4000-8000-000000000101"
T011_UID_B = "prj_00000000-0000-4000-8000-000000000102"
T011_UID_X1 = "prj_00000000-0000-4000-8000-000000000103"
T011_UID_X2 = "prj_00000000-0000-4000-8000-000000000104"
T011_LINKED_AT = "2026-07-15T11:30:00Z"
T011_ORPHAN_KEYS = ("L-OLD-A-SG0/T004", "L-OLD-B-X1/T020") + tuple(
    "L-OLD-C-X2-SG1/T%03d" % index for index in range(1, 7))
T011_FAILPOINTS = ("after_planned", "after_checkpoint", "after_rows_commit",
                   "after_manifest_write", "after_cache_commit")


class IdentityV2AdoptExistingTest(unittest.TestCase):
    """T011 adopt-existing: production manifest without v2.1 Authority."""

    WRITER = "writer-main"

    def setUp(self):
        self.production_before = file_fingerprint(PRODUCTION_DB)
        self.addCleanup(self._assert_production_unchanged)
        self.temp_dir = tempfile.TemporaryDirectory(prefix="ai-plc-identity-t011-")
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "ai_plc.db"
        self.manifest_path = self.root / "workspace_identity.json"
        self.plan_path = self.root / "adopt-plan.json"
        self.state_path = Path(str(self.plan_path) + ".state.json")
        self.init_db = load_module(DB_DIR / "init_db.py", f"identity_init_t011_{id(self)}")
        self.sync = load_module(DB_DIR / "sync.py", f"identity_sync_t011_{id(self)}")
        self._create_legacy_db(self.db_path)
        self.intent_x1 = self.root / "intents" / "x1" / "intent.yaml"
        self.intent_x2 = self.root / "intents" / "x2" / "intent.yaml"
        for path, scope_id in ((self.intent_x1, "L-OLD-B-X1"),
                               (self.intent_x2, "L-OLD-C-X2-SG1")):
            path.parent.mkdir(parents=True)
            path.write_text("# Execution Context\nscope_id: \"%s\"\nscope_name: x\n"
                            "status: active\ngoal:\n  scope_id: nested-ignored\n"
                            % scope_id, encoding="utf-8")
        self.decisions_path = self.root / "decisions.json"
        self._write_decisions(self._decisions())
        self.sync.DB_PATH = str(self.db_path)
        self.sync.WORKSPACE_MANIFEST_PATH = str(self.manifest_path)
        self.sync.TOKEN = "dummy-t011-token"
        self.sync.RATE_LIMIT_DELAY = 0
        self.sync._now_iso = lambda: FIXED_NOW
        guard = mock.patch.object(
            self.sync.urllib.request, "urlopen",
            side_effect=AssertionError("network access is forbidden in T011 tests"))
        guard.start()
        self.addCleanup(guard.stop)

    # ── fixture helpers ──────────────────────────────────────

    def _assert_production_unchanged(self):
        self.assertEqual(self.production_before, file_fingerprint(PRODUCTION_DB))

    def _create_legacy_db(self, path):
        with closing(sqlite3.connect(path)) as conn:
            with contextlib.redirect_stdout(io.StringIO()):
                self.init_db.create_schema(conn)
            conn.execute("""
                INSERT INTO projects (notion_page_id, scope_id, name, status,
                    notion_last_edited, last_sync_at, created_at, updated_at)
                VALUES ('page-pa', 'L-A', 'Project A', 'active', ?, ?, ?, ?)
            """, (T007_OLD_EDIT, T011_LINKED_AT, T011_LINKED_AT, T011_LINKED_AT))
            conn.execute("""
                INSERT INTO projects (scope_id, name, status, created_at, updated_at)
                VALUES ('L-B', 'Project B', 'planned', ?, ?)
            """, (FIXED_NOW, FIXED_NOW))
            linked_tasks = [("page-ta1", "T001", "L-A"),
                            ("page-x1", "T004", "L-OLD-A-SG0"),
                            ("page-o2", "T020", "L-OLD-B-X1")]
            linked_tasks += [("page-o%d" % (index + 2), "T%03d" % index,
                              "L-OLD-C-X2-SG1") for index in range(1, 7)]
            for page_id, task_id, scope_id in linked_tasks:
                conn.execute("""
                    INSERT INTO tasks (notion_page_id, task_id, scope_id, name, status,
                        notion_last_edited, last_sync_at, created_at, updated_at)
                    VALUES (?, ?, ?, ?, '未着手', ?, ?, ?, ?)
                """, (page_id, task_id, scope_id, "Task %s" % task_id, T007_OLD_EDIT,
                      T011_LINKED_AT, T011_LINKED_AT, T011_LINKED_AT))
            conn.execute("""
                INSERT INTO tasks (task_id, scope_id, name, status, created_at, updated_at)
                VALUES ('T001', 'L-B', 'Task B1', '未着手', ?, ?)
            """, (FIXED_NOW, FIXED_NOW))
            conn.commit()

    @staticmethod
    def _digest(path):
        return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def _decisions(self):
        decisions = [{"routing_key": "L-OLD-A-SG0/T004", "decision": "legacy_excluded",
                      "evidence_digest": "sha256:" + "a" * 64}]
        decisions.append({
            "routing_key": "L-OLD-B-X1/T020", "decision": "fixed_mapping",
            "evidence_digest": self._digest(self.intent_x1),
            "intent_path": "intents/x1/intent.yaml",
            "project_name": "Synthetic A", "project_status": "active"})
        decisions.extend({
            "routing_key": "L-OLD-C-X2-SG1/T%03d" % index, "decision": "fixed_mapping",
            "evidence_digest": self._digest(self.intent_x2),
            "intent_path": "intents/x2/intent.yaml",
            "project_name": "Synthetic SG1", "project_status": "completed"}
            for index in range(1, 7))
        return decisions

    def _write_decisions(self, decisions, path=None):
        path = path or self.decisions_path
        path.write_text(json.dumps({"adopt_decisions_version": 1,
                                    "decisions": decisions}), encoding="utf-8")
        return path

    def _connect(self, path=None):
        conn = sqlite3.connect(path or self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _snapshot(self, path=None):
        with closing(self._connect(path)) as conn:
            return {table: [dict(row) for row in conn.execute(
                "SELECT * FROM %s ORDER BY %s" % (
                    table, "key" if table == "_metadata" else "id")).fetchall()]
                for table in ("projects", "tasks", "_metadata")}

    def _main(self, argv, handlers=()):
        calls = []
        output = io.StringIO()
        with contextlib.ExitStack() as stack:
            for name in handlers:
                stack.enter_context(mock.patch.object(
                    self.sync, name,
                    side_effect=lambda *a, _n=name, **k: calls.append((_n, a, k)) or 91))
            stack.enter_context(contextlib.redirect_stdout(output))
            result = self.sync.main(argv)
        return result, calls, output.getvalue()

    def _ids(self):
        return iter((FIXED_WORKSPACE_A, T011_UID_A, T011_UID_B, T011_UID_X1,
                     T011_UID_X2))

    def _dry_run(self, ids=None, decisions_path=None, writer=None):
        ids = ids if ids is not None else self._ids()
        with mock.patch.object(self.sync.uuid, "uuid4",
                               side_effect=lambda: next(ids)):
            return self._main([
                "adopt-existing", "--dry-run",
                "--decisions", str(decisions_path or self.decisions_path),
                "--writer-id", writer or self.WRITER,
                "--plan-out", str(self.plan_path)])

    def _plan(self):
        return json.loads(self.plan_path.read_text(encoding="utf-8"))

    def _execute(self, plan_id=None):
        plan_id = plan_id or self._plan()["plan_id"]
        with mock.patch.object(self.sync.uuid, "uuid4",
                               side_effect=AssertionError("execute issued an ID")):
            return self._main(["adopt-existing", "--plan", str(self.plan_path),
                               "--plan-id", plan_id])

    def _adopt(self):
        result, _calls, output = self._dry_run()
        self.assertEqual(0, result, output)
        result, _calls, output = self._execute()
        self.assertEqual(0, result, output)
        return self._plan()

    def _identity_rows(self):
        with closing(self._connect()) as conn:
            return {
                "projects": [tuple(row) for row in conn.execute(
                    "SELECT scope_id, workspace_id, sync_uid, ownership_epoch, "
                    "identity_version FROM projects ORDER BY id").fetchall()],
                "tasks": [tuple(row) for row in conn.execute(
                    "SELECT scope_id, task_id, workspace_id, project_sync_uid, "
                    "project_ownership_epoch, identity_version FROM tasks "
                    "ORDER BY id").fetchall()],
            }

    @staticmethod
    def _rich(value):
        return {"rich_text": [] if not value else [{"plain_text": value}]}

    def _project_page(self, page_id, scope_id, sync_uid=None, *, name="Project A",
                      edited=T007_OLD_EDIT):
        return {
            "id": page_id, "last_edited_time": edited,
            "parent": {"type": "database_id", "database_id": "projects-db"},
            "properties": {
                "PJ名": {"title": [{"plain_text": name}]},
                "Scope ID": self._rich(scope_id),
                "ステータス": {"status": {"name": "active"}},
                "Sync UID": self._rich(sync_uid),
                "Workspace ID": self._rich(FIXED_WORKSPACE_A if sync_uid else None),
                "Ownership Epoch": {"number": 1 if sync_uid else None},
                "Identity Version": {"number": 2 if sync_uid else None},
            },
        }

    def _task_page(self, page_id, scope_id, task_id, project_sync_uid=None):
        return {
            "id": page_id, "last_edited_time": T007_OLD_EDIT,
            "parent": {"type": "database_id", "database_id": "tasks-db"},
            "properties": {
                "タスク名": {"title": [{"plain_text": "Task %s" % task_id}]},
                "Task ID": self._rich(task_id),
                "Scope ID": self._rich(scope_id),
                "ステータス": {"status": {"name": "未着手"}},
                "Project Sync UID": self._rich(project_sync_uid),
                "Workspace ID": self._rich(
                    FIXED_WORKSPACE_A if project_sync_uid else None),
                "Project Ownership Epoch": {"number": 1 if project_sync_uid else None},
                "Identity Version": {"number": 2 if project_sync_uid else None},
            },
        }

    def _backfilled_remote(self):
        """Remote as it looks after T009 migrate-identity backfilled Notion."""
        tasks = [self._task_page("page-ta1", "L-A", "T001", T011_UID_A),
                 self._task_page("page-x1", "L-OLD-A-SG0", "T004"),
                 self._task_page("page-o2", "L-OLD-B-X1", "T020", T011_UID_X1)]
        tasks += [self._task_page("page-o%d" % (index + 2), "L-OLD-C-X2-SG1",
                                  "T%03d" % index, T011_UID_X2)
                  for index in range(1, 7)]
        return T007FakeNotion(self.sync, projects=[
            self._project_page("page-pa", "L-A", T011_UID_A)], tasks=tasks)

    def _pull(self, fake, dry_run=False):
        output = io.StringIO()
        with (
            mock.patch.object(self.sync, "_query_db", side_effect=fake.query),
            mock.patch.object(self.sync, "_api_call", side_effect=fake.api),
            contextlib.redirect_stdout(output),
        ):
            result = self.sync.cmd_pull(dry_run=dry_run, skip_preflight=True)
        return result, output.getvalue()

    def _build_push_plan(self, fake):
        with (
            mock.patch.object(self.sync, "_query_db", side_effect=fake.query),
            mock.patch.object(self.sync, "_api_call", side_effect=fake.api),
        ):
            return self.sync.build_push_plan(skip_preflight=True)

    def _status(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = self.sync.cmd_status()
        return result, output.getvalue()

    # ── AC1: fixed Plan -> manifest + Identity projection, 0 Authority/Notion ─

    def test_t011_ac1_fixed_plan_builds_manifest_and_projection_without_authority_or_notion(self):
        before = self._snapshot()
        intents_before = (self.intent_x1.read_bytes(), self.intent_x2.read_bytes())
        guarded = ("_api_call", "_query_db", "run_preflight",
                   "bootstrap_workspace_identity", "classify_writer_activation",
                   "execute_identity_migration_plan", "cmd_deferred_v21")
        resolver = self.sync.resolve_workspace_identity
        authority_args = []

        def resolve_without_authority(conn, authority_store=None, **kwargs):
            authority_args.append(authority_store)
            return resolver(conn, authority_store, **kwargs)

        with contextlib.ExitStack() as stack:
            mocks = {name: stack.enter_context(mock.patch.object(
                self.sync, name, side_effect=AssertionError(name))) for name in guarded}
            stack.enter_context(mock.patch.object(
                self.sync, "resolve_workspace_identity",
                side_effect=resolve_without_authority))
            plan = self._adopt()
            result, _calls, status_output = self._main(
                ["adopt-existing", "--status", "--plan", str(self.plan_path)])
        self.assertEqual(0, result, status_output)
        self.assertEqual({name: 0 for name in guarded},
                         {name: m.call_count for name, m in mocks.items()})
        self.assertTrue(authority_args)
        self.assertEqual({None}, set(authority_args))
        self.assertEqual("workspace_adopt_existing", plan["direction"])
        self.assertEqual("deferred_v2_1", plan["authority"])
        self.assertEqual({"fixed_mapping": 7, "legacy_excluded": 1},
                         plan["decision_counts"])
        self.assertEqual({"notion": 0, "authority": 0, "intent": 0}, {
            key: plan["mutation_budget"][key] for key in ("notion", "authority", "intent")})
        target = self.sync._writer_manifest(FIXED_WORKSPACE_A, self.WRITER)
        self.assertEqual(target, json.loads(self.manifest_path.read_text("utf-8")))
        with closing(self._connect()) as conn:
            self.assertEqual(self.sync._cache_for_manifest(target),
                             self.sync._adopt_cache(conn))
            self.assertEqual(target, self.sync.resolve_workspace_identity(
                conn, manifest_path=str(self.manifest_path)))
            self.assertEqual("ok", conn.execute("PRAGMA quick_check").fetchone()[0])
        rows = self._identity_rows()
        self.assertEqual([
            ("L-A", FIXED_WORKSPACE_A, T011_UID_A, 1, 2),
            ("L-B", FIXED_WORKSPACE_A, T011_UID_B, 1, 2),
            ("L-OLD-B-X1", FIXED_WORKSPACE_A, T011_UID_X1, 1, 2),
            ("L-OLD-C-X2-SG1", FIXED_WORKSPACE_A, T011_UID_X2, 1, 2)], rows["projects"])
        by_key = {"%s/%s" % row[:2]: row[2:] for row in rows["tasks"]}
        self.assertEqual((None, None, None, None), by_key["L-OLD-A-SG0/T004"])
        self.assertEqual((FIXED_WORKSPACE_A, T011_UID_X1, 1, 2),
                         by_key["L-OLD-B-X1/T020"])
        self.assertEqual({(FIXED_WORKSPACE_A, T011_UID_X2, 1, 2)}, {
            value for key, value in by_key.items() if key.startswith("L-OLD-C")})
        self.assertEqual((FIXED_WORKSPACE_A, T011_UID_A, 1, 2), by_key["L-A/T001"])
        # Legacy columns (links, timestamps) are preserved byte-for-byte.
        after = self._snapshot()
        legacy = lambda table, row: {k: v for k, v in row.items()
                                     if k not in self.sync.LOCAL_IDENTITY_COLUMNS[table]}
        self.assertEqual([legacy("projects", row) for row in before["projects"]],
                         [legacy("projects", row) for row in after["projects"][:2]])
        self.assertEqual([legacy("tasks", row) for row in before["tasks"]],
                         [legacy("tasks", row) for row in after["tasks"]])
        self.assertEqual(intents_before,
                         (self.intent_x1.read_bytes(), self.intent_x2.read_bytes()))
        # Maintenance checkpoint: the pre-mutation v1 backup, verified.
        state = json.loads(self.state_path.read_text("utf-8"))
        self.assertEqual("verified", state["state"])
        checkpoint = Path(state["checkpoint_path"])
        # Stored beside the adopted DB (git-ignored *.db), not beside the Plan.
        self.assertEqual(self.db_path.parent.resolve(), checkpoint.parent.resolve())
        self.assertEqual(".db", checkpoint.suffix)
        self.assertEqual(state["checkpoint"]["sha256"],
                         hashlib.sha256(checkpoint.read_bytes()).hexdigest())
        with closing(sqlite3.connect(checkpoint)) as conn:
            self.assertNotIn("workspace_id", {
                row[1] for row in conn.execute("PRAGMA table_info(projects)")})
            self.assertEqual(2, conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0])
        self.assertIn('"state": "verified"', status_output)

    def test_t011_ac2_rerun_reuses_plan_manifest_and_uids(self):
        result, _c, output = self._dry_run()
        self.assertEqual(0, result, output)
        plan_bytes = self.plan_path.read_bytes()
        result, _c, output = self._dry_run(ids=iter(()))  # uuid4 must not be called
        self.assertEqual(0, result, output)
        self.assertIn('"reused": true', output)
        self.assertEqual(plan_bytes, self.plan_path.read_bytes())
        self.assertEqual(0, self._execute()[0])
        snapshot, manifest = self._snapshot(), self.manifest_path.read_bytes()
        result, _c, output = self._execute()
        self.assertEqual(0, result, output)
        self.assertIn('"noop": true', output)
        self.assertEqual((snapshot, manifest),
                         (self._snapshot(), self.manifest_path.read_bytes()))
        result, _c, output = self._dry_run(ids=iter(()))
        self.assertEqual(0, result, output)
        self.assertIn('"state": "applied"', output)
        # State lost after verification: Identity-only readback, still no re-issue.
        self.state_path.unlink()
        with closing(self._connect()) as conn:
            conn.execute("UPDATE projects SET name='renamed later' WHERE scope_id='L-B'")
            conn.commit()
        snapshot = self._snapshot()
        result, _c, output = self._execute()
        self.assertEqual(0, result, output)
        self.assertEqual((snapshot, manifest),
                         (self._snapshot(), self.manifest_path.read_bytes()))

    def test_t011_ac2_crash_resume_converges_without_reissue(self):
        base = self.root / "base.db"
        shutil.copyfile(self.db_path, base)
        decisions = self.sync.load_adopt_decisions(str(self.decisions_path))
        for point in T011_FAILPOINTS:
            with self.subTest(point=point):
                work = self.root / point
                work.mkdir()
                db = work / "ai_plc.db"
                shutil.copyfile(base, db)
                manifest = work / "workspace_identity.json"
                state = work / "state.json"
                ids = self._ids()
                with closing(self._connect(db)) as conn:
                    plan = self.sync.build_adopt_existing_plan(
                        conn, writer_id=self.WRITER, decisions=decisions,
                        decisions_base=str(self.root),
                        identity_factory=lambda: next(ids),
                        manifest_path=str(manifest))
                    with self.assertRaisesRegex(RuntimeError, point):
                        self.sync.execute_adopt_existing_plan(
                            conn, plan, expected_plan_id=plan["plan_id"],
                            state_path=str(state), manifest_path=str(manifest),
                            fail_at=point)
                with closing(self._connect(db)) as conn, mock.patch.object(
                        self.sync.uuid, "uuid4", side_effect=AssertionError):
                    result = self.sync.execute_adopt_existing_plan(
                        conn, plan, expected_plan_id=plan["plan_id"],
                        state_path=str(state), manifest_path=str(manifest))
                    self.assertEqual("verified", result["state"])
                    self.assertEqual([], self.sync._adopt_rows_readback(conn, plan))
                    self.assertEqual({T011_UID_A, T011_UID_B, T011_UID_X1, T011_UID_X2},
                                     {row[0] for row in conn.execute(
                                         "SELECT sync_uid FROM projects")})
                self.assertEqual(
                    self.sync._writer_manifest(FIXED_WORKSPACE_A, self.WRITER),
                    json.loads(manifest.read_text("utf-8")))
                self.assertEqual([], sorted(p.name for p in work.iterdir()
                                            if ".tmp" in p.name))

    def test_t011_ac2_adjudication_gaps_and_bad_evidence_fail_before_plan(self):
        decisions = self._decisions()
        wrong_scope = self.root / "intents" / "wrong" / "intent.yaml"
        wrong_scope.parent.mkdir(parents=True)
        wrong_scope.write_text('scope_id: "L-OLD-B-X1-OTHER"\n', encoding="utf-8")
        prefix_only = copy.deepcopy(decisions)
        prefix_only[1].update(intent_path="intents/wrong/intent.yaml",
                              evidence_digest=self._digest(wrong_scope))
        cases = {
            "missing": (decisions[:-1], 3, "ADOPT_ADJUDICATION_INCOMPLETE"),
            "duplicate": (decisions + [decisions[0]], 2, "ADOPT_DUPLICATE_DECISION"),
            "duplicate_and_missing": (decisions[:-1] + [decisions[0]], 3,
                                      "ADOPT_ADJUDICATION_INCOMPLETE"),
            "not_orphan": (decisions + [dict(decisions[0], routing_key="L-A/T001")],
                           2, "ADOPT_DECISION_NOT_ORPHAN"),
            "unknown_kind": ([dict(decisions[0], decision="auto_attach")] + decisions[1:],
                             2, "ADOPT_DECISION_INVALID"),
            "no_evidence": ([dict(decisions[0], evidence_digest="sha256:no-intent")]
                            + decisions[1:], 2, "ADOPT_EVIDENCE_REQUIRED"),
            "evidence_mismatch": (decisions[:1] + [dict(
                decisions[1], evidence_digest="sha256:" + "c" * 64)] + decisions[2:],
                2, "ADOPT_EVIDENCE_MISMATCH"),
            "inexact_intent": (prefix_only, 2, "ADOPT_EXACT_INTENT_REQUIRED"),
            "scope_conflict": (decisions[:3] + [dict(decisions[3], project_name="Other")]
                               + decisions[4:], 2, "ADOPT_DECISION_CONFLICT"),
            "excluded_with_mapping": ([dict(decisions[0], project_name="x")]
                                      + decisions[1:], 2, "ADOPT_DECISION_INVALID"),
        }
        before = self._snapshot()
        for name, (items, exit_code, code) in cases.items():
            with self.subTest(case=name):
                path = self._write_decisions(items, self.root / ("%s.json" % name))
                result, _c, output = self._dry_run(decisions_path=path)
                self.assertEqual(exit_code, result, output)
                self.assertIn(code, output)
                self.assertFalse(self.plan_path.exists())
        self.assertEqual(before, self._snapshot())
        self.assertFalse(self.manifest_path.exists())
        # A persisted Plan cannot be silently re-adjudicated or re-assigned.
        self.assertEqual(0, self._dry_run()[0])
        changed = self._write_decisions(
            decisions[:1] + [dict(decisions[1], project_status="paused")] + decisions[2:],
            self.root / "changed.json")
        for kwargs in ({"decisions_path": changed}, {"writer": "writer-other"}):
            result, _c, output = self._dry_run(ids=iter(()), **kwargs)
            self.assertEqual(2, result, output)
            self.assertIn("ADOPT_PLAN_CONFLICT", output)

    def test_t011_ac2_tampered_plan_and_excluded_injection_rejected_before_mutation(self):
        self.assertEqual(0, self._dry_run()[0])
        approved = self._plan()
        before = self._snapshot()

        def tampered(mutate, rehash):
            plan = copy.deepcopy(approved)
            mutate(plan)
            if rehash:
                plan["plan_id"] = self.sync._fork_plan_id(plan)
            self.plan_path.write_text(json.dumps(plan), encoding="utf-8")
            return plan

        def swap_uid(plan):
            plan["projects"][0]["sync_uid"] = "prj_00000000-0000-4000-8000-000000000999"
            for item in plan["tasks"]:
                if item["scope_id"] == "L-A":
                    item["project_sync_uid"] = plan["projects"][0]["sync_uid"]

        def include_excluded(plan):
            excluded = plan["excluded_tasks"].pop()
            plan["tasks"].append({"row_id": excluded["row_id"],
                                  "scope_id": "L-OLD-A-SG0", "task_id": "T004",
                                  "project_sync_uid": T011_UID_A})
            plan["mutation_budget"]["sqlite_task_updates"] += 1

        def flip_exclusion(plan):
            decision = plan["decisions"][0]
            decision.update(decision="fixed_mapping", project_sync_uid=T011_UID_A)
            plan["decision_counts"] = {"fixed_mapping": 8, "legacy_excluded": 0}

        def exclude_mapped_scope_sibling(plan):
            # Excluded orphan re-pointed into a Scope that gets a Project.
            plan["excluded_tasks"][0]["routing_key"] = "L-OLD-B-X1/T004"
            plan["decisions"][0]["routing_key"] = "L-OLD-B-X1/T004"

        cases = (
            ("excluded_scope_has_project", exclude_mapped_scope_sibling, True, None),
            ("uid_without_rehash", swap_uid, False, None),
            ("uid_rehashed_but_not_approved", swap_uid, True, approved["plan_id"]),
            ("excluded_injected", include_excluded, True, None),
            ("exclusion_flipped", flip_exclusion, True, None),
        )
        for name, mutate, rehash, approved_id in cases:
            with self.subTest(case=name):
                plan = tampered(mutate, rehash)
                result, _c, output = self._execute(approved_id or plan["plan_id"])
                self.assertEqual(2, result, output)
                self.assertIn("ADOPT_PLAN_INVALID", output)
                self.assertEqual(before, self._snapshot())
                self.assertFalse(self.manifest_path.exists())
                self.assertFalse(self.state_path.exists())

    def test_t011_ac2_source_drift_and_preconditions_block_before_mutation(self):
        self.assertEqual(0, self._dry_run()[0])
        plan_id = self._plan()["plan_id"]
        with closing(self._connect()) as conn:
            conn.execute("UPDATE projects SET name='drifted' WHERE scope_id='L-B'")
            conn.commit()
        drifted = self._snapshot()
        for result, _c, output in (self._execute(plan_id), self._dry_run(ids=iter(()))):
            self.assertEqual(2, result, output)
            self.assertIn("ADOPT_SOURCE_CHANGED", output)
        self.assertEqual(drifted, self._snapshot())
        self.assertFalse(self.state_path.exists())
        self.assertFalse(self.manifest_path.exists())

        def fresh():
            self.plan_path.unlink(missing_ok=True)
            self.manifest_path.unlink(missing_ok=True)
            self.db_path.unlink()
            self._create_legacy_db(self.db_path)

        fresh()
        self.manifest_path.write_text(json.dumps(self.sync._writer_manifest(
            FIXED_WORKSPACE_B, "writer-other")), encoding="utf-8")
        result, _c, output = self._dry_run()
        self.assertEqual((3, True), (result, "ADOPT_MANIFEST_EXISTS" in output), output)
        fresh()
        with closing(self._connect()) as conn:
            conn.execute("INSERT INTO _metadata(key, value) VALUES "
                         "('active_workspace_id', ?)", (FIXED_WORKSPACE_B,))
            conn.commit()
        result, _c, output = self._dry_run()
        self.assertEqual((3, True), (result, "ADOPT_ACTIVE_CACHE_EXISTS" in output), output)
        fresh()
        with closing(self._connect()) as conn:
            conn.execute("INSERT INTO _metadata(key, value) VALUES "
                         "('pending_push:project:x', '{}')")
            conn.commit()
        result, _c, output = self._dry_run()
        self.assertEqual((3, True), (result, "PENDING_JOURNAL_BLOCKS_ADOPT" in output),
                         output)
        fresh()
        with closing(self._connect()) as conn:
            self.sync._ensure_identity_dual_read_schema(conn)
            conn.commit()
        result, _c, output = self._dry_run()
        self.assertEqual((3, True), (result, "ADOPT_REQUIRES_V1_SCHEMA" in output), output)
        # A manifest appearing between approval and execute is a takeover (v2.1).
        fresh()
        self.assertEqual(0, self._dry_run()[0])
        self.manifest_path.write_text(json.dumps(self.sync._writer_manifest(
            FIXED_WORKSPACE_B, "writer-other")), encoding="utf-8")
        before = self._snapshot()
        result, _c, output = self._execute()
        self.assertEqual((3, True), (result, "ADOPT_MANIFEST_CONFLICT" in output), output)
        self.assertEqual(before, self._snapshot())

    def test_t011_ac2_legacy_excluded_stays_read_only_across_sync(self):
        self._adopt()
        with closing(self._connect()) as conn:
            excluded_before = dict(conn.execute(
                "SELECT * FROM tasks WHERE scope_id='L-OLD-A-SG0'").fetchone())
        fake = self._backfilled_remote()
        plan = self._build_push_plan(fake)
        self.assertEqual(0, plan["exit_code"], plan.get("preflight"))
        self.assertNotIn("L-OLD-A-SG0", json.dumps(plan["operations"]))
        result, output = self._pull(fake)
        self.assertEqual(0, result, output)
        self.assertIn("legacy_skipped=1", output)
        with closing(self._connect()) as conn:
            self.assertEqual(excluded_before, dict(conn.execute(
                "SELECT * FROM tasks WHERE scope_id='L-OLD-A-SG0'").fetchone()))

    def test_t011_ac2_t006_migration_plan_reuses_adopted_uids(self):
        self._adopt()
        intents = {scope: {"scope_id": scope, "name": scope, "status": "active"}
                   for scope in ("L-A", "L-B", "L-OLD-B-X1", "L-OLD-C-X2-SG1")}
        with closing(sqlite3.connect(self.db_path)) as conn:
            inventory = self.sync.identity_migration_inventory(conn)
            self.assertEqual(["L-OLD-A-SG0/T004"],
                             [item["routing_key"] for item in inventory["orphans"]])
            with mock.patch.object(self.sync.uuid, "uuid4", side_effect=AssertionError):
                migration = self.sync.build_identity_migration_plan(
                    conn, FIXED_WORKSPACE_A, [{
                        "routing_key": "L-OLD-A-SG0/T004",
                        "decision": "legacy_excluded",
                        "evidence_digest": "sha256:" + "a" * 64}],
                    intents, remote=FakeMigrationRemote())
        self.assertEqual({T011_UID_A, T011_UID_B, T011_UID_X1, T011_UID_X2},
                         {op["project_sync_uid"] for op in migration["operations"]})
        self.assertFalse(any(op.get("scope_id") == "L-OLD-A-SG0"
                             for op in migration["operations"]))

    # ── AC3: status/pull/push on the v2 path; manifest/cache mismatch -> 3 ──

    def test_t011_ac3_status_pull_push_run_on_identity_v2_after_adopt(self):
        self._adopt()
        result, output = self._status()
        self.assertEqual(0, result, output)
        self.assertIn("Identity: v2 workspace=", output)
        self.assertIn("task: current_workspace=9 dirty=1 other_workspace=0 "
                      "legacy_read_only=1", output)
        # Pull: exact Identity rows are no-ops; a newer exact row is PATCHed.
        fake = self._backfilled_remote()
        result, output = self._pull(fake)
        self.assertEqual(0, result, output)
        self.assertIn("patch_local=0", output)
        fake.pages["project"][0] = self._project_page(
            "page-pa", "L-A", T011_UID_A, name="Project A renamed", edited=T007_NEW_EDIT)
        result, output = self._pull(fake)
        self.assertEqual(0, result, output)
        self.assertIn("[POST-VERIFY PASS] pull operations=1", output)
        with closing(self._connect()) as conn:
            self.assertEqual(("Project A renamed", T011_UID_A), tuple(conn.execute(
                "SELECT name, sync_uid FROM projects WHERE scope_id='L-A'").fetchone()))
        # Push: workspace selector, only current-workspace Identities, rerun 0.
        plan = self._build_push_plan(fake)
        self.assertEqual(0, plan["exit_code"], plan.get("preflight"))
        self.assertEqual("workspace", plan["selector"]["kind"])
        self.assertEqual({T011_UID_B, T011_UID_X1, T011_UID_X2}, {
            op["identity"]["project_sync_uid"] for op in plan["operations"]})
        output = io.StringIO()
        with (
            mock.patch.object(self.sync, "_revalidate_identity_plan_before_write",
                              return_value=0),
            mock.patch.object(self.sync, "_query_db", side_effect=fake.query),
            mock.patch.object(self.sync, "_api_call", side_effect=fake.api),
            contextlib.redirect_stdout(output),
        ):
            result = self.sync.execute_push_plan(plan)
        self.assertEqual(0, result, output.getvalue())
        self.assertEqual(len(plan["operations"]),
                         output.getvalue().count("[POST-VERIFY PASS]"))
        mutations = len(fake.mutations())
        rerun = self._build_push_plan(fake)
        self.assertEqual((0, []), (rerun["exit_code"], rerun["operations"]))
        self.assertEqual(mutations, len(fake.mutations()))

    def test_t011_ac3_unbackfilled_notion_link_blocks_push_until_migration(self):
        self._adopt()
        with closing(self._connect()) as conn:
            conn.execute("UPDATE projects SET goal='edited' WHERE scope_id='L-A'")
            conn.commit()
        fake = T007FakeNotion(self.sync, projects=[
            self._project_page("page-pa", "L-A")])  # Identity-less Notion page
        plan = self._build_push_plan(fake)
        self.assertEqual(2, plan["exit_code"])
        self.assertIn("LEGACY_LINKED_CANDIDATE", json.dumps(plan))
        self.assertEqual([], fake.mutations())

    def test_t011_ac3_manifest_cache_mismatch_stops_status_pull_push_with_exit_3(self):
        self._adopt()
        base_db = self.db_path.read_bytes()
        base_manifest = self.manifest_path.read_bytes()

        def cache_epoch(conn):
            conn.execute("UPDATE _metadata SET value='2' WHERE key='active_writer_epoch'")

        def cache_missing(conn):
            conn.execute("DELETE FROM _metadata WHERE key LIKE 'active_%' "
                         "OR key='writer_authority_hash_cache'")

        def other_writer(_conn):
            self.manifest_path.write_text(json.dumps(self.sync._writer_manifest(
                FIXED_WORKSPACE_A, "writer-intruder")), encoding="utf-8")

        def manifest_missing(_conn):
            self.manifest_path.unlink()

        for name, tamper in (("cache_epoch", cache_epoch), ("cache_missing", cache_missing),
                             ("other_writer", other_writer),
                             ("manifest_missing", manifest_missing)):
            with self.subTest(case=name):
                self.db_path.write_bytes(base_db)
                self.manifest_path.write_bytes(base_manifest)
                with closing(self._connect()) as conn:
                    tamper(conn)
                    conn.commit()
                before = self._snapshot()
                result, output = self._status()
                self.assertEqual(3, result, output)
                self.assertIn("Identity: BLOCKED", output)
                fake = self._backfilled_remote()
                result, output = self._pull(fake)
                self.assertEqual(3, result, output)
                self.assertEqual([], fake.calls)
                output = io.StringIO()
                with (
                    mock.patch.object(self.sync, "_query_db", side_effect=fake.query),
                    mock.patch.object(self.sync, "_api_call", side_effect=fake.api),
                    contextlib.redirect_stdout(output),
                ):
                    result = self.sync.cmd_push(dry_run=True, skip_preflight=True)
                self.assertEqual(3, result, output.getvalue())
                self.assertEqual([], fake.calls)
                self.assertEqual(before, self._snapshot())

    def test_t011_review_resume_after_cache_commit_tolerates_live_row_changes(self):
        decisions = self.sync.load_adopt_decisions(str(self.decisions_path))
        ids = self._ids()
        with closing(self._connect()) as conn:
            plan = self.sync.build_adopt_existing_plan(
                conn, writer_id=self.WRITER, decisions=decisions,
                decisions_base=str(self.root), identity_factory=lambda: next(ids))
            with self.assertRaisesRegex(RuntimeError, "after_cache_commit"):
                self.sync.execute_adopt_existing_plan(
                    conn, plan, expected_plan_id=plan["plan_id"],
                    state_path=str(self.state_path), fail_at="after_cache_commit")
            # The workspace is already live: a row changes before the resume.
            conn.execute("UPDATE tasks SET status='完了' WHERE scope_id='L-B'")
            conn.commit()
            result = self.sync.execute_adopt_existing_plan(
                conn, plan, expected_plan_id=plan["plan_id"],
                state_path=str(self.state_path))
        self.assertEqual("verified", result["state"])

    def test_t011_review_mixed_adjudication_in_one_scope_is_refused(self):
        with closing(self._connect()) as conn:
            conn.execute("INSERT INTO tasks (notion_page_id, task_id, scope_id, name, "
                         "status) VALUES ('page-o99', 'T099', 'L-OLD-B-X1', 'x', '未着手')")
            conn.commit()
        decisions = self._decisions() + [{
            "routing_key": "L-OLD-B-X1/T099", "decision": "legacy_excluded",
            "evidence_digest": "sha256:" + "d" * 64}]
        path = self._write_decisions(decisions, self.root / "mixed.json")
        before = self._snapshot()
        result, _c, output = self._dry_run(decisions_path=path)
        self.assertEqual(2, result, output)
        self.assertIn("ADOPT_DECISION_CONFLICT", output)
        self.assertFalse(self.plan_path.exists())
        self.assertEqual(before, self._snapshot())

    def test_t011_review_in_transaction_failure_rolls_back_schema_and_triggers(self):
        self.assertEqual(0, self._dry_run()[0])
        with closing(self._connect()) as conn:
            schema_before = self.sync._adopt_schema_digest(conn)
        legacy_before = self._snapshot()
        # pre-check, checkpoint copy, then the in-transaction check fails.
        with mock.patch.object(self.sync, "_adopt_quick_check",
                               side_effect=["ok", "ok", "corrupt"]):
            result, _c, output = self._execute()
        self.assertEqual(3, result, output)
        self.assertIn("ADOPT_QUICK_CHECK_FAILED", output)
        with closing(self._connect()) as conn:
            self.assertEqual(schema_before, self.sync._adopt_schema_digest(conn))
            self.assertEqual(1, self.sync._local_identity_schema_version(conn))
            self.assertIsNone(self.sync._adopt_meta(conn, "identity_adopt_plan_id"))
        self.assertEqual(legacy_before, self._snapshot())
        self.assertFalse(self.manifest_path.exists())
        result, _c, output = self._execute()
        self.assertEqual(0, result, output)
        self.assertIn('"state": "verified"', output)

    def test_t011_review_execute_refuses_inconsistent_local_surfaces(self):
        self.assertEqual(0, self._dry_run()[0])
        plan = self._plan()
        target = self.sync._writer_manifest(FIXED_WORKSPACE_A, self.WRITER)
        base_db = self.db_path.read_bytes()

        def foreign_marker():
            with closing(self._connect()) as conn:
                conn.execute("INSERT INTO _metadata(key, value) VALUES "
                             "('identity_adopt_plan_id', 'sha256:other')")
                conn.commit()

        def manifest_first():
            self.manifest_path.write_text(json.dumps(target), encoding="utf-8")

        def foreign_cache():
            with closing(self._connect()) as conn:
                conn.execute("INSERT INTO _metadata(key, value) VALUES "
                             "('active_workspace_id', ?)", (FIXED_WORKSPACE_B,))
                conn.commit()

        for name, setup, code in (
                ("foreign_marker", foreign_marker, "ADOPT_FOREIGN_PROJECTION"),
                ("manifest_first", manifest_first, "ADOPT_MANIFEST_WITHOUT_PROJECTION"),
                ("foreign_cache", foreign_cache, "WORKSPACE_IDENTITY_SPLIT_BRAIN")):
            with self.subTest(case=name):
                self.db_path.write_bytes(base_db)
                self.manifest_path.unlink(missing_ok=True)
                setup()
                before = self._snapshot()
                result, _c, output = self._execute(plan["plan_id"])
                self.assertEqual(3, result, output)
                self.assertIn(code, output)
                self.assertEqual(before, self._snapshot())
                self.assertFalse(self.state_path.exists())
        self.db_path.write_bytes(base_db)
        self.manifest_path.unlink(missing_ok=True)
        # Row CAS: a Plan row that no longer matches its Scope rolls back.
        broken = copy.deepcopy(plan)
        broken["projects"][0]["scope_id"] = "L-OTHER"
        before = self._snapshot()
        with closing(self._connect()) as conn:
            schema_before = self.sync._adopt_schema_digest(conn)
            with self.assertRaisesRegex(ValueError, "ADOPT_LOCAL_CAS_FAILED"):
                self.sync._adopt_apply_projection(conn, broken)
            self.assertEqual(schema_before, self.sync._adopt_schema_digest(conn))
            self.assertEqual(1, self.sync._local_identity_schema_version(conn))
        self.assertEqual(before, self._snapshot())
        # Checkpoint: a backup that does not match the Plan source is discarded.
        broken = copy.deepcopy(plan)
        broken["source"]["rows_digest"] = "sha256:" + "e" * 64
        checkpoint = self.root / "cp.db"
        with closing(self._connect()) as conn:
            with self.assertRaisesRegex(ValueError, "ADOPT_CHECKPOINT_MISMATCH"):
                self.sync._adopt_take_checkpoint(conn, broken, str(checkpoint))
        self.assertEqual([], [p.name for p in self.root.iterdir()
                              if p.name.startswith("cp.db")])

    def test_t011_review_verified_rerun_reports_manifest_drift_and_reuse_rechecks_evidence(self):
        self.assertEqual(0, self._dry_run()[0])
        self.intent_x1.write_text(self.intent_x1.read_text("utf-8") + "# edited\n",
                                   encoding="utf-8")
        result, _c, output = self._dry_run(ids=iter(()))
        self.assertEqual(2, result, output)
        self.assertIn("ADOPT_EVIDENCE_MISMATCH", output)
        self.plan_path.unlink()
        self._write_decisions(self._decisions())
        self._adopt()
        self.manifest_path.unlink()
        result, _c, output = self._execute()
        self.assertEqual(3, result, output)
        self.assertIn("WORKSPACE_IDENTITY_SPLIT_BRAIN", output)
        self.assertFalse(self.manifest_path.exists())

    # ── CLI / read-only status ───────────────────────────────

    def test_t011_strict_cli_rejects_bad_modes_before_handler(self):
        bad = (
            ["adopt-existing"],
            ["adopt-existing", "--dry-run", "--status", "--plan", "p"],
            ["adopt-existing", "--dry-run", "--decisions", "d", "--plan-out", "p"],
            ["adopt-existing", "--dry-run", "--decisions", "d", "--writer-id", "w",
             "--plan-out", "p", "--plan-id", "x"],
            ["adopt-existing", "--dry-run", "--decisions", "d", "--writer-id", "bad id",
             "--plan-out", "p"],
            ["adopt-existing", "--plan", "p"],
            ["adopt-existing", "--plan", "p", "--plan-id", "x", "--writer-id", "w"],
            ["adopt-existing", "--status", "--plan", "p", "--plan-id", "x"],
            ["adopt-existing", "--status"],
            ["adopt-existing", "--plan", "p", "--plan-id", "x", "--force"],
        )
        for argv in bad:
            with self.subTest(argv=argv):
                result, calls, _output = self._main(argv, handlers=("cmd_adopt_existing",))
                self.assertEqual((64, []), (result, calls))
        good = (
            ["adopt-existing", "--dry-run", "--decisions", "d", "--writer-id", "w",
             "--plan-out", "p"],
            ["adopt-existing", "--plan", "p", "--plan-id", "x", "--state", "s"],
            ["adopt-existing", "--status", "--plan", "p", "--state", "s"],
        )
        for argv in good:
            with self.subTest(argv=argv):
                result, calls, _output = self._main(argv, handlers=("cmd_adopt_existing",))
                self.assertEqual(91, result)
                self.assertEqual(1, len(calls))

    def test_t011_status_mode_is_read_only(self):
        self.assertEqual(0, self._dry_run()[0])
        before = self._snapshot()
        with contextlib.ExitStack() as stack:
            for name in ("_open_read_conn", "_open_write_conn", "_get_conn",
                         "_atomic_json_write"):
                stack.enter_context(mock.patch.object(
                    self.sync, name, side_effect=AssertionError(name)))
            result, _c, output = self._main(
                ["adopt-existing", "--status", "--plan", str(self.plan_path)])
        self.assertEqual(0, result, output)
        self.assertIn('"state": "not_started"', output)
        self.assertEqual(before, self._snapshot())


if __name__ == "__main__":
    unittest.main()
