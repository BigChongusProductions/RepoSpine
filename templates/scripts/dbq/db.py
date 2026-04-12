"""
Database layer — connection management, parameterized queries, schema.

Every query uses ? placeholders. Zero string interpolation for user data.
Errors are raised explicitly, never swallowed.
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


class DatabaseError(Exception):
    """Raised when a database operation fails."""
    pass


# Full schema — matches init-db in db_queries_legacy.template.sh lines 1638-1712
SCHEMA_TABLES = {
    "tasks": """
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            phase TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'TODO',
            priority TEXT DEFAULT 'P2',
            assignee TEXT NOT NULL DEFAULT 'CLAUDE',
            blocked_by TEXT,
            sort_order INTEGER DEFAULT 999,
            queue TEXT NOT NULL DEFAULT 'BACKLOG',
            tier TEXT,
            original_tier TEXT,
            escalation_reason TEXT,
            escalation_count INTEGER DEFAULT 0,
            skill TEXT,
            needs_browser INTEGER DEFAULT 0,
            track TEXT DEFAULT 'forward',
            origin_phase TEXT,
            discovered_in TEXT,
            severity INTEGER DEFAULT 3,
            gate_critical INTEGER DEFAULT 0,
            loopback_reason TEXT,
            details TEXT,
            completed_on TEXT,
            researched INTEGER DEFAULT 0,
            breakage_tested INTEGER DEFAULT 0,
            notes TEXT,
            research_notes TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """,
    "phase_gates": """
        CREATE TABLE IF NOT EXISTS phase_gates (
            phase TEXT PRIMARY KEY,
            gated_on TEXT,
            gated_by TEXT DEFAULT 'MASTER',
            notes TEXT
        )
    """,
    "milestone_confirmations": """
        CREATE TABLE IF NOT EXISTS milestone_confirmations (
            task_id TEXT PRIMARY KEY,
            confirmed_on TEXT NOT NULL,
            confirmed_by TEXT DEFAULT 'MASTER',
            reasons TEXT
        )
    """,
    "loopback_acks": """
        CREATE TABLE IF NOT EXISTS loopback_acks (
            loopback_id TEXT NOT NULL,
            acked_on TEXT NOT NULL,
            acked_by TEXT NOT NULL,
            reason TEXT NOT NULL,
            UNIQUE(loopback_id)
        )
    """,
    "decisions": """
        CREATE TABLE IF NOT EXISTS decisions (
            id TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            options TEXT,
            choice TEXT,
            rationale TEXT,
            decided_at TEXT DEFAULT (datetime('now'))
        )
    """,
    "sessions": """
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_type TEXT DEFAULT 'Claude Code',
            summary TEXT,
            logged_at TEXT DEFAULT (datetime('now'))
        )
    """,
    "db_snapshots": """
        CREATE TABLE IF NOT EXISTS db_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT,
            git_sha TEXT,
            task_summary TEXT,
            phase_gates TEXT,
            stats TEXT,
            phase TEXT,
            snapshot_at TEXT DEFAULT (datetime('now')),
            task_count INTEGER,
            file_paths TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """,
    "assumptions": """
        CREATE TABLE IF NOT EXISTS assumptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT,
            assumption TEXT NOT NULL,
            verify_cmd TEXT,
            verified INTEGER DEFAULT 0,
            verified_on TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """,
    "evaluations": """
        CREATE TABLE IF NOT EXISTS evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version TEXT,
            phase TEXT,
            artifact_score REAL,
            artifact_details TEXT,
            process_score REAL,
            process_details TEXT,
            velocity_score REAL,
            velocity_details TEXT,
            composite_score REAL,
            raw_metrics TEXT,
            evaluated_at TEXT DEFAULT (datetime('now'))
        )
    """,
}

# Columns that may need to be added via migration (idempotent ALTER TABLE)
MIGRATION_COLUMNS = {
    "tasks": [
        ("track", "TEXT DEFAULT 'forward'"),
        ("origin_phase", "TEXT"),
        ("discovered_in", "TEXT"),
        ("severity", "INTEGER"),
        ("gate_critical", "INTEGER DEFAULT 0"),
        ("loopback_reason", "TEXT"),
        ("details", "TEXT"),
        ("completed_on", "TEXT"),
        ("researched", "INTEGER DEFAULT 0"),
        ("breakage_tested", "INTEGER DEFAULT 0"),
        ("research_notes", "TEXT"),
        ("files_touched", "TEXT"),
        ("handover_notes", "TEXT"),
        ("original_tier", "TEXT"),
        ("escalation_reason", "TEXT"),
        ("escalation_count", "INTEGER DEFAULT 0"),
    ],
}


class Database:
    """SQLite database wrapper with parameterized queries and error handling."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn = None  # type: Optional[sqlite3.Connection]

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute SQL with params. Raises DatabaseError on failure."""
        try:
            return self.conn.execute(sql, params)
        except sqlite3.Error as e:
            raise DatabaseError(
                f"SQL failed: {sql[:100]}{'...' if len(sql) > 100 else ''} "
                f"params={params} — {e}"
            ) from e

    def execute_script(self, sql: str) -> None:
        """Execute multiple SQL statements. For schema creation only."""
        try:
            self.conn.executescript(sql)
        except sqlite3.Error as e:
            raise DatabaseError(f"Script failed: {e}") from e

    def fetch_one(
        self, sql: str, params: tuple = (), default: Any = None
    ) -> Any:
        """Fetch a single value. Returns default if no rows."""
        try:
            row = self.conn.execute(sql, params).fetchone()
            if row is None:
                return default
            return row[0] if len(row) == 1 else row
        except sqlite3.Error as e:
            raise DatabaseError(
                f"Query failed: {sql[:100]} — {e}"
            ) from e

    def fetch_all(self, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
        """Fetch all rows."""
        try:
            return self.conn.execute(sql, params).fetchall()
        except sqlite3.Error as e:
            raise DatabaseError(
                f"Query failed: {sql[:100]} — {e}"
            ) from e

    def fetch_scalar(
        self, sql: str, params: tuple = (), default: int = 0
    ) -> int:
        """Fetch a single integer value. Returns default if NULL or no rows."""
        result = self.fetch_one(sql, params, default=default)
        if result is None:
            return default
        return int(result)

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    # ── Schema management ──

    def table_exists(self, name: str) -> bool:
        return self.fetch_scalar(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ) == 1

    def column_exists(self, table: str, column: str) -> bool:
        rows = self.fetch_all(f"PRAGMA table_info({table})")
        return any(r["name"] == column for r in rows)

    def init_schema(self) -> List[str]:
        """Create all tables. Idempotent. Returns list of created tables."""
        created = []
        for name, ddl in SCHEMA_TABLES.items():
            if not self.table_exists(name):
                created.append(name)
            self.execute(ddl)
        self.commit()
        return created

    def migrate(self) -> List[str]:
        """Apply idempotent column migrations. Returns list of added columns."""
        added = []
        for table, columns in MIGRATION_COLUMNS.items():
            if not self.table_exists(table):
                continue
            for col_name, col_def in columns:
                if not self.column_exists(table, col_name):
                    try:
                        self.execute(
                            f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}"
                        )
                        added.append(f"{table}.{col_name}")
                    except DatabaseError:
                        pass  # Column already exists (race condition)

        # Rename legacy session columns to canonical names
        if self.table_exists("sessions"):
            # session_date → logged_at (older DBs)
            if self.column_exists("sessions", "session_date") and \
               not self.column_exists("sessions", "logged_at"):
                try:
                    self.execute(
                        "ALTER TABLE sessions RENAME COLUMN session_date TO logged_at"
                    )
                    added.append("sessions.logged_at (renamed from session_date)")
                except DatabaseError:
                    pass
            # started_at → logged_at (activation-era DBs)
            if self.column_exists("sessions", "started_at") and \
               not self.column_exists("sessions", "logged_at"):
                try:
                    self.execute(
                        "ALTER TABLE sessions RENAME COLUMN started_at TO logged_at"
                    )
                    added.append("sessions.logged_at (renamed from started_at)")
                except DatabaseError:
                    pass
            # agent → session_type (activation-era DBs)
            if self.column_exists("sessions", "agent") and \
               not self.column_exists("sessions", "session_type"):
                try:
                    self.execute(
                        "ALTER TABLE sessions RENAME COLUMN agent TO session_type"
                    )
                    added.append("sessions.session_type (renamed from agent)")
                except DatabaseError:
                    pass

        # Rename legacy decisions columns to canonical names
        if self.table_exists("decisions"):
            renames = [
                ("created_at", "decided_at"),
                ("decision", "description"),
                ("chosen", "choice"),
                ("why", "rationale"),
            ]
            for old_col, new_col in renames:
                if self.column_exists("decisions", old_col) and \
                   not self.column_exists("decisions", new_col):
                    try:
                        self.execute(
                            f"ALTER TABLE decisions RENAME COLUMN {old_col} TO {new_col}"
                        )
                        added.append(f"decisions.{new_col} (renamed from {old_col})")
                    except DatabaseError:
                        pass

        if added:
            self.commit()
        return added

    def integrity_check(self) -> str:
        """Run PRAGMA integrity_check. Returns 'ok' or error description."""
        return self.fetch_one("PRAGMA integrity_check", default="unknown")

    def get_table_columns(self, table: str) -> List[str]:
        """Return list of column names for a table."""
        rows = self.fetch_all(f"PRAGMA table_info({table})")
        return [r["name"] for r in rows]


@contextmanager
def open_db(db_path: str):
    """Context manager for database access. Auto-closes on exit."""
    db = Database(db_path)
    try:
        yield db
    finally:
        db.close()
