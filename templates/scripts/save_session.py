#!/usr/bin/env python3
"""save_session.py — Structured NEXT_SESSION.md generation.

Gathers session state from the project DB, computes signal via session_briefing,
writes a compact NEXT_SESSION.md handoff, logs the session, and creates a git tag.

The shell save_session.sh / save_session.template.sh are thin wrappers.

Usage:
    python3 save_session.py "Session summary"
    python3 save_session.py --json
    PROJECT_DB=project.db python3 save_session.py --project-name MyProject "Done"
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Import signal computation from session_briefing (same directory)
# ---------------------------------------------------------------------------

_THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS_DIR))

from session_briefing import compute_signal, find_db  # noqa: E402


# ---------------------------------------------------------------------------
# DB helpers (read-write — we INSERT into sessions)
# ---------------------------------------------------------------------------

def _query(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list:
    """Run a query and return rows, returning [] on any error."""
    try:
        cur = conn.execute(sql, params)
        return cur.fetchall()
    except sqlite3.Error:
        return []


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple = (), default=0):
    """Run a query and return the first column of the first row."""
    rows = _query(conn, sql, params)
    if rows and rows[0][0] is not None:
        return rows[0][0]
    return default


# ---------------------------------------------------------------------------
# State gathering
# ---------------------------------------------------------------------------

def gather_state(db_path: str, project_dir: str, skip_eval: bool = False) -> dict:
    """Query DB + git to build the full session state dict.

    Returns a dict with keys: signal, reasons, stats, next_task,
    current_phase, gates_passed, master_pending, next_3,
    next_task_files, next_task_handover, git, eval, version, date.
    """
    # ── Signal (from session_briefing) ────────────────────────────────────
    signal_data = compute_signal(db_path)
    signal = signal_data["signal"]
    reasons = signal_data["reasons"]
    stats = signal_data["stats"]
    next_task = signal_data["next_task"]

    # ── Open DB read-write for additional queries ──────────────────────────
    try:
        conn = sqlite3.connect(db_path)  # nosemgrep: no-direct-sqlite
    except sqlite3.OperationalError as exc:
        return {
            "signal": "RED",
            "reasons": [f"DB not openable: {exc}"],
            "stats": stats,
            "next_task": next_task,
            "current_phase": "(unknown)",
            "gates_passed": "None yet",
            "master_pending": 0,
            "next_3": [],
            "next_task_files": "",
            "next_task_handover": "",
            "git": {"branch": "unknown", "uncommitted": 0, "completed_this_session": []},
            "eval": None,
            "version": "unknown",
            "date": datetime.now().strftime("%Y-%m-%d"),
        }

    # ── Current phase ──────────────────────────────────────────────────────
    # Try sort_key first (newer schema), fall back to sort_order
    current_phase_rows = _query(
        conn,
        """
        SELECT phase FROM tasks
        WHERE status NOT IN ('DONE','WONTFIX','SKIP') AND COALESCE(queue,'') != 'INBOX'
        ORDER BY phase, sort_key LIMIT 1
        """,
    )
    if not current_phase_rows:
        current_phase_rows = _query(
            conn,
            """
            SELECT phase FROM tasks
            WHERE status NOT IN ('DONE','WONTFIX','SKIP') AND COALESCE(queue,'') != 'INBOX'
            ORDER BY phase, sort_order LIMIT 1
            """,
        )
    current_phase = current_phase_rows[0][0] if current_phase_rows else "(all done)"

    # ── Gates passed ───────────────────────────────────────────────────────
    gates_passed = _scalar(
        conn,
        "SELECT GROUP_CONCAT(phase, ', ') FROM phase_gates WHERE gated_on IS NOT NULL",
        default="",
    )
    if not gates_passed:
        gates_passed = "None yet"

    # ── Master/Gemini pending ──────────────────────────────────────────────
    # Try tier column first, fall back to assignee
    master_pending = _scalar(
        conn,
        "SELECT COUNT(*) FROM tasks WHERE status NOT IN ('DONE','WONTFIX','SKIP') AND tier IN ('master','gemini')",
        default=None,
    )
    if master_pending is None:
        master_pending = _scalar(
            conn,
            "SELECT COUNT(*) FROM tasks WHERE status NOT IN ('DONE','WONTFIX','SKIP') AND assignee IN ('MASTER','GEMINI')",
            default=0,
        )

    # ── Next 3 ready Claude tasks ──────────────────────────────────────────
    # Try sort_key first
    next_3_rows = _query(
        conn,
        """
        SELECT id, title FROM tasks
        WHERE status NOT IN ('DONE','WONTFIX','SKIP')
          AND (tier IS NULL OR tier NOT IN ('master','gemini','skip'))
          AND COALESCE(queue,'')!='INBOX'
          AND (blocked_by IS NULL OR blocked_by=''
               OR blocked_by IN (SELECT id FROM tasks WHERE status IN ('DONE','WONTFIX','SKIP')))
        ORDER BY phase, sort_key LIMIT 3
        """,
    )
    if not next_3_rows:
        next_3_rows = _query(
            conn,
            """
            SELECT id, title FROM tasks
            WHERE status NOT IN ('DONE','WONTFIX','SKIP')
              AND COALESCE(assignee,'') NOT IN ('MASTER','GEMINI','SKIP')
              AND COALESCE(queue,'')!='INBOX'
              AND (blocked_by IS NULL OR blocked_by=''
                   OR blocked_by IN (SELECT id FROM tasks WHERE status IN ('DONE','WONTFIX','SKIP')))
            ORDER BY phase, sort_order LIMIT 3
            """,
        )
    next_3 = [{"id": r[0], "title": r[1]} for r in next_3_rows]

    # ── File context and handover notes for next task ──────────────────────
    next_task_files = ""
    next_task_handover = ""
    next_task_id = (next_task or {}).get("id", "")
    if next_task_id:
        files_rows = _query(
            conn,
            """
            SELECT t2.files_touched
            FROM tasks t1
            LEFT JOIN tasks t2 ON t1.blocked_by = t2.id
            WHERE t1.id = ?
              AND t2.files_touched IS NOT NULL AND t2.files_touched != ''
            """,
            (next_task_id,),
        )
        if files_rows:
            next_task_files = files_rows[0][0] or ""

        handover_rows = _query(
            conn,
            """
            SELECT handover_notes FROM tasks
            WHERE handover_notes IS NOT NULL AND handover_notes != ''
            ORDER BY
                CASE WHEN status='IN_PROGRESS' THEN 0
                     WHEN status='DONE' THEN 1
                     ELSE 2 END,
                updated_at DESC
            LIMIT 1
            """,
        )
        if handover_rows:
            next_task_handover = handover_rows[0][0] or ""

    conn.close()

    # ── Git state ─────────────────────────────────────────────────────────
    git_branch = "unknown"
    uncommitted = 0
    completed_this_session: list[str] = []

    try:
        branch_result = subprocess.run(
            ["git", "-C", project_dir, "branch", "--show-current"],
            capture_output=True, text=True, timeout=5,
        )
        if branch_result.returncode == 0:
            git_branch = branch_result.stdout.strip() or "unknown"
    except Exception:
        pass

    try:
        status_result = subprocess.run(
            ["git", "-C", project_dir, "status", "--porcelain"],
            capture_output=True, text=True, timeout=5,
        )
        if status_result.returncode == 0:
            uncommitted = len([l for l in status_result.stdout.splitlines() if l.strip()])
    except Exception:
        pass

    try:
        tag_result = subprocess.run(
            ["git", "-C", project_dir, "tag", "-l", "session/*"],
            capture_output=True, text=True, timeout=5,
        )
        last_tag = ""
        if tag_result.returncode == 0:
            tags = [t for t in tag_result.stdout.strip().splitlines() if t]
            if tags:
                # Sort by date component then numeric session number
                tags.sort()
                last_tag = tags[-1]

        if last_tag:
            log_result = subprocess.run(
                ["git", "-C", project_dir, "log", "--oneline", "-10",
                 f"{last_tag}..HEAD"],
                capture_output=True, text=True, timeout=5,
            )
        else:
            log_result = subprocess.run(
                ["git", "-C", project_dir, "log", "--oneline", "-5"],
                capture_output=True, text=True, timeout=5,
            )

        if log_result.returncode == 0 and log_result.stdout.strip():
            completed_this_session = [
                f"- {line}" for line in log_result.stdout.strip().splitlines()
            ]
        else:
            completed_this_session = ["- No commits since last session tag"]
    except Exception:
        completed_this_session = ["- (git log unavailable)"]

    # ── Eval (non-fatal) ───────────────────────────────────────────────────
    eval_data = None
    dbq_path = Path(project_dir) / "db_queries.sh"
    if not skip_eval and dbq_path.is_file():
        try:
            eval_result = subprocess.run(
                ["bash", str(dbq_path), "eval", "--json"],
                capture_output=True, text=True, timeout=30,
            )
            if eval_result.returncode == 0 and eval_result.stdout.strip():
                parsed = json.loads(eval_result.stdout.strip())
                composite = parsed.get("composite")
                recs = parsed.get("recommendations", [])
                warnings = []
                if composite is not None and composite < 70:
                    warnings.append(
                        f"COMPOSITE SCORE: {composite:.0f}/100 — needs attention"
                    )
                elif composite is not None and composite < 85:
                    warnings.append(
                        f"COMPOSITE SCORE: {composite:.0f}/100 — declining"
                    )
                for r in recs:
                    priority = r.get("priority", 3)
                    marker = {1: "[P1]", 2: "[P2]", 3: "[P3]"}.get(priority, "[P?]")
                    warnings.append(f"{marker} [{r['trigger']}] {r['message']}")
                eval_data = {
                    "composite": composite,
                    "warnings": warnings,
                }
        except Exception:
            pass

    # ── Version ────────────────────────────────────────────────────────────
    version = "unknown"
    version_file = Path(project_dir) / "VERSION"
    try:
        version = version_file.read_text().strip()
    except Exception:
        pass

    return {
        "signal": signal,
        "reasons": reasons,
        "stats": stats,
        "next_task": next_task,
        "current_phase": current_phase,
        "gates_passed": gates_passed,
        "master_pending": master_pending,
        "next_3": next_3,
        "next_task_files": next_task_files,
        "next_task_handover": next_task_handover,
        "git": {
            "branch": git_branch,
            "uncommitted": uncommitted,
            "completed_this_session": completed_this_session,
        },
        "eval": eval_data,
        "version": version,
        "date": datetime.now().strftime("%Y-%m-%d"),
    }


# ---------------------------------------------------------------------------
# NEXT_SESSION.md generation
# ---------------------------------------------------------------------------

def generate_next_session_md(state: dict, project_name: str, summary: str = "") -> str:
    """Produce compact NEXT_SESSION.md content.

    Targets under 20 lines for the GREEN/no-warnings case.
    """
    signal = state["signal"]
    date = state["date"]
    stats = state["stats"]
    next_3 = state.get("next_3", [])
    current_phase = state.get("current_phase", "(unknown)")
    git = state.get("git", {})
    eval_data = state.get("eval")
    reasons = state.get("reasons", [])

    lines: list[str] = []

    # Header
    lines.append(f"# Next Session — {project_name}")
    lines.append("")

    # Signal line
    lines.append(
        f"Signal: {signal} | Date: {date} | Blocks: {stats.get('blocked', 0)}"
    )
    lines.append("")

    # Last session — human summary
    lines.append("## Last session")
    lines.append(summary or "No summary provided")
    lines.append("")

    # Pick up — next 3 tasks
    lines.append("## Pick up")
    if next_3:
        for t in next_3:
            lines.append(f"- {t['id']} — {t['title']}")
    else:
        lines.append("- (none)")
    lines.append("")

    # Context block
    lines.append("## Context")
    lines.append(
        f"- Phase: {current_phase} | Tasks: {stats.get('total', 0)} total"
        f" | {stats.get('done', 0)} done | {stats.get('ready', 0)} ready"
        f" | {stats.get('blocked', 0)} blocked"
    )
    lines.append(
        f"- Git: {git.get('branch', 'unknown')} ({git.get('uncommitted', 0)} uncommitted)"
    )
    if eval_data and eval_data.get("composite") is not None:
        lines.append(f"- Eval: {eval_data['composite']:.0f}/100")
    if reasons:
        for reason in reasons:
            lines.append(f"- {reason}")
    # Git commits (compact — max 5 lines)
    completed = git.get("completed_this_session", [])
    if completed and completed != ["- No commits since last session tag"]:
        for c in completed[:5]:
            lines.append(c)

    # Avoid section — only if avoid items exist
    avoid_items = state.get("avoid", [])
    if avoid_items:
        lines.append("")
        lines.append("## Avoid")
        for a in avoid_items[:2]:
            lines.append(f"- {a}")

    # Warnings section — only if warnings exist
    eval_warnings = (eval_data or {}).get("warnings", [])
    if eval_warnings:
        lines.append("")
        lines.append("## Warnings")
        for w in eval_warnings:
            lines.append(f"- {w}")

    lines.append("")  # trailing newline
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# DB session logging
# ---------------------------------------------------------------------------

def log_session(db_path: str, summary: str) -> bool:
    """INSERT a session record into the sessions table.

    Returns True on success, False on error (warning printed to stderr).
    """
    try:
        conn = sqlite3.connect(db_path)  # nosemgrep: no-direct-sqlite
        conn.execute(
            "INSERT INTO sessions (session_type, summary) VALUES (?, ?)",
            ("Claude Code", summary),
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.Error as exc:
        print(
            f"Warning: failed to log session to DB: {exc}",
            file=sys.stderr,
        )
        return False


# ---------------------------------------------------------------------------
# Git tag
# ---------------------------------------------------------------------------

def tag_session(project_dir: str) -> str | None:
    """Create a session/{date}/{N} git tag at HEAD.

    Mirrors cmd_tag_session() in templates/scripts/dbq/commands/sessions.py.
    Returns the tag name on success, None on failure.
    """
    try:
        tag_list = subprocess.run(
            ["git", "-C", project_dir, "tag", "-l", "session/*"],
            capture_output=True, text=True, timeout=5,
        )
        existing = [t for t in tag_list.stdout.strip().splitlines() if t]
        session_num = len(existing) + 1

        today = datetime.now().strftime("%Y-%m-%d")
        tag_name = f"session/{today}/{session_num}"

        result = subprocess.run(
            ["git", "-C", project_dir, "tag", tag_name, "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            print(
                f"Warning: failed to create git tag: {result.stderr.strip()}",
                file=sys.stderr,
            )
            return None
        return tag_name
    except Exception as exc:
        print(f"Warning: git tag failed: {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Snapshot helper
# ---------------------------------------------------------------------------

def run_snapshot(project_dir: str) -> bool:
    """Run db_queries.sh snapshot (non-fatal).

    Returns True on success, False on error.
    """
    dbq_path = Path(project_dir) / "db_queries.sh"
    if not dbq_path.is_file():
        return False
    try:
        result = subprocess.run(
            ["bash", str(dbq_path), "snapshot"],
            capture_output=True, text=True, timeout=30,
            cwd=project_dir,
        )
        return result.returncode == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------

def print_banner(state: dict) -> None:
    """Print terminal summary matching save_session.template.sh format."""
    border = "━" * 60
    now_str = datetime.now().strftime("%b %d, %Y %H:%M")
    signal = state["signal"]
    stats = state["stats"]
    next_task = state.get("next_task")
    master_pending = state.get("master_pending", 0)

    next_label = "(none)"
    if next_task:
        task_id = next_task.get("id", "")
        task_title = next_task.get("title", "")
        next_label = f"{task_id} — {task_title}"

    print(f"\n{border}")
    print(f"  Session Saved — {now_str}")
    print(border)
    print("")
    print(f"  Signal:    {signal}")
    print(f"  Next task: {next_label}")
    print(
        f"  Ready:     {stats.get('ready', 0)} Claude tasks"
        f"   |   Blocked: {stats.get('blocked', 0)}"
        f"   |   Master: {master_pending}"
    )
    print("")
    print("  NEXT_SESSION.md written.")
    print(border)
    print("")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate NEXT_SESSION.md from current project DB + git state.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 save_session.py 'Implemented V1-042'\n"
            "  python3 save_session.py --json\n"
            "  PROJECT_DB=myproject.db python3 save_session.py --project-name MyProject 'Done'\n"
        ),
    )
    parser.add_argument(
        "summary",
        nargs="?",
        default="No summary provided",
        help="Session summary (what was accomplished)",
    )
    parser.add_argument(
        "--db",
        metavar="PATH",
        help="Path to the SQLite DB (overrides PROJECT_DB env var)",
    )
    parser.add_argument(
        "--out",
        metavar="PATH",
        default=None,
        help="Output path for NEXT_SESSION.md (default: next to DB file)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output state as JSON to stdout; skip file write, DB log, git tag",
    )
    parser.add_argument(
        "--project-name",
        metavar="NAME",
        default=None,
        help="Project name for NEXT_SESSION.md header (or PROJECT_NAME env var)",
    )
    parser.add_argument(
        "--project-dir",
        metavar="PATH",
        default=None,
        help="Project directory (default: parent of DB file)",
    )
    parser.add_argument(
        "--skip-git",
        action="store_true",
        help="Skip git tag creation and auto-commit",
    )
    parser.add_argument(
        "--skip-eval",
        action="store_true",
        help="Skip eval subprocess (and snapshot)",
    )
    parser.add_argument(
        "--skip-db-log",
        action="store_true",
        help="Skip INSERT into sessions table",
    )
    args = parser.parse_args()

    # ── Resolve DB path ───────────────────────────────────────────────────
    db_path = args.db or os.environ.get("PROJECT_DB", "") or find_db()
    if not db_path:
        msg = "No DB found. Set PROJECT_DB env var or pass --db PATH."
        if args.json:
            print(json.dumps({"error": msg}))
        else:
            print(f"Error: {msg}", file=sys.stderr)
        sys.exit(1)

    db_path = str(Path(db_path).resolve())

    # ── Resolve project dir ───────────────────────────────────────────────
    if args.project_dir:
        project_dir = str(Path(args.project_dir).resolve())
    else:
        project_dir = str(Path(db_path).parent.resolve())

    # ── Resolve project name ──────────────────────────────────────────────
    project_name = (
        args.project_name
        or os.environ.get("PROJECT_NAME", "")
        or Path(project_dir).name
    )

    # ── Resolve output path ───────────────────────────────────────────────
    if args.out:
        out_path = Path(args.out).resolve()
    else:
        out_path = Path(db_path).parent / "NEXT_SESSION.md"

    # ── Gather state ──────────────────────────────────────────────────────
    state = gather_state(db_path, project_dir, skip_eval=args.skip_eval)

    # ── --json mode: dump and exit ─────────────────────────────────────────
    if args.json:
        print(json.dumps(state, indent=2, default=str))
        return

    # ── Snapshot (unless --skip-eval) ─────────────────────────────────────
    if not args.skip_eval:
        run_snapshot(project_dir)

    # ── Write NEXT_SESSION.md ─────────────────────────────────────────────
    content = generate_next_session_md(state, project_name, args.summary)
    try:
        out_path.write_text(content, encoding="utf-8")
    except OSError as exc:
        print(f"Error: failed to write {out_path}: {exc}", file=sys.stderr)
        sys.exit(1)

    # ── Log session to DB ─────────────────────────────────────────────────
    if not args.skip_db_log:
        log_session(db_path, args.summary)

    # ── Git tag ───────────────────────────────────────────────────────────
    if not args.skip_git:
        tag_session(project_dir)

    # ── Banner ────────────────────────────────────────────────────────────
    print_banner(state)


if __name__ == "__main__":
    main()
