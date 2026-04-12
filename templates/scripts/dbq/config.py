"""
Project configuration — env-var driven when launched via the bash wrapper,
auto-detecting when run standalone (e.g. testing, direct python -m dbq).

Env vars set by the wrapper (db_queries.sh):
    DB_OVERRIDE       — absolute path to the SQLite database
    DBQ_PROJECT_NAME  — human-readable project name
    DBQ_LESSONS_FILE  — path to LESSONS*.md
    DBQ_PHASES        — space-separated phase list (e.g. "P1-PLAN P2-BUILD")
"""
import os
from pathlib import Path
from typing import Dict, List, Optional


class ProjectConfig:
    """Runtime configuration for a project's database CLI."""

    def __init__(
        self,
        db_path: str,
        project_name: str = "",
        lessons_file: str = "",
        phases: Optional[List[str]] = None,
    ):
        self.db_path = Path(db_path)
        self.project_dir = self.db_path.parent
        self.project_name = project_name or self.db_path.stem
        self.lessons_file = lessons_file
        self.phases = phases or []
        # Build ordinal map: {"P1-PLAN": 0, "P2-BUILD": 1, ...}
        self.phase_ordinals: Dict[str, int] = {
            p: i for i, p in enumerate(self.phases)
        }

    def phase_ordinal(self, phase: str) -> int:
        """Return ordinal for a phase name, 99 if unknown."""
        return self.phase_ordinals.get(phase, 99)

    def phase_case_sql(self) -> str:
        """Generate SQL CASE arms for phase scoring.

        Returns e.g.: "WHEN 'P1-PLAN' THEN 0 WHEN 'P2-BUILD' THEN 1"
        """
        return " ".join(
            f"WHEN '{phase}' THEN {i}" for i, phase in enumerate(self.phases)
        )

    def phase_in_sql(self) -> str:
        """Generate SQL IN list for valid phases.

        Returns e.g.: "'P1-PLAN', 'P2-BUILD', 'P3-POLISH'"
        """
        return ", ".join(f"'{p}'" for p in self.phases)


def detect_config(db_path_override: Optional[str] = None) -> ProjectConfig:
    """Build config from env vars (wrapper) or auto-detect (standalone).

    Resolution order for DB path:
    1. Explicit db_path_override argument
    2. DB_OVERRIDE env var
    3. Look for *.db in current directory
    4. Look for *.db in script directory

    Phases / project name / lessons file:
    - If DBQ_PHASES env var is set, use it (wrapper mode)
    - Otherwise, auto-detect from DB contents and filesystem
    """
    db_path = db_path_override or os.environ.get("DB_OVERRIDE")

    if not db_path:
        # Try current directory
        cwd = Path.cwd()
        dbs = list(cwd.glob("*.db"))
        if len(dbs) == 1:
            db_path = str(dbs[0])

    if not db_path:
        # Try script directory
        script_dir = Path(__file__).parent.parent
        dbs = list(script_dir.glob("*.db"))
        if len(dbs) == 1:
            db_path = str(dbs[0])

    if not db_path:
        raise SystemExit(
            "No database found. Set DB_OVERRIDE or run from a project directory."
        )

    db = Path(db_path)
    if not db.exists() and not _is_init_command():
        raise SystemExit(
            f"Database not found: {db}\n"
            f"   Create it: python -m dbq init-db"
        )

    # -- Phases: prefer env var, fall back to DB query --
    env_phases = os.environ.get("DBQ_PHASES", "").strip()
    if env_phases and not _looks_like_placeholder(env_phases):
        phases = env_phases.split()
    elif db.exists():
        phases = _detect_phases_from_db(db)
    else:
        phases = []

    # -- Project name: prefer env var --
    env_name = os.environ.get("DBQ_PROJECT_NAME", "").strip()
    if env_name and not _looks_like_placeholder(env_name):
        project_name = env_name
    else:
        project_name = ""

    # -- Lessons file: prefer env var --
    env_lessons = os.environ.get("DBQ_LESSONS_FILE", "").strip()
    if env_lessons and not _looks_like_placeholder(env_lessons):
        lessons_file = env_lessons
    else:
        project_dir = db.parent
        lessons_candidates = list(project_dir.glob("LESSONS*.md"))
        lessons_file = str(lessons_candidates[0]) if lessons_candidates else ""

    return ProjectConfig(
        db_path=str(db),
        project_name=project_name,
        phases=phases,
        lessons_file=lessons_file,
    )


def _looks_like_placeholder(value: str) -> bool:
    """Return True if value is an unresolved %%PLACEHOLDER%%."""
    return value.startswith("%%") and value.endswith("%%")


def _detect_phases_from_db(db: Path) -> List[str]:
    """Query distinct phases from the tasks table."""
    import sqlite3
    try:
        conn = sqlite3.connect(str(db))
        rows = conn.execute(
            "SELECT DISTINCT phase FROM tasks ORDER BY phase"
        ).fetchall()
        conn.close()
        return [r[0] for r in rows]
    except sqlite3.Error:
        return []


def _is_init_command() -> bool:
    """Check if we're running init-db (which creates the DB)."""
    import sys
    return "init-db" in sys.argv or "init_db" in sys.argv
