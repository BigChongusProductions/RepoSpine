#!/usr/bin/env python3
"""session_briefing.py — Signal computation and compact JSON output for session briefing.

Computes session state (GREEN/YELLOW/RED) from the project DB and outputs either
a brief human-readable signal block (default) or compact JSON (--json/--compact).

The shell session_briefing.template.sh handles full human-readable output.
This script handles signal computation and machine-readable export only.

Usage:
    python3 session_briefing.py            # human-readable signal block
    python3 session_briefing.py --json     # compact JSON
    python3 session_briefing.py --compact  # alias for --json
    PROJECT_DB=myproject.db python3 session_briefing.py --json
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sqlite3
import sys
from pathlib import Path


def find_db() -> str | None:
    """Find the project DB path.

    Resolution order:
    1. PROJECT_DB env var
    2. Any *.db file in the current directory (first match)
    """
    env_db = os.environ.get("PROJECT_DB", "")
    if env_db:
        return env_db
    matches = glob.glob("*.db")
    if matches:
        return matches[0]
    return None


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


def compute_signal(db_path: str) -> dict:
    """Compute session signal from DB state.

    Returns dict with:
      signal: "GREEN" | "YELLOW" | "RED"
      reasons: list of reason strings (plain text, no emoji)
      next_task: {id, phase, title, blocked_by} or None
      stats: {total, done, ready, blocked, active}
    """
    signal = "GREEN"
    reasons: list[str] = []

    uri = f"file:{db_path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)  # nosemgrep: no-direct-sqlite
    except sqlite3.OperationalError:
        # DB missing or unreadable — return minimal result
        return {
            "signal": "RED",
            "reasons": [f"DB not found or unreadable: {db_path}"],
            "next_task": None,
            "stats": {"total": 0, "done": 0, "ready": 0, "blocked": 0, "active": 0},
        }

    # ── Next Claude task ───────────────────────────────────────────────────────
    next_rows = _query(
        conn,
        """
        SELECT id, phase, title, COALESCE(blocked_by, ''), status
        FROM tasks
        WHERE status NOT IN ('DONE','WONTFIX','SKIP')
          AND (tier IS NULL OR tier NOT IN ('master','gemini','skip'))
          AND COALESCE(queue, '') != 'INBOX'
        ORDER BY sort_key, id
        LIMIT 5
        """,
    )

    # Fall back to older schema (sort_order column, assignee column)
    if not next_rows:
        next_rows = _query(
            conn,
            """
            SELECT id, phase, title, COALESCE(blocked_by, ''), status
            FROM tasks
            WHERE status NOT IN ('DONE','WONTFIX','SKIP')
              AND COALESCE(assignee, '') NOT IN ('MASTER','GEMINI','SKIP')
              AND COALESCE(queue, '') != 'INBOX'
            ORDER BY phase, sort_order, id
            LIMIT 5
            """,
        )

    next_task = None
    next_task_id = ""
    next_task_phase = ""
    next_task_blocked = ""

    if next_rows:
        row = next_rows[0]
        next_task_id = row[0] or ""
        next_task_phase = row[1] or ""
        next_task_title = row[2] or ""
        next_task_blocked = row[3] or ""
        next_task = {
            "id": next_task_id,
            "phase": next_task_phase,
            "title": next_task_title,
            "blocked_by": next_task_blocked or None,
        }

    # ── Rule 1: Prior phases have incomplete forward-track tasks → RED ────────
    if next_task_phase:
        incomplete = _query(
            conn,
            """
            SELECT phase, COUNT(*) as cnt
            FROM tasks
            WHERE status NOT IN ('DONE','WONTFIX','SKIP')
              AND COALESCE(track, 'forward') = 'forward'
              AND phase < ?
              AND COALESCE(queue, '') != 'INBOX'
            GROUP BY phase
            """,
            (next_task_phase,),
        )
        if incomplete:
            signal = "RED"
            parts = ", ".join(f"{r[0]} ({r[1]} task(s))" for r in incomplete)
            reasons.append(f"Prior phase(s) have incomplete tasks: {parts}")

    # ── Rule 2: Prior phase gate not passed → RED ──────────────────────────────
    if next_task_phase:
        phases_before = _query(
            conn,
            """
            SELECT DISTINCT phase FROM tasks
            WHERE phase < ? AND COALESCE(queue, '') != 'INBOX'
            ORDER BY phase
            """,
            (next_task_phase,),
        )
        gated_phases = {
            r[0]
            for r in _query(
                conn,
                "SELECT phase FROM phase_gates WHERE gated_on IS NOT NULL",
            )
        }
        for (pb,) in phases_before:
            if pb not in gated_phases:
                signal = "RED"
                reasons.append(f"{pb} phase gate not passed")

    # ── Rule 3/4: Master/Gemini blockers ──────────────────────────────────────
    blocker_count = _scalar(
        conn,
        """
        SELECT COUNT(DISTINCT b.id)
        FROM tasks t JOIN tasks b ON t.blocked_by = b.id
        WHERE t.status NOT IN ('DONE','WONTFIX','SKIP')
          AND COALESCE(t.assignee,'') NOT IN ('MASTER','GEMINI','SKIP')
          AND b.status NOT IN ('DONE','WONTFIX','SKIP')
          AND COALESCE(b.assignee,'') IN ('MASTER','GEMINI')
        """,
    )
    if blocker_count > 0:
        unblocked_claude = _scalar(
            conn,
            """
            SELECT COUNT(*) FROM tasks
            WHERE status NOT IN ('DONE','WONTFIX','SKIP')
              AND COALESCE(assignee,'') NOT IN ('MASTER','GEMINI','SKIP')
              AND COALESCE(queue,'') != 'INBOX'
              AND (blocked_by IS NULL OR blocked_by = ''
                   OR blocked_by IN (SELECT id FROM tasks WHERE status IN ('DONE','WONTFIX','SKIP'))
                   OR blocked_by NOT IN (SELECT id FROM tasks))
            """,
        )
        if unblocked_claude == 0:
            signal = "RED"
            reasons.append("All Claude tasks are blocked by Master/Gemini")
        elif signal != "RED":
            signal = "YELLOW"
            reasons.append(
                "Some Master/Gemini blockers exist but unblocked Claude tasks available"
            )

    # ── Rule 5: S1 gate-critical loopback unacknowledged → YELLOW ────────────
    # Try loopback_acks table first; fall back to simpler query if absent
    try:
        cb_unacked = _scalar(
            conn,
            """
            SELECT COUNT(*) FROM tasks t
            LEFT JOIN loopback_acks la ON t.id = la.loopback_id
            WHERE t.track = 'loopback' AND t.severity = 1 AND t.gate_critical = 1
              AND t.status NOT IN ('DONE','WONTFIX','SKIP')
              AND la.loopback_id IS NULL
            """,
        )
    except sqlite3.OperationalError:
        cb_unacked = _scalar(
            conn,
            """
            SELECT COUNT(*) FROM tasks
            WHERE track = 'loopback' AND severity = 1
              AND status NOT IN ('DONE','WONTFIX','SKIP')
            """,
        )
    if cb_unacked > 0:
        if signal != "RED":
            signal = "YELLOW"
        reasons.append(f"{cb_unacked} S1 circuit breaker(s) unacknowledged")

    # ── Rules 6/7: Next task blocked_by checks → YELLOW ──────────────────────
    if next_task_blocked:
        blocker_info = _query(
            conn,
            "SELECT status, phase FROM tasks WHERE id = ?",
            (next_task_blocked,),
        )
        if not blocker_info:
            # Stale reference — blocker task not found
            if signal != "RED":
                signal = "YELLOW"
            reasons.append(
                f"Next task {next_task_id} has stale blocked_by: {next_task_blocked} (not found)"
            )
        else:
            blocker_status, blocker_phase = blocker_info[0]
            if blocker_status not in ("DONE", "WONTFIX", "SKIP"):
                if blocker_phase != next_task_phase:
                    # Cross-phase blocker
                    if signal != "RED":
                        signal = "YELLOW"
                    reasons.append(
                        f"Next task {next_task_id} is blocked by {next_task_blocked} (cross-phase)"
                    )
                # Same-phase blocker is advisory only — no signal change

    # ── Overall stats ──────────────────────────────────────────────────────────
    total = _scalar(conn, "SELECT COUNT(*) FROM tasks")
    done = _scalar(
        conn,
        "SELECT COUNT(*) FROM tasks WHERE status IN ('DONE','WONTFIX','SKIP')",
    )
    ready = _scalar(
        conn,
        """
        SELECT COUNT(*) FROM tasks
        WHERE status NOT IN ('DONE','WONTFIX','SKIP')
          AND COALESCE(assignee,'') NOT IN ('MASTER','GEMINI','SKIP')
          AND COALESCE(queue,'') != 'INBOX'
          AND (blocked_by IS NULL OR blocked_by = ''
               OR blocked_by IN (SELECT id FROM tasks WHERE status IN ('DONE','WONTFIX','SKIP'))
               OR blocked_by NOT IN (SELECT id FROM tasks))
        """,
    )
    blocked = _scalar(
        conn,
        """
        SELECT COUNT(*) FROM tasks
        WHERE status NOT IN ('DONE','WONTFIX','SKIP')
          AND blocked_by IS NOT NULL AND blocked_by != ''
          AND blocked_by IN (SELECT id FROM tasks WHERE status NOT IN ('DONE','WONTFIX','SKIP'))
        """,
    )
    active = _scalar(
        conn,
        "SELECT COUNT(*) FROM tasks WHERE status = 'IN_PROGRESS'",
    )

    conn.close()

    return {
        "signal": signal,
        "reasons": reasons,
        "next_task": next_task,
        "stats": {
            "total": total,
            "done": done,
            "ready": ready,
            "blocked": blocked,
            "active": active,
        },
    }


def format_human(result: dict) -> str:
    """Format result as a brief human-readable signal block."""
    signal = result["signal"]
    reasons = result["reasons"]
    next_task = result["next_task"]
    stats = result["stats"]

    lines = []
    lines.append(f"Signal: {signal}")

    for r in reasons:
        lines.append(f"  - {r}")

    if next_task:
        lines.append(f"Next: {next_task['id']} -- {next_task['title']}")

    s = stats
    lines.append(
        f"Stats: {s['done']}/{s['total']} done | {s['ready']} ready | {s['blocked']} blocked"
    )

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute session signal from project DB"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output compact JSON",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Alias for --json",
    )
    parser.add_argument(
        "--db",
        metavar="PATH",
        help="Path to the SQLite DB (overrides PROJECT_DB env var)",
    )
    args = parser.parse_args()

    db_path = args.db or find_db()
    if not db_path:
        msg = "No DB found. Set PROJECT_DB env var or pass --db PATH."
        if args.json or args.compact:
            print(json.dumps({"error": msg, "signal": "RED", "reasons": [msg]}))
        else:
            print(f"Error: {msg}", file=sys.stderr)
        sys.exit(1)

    result = compute_signal(db_path)

    if args.json or args.compact:
        print(json.dumps(result, separators=(",", ":")))
    else:
        print(format_human(result))


if __name__ == "__main__":
    main()
