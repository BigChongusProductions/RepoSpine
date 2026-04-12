"""
Phase & gate commands: phase, gate, gate-pass, status, blockers,
confirm, confirmations, master.

All display-only commands except gate-pass and confirm which write to DB.
"""
import sys
import time
from datetime import datetime
from pathlib import Path

from ..db import Database
from .. import output


def _format_date() -> str:
    """Format date as 'Mon DD' matching bash: date '+%b %d' | sed 's/ 0/ /'"""
    now = datetime.now()
    return now.strftime("%b ") + str(now.day)


# ── phase command ────────────────────────────────────────────────────

def cmd_phase(db: Database):
    """Show current forward-track phase with task counts.

    Matches db_queries_legacy.template.sh lines 98-114.
    """
    output.print_section("Current Phase")

    rows = db.fetch_all(
        "SELECT phase, "
        "COUNT(*) AS total, "
        "SUM(CASE WHEN status='DONE' THEN 1 ELSE 0 END) AS done, "
        "SUM(CASE WHEN status NOT IN ('DONE','SKIP') THEN 1 ELSE 0 END) AS remaining "
        "FROM tasks "
        "WHERE COALESCE(track,'forward')='forward' "
        "GROUP BY phase "
        "HAVING remaining > 0 "
        "ORDER BY phase "
        "LIMIT 1"
    )

    if not rows:
        print("  ✅ All phases complete (no remaining tasks)")
        print("")
        return

    # Print as table
    print(f"  {'phase':<20} {'total':>5} {'done':>5} {'remaining':>9}")
    for r in rows:
        print(f"  {r['phase']:<20} {r['total']:>5} {r['done']:>5} {r['remaining']:>9}")
    print("")


# ── gate command ─────────────────────────────────────────────────────

def cmd_gate(db: Database):
    """Show all recorded phase gates.

    Matches db_queries_legacy.template.sh lines 151-165.
    """
    output.print_section("Phase Gate Status")

    count = db.fetch_scalar("SELECT COUNT(*) FROM phase_gates")

    if count == 0:
        print("  No phase gates passed yet.")
        print("")
        return

    rows = db.fetch_all(
        "SELECT phase, gated_on AS date, gated_by, notes "
        "FROM phase_gates "
        "ORDER BY phase"
    )
    print(f"  {'phase':<20} {'date':<12} {'gated_by':<10} notes")
    for r in rows:
        notes = r["notes"] or ""
        print(f"  {r['phase']:<20} {r['date']:<12} {r['gated_by']:<10} {notes}")
    print("")


# ── gate-pass command ────────────────────────────────────────────────

def cmd_gate_pass(
    db: Database,
    phase: str,
    gated_by: str = "MASTER",
    notes: str = "Phase gate review passed",
):
    """Record a phase gate pass.

    Matches db_queries_legacy.template.sh lines 167-176.
    """
    today = _format_date()

    db.execute(
        "INSERT OR REPLACE INTO phase_gates (phase, gated_on, gated_by, notes) "
        "VALUES (?, ?, ?, ?)",
        (phase, today, gated_by, notes),
    )
    db.commit()
    print(f"🚧 Phase gate recorded: {phase} passed ({today}, by {gated_by})")


# ── status command ───────────────────────────────────────────────────

def cmd_status(db: Database):
    """Show task counts by phase and loopback summary.

    Matches db_queries_legacy.template.sh lines 932-953.
    """
    output.print_section("Phase status (forward track)")

    rows = db.fetch_all(
        "SELECT phase, "
        "COUNT(*) AS total, "
        "SUM(CASE WHEN status='DONE' THEN 1 ELSE 0 END) AS done, "
        "SUM(CASE WHEN status='TODO' THEN 1 ELSE 0 END) AS todo, "
        "SUM(CASE WHEN blocked_by IS NOT NULL AND blocked_by != '' "
        "    AND status NOT IN ('DONE','SKIP') THEN 1 ELSE 0 END) AS blocked "
        "FROM tasks "
        "WHERE COALESCE(track,'forward')='forward' "
        "GROUP BY phase "
        "ORDER BY phase"
    )

    if not rows:
        print("  No tasks found.")
        print("")
        return

    print(f"  {'phase':<20} {'total':>5} {'done':>5} {'todo':>5} {'blocked':>7}")
    for r in rows:
        print(
            f"  {r['phase']:<20} {r['total']:>5} {r['done']:>5} "
            f"{r['todo']:>5} {r['blocked']:>7}"
        )

    # Loopback summary
    lb_total = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks WHERE track='loopback'"
    )
    lb_open = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks "
        "WHERE track='loopback' AND status NOT IN ('DONE','SKIP')"
    )
    if lb_total > 0:
        print(f"  Loopback track: {lb_total} total, {lb_open} open "
              f"— run 'loopbacks' for details")
    print("")


# ── blockers command ─────────────────────────────────────────────────

def cmd_blockers(db: Database):
    """Show Master/Gemini tasks blocking Claude work.

    Matches db_queries_legacy.template.sh lines 116-149.
    """
    output.print_section("Blockers: Master/Gemini tasks blocking Claude work")

    count = db.fetch_scalar(
        "SELECT COUNT(DISTINCT b.id) "
        "FROM tasks t "
        "JOIN tasks b ON t.blocked_by = b.id "
        "WHERE t.status != 'DONE' "
        "AND t.assignee = 'CLAUDE' "
        "AND b.status != 'DONE' "
        "AND b.assignee IN ('MASTER', 'GEMINI')"
    )

    if count == 0:
        print("  ✅ No Master/Gemini blockers — Claude work is unblocked")
        print("")
        return

    rows = db.fetch_all(
        "SELECT DISTINCT b.id AS blocker_id, "
        "b.phase, b.assignee, b.title AS blocker_task, "
        "GROUP_CONCAT(t.id, ', ') AS blocks_claude_tasks "
        "FROM tasks t "
        "JOIN tasks b ON t.blocked_by = b.id "
        "WHERE t.status != 'DONE' "
        "AND t.assignee = 'CLAUDE' "
        "AND b.status != 'DONE' "
        "AND b.assignee IN ('MASTER', 'GEMINI') "
        "GROUP BY b.id "
        "ORDER BY b.phase, b.sort_order"
    )

    for r in rows:
        print(
            f"  {r['blocker_id']} | {r['phase']} | {r['assignee']} | "
            f"{r['blocker_task']} | blocks: {r['blocks_claude_tasks']}"
        )
    print("")


# ── confirm command ──────────────────────────────────────────────────

def cmd_confirm(
    db: Database,
    config,
    task_id: str,
    confirmed_by: str = "MASTER",
    reasons: str = "Milestone confirmed",
):
    """Record a milestone confirmation.

    Matches db_queries_legacy.template.sh lines 178-195.
    """
    # Verify task exists
    task = db.fetch_one(
        "SELECT id FROM tasks WHERE id=?", (task_id,),
    )
    if task is None:
        print(f"❌ Task '{task_id}' not found")
        sys.exit(1)

    today = _format_date()

    db.execute(
        "INSERT OR REPLACE INTO milestone_confirmations "
        "(task_id, confirmed_on, confirmed_by, reasons) "
        "VALUES (?, ?, ?, ?)",
        (task_id, today, confirmed_by, reasons),
    )
    db.commit()

    count = db.fetch_scalar(
        "SELECT COUNT(*) FROM milestone_confirmations"
    )
    print(f"⏸️  Milestone confirmed: {task_id} ({today}, by {confirmed_by})")
    print(f"   Total milestone confirmations: {count}")

    # ── Write state file for agent-spawn-gate hook ──
    hooks_dir = config.project_dir / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    confirm_file = hooks_dir / ".last_confirm_timestamp"
    confirm_file.write_text(f"{int(time.time())}|{task_id}\n")


# ── confirmations command ────────────────────────────────────────────

def cmd_confirmations(db: Database):
    """Show all milestone confirmations.

    Matches db_queries_legacy.template.sh lines 197-213.
    """
    output.print_section("Milestone Confirmations")

    count = db.fetch_scalar(
        "SELECT COUNT(*) FROM milestone_confirmations"
    )

    if count == 0:
        print("  No milestone confirmations recorded yet.")
        print("")
        return

    rows = db.fetch_all(
        "SELECT mc.task_id, mc.confirmed_on AS date, "
        "mc.confirmed_by AS by, t.phase, t.title "
        "FROM milestone_confirmations mc "
        "JOIN tasks t ON mc.task_id = t.id "
        "ORDER BY t.sort_order"
    )

    for r in rows:
        print(
            f"  {r['task_id']} | {r['date']} | {r['by']} | "
            f"{r['phase']} | {r['title']}"
        )
    print("")


# ── master command ───────────────────────────────────────────────────

def cmd_master(db: Database):
    """Show all Master/Gemini TODO tasks.

    Matches db_queries_legacy.template.sh lines 955-965.
    """
    output.print_section("Master's TODO tasks")

    rows = db.fetch_all(
        "SELECT id, phase, priority, title "
        "FROM tasks "
        "WHERE status='TODO' AND assignee IN ('MASTER', 'GEMINI') "
        "ORDER BY phase, sort_order"
    )

    if not rows:
        print("  No Master/Gemini TODO tasks.")
        print("")
        return

    for r in rows:
        print(f"  {r['id']} | {r['phase']} | {r['priority']} | {r['title']}")
    print("")
