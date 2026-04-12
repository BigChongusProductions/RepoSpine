"""
Health & recovery commands: init-db, health, backup, restore, verify.
"""
import json
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from ..db import Database, DatabaseError, SCHEMA_TABLES
from ..config import ProjectConfig
from .. import output


def cmd_init_db(db: Database):
    """Create all tables. Idempotent — safe to run multiple times.

    Matches db_queries_legacy.template.sh lines 1631-1717.
    """
    from pathlib import Path

    db_path = Path(db.db_path)
    if not db_path.exists():
        db_path.touch()
        print(f"  Created {db_path.name}")

    print(
        output.section_header(
            f"Initializing {db_path.name} schema"
        )
    )

    # This reconnects to the now-existing file
    created = db.init_schema()

    # Print table list matching bash output format
    print(
        "  ✅ Schema ready. Tables: tasks, phase_gates, "
        "milestone_confirmations, loopback_acks,"
    )
    print("     decisions, sessions, db_snapshots, assumptions")
    print("")


def _semgrep_env(project_dir: Path) -> dict:
    """Build a hardened environment for Semgrep execution.

    Respects caller-provided values for SSL_CERT_FILE, SEMGREP_LOG_FILE,
    SEMGREP_SETTINGS_FILE, and SEMGREP_VERSION_CACHE_PATH. Otherwise
    auto-populates to avoid trust-store/X509 crashes and ~/.semgrep
    write failures in restricted environments.
    """
    import os

    env = os.environ.copy()

    # SSL certificate bundle — try common locations
    if "SSL_CERT_FILE" not in env:
        cert_candidates = [
            "/etc/ssl/cert.pem",
            "/private/etc/ssl/cert.pem",
            "/opt/homebrew/etc/openssl@3/cert.pem",
            "/opt/homebrew/etc/ca-certificates/cert.pem",
            "/etc/ssl/certs/ca-certificates.crt",
        ]
        for candidate in cert_candidates:
            if Path(candidate).is_file():
                env["SSL_CERT_FILE"] = candidate
                break

    # Redirect Semgrep user-data to project hooks dir (avoids ~/.semgrep writes)
    hooks_dir = project_dir / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    if "SEMGREP_LOG_FILE" not in env:
        env["SEMGREP_LOG_FILE"] = str(hooks_dir / "semgrep.log")
    if "SEMGREP_SETTINGS_FILE" not in env:
        env["SEMGREP_SETTINGS_FILE"] = str(hooks_dir / "semgrep-settings.yml")
    if "SEMGREP_VERSION_CACHE_PATH" not in env:
        env["SEMGREP_VERSION_CACHE_PATH"] = str(hooks_dir / "semgrep-version-cache")

    env.setdefault("SEMGREP_VERSION_CHECK_TIMEOUT", "1")

    return env


def _check_sast(project_dir: Path) -> Tuple[str, str]:
    """Run a Semgrep SAST check on the project directory and return a signal tuple.

    Returns a tuple of (state, detail) where state is one of:
        "skip"          — semgrep binary absent or .semgrep/ dir missing (silent)
        "sast_clean"    — semgrep ran and found zero S1/S2 findings
        "sast_findings" — semgrep found S1 and/or S2 findings
        "sast_error"    — semgrep exited non-zero or produced unparseable output

    detail is a human-readable description of the result.

    Severity mapping (semgrep native → S-scale):
        ERROR   → S1 (critical — blocks forward work)
        WARNING → S2 (major — significant defect)
        INFO    → S3/S4 (not counted by this check)

    Thresholds (consistent with pre-commit.template.sh and quality-gates.md):
        Any S1 (ERROR)  → sast_findings (triggers CRITICAL in caller)
        1–3 S2 (WARNING) → sast_findings (triggers WARNING in caller)
        S3/S4 only       → sast_clean
    """
    # Graceful degradation: skip if semgrep binary not on PATH
    if not shutil.which("semgrep"):
        return ("skip", "semgrep not installed")

    # Graceful degradation: skip if no .semgrep/ config directory
    semgrep_dir = project_dir / ".semgrep"
    if not semgrep_dir.is_dir():
        return ("skip", "no .semgrep/ config directory")

    env = _semgrep_env(project_dir)

    # Point --config at individual rule files, not the directory.
    # The .semgrep/ dir may contain non-rule files (settings.yml, logs)
    # that cause semgrep to fail with "invalid configuration file".
    import glob as _glob
    rule_files = sorted(_glob.glob(str(semgrep_dir / "*.yaml")))
    if not rule_files:
        return ("skip", "no .yaml rule files in .semgrep/")

    cmd = ["semgrep", "--json", "--quiet"]
    for rf in rule_files:
        cmd.extend(["--config", rf])
    cmd.append(str(project_dir))

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(project_dir),
            env=env,
        )
    except subprocess.TimeoutExpired:
        return ("sast_error", "semgrep timed out after 60s")
    except OSError as exc:
        return ("sast_error", f"semgrep failed to launch: {exc}")

    # semgrep exits 0 (clean), 1 (findings), or 2+ (error/crash)
    if proc.returncode not in (0, 1):
        stderr_lower = (proc.stderr or "").lower()
        if "x509" in stderr_lower or "certificate" in stderr_lower or "trust" in stderr_lower:
            return ("sast_error", "Semgrep startup failed: certificate bundle unavailable")
        if "permission" in stderr_lower or "errno" in stderr_lower or ".semgrep" in stderr_lower:
            return ("sast_error", "Semgrep startup failed: user data path not writable")
        detail = f"semgrep exited {proc.returncode}"
        stderr_snippet = (proc.stderr or "").strip()
        if stderr_snippet:
            # Truncate to avoid flooding the health output
            detail += f": {stderr_snippet[:120]}"
        return ("sast_error", detail)

    # Parse JSON output
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return ("sast_error", "semgrep produced non-JSON output")

    results = data.get("results", [])

    s1_count = sum(
        1 for r in results
        if (r.get("extra", {}).get("severity") or "").upper() == "ERROR"
    )
    s2_count = sum(
        1 for r in results
        if (r.get("extra", {}).get("severity") or "").upper() == "WARNING"
    )

    if s1_count == 0 and s2_count == 0:
        return ("sast_clean", f"{len(results)} finding(s), none S1/S2")

    parts = []
    if s1_count > 0:
        parts.append(f"{s1_count} S1 (ERROR)")
    if s2_count > 0:
        parts.append(f"{s2_count} S2 (WARNING)")
    return ("sast_findings", ", ".join(parts))


def cmd_health(db: Database, config):
    """Pipeline health diagnostic — comprehensive integrity check.

    Returns exit code: 0 for HEALTHY/DEGRADED, 1 for CRITICAL.
    Matches db_queries_legacy.template.sh lines 1719-1842.

    OUTPUT CONTRACT:
        session_briefing.template.sh:53 does `tail -3 | head -2`
        The last 3 lines MUST be: blank, verdict, blank.
        session-start-check.template.sh:62 greps for error|fail|corrupt.
    """
    warnings = 0
    criticals = 0

    print("")
    print(output.section_header("Pipeline Health Check"))

    # 1. SQLite integrity check
    integrity = db.integrity_check()
    if integrity == "ok":
        print("  ✅ SQLite integrity: ok")
    else:
        print("  ❌ SQLite integrity: FAILED")
        print(f"     {integrity}")
        criticals += 1
        # Early exit — all other checks unreliable on corrupt DB
        output.health_verdict(criticals, warnings)
        sys.exit(1)

    # 2. Table existence
    expected_tables = [
        "tasks", "phase_gates", "decisions", "sessions",
        "milestone_confirmations", "db_snapshots", "assumptions",
        "loopback_acks",
    ]
    for tbl in expected_tables:
        if not db.table_exists(tbl):
            print(f"  ❌ Missing table: {tbl}")
            criticals += 1
    if criticals == 0:
        print("  ✅ Required tables: all present")

    # 3. Schema columns on tasks table
    expected_cols = [
        "id", "phase", "queue", "assignee", "title", "priority", "status",
        "blocked_by", "sort_order", "tier", "skill", "track", "origin_phase",
        "severity", "gate_critical",
    ]
    if db.table_exists("tasks"):
        actual_cols = db.get_table_columns("tasks")
        missing_cols = [c for c in expected_cols if c not in actual_cols]
        if not missing_cols:
            print(f"  ✅ Schema columns: all {len(expected_cols)} present")
        else:
            print(f"  ⚠️  Missing columns: {' '.join(missing_cols)}")
            warnings += 1

    # 4. Data integrity checks (only if tasks table exists)
    if db.table_exists("tasks"):
        # 4a. Duplicate task IDs (shouldn't happen with PRIMARY KEY, but check)
        dupes = db.fetch_scalar(
            "SELECT COUNT(*) FROM "
            "(SELECT id FROM tasks GROUP BY id HAVING COUNT(*) > 1)"
        )
        if dupes > 0:
            print(f"  ❌ Duplicate task IDs: {dupes}")
            criticals += 1

        # 4b. Circular dependencies (A blocks B, B blocks A)
        circular = db.fetch_scalar(
            "SELECT COUNT(*) FROM tasks a "
            "JOIN tasks b ON a.blocked_by = b.id AND b.blocked_by = a.id"
        )
        if circular > 0:
            print(f"  ❌ Circular dependencies: {circular}")
            criticals += 1

        # 4c. Broken blocked_by references (supports multi-ID fields)
        rows_with_blockers = db.fetch_all(
            "SELECT id, blocked_by FROM tasks "
            "WHERE blocked_by IS NOT NULL AND blocked_by != '' "
            "AND blocked_by != '—'"
        )
        broken_refs = 0
        for row in rows_with_blockers:
            for bid in row["blocked_by"].split():
                exists = db.fetch_scalar(
                    "SELECT COUNT(*) FROM tasks WHERE id = ?", (bid,)
                )
                if exists == 0:
                    broken_refs += 1
        if broken_refs > 0:
            print(f"  ⚠️  Broken blocked_by refs: {broken_refs}")
            warnings += 1

        # 4d. Unknown phases
        if config.phases:
            placeholders = ",".join("?" for _ in config.phases)
            unknown_ph = db.fetch_scalar(
                f"SELECT COUNT(*) FROM tasks WHERE phase NOT IN ({placeholders})",
                tuple(config.phases),
            )
            if unknown_ph > 0:
                print(f"  ⚠️  Unknown phases: {unknown_ph}")
                warnings += 1

        # 4e. Invalid statuses
        valid_statuses = ("TODO", "DONE", "SKIP", "MASTER", "WONTFIX", "IN_PROGRESS")
        placeholders = ",".join("?" for _ in valid_statuses)
        invalid_st = db.fetch_scalar(
            f"SELECT COUNT(*) FROM tasks WHERE status NOT IN ({placeholders})",
            valid_statuses,
        )
        if invalid_st > 0:
            print(f"  ⚠️  Invalid statuses: {invalid_st}")
            warnings += 1

        # 4f. Loopbacks missing origin_phase
        if db.column_exists("tasks", "track"):
            lb_no_orig = db.fetch_scalar(
                "SELECT COUNT(*) FROM tasks "
                "WHERE track='loopback' AND "
                "(origin_phase IS NULL OR origin_phase = '')"
            )
            if lb_no_orig > 0:
                print(f"  ⚠️  Loopbacks missing origin_phase: {lb_no_orig}")
                warnings += 1

        # 4g. Orphaned phase gates
        if db.table_exists("phase_gates"):
            orphan_gates = db.fetch_scalar(
                "SELECT COUNT(*) FROM phase_gates pg "
                "WHERE NOT EXISTS "
                "(SELECT 1 FROM tasks t WHERE t.phase = pg.phase)"
            )
            if orphan_gates > 0:
                print(f"  ⚠️  Orphaned phase gates: {orphan_gates}")
                warnings += 1

    # 5. SAST check (Semgrep)
    #    Three states: skip (silent), sast_clean, sast_findings, sast_error
    #    Failure ≠ clean: a non-zero semgrep exit is reported as WARNING, never silently passed.
    sast_state, sast_detail = _check_sast(config.project_dir)
    if sast_state == "skip":
        pass  # No .semgrep/ or binary absent — do not print anything
    elif sast_state == "sast_clean":
        print(f"  ✅ SAST: clean ({sast_detail})")
    elif sast_state == "sast_error":
        print(f"  ⚠️  SAST check failed: {sast_detail}")
        warnings += 1
    elif sast_state == "sast_findings":
        # Parse S1/S2 counts from detail string to decide severity
        if "S1" in sast_detail:
            print(f"  ❌ SAST: S1 findings detected: {sast_detail}")
            criticals += 1
        else:
            print(f"  ⚠️  SAST: S2 findings detected: {sast_detail}")
            warnings += 1

    # 6. Lint checks (structural — fast subset)
    from .lint import quick_lint
    lint_warnings, lint_errors = quick_lint(config)
    if lint_errors > 0:
        print(f"  \u274c Lint: {lint_errors} error(s)")
        criticals += lint_errors
    elif lint_warnings > 0:
        print(f"  \u26a0\ufe0f  Lint: {lint_warnings} warning(s)")
        warnings += lint_warnings
    else:
        print(f"  \u2705 Lint: clean")

    # Verdict — OUTPUT CONTRACT: last 3 lines must be \n verdict \n
    output.health_verdict(criticals, warnings)

    # Write health cache for hooks (avoids subprocess spawn in time-critical hooks)
    exit_code = 1 if criticals > 0 else 0
    verdict = (
        f"CRITICAL ({criticals} critical, {warnings} warnings)"
        if criticals > 0
        else f"DEGRADED ({warnings} warnings)"
        if warnings > 0
        else "HEALTHY (0 warnings)"
    )
    try:
        cache_path = config.project_dir / ".claude" / "hooks" / ".health_cache"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(f"{int(time.time())}|{exit_code}|{verdict}")
    except OSError:
        pass  # Non-critical — hooks will just skip the cache

    if criticals > 0:
        sys.exit(1)


# ── backup command ──────────────────────────────────────────────────

def cmd_backup(db: Database, config: ProjectConfig):
    """Backup DB to backups/ directory with rotation (keep last 10).

    Matches db_queries_legacy.template.sh lines 1844-1892.
    Uses SQLite's native backup via .backup command for WAL safety.
    """
    backup_dir = config.project_dir / "backups"
    backup_dir.mkdir(exist_ok=True)

    # Check integrity before backup
    integrity = db.integrity_check()
    if integrity != "ok":
        print("❌ DB integrity check failed — refusing to backup corrupt data")
        print("   Run: bash db_queries.sh health")
        sys.exit(1)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    db_name = Path(db.db_path).stem
    backup_file = backup_dir / f"{db_name}-{timestamp}.db"

    # Flush WAL to main file before copying (ensures consistent backup)
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    # Use SQLite backup API via a separate connection for safe copy
    import sqlite3 as _sqlite3
    src_conn = _sqlite3.connect(db.db_path)
    dst_conn = _sqlite3.connect(str(backup_file))
    src_conn.backup(dst_conn)
    dst_conn.close()
    src_conn.close()

    if not backup_file.exists():
        print("❌ Backup failed")
        sys.exit(1)

    # Verify backup integrity
    try:
        conn = sqlite3.connect(str(backup_file))
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        conn.close()
    except sqlite3.Error:
        result = "failed"

    if result != "ok":
        print("❌ Backup file failed integrity check — removing")
        backup_file.unlink()
        sys.exit(1)

    # Count tasks in backup
    try:
        conn = sqlite3.connect(str(backup_file))
        task_count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        conn.close()
    except sqlite3.Error:
        task_count = "?"

    backup_size = backup_file.stat().st_size
    size_str = _format_size(backup_size)

    # Rotation: keep last 10
    pattern = f"{db_name}-*.db"
    existing = sorted(backup_dir.glob(pattern), key=lambda p: p.stat().st_mtime)
    if len(existing) > 10:
        for old in existing[:-10]:
            old.unlink()
    backup_count = min(len(existing), 10)

    print(f"✅ Backup created: {backup_file.name}")
    print(f"   Size: {size_str} | Tasks: {task_count} | Backups: {backup_count}/10")


# ── restore command ─────────────────────────────────────────────────

def cmd_restore(db: Database, config: ProjectConfig, restore_file: Optional[str] = None):
    """Restore DB from backup. Lists backups if no file given.

    Matches db_queries_legacy.template.sh lines 1894-1961.
    """
    backup_dir = config.project_dir / "backups"
    db_name = Path(db.db_path).stem

    if not restore_file:
        # List available backups
        output.print_section("Available Backups")

        pattern = f"{db_name}-*.db"
        backups = sorted(backup_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True) if backup_dir.exists() else []

        if not backups:
            print(f"  No backups found in {backup_dir}/")
            db_basename = Path(db.db_path).name
            print(f"  Recovery option: git checkout -- {db_basename}")
            return

        print("")
        for bf in backups:
            size_str = _format_size(bf.stat().st_size)
            try:
                conn = sqlite3.connect(str(bf))
                tc = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
                conn.close()
            except sqlite3.Error:
                tc = "?"
            print(f"  {bf.name}  ({size_str}, {tc} tasks)")
        print("")
        print("Usage: bash db_queries.sh restore <filename>")
        print("  (filename only — resolved relative to backups/)")
        return

    # Resolve backup file path
    rf = Path(restore_file)
    if not rf.exists():
        rf = backup_dir / restore_file
    if not rf.exists():
        print(f"❌ Backup file not found: {restore_file}")
        print(f"   Tried: {restore_file} and {backup_dir / restore_file}")
        print("   Run: bash db_queries.sh restore  (to list available backups)")
        sys.exit(1)

    # Validate backup integrity
    try:
        conn = sqlite3.connect(str(rf))
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        restore_tasks = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        conn.close()
    except sqlite3.Error as e:
        print(f"❌ Backup file failed integrity check — refusing to restore corrupt data")
        sys.exit(1)

    if result != "ok":
        print("❌ Backup file failed integrity check — refusing to restore corrupt data")
        sys.exit(1)

    # Safety backup of current DB before overwriting
    backup_dir.mkdir(exist_ok=True)
    safety_ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    safety_file = backup_dir / f"pre-restore-{safety_ts}.db"
    shutil.copy2(db.db_path, str(safety_file))
    print(f"  Safety backup: {safety_file.name}")

    # Close current connection, restore, then verify
    db.close()
    shutil.copy2(str(rf), db.db_path)

    # Verify post-restore
    try:
        conn = sqlite3.connect(db.db_path)
        post_tasks = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        conn.close()
    except sqlite3.Error:
        post_tasks = "?"

    if str(post_tasks) == str(restore_tasks):
        print(f"✅ Restored from: {rf.name}")
        print(f"   Tasks: {post_tasks} (matches backup)")
    else:
        print(f"⚠️  Restored but task count mismatch: expected {restore_tasks}, got {post_tasks}")


# ── verify command ──────────────────────────────────────────────────

def cmd_verify(db: Database):
    """Verify DB is populated — machine-readable check for handoff documents.

    Matches db_queries_legacy.template.sh lines 1585-1629.
    """
    # Query task count — must return a real number
    task_count = db.fetch_scalar("SELECT COUNT(*) FROM tasks")

    claude_count = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks WHERE assignee='CLAUDE'"
    )
    master_count = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks WHERE assignee='MASTER'"
    )
    phase_count = db.fetch_scalar(
        "SELECT COUNT(DISTINCT phase) FROM tasks"
    )

    # Check delegation columns
    tier_col = db.column_exists("tasks", "tier")
    skill_col = db.column_exists("tasks", "skill")
    rnotes_col = db.column_exists("tasks", "research_notes")

    output.print_section("DB Verification")
    print(f"  Tasks total:  {task_count}")
    print(f"  Claude tasks: {claude_count}")
    print(f"  Master tasks: {master_count}")
    print(f"  Phases:       {phase_count}")
    print("")
    print("  Schema:")
    print(f"    {'✅' if tier_col else '❌'} tier column{'' if tier_col else ' MISSING'}")
    print(f"    {'✅' if skill_col else '❌'} skill column{'' if skill_col else ' MISSING'}")
    print(f"    {'✅' if rnotes_col else '❌'} research_notes column{'' if rnotes_col else ' MISSING'}")
    print("")

    if task_count == 0:
        print("  ❌ DB IS EMPTY — run: sqlite3 project.db < seed_tasks.sql")
    elif not (tier_col and skill_col and rnotes_col):
        print("  ⚠️  DB populated but schema incomplete — run migration 001")
    else:
        print("  ✅ DB populated and schema complete")
    print("")


# ── board command ───────────────────────────────────────────────────

def cmd_board(config: ProjectConfig):
    """Delegate to generate_board.py script.

    Matches db_queries_legacy.template.sh lines 1210-1212.
    """
    import subprocess

    board_script = config.project_dir / "generate_board.py"
    if not board_script.exists():
        print(f"❌ generate_board.py not found in {config.project_dir}")
        sys.exit(1)

    result = subprocess.run(
        ["python3", str(board_script)],
        capture_output=True, text=True, timeout=30,
    )
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        sys.exit(result.returncode)


# ── export command ─────────────────────────────────────────────────

def cmd_export(db: Database, config: ProjectConfig,
               tables: str = "", pretty: bool = False,
               output_file: str = ""):
    """Export DB contents as JSON for version-control visibility and portability.

    Discovers columns via PRAGMA table_info (not DDL) so migration-added
    columns like files_touched and handover_notes are always included.
    """
    import json

    # Determine which tables to export
    all_tables = [t for t in SCHEMA_TABLES if db.table_exists(t)]
    if tables:
        requested = [t.strip() for t in tables.split(",")]
        missing = [t for t in requested if t not in all_tables]
        if missing:
            print(f"❌ Tables not found: {', '.join(missing)}", file=sys.stderr)
            sys.exit(1)
        export_tables = requested
    else:
        export_tables = all_tables

    # Build export payload
    result = {
        "meta": {
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "project_name": config.project_name,
            "source_db": str(Path(db.db_path).name),
            "tables": export_tables,
        }
    }

    total_rows = 0
    for table in export_tables:
        rows = db.fetch_all(f"SELECT * FROM [{table}]")
        result[table] = [dict(row) for row in rows]
        total_rows += len(rows)

    # Serialize
    indent = 2 if pretty else None
    json_str = json.dumps(result, indent=indent, default=str, ensure_ascii=False)

    # Output
    if output_file:
        Path(output_file).write_text(json_str + "\n", encoding="utf-8")
        print(f"✅ Exported {len(export_tables)} tables ({total_rows} rows) → {output_file}",
              file=sys.stderr)
    else:
        print(json_str)
        print(f"✅ Exported {len(export_tables)} tables ({total_rows} rows) → stdout",
              file=sys.stderr)


# ── import command ─────────────────────────────────────────────────

def cmd_import(db: Database, config: ProjectConfig,
               input_file: str, replace: bool = False):
    """Import DB contents from JSON. Merge mode (INSERT OR IGNORE) by default.

    Column intersection: extra keys in JSON are silently skipped, missing
    columns get SQLite defaults. This handles bidirectional schema drift.
    """
    import json

    # Read input
    if input_file == "-":
        raw = sys.stdin.read()
    else:
        p = Path(input_file)
        if not p.exists():
            print(f"❌ File not found: {input_file}", file=sys.stderr)
            sys.exit(1)
        raw = p.read_text(encoding="utf-8")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    if "meta" not in data:
        print("❌ Missing 'meta' key — not a valid dbq export file", file=sys.stderr)
        sys.exit(1)

    # Process tasks first for logical FK consistency, then rest
    import_order = []
    if "tasks" in data and data["tasks"] and db.table_exists("tasks"):
        import_order.append("tasks")
    for key in data:
        if key == "meta" or key == "tasks":
            continue
        if isinstance(data[key], list) and db.table_exists(key):
            import_order.append(key)

    total_rows = 0
    table_counts = {}
    for table in import_order:
        rows = data[table]
        if not rows:
            table_counts[table] = 0
            continue

        db_columns = db.get_table_columns(table)

        if replace:
            db.execute(f"DELETE FROM [{table}]")

        count = 0
        for row in rows:
            # Column intersection: only insert columns that exist in DB
            cols = [c for c in row if c in db_columns]
            if not cols:
                continue
            placeholders = ", ".join("?" for _ in cols)
            col_names = ", ".join(f"[{c}]" for c in cols)
            values = tuple(row[c] for c in cols)

            if replace:
                sql = f"INSERT INTO [{table}] ({col_names}) VALUES ({placeholders})"
            else:
                sql = f"INSERT OR IGNORE INTO [{table}] ({col_names}) VALUES ({placeholders})"

            cursor = db.execute(sql, values)
            count += cursor.rowcount

        table_counts[table] = count
        total_rows += count

    db.commit()

    # Summary
    print(f"✅ Imported {len(import_order)} tables ({total_rows} rows) from {input_file}",
          file=sys.stderr)
    for table, count in table_counts.items():
        print(f"   {table}: {count} rows", file=sys.stderr)


def _format_size(size_bytes: int) -> str:
    """Human-readable file size."""
    for unit in ("B", "K", "M", "G"):
        if size_bytes < 1024:
            return f"{size_bytes}{unit}"
        size_bytes //= 1024
    return f"{size_bytes}T"
