"""
Handover commands — session continuity with file-level context.

Commands:
    resume    — Single command to start working (replaces 5-command startup)
    handover  — Annotate a task with handover notes before ending session
"""
import json
import subprocess
import sys
from typing import Optional

from ..db import Database
from ..config import ProjectConfig
from .. import output


def cmd_resume(db: Database, config: ProjectConfig,
               task_override: str = ""):
    """Output compact context block for immediate work start.

    Priority order:
    1. Explicit task_override (if provided)
    2. IN_PROGRESS task (continuing from last session)
    3. Next ready task (from forward queue logic)
    """
    print("")
    print(output.section_header("Session Resume"))

    # ── Find the target task ──
    task = None

    if task_override:
        task = _fetch_task(db, task_override)
        if task is None:
            print(f"  Task '{task_override}' not found")
            sys.exit(1)
    else:
        # Check for IN_PROGRESS first
        task = db.fetch_one(
            "SELECT id, phase, title, priority, status, assignee, "
            "COALESCE(tier,'unassigned') as tier, "
            "COALESCE(blocked_by,'') as blocked_by, "
            "details, handover_notes, files_touched, "
            "COALESCE(track,'forward') as track "
            "FROM tasks WHERE status='IN_PROGRESS' AND assignee='CLAUDE' "
            "ORDER BY phase, sort_order LIMIT 1"
        )

        if task is None:
            # Fall back to next ready task
            task = db.fetch_one(
                "SELECT t.id, t.phase, t.title, t.priority, t.status, "
                "t.assignee, COALESCE(t.tier,'unassigned') as tier, "
                "COALESCE(t.blocked_by,'') as blocked_by, "
                "t.details, t.handover_notes, t.files_touched, "
                "COALESCE(t.track,'forward') as track "
                "FROM tasks t "
                "LEFT JOIN tasks b ON t.blocked_by = b.id "
                "WHERE t.status='TODO' AND t.assignee='CLAUDE' "
                "AND t.queue != 'INBOX' "
                "AND (t.blocked_by IS NULL OR t.blocked_by = '' "
                "     OR b.status IN ('DONE','SKIP') OR b.id IS NULL) "
                "ORDER BY t.phase, t.sort_order LIMIT 1"
            )

    if task is None:
        print("  No actionable tasks found.")
        print("  Run: bash db_queries.sh next  (for full queue view)")
        print("")
        return

    # ── Header ──
    continuation = " (CONTINUING)" if task["status"] == "IN_PROGRESS" else ""
    print(f"\n== RESUME: {task['id']} — {task['title']}{continuation} ==")
    print(f"Phase: {task['phase']} | Priority: {task['priority']} | "
          f"Tier: {task['tier']}")

    # ── Details ──
    if task["details"]:
        lines = task["details"].strip().splitlines()
        preview = "\n  ".join(lines[:5])
        print(f"\nDETAILS:\n  {preview}")
        if len(lines) > 5:
            print(f"  ... ({len(lines) - 5} more lines)")

    # ── Predecessor files (from blocked_by task's files_touched) ──
    blocked_by = task["blocked_by"]
    if blocked_by:
        pred = db.fetch_one(
            "SELECT id, title, files_touched, handover_notes "
            "FROM tasks WHERE id=?",
            (blocked_by,),
        )
        if pred is not None:
            if pred["files_touched"]:
                try:
                    files = json.loads(pred["files_touched"])
                    if files:
                        print(f"\nPREDECESSOR FILES ({pred['id']}):")
                        for f in files[:10]:
                            print(f"  {f}")
                        if len(files) > 10:
                            print(f"  ... ({len(files) - 10} more)")
                except (json.JSONDecodeError, TypeError):
                    pass

            if pred["handover_notes"]:
                print(f"\nPREDECESSOR NOTES ({pred['id']}):")
                for line in pred["handover_notes"].strip().splitlines()[:5]:
                    print(f"  {line}")

    # ── Own files (if continuing and has files_touched) ──
    if task["files_touched"]:
        try:
            files = json.loads(task["files_touched"])
            if files:
                print(f"\nFILES (from prior work on this task):")
                for f in files[:10]:
                    print(f"  {f}")
        except (json.JSONDecodeError, TypeError):
            pass

    # ── Handover notes (own) ──
    if task["handover_notes"]:
        print(f"\nHANDOVER NOTES:")
        for line in task["handover_notes"].strip().splitlines()[:8]:
            print(f"  {line}")

    # ── Recent git activity ──
    _show_git_activity(config)

    # ── Unverified assumptions ──
    assumptions = db.fetch_all(
        "SELECT id, assumption, verify_cmd FROM assumptions "
        "WHERE task_id=? AND verified=0",
        (task["id"],),
    )
    if assumptions:
        print(f"\nASSUMPTIONS (unverified):")
        for a in assumptions[:5]:
            cmd_hint = f" (verify: {a['verify_cmd']})" if a["verify_cmd"] else ""
            print(f"  #{a['id']}: {a['assumption']}{cmd_hint}")

    # ── Quick commands ──
    print(f"\nQUICK COMMANDS:")
    if task["status"] != "IN_PROGRESS":
        print(f"  Start:    bash db_queries.sh start {task['id']}")
    print(f"  Check:    bash db_queries.sh check {task['id']}")
    print(f"  Done:     bash db_queries.sh done {task['id']}")
    print(f"  Handover: bash db_queries.sh handover {task['id']} \"notes\"")

    print("")


def cmd_handover(db: Database, task_id: str, notes: str):
    """Save handover notes for a task (file refs, arch context, state)."""
    task = db.fetch_one("SELECT id FROM tasks WHERE id=?", (task_id,))
    if task is None:
        print(f"❌ Task '{task_id}' not found")
        sys.exit(1)

    db.execute(
        "UPDATE tasks SET handover_notes=? WHERE id=?",
        (notes, task_id),
    )
    db.commit()
    print(f"📝 Handover notes saved for {task_id}")


def _fetch_task(db: Database, task_id: str):
    """Fetch a task with all handover-relevant fields."""
    return db.fetch_one(
        "SELECT id, phase, title, priority, status, assignee, "
        "COALESCE(tier,'unassigned') as tier, "
        "COALESCE(blocked_by,'') as blocked_by, "
        "details, handover_notes, files_touched, "
        "COALESCE(track,'forward') as track "
        "FROM tasks WHERE id=?",
        (task_id,),
    )


def _show_git_activity(config: ProjectConfig):
    """Show git diff --stat from last session tag."""
    proj_dir = str(config.project_dir)

    # Find last session tag
    tag_result = subprocess.run(
        ["git", "-C", proj_dir, "tag", "-l", "session/*"],
        capture_output=True, text=True,
    )
    if tag_result.returncode != 0 or not tag_result.stdout.strip():
        return

    tags = sorted(tag_result.stdout.strip().splitlines())
    if not tags:
        return

    last_tag = tags[-1]
    stat_result = subprocess.run(
        ["git", "-C", proj_dir, "diff", "--stat", f"{last_tag}..HEAD"],
        capture_output=True, text=True,
    )
    if stat_result.returncode != 0 or not stat_result.stdout.strip():
        return

    lines = stat_result.stdout.strip().splitlines()
    if lines:
        print(f"\nGIT ACTIVITY (since {last_tag}):")
        for line in lines[:15]:
            print(f"  {line}")
        if len(lines) > 15:
            print(f"  ... ({len(lines) - 15} more)")
