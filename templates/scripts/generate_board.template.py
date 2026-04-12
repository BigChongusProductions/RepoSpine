#!/usr/bin/env python3
"""
generate_board.py — Markdown task board generator
Parameterized template — replace %%PROJECT_DB%% before use.

Usage: python3 generate_board.py [--phase PHASE] [--all]

Outputs a formatted markdown task board grouped by phase.
"""

import sqlite3
import sys
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "%%PROJECT_DB%%")

def sev_icon(s):
    return {1: "🔴", 2: "🟡", 3: "🟢", 4: "⚪"}.get(s, "?")

def status_icon(status):
    return {"TODO": "⬜", "IN_PROGRESS": "🔵", "DONE": "✅", "SKIP": "⏭️", "MASTER": "👤"}.get(status, "?")

def main():
    show_all = "--all" in sys.argv
    filter_phase = None
    if "--phase" in sys.argv:
        idx = sys.argv.index("--phase")
        if idx + 1 < len(sys.argv):
            filter_phase = sys.argv[idx + 1]

    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Build query
    where_clauses = []
    if not show_all:
        where_clauses.append("t.status NOT IN ('DONE','SKIP')")
    if filter_phase:
        where_clauses.append(f"t.phase = '{filter_phase}'")

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    rows = conn.execute(f"""
        SELECT t.id, t.phase, t.title, t.status, t.assignee, t.priority,
               t.blocked_by, t.track, t.severity, t.gate_critical
        FROM tasks t
        {where_sql}
        ORDER BY t.phase, t.sort_order, t.id
    """).fetchall()

    if not rows:
        print("_No tasks found._")
        return

    # Group by phase
    phases = {}
    for row in rows:
        phase = row["phase"] or "INBOX"
        phases.setdefault(phase, []).append(row)

    print(f"# Task Board — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print()

    for phase, tasks in sorted(phases.items()):
        total = len(tasks)
        done = sum(1 for t in tasks if t["status"] in ("DONE", "SKIP"))
        print(f"## {phase}  ({done}/{total})")
        print()
        print("| ID | Status | Assignee | Title | Notes |")
        print("|----|--------|----------|-------|-------|")

        for t in tasks:
            s_icon = status_icon(t["status"])
            blocked = f" ⛔ blocked:{t['blocked_by']}" if t["blocked_by"] else ""
            lb_tag = ""
            if t["track"] == "loopback":
                sev = t["severity"] or 3
                gc = " [GC]" if t["gate_critical"] else ""
                lb_tag = f" {sev_icon(sev)}S{sev}{gc}"
            title_col = t["title"] + blocked + lb_tag
            print(f"| `{t['id']}` | {s_icon} {t['status']} | {t['assignee']} | {title_col} | |")
        print()

    conn.close()

if __name__ == "__main__":
    main()
