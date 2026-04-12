"""
Shared pytest fixtures for dbq test suite.

All fixtures use temp/in-memory databases so the real bootstrap.db
is never touched during test runs.
"""
import os
import tempfile
from pathlib import Path
from typing import Generator

import pytest

# Add the dbq parent directory to sys.path so `dbq` is importable as a package.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dbq.db import Database, open_db
from dbq.config import ProjectConfig


# ---------------------------------------------------------------------------
# Low-level DB fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_db_path(tmp_path: Path) -> Path:
    """Return a path to a non-existent (but writable) SQLite file."""
    return tmp_path / "test.db"


@pytest.fixture()
def empty_db(tmp_db_path: Path) -> Generator[Database, None, None]:
    """An open Database with all tables created but no rows."""
    db = Database(str(tmp_db_path))
    db.init_schema()
    db.migrate()
    yield db
    db.close()


@pytest.fixture()
def populated_db(empty_db: Database) -> Database:
    """A Database pre-populated with a small, realistic task set.

    Phase layout:
        P1-DISCOVER  T-01 (DONE, CLAUDE), T-02 (TODO, CLAUDE)
        P2-DESIGN    T-03 (TODO, CLAUDE, blocked_by T-02)
        P3-IMPLEMENT T-04 (TODO, MASTER)
    Loopback:
        LB-01 (TODO, loopback, origin=P1-DISCOVER, severity=3)
    """
    db = empty_db
    tasks = [
        # (id, phase, title, status, assignee, blocked_by, sort_order, tier, track, origin_phase, severity, gate_critical)
        ("T-01", "P1-DISCOVER", "Audit templates", "DONE",  "CLAUDE", None, 1,   "haiku",  "forward", None, 3, 0),
        ("T-02", "P1-DISCOVER", "Extract patterns", "TODO", "CLAUDE", None, 2,   "sonnet", "forward", None, 3, 0),
        ("T-03", "P2-DESIGN",   "Design changes",   "TODO", "CLAUDE", "T-02", 1, "sonnet", "forward", None, 3, 0),
        ("T-04", "P3-IMPLEMENT","Master review",    "TODO", "MASTER", None, 1,   None,     "forward", None, 3, 0),
        ("LB-01","P1-DISCOVER", "Fix broken ref",  "TODO", "CLAUDE", None, 999, "haiku",  "loopback","P1-DISCOVER", 3, 0),
    ]
    for (tid, phase, title, status, assignee, blocked_by, sort_order,
         tier, track, origin_phase, severity, gate_critical) in tasks:
        db.execute(
            "INSERT INTO tasks "
            "(id, phase, title, status, assignee, blocked_by, sort_order, "
            "tier, track, origin_phase, severity, gate_critical, queue) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'A')",
            (tid, phase, title, status, assignee, blocked_by, sort_order,
             tier, track, origin_phase, severity, gate_critical),
        )
    db.commit()
    return db


# ---------------------------------------------------------------------------
# Config fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def simple_config(tmp_db_path: Path) -> ProjectConfig:
    """Minimal ProjectConfig pointing at a temp DB."""
    return ProjectConfig(
        db_path=str(tmp_db_path),
        project_name="test-project",
        phases=["P1-DISCOVER", "P2-DESIGN", "P3-IMPLEMENT"],
    )


@pytest.fixture()
def populated_config(tmp_db_path: Path, populated_db: Database) -> ProjectConfig:
    """Config whose db_path points at the populated_db file."""
    return ProjectConfig(
        db_path=str(tmp_db_path),
        project_name="test-project",
        phases=["P1-DISCOVER", "P2-DESIGN", "P3-IMPLEMENT"],
    )


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolate_db_env(tmp_db_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Override DB_OVERRIDE so any detect_config() call uses the temp DB.

    Also clears DBQ_PHASES / DBQ_PROJECT_NAME to avoid interference from
    the real wrapper environment (if tests are run via db_queries.sh).
    """
    monkeypatch.setenv("DB_OVERRIDE", str(tmp_db_path))
    monkeypatch.delenv("DBQ_PHASES", raising=False)
    monkeypatch.delenv("DBQ_PROJECT_NAME", raising=False)
    monkeypatch.delenv("DBQ_LESSONS_FILE", raising=False)
