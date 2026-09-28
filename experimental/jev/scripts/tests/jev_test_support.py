"""Test helper (not a test module): run jev_client's do-not-send check with a fixed, fictional word list.

The real environment-specific list (<repo>/.claude/db/jev_redact_extra.txt) and $JEV_REDACT_EXTRA are never read
while isolated, so the tests give the same result in any checkout (including the public one).

Usage in a test module:
    import jev_test_support as jts
    def setUpModule(): jts.isolate()
    def tearDownModule(): jts.restore()
Call jts.isolate() again after importlib.reload(jev_client), because a reload rebuilds the default list.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jev_client  # noqa: E402

# Fictional environment-specific words, written the way a real local file would be.
TEST_EXTRA_LINES = [
    "# fictional words used by the tests",
    "",
    "zetaproj",
    "ゼータ案件",
    r"L-9999(?:-\d+)?",
    "FakePerson",
    r"(?<![A-Za-z])zetagame(?![A-Za-z])",
]

_tmp = None


def extra_path():
    global _tmp
    if _tmp is None:
        _tmp = tempfile.TemporaryDirectory()
    p = Path(_tmp.name) / "jev_redact_extra.txt"
    if not p.exists():
        p.write_text("\n".join(TEST_EXTRA_LINES) + "\n", encoding="utf-8")
    return p


def isolate():
    """Base list + the fictional extra file only (no real local file, no $JEV_REDACT_EXTRA)."""
    return jev_client.load_redact_patterns(local_path=extra_path(), env_path=None)


def restore():
    """Back to the normal behaviour (real local file and $JEV_REDACT_EXTRA, when present)."""
    return jev_client.load_redact_patterns()
