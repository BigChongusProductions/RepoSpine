"""
Task commands: done, quick, check, and supporting utilities.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from ..db import Database, DatabaseError
from .. import output


# ── done command ──────────────────────────────────────────────────────

def cmd_done(db: Database, config, task_id: str, skip_break: bool = False,
             files: Optional[List[str]] = None, research: bool = False):
    """Mark a task DONE. Side effects: auto-commit + push, phase-complete banner.

    Matches db_queries_legacy.template.sh lines 987-1166.

    The critical pattern: DB is updated FIRST, then git commit attempted.
    If git commit fails, DB is rolled back to TODO.

    Args:
        files: Specific files to stage. When provided, only these files are
               staged instead of ``git add -A``. Use this during parallel work
               to prevent cross-task contamination in commits.
        research: If True, skip auto-commit entirely. For investigation-only
                  tasks that produce no code changes.
    """
    # Validate task exists
    task = db.fetch_one(
        "SELECT id, status, phase, completed_on, tier FROM tasks WHERE id=?",
        (task_id,),
    )
    if task is None:
        print(f"❌ Task '{task_id}' not found in database — check the ID")
        sys.exit(1)

    # Guard: don't re-process already-DONE tasks
    if task["status"] == "DONE":
        completed = task["completed_on"] or "?"
        print(f"⚠️  Task '{task_id}' is already DONE (completed: {completed})")
        print("   Skipping auto-commit. Use 'git commit' manually if needed.")
        return

    # Mark DONE in DB (also normalize queue so INBOX tasks don't linger)
    today = _format_date()
    phase = task["phase"]
    db.execute(
        "UPDATE tasks SET status='DONE', completed_on=?, queue='A' WHERE id=?",
        (today, task_id),
    )
    db.commit()
    output.task_done_message(task_id, today)

    # Loopback-specific done logic
    track = db.fetch_one(
        "SELECT COALESCE(track,'forward') FROM tasks WHERE id=?",
        (task_id,),
    )
    if track == "loopback":
        _handle_loopback_done(db, task_id)

    # Auto-commit on task completion (skip for research-only tasks)
    if not research:
        _auto_commit(db, task_id, phase, config, files=files)

    # Clear hook state — prevents stale tier gate from blocking post-task work
    hooks_dir = config.project_dir / ".claude" / "hooks"
    check_result = hooks_dir / ".last_check_result"
    if check_result.exists():
        check_result.unlink()

    # Reset delegation edit counter — post-task writes (e.g. NEXT_SESSION.md)
    # must not be blocked by the previous task's delegation gate
    delegation_state = hooks_dir / ".delegation_state"
    if delegation_state.exists():
        delegation_state.write_text("0\n0\n")

    # Phase completion check
    _check_phase_complete(db, phase)

    # Verification signal — prompt orchestrator to spawn verifier
    tier = task["tier"] or ""
    if tier.lower() not in ("", "haiku", "skip"):
        files_str = ", ".join(files) if files else "(all staged)"
        print(f"\n\U0001f50d VERIFY RECOMMENDED: Task {task_id} marked done (tier: {tier}).")
        print(f"   Files: {files_str}")
        print(f"   Spawn verifier agent to confirm: spec alignment + test pass.")
    elif files and len(files) > 3:
        print(f"\n\U0001f50d VERIFY RECOMMENDED: Task {task_id} touched {len(files)} files.")
        print(f"   Consider running tests before proceeding.")

    # Sync drift warning
    untiered = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks "
        "WHERE tier IS NULL AND status NOT IN ('DONE','SKIP')"
    )
    if untiered > 0:
        print(f"\n  🔄 {untiered} task(s) missing tier assignment. "
              f"Run: bash db_queries.sh sync-check")

    # Breakage test nag (Layer 4)
    if not skip_break:
        tier = task["tier"] or ""
        if tier.lower() in ("sonnet", "opus"):
            bt = db.fetch_scalar(
                "SELECT COALESCE(breakage_tested,0) FROM tasks WHERE id=?",
                (task_id,),
            )
            if bt != 1:
                print(f"\n  🔨 Breakage test not done for {task_id} (tier: {tier})")
                print("     Pick the most critical assumption → temporarily "
                      "break it → verify graceful failure")
                print(f"     Mark done: bash db_queries.sh break-tested {task_id}")
                print(f"     Skip: bash db_queries.sh done {task_id} --skip-break")

    # Task boundary reminder — delegation approval expires per-task
    print("")
    print("  ── Next Task ──────────────────────────────────")
    print("  Present a delegation table before starting the next task.")
    print("  Run: bash db_queries.sh next")


def _format_date() -> str:
    """Format date as 'Mon DD' matching bash: date '+%b %d' | sed 's/ 0/ /'"""
    now = datetime.now()
    return now.strftime("%b ") + str(now.day)


def _handle_loopback_done(db: Database, task_id: str):
    """Handle loopback-specific done logic (lines 1008-1047)."""
    row = db.fetch_one(
        "SELECT severity, origin_phase, discovered_in, gate_critical "
        "FROM tasks WHERE id=?",
        (task_id,),
    )
    if row is None:
        return

    sev = row["severity"]
    origin = row["origin_phase"]
    disc = row["discovered_in"]
    gc = row["gate_critical"]

    # Severity re-triage prompt (S1/S2 only)
    if sev is not None and sev <= 2:
        print(f"\n  📋 Severity was S{sev}. Still accurate? Adjust via:")
        print(f"     sqlite3 \"$DB\" \"UPDATE tasks SET severity=N "
              f"WHERE id='{task_id}';\"")

    # Cluster check
    lb_same = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks "
        "WHERE track='loopback' AND origin_phase=? "
        "AND status NOT IN ('DONE','SKIP') AND id != ?",
        (origin, task_id),
    )
    print(f"  🔄 {lb_same} other loopback(s) target {origin}.")

    # Gate-critical resolution check
    if gc == 1 and disc:
        gc_remaining = db.fetch_scalar(
            "SELECT COUNT(*) FROM tasks "
            "WHERE track='loopback' AND discovered_in=? "
            "AND gate_critical=1 AND status NOT IN ('DONE','SKIP')",
            (disc,),
        )
        if gc_remaining == 0:
            print(f"  ✅ All gate-critical loopbacks for {disc} resolved. "
                  f"Gate check should pass.")

    # Clean up circuit breaker ack if S1
    if sev == 1:
        db.execute(
            "DELETE FROM loopback_acks WHERE loopback_id=?", (task_id,)
        )
        db.commit()


def _auto_commit(db: Database, task_id: str, phase: str, config,
                 files: Optional[List[str]] = None):
    """Auto-commit on task completion (lines 1049-1073).

    CRITICAL: If git commit fails, revert DB status to TODO.

    Args:
        files: When provided, stage only these files instead of ``git add -A``.
               Prevents cross-task contamination during parallel sub-agent work.
    """
    proj_dir = str(config.project_dir)

    # Clean up stale agent worktrees (only those with no active git lock)
    worktree_dir = Path(proj_dir) / ".claude" / "worktrees"
    if worktree_dir.exists():
        agent_dirs = list(worktree_dir.glob("agent-*"))
        cleaned = 0
        for d in agent_dirs:
            # Skip worktrees that have an active git lock (agent still running)
            lock_file = d / ".git" / "index.lock"
            if lock_file.exists():
                continue
            shutil.rmtree(d, ignore_errors=True)
            cleaned += 1
        if cleaned:
            print(f"  🧹 Cleaned {cleaned} stale agent worktree(s)")

    # Check for changes
    result = subprocess.run(
        ["git", "-C", proj_dir, "status", "--short"],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return  # No git repo or no changes

    changed = result.stdout.strip()
    file_count = len(changed.splitlines())
    title = db.fetch_one(
        "SELECT title FROM tasks WHERE id=?", (task_id,),
    )

    # Stage files
    if files:
        # Targeted staging — only the files the caller specified
        file_count = len(files)
        print(f"\n  📦 Auto-committing {file_count} specified file(s)...")
        add_result = subprocess.run(
            ["git", "-C", proj_dir, "add", "--"] + files,
            capture_output=True, text=True,
        )
    else:
        # Safety: refuse git add -A when tree has many unrelated changes
        non_db = [
            l for l in changed.splitlines()
            if not l.strip().endswith(".db")
        ]
        if len(non_db) > 5:
            print(f"\n  ⚠️  Dirty tree: {len(non_db)} changed file(s) beyond the DB.")
            print("     Use --files to specify which files to commit:")
            print(f"     bash db_queries.sh done {task_id} --files <file1> <file2> ...")
            print(f"  ⚠️  Reverting DB status — task '{task_id}' back to TODO")
            db.execute(
                "UPDATE tasks SET status='TODO', completed_on=NULL WHERE id=?",
                (task_id,),
            )
            db.commit()
            sys.exit(1)
        print(f"\n  📦 Auto-committing {file_count} changed file(s)...")
        add_result = subprocess.run(
            ["git", "-C", proj_dir, "add", "-A"],
            capture_output=True, text=True,
        )
    if add_result.returncode != 0 or (add_result.stderr and "ignored" in add_result.stderr):
        print(f"  ⚠️  git add failed: {add_result.stderr.strip()}")
        print(f"  ⚠️  Reverting DB status — task '{task_id}' back to TODO")
        db.execute(
            "UPDATE tasks SET status='TODO', completed_on=NULL, queue='INBOX' WHERE id=?",
            (task_id,),
        )
        db.commit()
        sys.exit(1)

    # Check if staging produced any diff (handles already-committed files)
    diff_result = subprocess.run(
        ["git", "-C", proj_dir, "diff", "--cached", "--quiet"],
        capture_output=True,
    )
    if diff_result.returncode == 0:
        # Nothing staged — files were already committed or unchanged
        if files:
            print("  ℹ️  Specified files already committed — skipping auto-commit.")
        return

    # Commit
    commit_msg = f"[{phase}] {task_id}: {title}"
    full_msg = (
        f"{commit_msg}\n\n"
        f"Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
    )
    commit_result = subprocess.run(
        ["git", "-C", proj_dir, "commit", "-m", full_msg],
        capture_output=True,
    )

    if commit_result.returncode == 0:
        output.commit_success_message(commit_msg)
        # Capture files touched for session handover
        files_result = subprocess.run(
            ["git", "-C", proj_dir, "diff", "--name-only", "HEAD~1", "HEAD"],
            capture_output=True, text=True,
        )
        if files_result.returncode == 0 and files_result.stdout.strip():
            touched = [
                f for f in files_result.stdout.strip().splitlines()
                if not f.endswith(".db")
            ]
            if touched:
                db.execute(
                    "UPDATE tasks SET files_touched=? WHERE id=?",
                    (json.dumps(touched), task_id),
                )
                db.commit()
        # Auto-push
        push_result = subprocess.run(
            ["git", "-C", proj_dir, "push"],
            capture_output=True,
        )
        if push_result.returncode == 0:
            print("  ✅ Pushed.")
        else:
            print("  ⚠️  Push failed (commit saved locally).")
    else:
        # ROLLBACK: revert DB status
        print("  ⚠️  Commit failed (pre-commit hook may have blocked it).")
        print(f"  ⚠️  Reverting DB status — task '{task_id}' back to TODO")
        db.execute(
            "UPDATE tasks SET status='TODO', completed_on=NULL WHERE id=?",
            (task_id,),
        )
        db.commit()
        print(f"  Fix the issue and re-run: bash db_queries.sh done {task_id}")
        sys.exit(1)


def _check_phase_complete(db: Database, phase: str):
    """Check if phase is complete and print appropriate banner (lines 1075-1125)."""
    remaining = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks "
        "WHERE phase=? AND COALESCE(track,'forward')='forward' "
        "AND status NOT IN ('DONE','SKIP')",
        (phase,),
    )
    # Include gate-critical loopbacks
    gc_lb = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks "
        "WHERE track='loopback' AND discovered_in=? "
        "AND gate_critical=1 AND status NOT IN ('DONE','SKIP')",
        (phase,),
    )
    remaining += gc_lb

    remaining_claude = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks "
        "WHERE phase=? AND assignee='CLAUDE' "
        "AND COALESCE(track,'forward')='forward' "
        "AND status NOT IN ('DONE','SKIP')",
        (phase,),
    )

    if remaining == 0:
        print("")
        print("╔═══════════════════════════════════════════════════════════╗")
        print(f"║  🚧  PHASE COMPLETE: {phase:<37}")
        print("║                                                           ")
        print(f"║  All tasks in {phase} are DONE. Run the phase gate:{'':>5}")
        print("║                                                           ")
        print("║  Step 1 — Full validation:                                ")
        print("║    bash build_summarizer.sh test                          ")
        print("║                                                           ")
        print("║  Step 2 — Milestone merge check:                          ")
        print(f"║    bash milestone_check.sh {phase:<31}")
        print("║                                                           ")
        print("║  Step 3 — Review changes (before merging):                ")
        print("║    git diff main..dev                                     ")
        print("║                                                           ")
        print("║  Step 4 — If all pass, record the gate:                   ")
        print(f"║    bash db_queries.sh gate-pass {phase:<26}")
        print("║                                                           ")
        print("║  Step 5 — Merge (only after gate-pass):                   ")
        print("║    git checkout main                                      ")
        print(f'║    git merge dev --no-ff -m "Milestone: {phase}"{"":>8}')
        print("║    git checkout dev                                       ")
        print("╚═══════════════════════════════════════════════════════════╝")
    elif remaining_claude == 0 and remaining > 0:
        master_remaining = db.fetch_one(
            "SELECT GROUP_CONCAT(id || ' (' || assignee || ')', ', ') "
            "FROM tasks "
            "WHERE phase=? AND status NOT IN ('DONE','SKIP')",
            (phase,),
        )
        print(f"\n📋 All Claude tasks in {phase} done. "
              f"Remaining: {master_remaining}")
        print("   Phase gate cannot run until those complete.")


# ── quick command ─────────────────────────────────────────────────────

def cmd_quick(
    db: Database,
    title: str,
    phase: str = "INBOX",
    tag: str = "",
    loopback_origin: str = "",
    severity: int = 3,
    gate_critical: bool = False,
    reason: str = "",
):
    """Quick ad-hoc task capture.

    Matches db_queries_legacy.template.sh lines 2324-2407.
    Two paths: standard INBOX capture or loopback task.
    """
    stamp = str(int(time.time()))

    if loopback_origin:
        _quick_loopback(
            db, title, phase, tag, stamp,
            loopback_origin, severity, gate_critical, reason,
        )
    else:
        _quick_inbox(db, title, phase, tag, stamp)


def _unique_task_id(db: Database, prefix: str, stamp: str) -> str:
    """Generate a unique task ID, appending a-z suffix on collision."""
    task_id = f"{prefix}-{stamp[-4:]}"
    if db.fetch_one("SELECT id FROM tasks WHERE id=?", (task_id,)) is None:
        return task_id
    for suffix in "abcdefghijklmnopqrstuvwxyz":
        candidate = f"{task_id}{suffix}"
        if db.fetch_one("SELECT id FROM tasks WHERE id=?", (candidate,)) is None:
            return candidate
    raise SystemExit(f"❌ Cannot generate unique {prefix} ID — 27 collisions on stamp {stamp[-4:]}")


def _quick_inbox(
    db: Database, title: str, phase: str, tag: str, stamp: str
):
    """Create standard INBOX task (lines 2393-2406)."""
    task_id = _unique_task_id(db, "QK", stamp)

    tag_val = tag if tag else None

    db.execute(
        "INSERT INTO tasks "
        "(id, phase, assignee, title, priority, status, queue, sort_order, details) "
        "VALUES (?, ?, 'CLAUDE', ?, 'QK', 'TODO', 'INBOX', 999, ?)",
        (task_id, phase, title, tag_val),
    )
    db.commit()

    output.quick_task_message(task_id, title)


def _quick_loopback(
    db: Database,
    title: str,
    phase: str,
    tag: str,
    stamp: str,
    origin: str,
    severity: int,
    gate_critical: bool,
    reason: str,
):
    """Create loopback task (lines 2357-2406)."""
    task_id = _unique_task_id(db, "LB", stamp)

    tag_val = tag if tag else None
    reason_val = reason if reason else None
    gc_val = 1 if gate_critical else 0

    db.execute(
        "INSERT INTO tasks "
        "(id, phase, assignee, title, priority, status, queue, sort_order, "
        "details, track, origin_phase, discovered_in, severity, "
        "gate_critical, loopback_reason) "
        "VALUES (?, ?, 'CLAUDE', ?, 'LB', 'TODO', 'A', 999, "
        "?, 'loopback', ?, ?, ?, ?, ?)",
        (task_id, phase, title, tag_val, origin, phase,
         severity, gc_val, reason_val),
    )
    db.commit()

    output.quick_loopback_message(
        task_id, title, origin, severity, gate_critical
    )
    if reason:
        print(f"   Reason: {reason}")

    # Circuit breaker warning
    if severity == 1 and gate_critical:
        print("")
        print("   ⚠️  CIRCUIT BREAKER: S1 gate-critical loopback created.")
        print("   Forward tasks will show CONFIRM until this is resolved "
              "or acknowledged.")

    # Blast radius estimation
    blast = db.fetch_scalar(
        "SELECT COUNT(DISTINCT phase) FROM tasks "
        "WHERE phase > ? AND COALESCE(track,'forward')='forward' "
        "AND status NOT IN ('DONE','SKIP')",
        (origin,),
    )
    if blast > 0:
        print(f"   Blast radius: {origin} → may affect {blast} phase(s) downstream")


def _print_discipline_advisory(is_loopback=False):
    """Ephemeral development discipline advisory."""
    if is_loopback:
        print("\n  🔧 DISCIPLINE — If this fix involves code changes:")
        print("     Investigate root cause before attempting fixes.")
        print("     📖 frameworks/development-discipline.md")
    else:
        print("\n  🔨 DISCIPLINE — If this task involves code changes:")
        print("     TDD: failing test → verify RED → minimal code → verify GREEN")
        print("     Debugging: investigate root cause before attempting fixes.")
        print("     📖 frameworks/development-discipline.md")


# ── check command ─────────────────────────────────────────────────────

def cmd_check(db: Database, config, task_id: str):
    """Pre-task safety check — GO, CONFIRM, ASSUME, or STOP with reasons.

    Matches db_queries_legacy.template.sh lines 215-725.

    PoC: implements core verdict logic. Skips lesson recall,
    critical file awareness, UI stress checklist.
    """
    # Fetch task info
    task = db.fetch_one(
        "SELECT id, phase, assignee, COALESCE(blocked_by,'') as blocked_by, "
        "status, title, COALESCE(needs_browser,0) as needs_browser, "
        "sort_order, COALESCE(track,'forward') as track, "
        "COALESCE(tier,'') as tier "
        "FROM tasks WHERE id=?",
        (task_id,),
    )
    if task is None:
        print(f"❌ STOP — Task '{task_id}' not found in database")
        sys.exit(1)

    phase = task["phase"]
    assignee = task["assignee"]
    blocked_by = task["blocked_by"]
    status = task["status"]
    title = task["title"]
    sort_order = task["sort_order"]
    track = task["track"]

    print("")
    print(f"── Pre-Task Check: {task_id} — {title} ─────")

    check_pass = True

    # ── Loopback path (relaxed phase rules) ──
    if track == "loopback":
        return _check_loopback(db, task_id, task, config)

    # Already done?
    if status == "DONE":
        print("  ⚠️  Task is already DONE")
        return

    # Check: assigned to Claude?
    if assignee != "CLAUDE":
        print(f"  🛑 STOP — Task is assigned to {assignee}, not Claude")
        check_pass = False

    # Check: prior phase incomplete?
    prior = db.fetch_all(
        "SELECT phase || ': ' || COUNT(*) || ' task(s)' "
        "FROM tasks "
        "WHERE status NOT IN ('DONE','SKIP') "
        "AND COALESCE(track,'forward')='forward' "
        "AND phase < ? AND queue != 'INBOX' "
        "GROUP BY phase",
        (phase,),
    )
    if prior:
        for row in prior:
            print(f"  🛑 STOP — Prior phase(s) have incomplete tasks: {row[0]}")
        check_pass = False

    # Check: prior phase gated?
    phases_before = db.fetch_all(
        "SELECT DISTINCT phase FROM tasks WHERE phase < ? ORDER BY phase",
        (phase,),
    )
    for row in phases_before:
        prior_phase = row[0]
        gate_exists = db.fetch_scalar(
            "SELECT COUNT(*) FROM phase_gates WHERE phase=?",
            (prior_phase,),
        )
        if gate_exists == 0:
            print(f"  🛑 STOP — {prior_phase} phase gate not passed "
                  f"(run: bash db_queries.sh gate-pass {prior_phase})")
            check_pass = False

    # Check: blocked by unfinished dependency?
    if blocked_by:
        blocker = db.fetch_one(
            "SELECT status, assignee, title, phase FROM tasks WHERE id=?",
            (blocked_by,),
        )
        if blocker is None:
            print(f"  ⚠️  WARN — blocked_by '{blocked_by}' references a "
                  f"nonexistent task (stale reference)")
            print(f"         Fix: bash db_queries.sh unblock {task_id}")
        else:
            if blocker["status"] not in ("DONE", "SKIP"):
                if blocker["phase"] != phase:
                    print(f"  🛑 STOP — Blocked by {blocked_by} "
                          f"({blocker['assignee']}, {blocker['status']}): "
                          f"{blocker['title']}")
                    check_pass = False
                else:
                    print(f"  ⚠️  HINT — {blocked_by} is not yet done "
                          f"({blocker['status']}), recommended to complete first")
                    print("         Override: proceed if order doesn't matter "
                          "for this task")

    # ── Milestone Gate (auto-detect) ──
    milestone_reasons = []

    if check_pass:
        milestone_reasons = _check_milestone_gate(
            db, task_id, phase, sort_order
        )

        # Circuit breaker: unresolved S1 gate-critical loopbacks
        unacked = db.fetch_all(
            "SELECT t.id || ': ' || t.title "
            "FROM tasks t "
            "LEFT JOIN loopback_acks la ON t.id = la.loopback_id "
            "WHERE t.track='loopback' AND t.severity=1 AND t.gate_critical=1 "
            "AND t.status NOT IN ('DONE','SKIP') "
            "AND la.loopback_id IS NULL",
        )
        if unacked:
            print("\n  ⚠️  CIRCUIT BREAKER — Unresolved S1 gate-critical loopback(s):")
            for row in unacked:
                print(f"    {row[0]}")
            print("")
            print("  Acknowledge to continue: bash db_queries.sh "
                  "ack-breaker <LB-ID> \"reason\"")
            milestone_reasons.append(
                "  - Circuit breaker: S1 loopback(s) unresolved"
            )

    # ── Assumption Check (Layer 1) ──
    assume_block = False
    if check_pass and db.table_exists("assumptions"):
        tier = db.fetch_one(
            "SELECT COALESCE(tier,'') FROM tasks WHERE id=?",
            (task_id,),
        ) or ""
        if tier.lower() in ("sonnet", "opus"):
            unverified = db.fetch_scalar(
                "SELECT COUNT(*) FROM assumptions "
                "WHERE task_id=? AND verified=0",
                (task_id,),
            )
            if unverified > 0:
                print(f"\n  🔬 ASSUME — {unverified} unverified assumption(s) "
                      f"for {task_id}:")
                rows = db.fetch_all(
                    "SELECT '     ' || id || '. ' || assumption || "
                    "CASE WHEN verify_cmd IS NOT NULL "
                    "THEN ' [cmd: ' || verify_cmd || ']' "
                    "ELSE ' [manual]' END "
                    "FROM assumptions "
                    "WHERE task_id=? AND verified=0",
                    (task_id,),
                )
                for row in rows:
                    print(row[0])
                print(f"\n  Run: bash db_queries.sh verify-all {task_id}")
                assume_block = True

    # ── Research Brief Check (Layer 2) ──
    research_warn = False
    if check_pass and not assume_block:
        tier = db.fetch_one(
            "SELECT COALESCE(tier,'') FROM tasks WHERE id=?",
            (task_id,),
        ) or ""
        if tier.lower() in ("sonnet", "opus"):
            researched = db.fetch_scalar(
                "SELECT COALESCE(researched,0) FROM tasks WHERE id=?",
                (task_id,),
            )
            if researched != 1:
                research_warn = True

    # ── Lesson Recall ──
    if check_pass:
        details = db.fetch_one(
            "SELECT COALESCE(details,'') FROM tasks WHERE id=?",
            (task_id,),
        ) or ""
        _lesson_recall(config, title, details)

    # ── Critical File Awareness ──
    if check_pass:
        details = db.fetch_one(
            "SELECT COALESCE(details,'') FROM tasks WHERE id=?",
            (task_id,),
        ) or ""
        _critical_files_check(config, title, details)

    # ── Verdict ──
    if not check_pass:
        print("\n  🛑 CANNOT PROCEED — resolve issues above first")
        print("  📌 ROUTING: Phase gate triggered. Read frameworks/phase-gates.md")
    elif assume_block:
        print(f"\n  🔬 ASSUME — Verify assumptions before starting {task_id}")
        print("  Orchestrator must verify or clear assumptions "
              "before spawning sub-agents.")
    elif milestone_reasons:
        print(f"\n  ⏸️  CONFIRM — Milestone checkpoint before starting {task_id}")
        for reason in milestone_reasons:
            print(reason)
        print("  Present current progress to Master and wait "
              "for explicit approval.")
        print(f"  Master says 'go' → run: bash db_queries.sh confirm "
              f"{task_id} → then proceed.")
        print("  Master says 'skip gate' → proceed + log override in session.")
        print("  📌 ROUTING: Phase gate triggered. Read frameworks/phase-gates.md")
        _print_discipline_advisory()
    else:
        print(f"  ✅ GO — {task_id} is clear to start")
        if research_warn:
            print(f"\n  📚 RESEARCH — Task not marked as researched. "
                  f"Before coding:")
            print("     1. Read lesson recall output above")
            print("     2. Query context7 if using library APIs")
            print("     3. Grep codebase for existing patterns to reuse")
            print("     4. Verify types/interfaces this task depends on")
            print(f"     Mark done: bash db_queries.sh researched {task_id}")
        _print_discipline_advisory()

    # ── Write state file for agent-spawn-gate hook ──
    hooks_dir = config.project_dir / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    check_result_file = hooks_dir / ".last_check_result"

    if not check_pass:
        verdict = "STOP"
    elif assume_block:
        verdict = "ASSUME"
    elif milestone_reasons:
        verdict = "CONFIRM"
    else:
        verdict = "GO"

    task_tier = task["tier"] if task["tier"] else ""
    check_result_file.write_text(f"{verdict}|{int(time.time())}|{task_id}|{task_tier}\n")

    # Reset edit counter so each task gets its own 3-edit allowance
    delegation_file = hooks_dir / ".delegation_state"
    last_approval = "0"
    if delegation_file.exists():
        lines = delegation_file.read_text().strip().splitlines()
        if len(lines) >= 2:
            last_approval = lines[1]
    delegation_file.write_text(f"0\n{last_approval}\n")

    print("")


def _check_loopback(db: Database, task_id: str, task, config):
    """Loopback check path (lines 240-294) — relaxed phase rules."""
    print("  ℹ️  Track: loopback (phase gate checks skipped)")

    sev = db.fetch_one(
        "SELECT severity FROM tasks WHERE id=?", (task_id,)
    )
    gc = db.fetch_one(
        "SELECT gate_critical FROM tasks WHERE id=?", (task_id,)
    )
    origin = db.fetch_one(
        "SELECT origin_phase FROM tasks WHERE id=?", (task_id,)
    )
    gc_text = "YES" if gc == 1 else "no"
    print(f"  Origin: {origin or '?'} | Severity: S{sev or '?'} | "
          f"Gate-critical: {gc_text}")

    if task["status"] == "DONE":
        print("  ⚠️  Task is already DONE")
        return

    if task["assignee"] != "CLAUDE":
        print(f"  🛑 STOP — Task is assigned to {task['assignee']}, not Claude")
        print("")
        print("  🛑 CANNOT PROCEED")
        sys.exit(1)

    blocked_by = task["blocked_by"]
    if blocked_by:
        blocker_status = db.fetch_one(
            "SELECT status FROM tasks WHERE id=?", (blocked_by,)
        )
        if blocker_status and blocker_status not in ("DONE", "SKIP"):
            print(f"  🛑 STOP — Blocked by {blocked_by} ({blocker_status})")
            print("")
            print("  🛑 CANNOT PROCEED")
            sys.exit(1)
        elif blocker_status is None:
            print(f"  ⚠️  WARN — blocked_by '{blocked_by}' not found "
                  f"(stale reference)")

    # Lesson recall for loopbacks too
    _lesson_recall(config, task["title"], "")

    print(f"\n  ✅ GO — {task_id} is clear to start (loopback)")
    _print_discipline_advisory(is_loopback=True)
    print("")


def _check_milestone_gate(
    db: Database, task_id: str, phase: str, sort_order: int
) -> list:
    """Check milestone gate rules (lines 372-506). Returns list of reasons."""
    # If this task was already confirmed by Master, skip ALL milestone gate
    # rules — the approval was already recorded and re-firing would block
    # forward progress unnecessarily.
    already_confirmed = db.fetch_scalar(
        "SELECT COUNT(*) FROM milestone_confirmations WHERE task_id = ?",
        (task_id,),
    )
    if already_confirmed and already_confirmed > 0:
        return []

    reasons = []

    # Rule 1: First Claude task in this phase
    done_claude = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks "
        "WHERE phase=? AND assignee='CLAUDE' AND status='DONE'",
        (phase,),
    )
    if done_claude == 0:
        reasons.append(f"  - First Claude task in phase {phase}")

    # Rule 2: Previous task is Master/Gemini
    prev = db.fetch_one(
        "SELECT assignee, id, title FROM tasks "
        "WHERE sort_order < ? AND status != 'SKIP' "
        "ORDER BY sort_order DESC LIMIT 1",
        (sort_order,),
    )
    if prev and prev["assignee"] in ("MASTER", "GEMINI"):
        reasons.append(
            f"  - Follows {prev['assignee']} task {prev['id']}: {prev['title']}"
        )

    # Rule 3: Last remaining Claude task in this phase
    remaining_claude = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks "
        "WHERE phase=? AND assignee='CLAUDE' "
        "AND status NOT IN ('DONE','SKIP') AND id != ?",
        (phase, task_id),
    )
    if remaining_claude == 0:
        remaining_master = db.fetch_one(
            "SELECT GROUP_CONCAT(id, ', ') FROM tasks "
            "WHERE phase=? AND assignee IN ('MASTER','GEMINI') "
            "AND status NOT IN ('DONE','SKIP')",
            (phase,),
        )
        if remaining_master and remaining_master[0]:
            reasons.append(
                f"  - Last Claude task in {phase} — "
                f"Master tasks remain: {remaining_master[0]}"
            )
        else:
            reasons.append(
                f"  - Last task in {phase} — phase gate review follows"
            )

    # Rule 4: Rolling checkpoint

    rolling_threshold = 5
    last_confirmed_sort = db.fetch_scalar(
        "SELECT MAX(t.sort_order) FROM milestone_confirmations mc "
        "JOIN tasks t ON mc.task_id = t.id "
        "WHERE t.sort_order < ?",
        (sort_order,),
    )

    if last_confirmed_sort and last_confirmed_sort > 0:
        # Strategy A: count since last confirmation
        rolling = db.fetch_scalar(
            "SELECT COUNT(*) FROM tasks "
            "WHERE assignee='CLAUDE' AND status='DONE' "
            "AND sort_order > ? AND sort_order < ?",
            (last_confirmed_sort, sort_order),
        )
        if rolling >= rolling_threshold:
            reasons.append(
                f"  - Rolling checkpoint: {rolling} tasks since last "
                f"confirmed milestone"
            )
    else:
        # Strategy B: structural detection (complex CTE)
        # Replicate the bash version's SQL exactly
        rolling = db.fetch_scalar(
            """
            WITH done_claude AS (
                SELECT id, phase, sort_order,
                    ROW_NUMBER() OVER (ORDER BY sort_order DESC) AS rn
                FROM tasks
                WHERE assignee='CLAUDE' AND status='DONE'
                  AND sort_order < ?
                ORDER BY sort_order DESC
            ),
            with_checks AS (
                SELECT dc.*,
                    (SELECT COUNT(*) FROM tasks t2
                     WHERE t2.phase = dc.phase AND t2.assignee = 'CLAUDE'
                       AND t2.status = 'DONE'
                       AND t2.sort_order < dc.sort_order) AS done_before_in_phase,
                    COALESCE((SELECT t3.assignee FROM tasks t3
                     WHERE t3.sort_order < dc.sort_order AND t3.status != 'SKIP'
                     ORDER BY t3.sort_order DESC LIMIT 1), '') AS prev_assignee,
                    (SELECT COUNT(*) FROM tasks t4
                     WHERE t4.phase = dc.phase AND t4.assignee = 'CLAUDE'
                       AND t4.sort_order > dc.sort_order) AS later_in_phase
                FROM done_claude dc
            ),
            counted AS (
                SELECT *,
                    CASE WHEN done_before_in_phase = 0 THEN 1
                         WHEN prev_assignee IN ('MASTER','GEMINI') THEN 1
                         WHEN later_in_phase = 0 THEN 1
                         ELSE 0 END AS is_checkpoint
                FROM with_checks
                ORDER BY sort_order DESC
            )
            SELECT COUNT(*) FROM (
                SELECT sort_order, is_checkpoint,
                    SUM(is_checkpoint) OVER (
                        ORDER BY sort_order DESC
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ) AS cp_seen
                FROM counted
            ) sub
            WHERE cp_seen = 0
            """,
            (sort_order,),
        )
        if rolling >= rolling_threshold:
            reasons.append(
                f"  - Rolling checkpoint: {rolling} tasks since last "
                f"structural confirm"
            )

    return reasons


# ── task command (read-only detail view) ─────────────────────────────

def cmd_task(db: Database, task_id: str):
    """Show detailed info for a single task.

    Matches db_queries_legacy.template.sh lines 967-985.
    """
    task = db.fetch_one(
        "SELECT id, phase, queue, assignee, priority, status, "
        "COALESCE(tier, '⚠️  NOT ASSIGNED') as tier, "
        "COALESCE(skill, 'none') as skill, "
        "blocked_by, completed_on, title, details, research_notes, "
        "COALESCE(track,'forward') as track, origin_phase, severity, "
        "gate_critical, loopback_reason, needs_browser, researched, "
        "breakage_tested, files_touched, handover_notes "
        "FROM tasks WHERE id=?",
        (task_id,),
    )
    if task is None:
        print(f"❌ Task '{task_id}' not found")
        sys.exit(1)

    print(f"── Task: {task['id']} ──")
    print(f"Phase:    {task['phase']}")
    print(f"Queue:    {task['queue']} | Assignee: {task['assignee']}")
    print(f"Priority: {task['priority']} | Status: {task['status']}")
    print(f"Tier:     {task['tier']} | Skill: {task['skill']}")
    if task["blocked_by"]:
        print(f"Blocked by: {task['blocked_by']}")
    if task["completed_on"]:
        print(f"Completed: {task['completed_on']}")
    print(f"")
    print(f"Title: {task['title']}")
    if task["details"]:
        print(f"\nDetails:\n{task['details']}")
    if task["research_notes"]:
        print(f"\n📖 Research:\n{task['research_notes']}")
    if task["files_touched"]:
        try:
            files = json.loads(task["files_touched"])
            if files:
                print(f"\n📁 Files touched:")
                for f in files[:15]:
                    print(f"  {f}")
                if len(files) > 15:
                    print(f"  ... ({len(files) - 15} more)")
        except (json.JSONDecodeError, TypeError):
            pass
    if task["handover_notes"]:
        print(f"\n📝 Handover notes:\n{task['handover_notes']}")


# ── start command ────────────────────────────────────────────────────

def cmd_start(db: Database, task_id: str, config=None):
    """Mark a task as IN_PROGRESS and update hook state.

    Also writes .last_check_result so the tier gate tracks the correct
    active task (prevents false blocks during batch operations).
    """
    task = db.fetch_one(
        "SELECT id, status, tier FROM tasks WHERE id=?", (task_id,),
    )
    if task is None:
        print(f"❌ Task '{task_id}' not found")
        sys.exit(1)

    db.execute(
        "UPDATE tasks SET status='IN_PROGRESS' WHERE id=?", (task_id,),
    )
    db.commit()
    print(f"🔵 Marked IN_PROGRESS: {task_id}")

    # Update hook state so tier gate tracks the active task
    if config is not None:
        hooks_dir = config.project_dir / ".claude" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        check_file = hooks_dir / ".last_check_result"
        task_tier = task["tier"] if task["tier"] else ""
        check_file.write_text(f"GO|{int(time.time())}|{task_id}|{task_tier}\n")


# ── skip command ─────────────────────────────────────────────────────

def cmd_skip(db: Database, task_id: str, reason: str = ""):
    """Mark a task as SKIP with optional reason.

    Matches db_queries_legacy.template.sh lines 2820-2839.
    """
    task = db.fetch_one(
        "SELECT id, COALESCE(track,'forward') as track FROM tasks WHERE id=?",
        (task_id,),
    )
    if task is None:
        print(f"❌ Task '{task_id}' not found")
        sys.exit(1)

    today = _format_date()

    if reason:
        db.execute(
            "UPDATE tasks SET status='SKIP', completed_on=?, details=? WHERE id=?",
            (today, reason, task_id),
        )
    else:
        db.execute(
            "UPDATE tasks SET status='SKIP', completed_on=? WHERE id=?",
            (today, task_id),
        )
    db.commit()

    print(f"⏭️  Skipped: {task_id} ({today})")
    if reason:
        print(f"   Reason: {reason}")

    # Loopback cleanup: delete ack if exists
    if task["track"] == "loopback":
        db.execute(
            "DELETE FROM loopback_acks WHERE loopback_id=?", (task_id,),
        )
        db.commit()


# ── unblock command ──────────────────────────────────────────────────

def cmd_unblock(db: Database, task_id: str):
    """Clear blocked_by on a task.

    Matches db_queries_legacy.template.sh lines 2784-2794.
    """
    task = db.fetch_one(
        "SELECT id, blocked_by FROM tasks WHERE id=?", (task_id,),
    )
    if task is None:
        print(f"❌ Task '{task_id}' not found")
        sys.exit(1)

    old_blocker = task["blocked_by"]
    if not old_blocker:
        print(f"  Task {task_id} has no blocked_by set")
        return

    db.execute(
        "UPDATE tasks SET blocked_by=NULL WHERE id=?", (task_id,),
    )
    db.commit()
    print(f"✅ Cleared blocked_by on {task_id} (was: {old_blocker})")


# ── tag-browser command ──────────────────────────────────────────────

def cmd_tag_browser(db: Database, task_id: str, value: int = 1):
    """Tag or untag a task as needs_browser.

    Matches db_queries_legacy.template.sh lines 1214-1224.
    """
    task = db.fetch_one(
        "SELECT id FROM tasks WHERE id=?", (task_id,),
    )
    if task is None:
        print(f"❌ Task '{task_id}' not found")
        sys.exit(1)

    db.execute(
        "UPDATE tasks SET needs_browser=? WHERE id=?", (value, task_id),
    )
    db.commit()

    if value:
        print(f"🌐 Tagged {task_id} as needs_browser")
    else:
        print(f"🌐 Untagged {task_id} — no longer needs_browser")


# ── researched command ───────────────────────────────────────────────

def cmd_researched(db: Database, task_id: str):
    """Mark a task as researched (Layer 2 gate).

    Matches db_queries_legacy.template.sh lines 2290-2305.
    """
    task = db.fetch_one(
        "SELECT id FROM tasks WHERE id=?", (task_id,),
    )
    if task is None:
        print(f"❌ Task '{task_id}' not found")
        sys.exit(1)

    db.execute(
        "UPDATE tasks SET researched=1 WHERE id=?", (task_id,),
    )
    db.commit()
    print(f"✅ Marked as researched: {task_id}")


# ── break-tested command ─────────────────────────────────────────────

def cmd_break_tested(db: Database, task_id: str):
    """Mark a task as breakage-tested (Layer 4 gate).

    Matches db_queries_legacy.template.sh lines 2307-2322.
    """
    task = db.fetch_one(
        "SELECT id FROM tasks WHERE id=?", (task_id,),
    )
    if task is None:
        print(f"❌ Task '{task_id}' not found")
        sys.exit(1)

    db.execute(
        "UPDATE tasks SET breakage_tested=1 WHERE id=?", (task_id,),
    )
    db.commit()
    print(f"✅ Marked as breakage-tested: {task_id}")


# ── inbox command ────────────────────────────────────────────────────

def cmd_inbox(db: Database):
    """Show untriaged inbox tasks.

    Matches db_queries_legacy.template.sh lines 2467-2487.
    """
    output.print_section("Inbox (untriaged tasks)")

    count = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks "
        "WHERE queue='INBOX' AND status NOT IN ('SKIP','DONE','WONTFIX')"
    )

    if count == 0:
        print("  (empty)")
        print("")
        return

    rows = db.fetch_all(
        "SELECT id, title, phase, COALESCE(details, '') AS tag "
        "FROM tasks "
        "WHERE queue='INBOX' AND status NOT IN ('SKIP','DONE','WONTFIX') "
        "ORDER BY sort_order, id"
    )

    for r in rows:
        tag = f"  [{r['tag']}]" if r["tag"] else ""
        print(f"  {r['id']}  {r['title']}  ({r['phase']}){tag}")

    print("")
    print(f"  {count} item(s) in inbox")
    print("  Triage: bash db_queries.sh triage <id> <phase> <tier> [skill] [blocked_by]")
    print("")


# ── triage command ───────────────────────────────────────────────────

def cmd_triage(
    db: Database,
    task_id: str,
    phase: str,
    tier: str = "",
    skill: str = "",
    blocked_by: str = "",
    loopback_origin: str = "",
    severity: int = 3,
    gate_critical: bool = False,
    reason: str = "",
):
    """Triage an inbox task into a phase/queue.

    Two modes:
    - Standard: triage <id> <phase> <tier> [skill] [blocked_by]
    - Loopback: triage <id> loopback <origin_phase> --severity N --gate-critical

    Matches db_queries_legacy.template.sh lines 2489-2581.
    """
    # Validate task is in INBOX
    queue = db.fetch_one(
        "SELECT queue FROM tasks WHERE id=?", (task_id,),
    )
    if queue is None:
        print(f"❌ Task '{task_id}' not found")
        sys.exit(1)
    if queue != "INBOX":
        print(f"⚠️  Task '{task_id}' is not in INBOX (queue: {queue})")
        sys.exit(1)

    if phase == "loopback":
        _triage_loopback(db, task_id, loopback_origin or tier,
                         severity, gate_critical, reason)
    else:
        _triage_standard(db, task_id, phase, tier, skill, blocked_by)


def _triage_standard(
    db: Database, task_id: str, phase: str, tier: str,
    skill: str, blocked_by: str,
):
    """Standard triage: move to phase with tier assignment."""
    # Get next sort_order for that phase
    max_sort = db.fetch_scalar(
        "SELECT COALESCE(MAX(sort_order), 0) FROM tasks WHERE phase=?",
        (phase,),
    )
    sort_order = max_sort + 10

    # Derive priority from phase prefix
    priority = phase.split("-")[0] if "-" in phase else phase

    skill_val = skill if skill else None
    blocked_val = blocked_by if blocked_by else None

    db.execute(
        "UPDATE tasks SET queue='A', phase=?, tier=?, priority=?, "
        "sort_order=?, skill=?, blocked_by=?, original_tier=? WHERE id=?",
        (phase, tier, priority, sort_order, skill_val, blocked_val, tier, task_id),
    )
    db.commit()

    title = db.fetch_one(
        "SELECT title FROM tasks WHERE id=?", (task_id,),
    )
    print(f"✅ Triaged: {task_id} → {phase} ({tier})")
    print(f"   {title}")
    print(f"   Sort order: {sort_order} | Skill: {skill or 'none'} | "
          f"Blocked by: {blocked_by or 'none'}")


def _triage_loopback(
    db: Database, task_id: str, origin_phase: str,
    severity: int, gate_critical: bool, reason: str,
):
    """Loopback triage: convert inbox task to loopback."""
    # Get current phase as discovered_in
    disc_phase = db.fetch_one(
        "SELECT phase FROM tasks WHERE id=?", (task_id,),
    )
    gc_val = 1 if gate_critical else 0
    reason_val = reason if reason else None

    db.execute(
        "UPDATE tasks SET queue='A', track='loopback', priority='LB', "
        "origin_phase=?, discovered_in=?, severity=?, gate_critical=?, "
        "loopback_reason=? WHERE id=?",
        (origin_phase, disc_phase, severity, gc_val, reason_val, task_id),
    )
    db.commit()

    title = db.fetch_one(
        "SELECT title FROM tasks WHERE id=?", (task_id,),
    )
    sev_icon = output.severity_icon(severity)
    print(f"{sev_icon} Triaged as loopback: {task_id} → origin {origin_phase} (S{severity})")
    print(f"   {title}")
    if gate_critical:
        print("   Gate-critical: YES")
    if reason:
        print(f"   Reason: {reason}")


# ── add-task command ─────────────────────────────────────────────────

def cmd_add_task(
    db: Database,
    task_id: str,
    phase: str,
    title: str,
    tier: str,
    skill: str = "",
    blocked_by: str = "",
    sort_order: int = 999,
):
    """Add a task with full field control.

    Matches db_queries_legacy.template.sh lines 1542-1583.
    """
    # Derive priority from phase prefix
    priority = phase.split("-")[0] if "-" in phase else phase

    skill_val = skill if skill else None
    blocked_val = blocked_by if blocked_by else None

    db.execute(
        "INSERT OR REPLACE INTO tasks "
        "(id, phase, assignee, title, priority, status, blocked_by, "
        "sort_order, tier, skill) "
        "VALUES (?, ?, 'CLAUDE', ?, ?, 'TODO', ?, ?, ?, ?)",
        (task_id, phase, title, priority, blocked_val, sort_order, tier, skill_val),
    )
    db.commit()

    print(f"✅ Added task: {task_id} ({tier}) — {title}")
    print(f"   Phase: {phase} | Skill: {skill or 'none'} | "
          f"Blocked by: {blocked_by or 'none'}")


# ── Lesson Recall & Critical Files Helpers ──────────────────────────


def _extract_keywords(text: str, min_len: int = 4, max_count: int = 8) -> List[str]:
    """Extract keywords from text: lowercase, alpha-only, length >= min_len."""
    words = re.findall(r"[a-zA-Z]+", text.lower())
    seen = set()
    result = []
    for w in words:
        if len(w) >= min_len and w not in seen:
            seen.add(w)
            result.append(w)
            if len(result) >= max_count:
                break
    return result


def _context_keywords(combined_text: str) -> List[str]:
    """Add context-aware keywords based on task content patterns."""
    text = combined_text.lower()
    extra = []  # type: List[str]
    if any(k in text for k in ("delegat", "sub-agent", "subagent", "haiku", "sonnet", "tier")):
        extra.extend(["delegation", "tier"])
    if any(k in text for k in ("handoff", "next_session", "session", "save")):
        extra.extend(["handoff", "intent", "fact"])
    if any(k in text for k in ("model", "orchestrat", "opus")):
        extra.extend(["model", "verification", "orchestrator"])
    if any(k in text for k in ("phase", "gate", "batch")):
        extra.extend(["delegation", "batch", "phase"])
    return extra


def _grep_lessons(lessons_path: str, keywords: List[str],
                  max_hits: int = 5) -> List[Tuple[str, str]]:
    """Search LESSONS file for keyword matches in both table rows and ### blocks.

    Returns list of (pattern, rule) tuples extracted from matching entries.
    Supports variable-width markdown tables and ### block format with
    **Pattern:** / **Prevention:** fields.
    """
    if not lessons_path or not Path(lessons_path).is_file():
        return []

    try:
        content = Path(lessons_path).read_text(encoding="utf-8")
    except OSError:
        return []

    lines = content.splitlines()

    # Detect column positions from header row (if table exists)
    pattern_col = -1
    rule_col = -1
    for line in lines:
        if line.startswith("| Date") or line.startswith("| #"):
            cols = [c.strip().lower() for c in line.split("|")]
            for idx, col in enumerate(cols):
                if col in ("pattern", "what happened", "what went wrong", "lesson"):
                    pattern_col = idx
                elif col in ("prevention rule", "prevention", "rule"):
                    rule_col = idx
            break

    # Collect matching table rows
    table_hits: set = set()
    for kw in keywords:
        kw_lower = kw.lower()
        for line in lines:
            if not line.startswith("|"):
                continue
            if line.startswith("| Date") or line.startswith("| #") or line.startswith("|---"):
                continue
            if kw_lower in line.lower():
                table_hits.add(line)

    results: List[Tuple[str, str]] = []
    for line in sorted(table_hits):
        parts = [p.strip() for p in line.split("|")]
        # Use detected column positions, fallback to heuristic
        if pattern_col > 0 and pattern_col < len(parts):
            pattern = parts[pattern_col]
        elif len(parts) >= 4:
            pattern = parts[2] if len(parts) <= 5 else parts[3]
        else:
            continue
        if rule_col > 0 and rule_col < len(parts):
            rule = parts[rule_col]
        elif len(parts) >= 5:
            rule = parts[3] if len(parts) <= 5 else parts[4]
        else:
            rule = ""
        if pattern:
            results.append((pattern, rule))
        if len(results) >= max_hits:
            return results

    # Collect matching ### blocks
    i = 0
    while i < len(lines):
        if lines[i].strip().startswith("### "):
            # Gather the block: heading + subsequent **Key:** lines
            heading = lines[i].strip()[4:]  # strip "### "
            block_text = heading
            pattern = ""
            rule = ""
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith("### ") and not lines[j].strip().startswith("## "):
                bl = lines[j].strip()
                block_text += " " + bl
                if bl.startswith("**Pattern:**"):
                    pattern = bl[len("**Pattern:**"):].strip()
                elif bl.startswith("**Prevention:**"):
                    rule = bl[len("**Prevention:**"):].strip()
                j += 1
            # Check keyword match across the entire block
            block_lower = block_text.lower()
            if any(kw.lower() in block_lower for kw in keywords):
                display = pattern or heading
                if display:
                    results.append((display, rule))
                if len(results) >= max_hits:
                    return results
            i = j
        else:
            i += 1

    return results


def _lesson_recall(config, title: str, details: str):
    """Search LESSONS file for corrections relevant to this task."""
    lessons_path = config.lessons_file
    if not lessons_path:
        # Try to find it relative to project dir
        project_dir = config.project_dir
        candidates = list(project_dir.glob("LESSONS*.md"))
        if candidates:
            lessons_path = str(candidates[0])

    if not lessons_path or not Path(lessons_path).is_file():
        return

    # Build keyword list: title keywords + context keywords
    keywords = _extract_keywords(title)
    combined = f"{title} {details}"
    keywords.extend(_context_keywords(combined))

    if not keywords:
        return

    matches = _grep_lessons(lessons_path, keywords)
    if matches:
        print("")
        print("  📖 Relevant lessons from past corrections:")
        for pattern, rule in matches:
            print(f"     ⚠️  {pattern}")
            print(f"     → {rule}")
            print("")


def _critical_files_check(config, title: str, details: str):
    """Check if task might touch critical files and surface audit prompts.

    Supports two registry formats:
    1. JSON: critical_files_registry.json — array of {pattern, level, audit}
    2. Bash: critical_files_registry.sh — parallel arrays (parsed from source)
    """
    project_dir = config.project_dir

    # Try JSON first (preferred format)
    json_path = project_dir / "critical_files_registry.json"
    if json_path.is_file():
        entries = _load_registry_json(json_path)
    else:
        # Fall back to bash array parsing
        bash_path = project_dir / "critical_files_registry.sh"
        if bash_path.is_file():
            entries = _load_registry_bash(bash_path)
        else:
            return

    if not entries:
        return

    # Build keywords from title + details
    combined = f"{title} {details}".lower()
    keywords = re.findall(r"[a-zA-Z.]+", combined)
    keywords = [k for k in keywords if len(k) >= 3][:15]

    if not keywords:
        return

    # Match keywords against registry patterns
    hits = []
    for entry in entries:
        pattern_lower = entry["pattern"].lower()
        for kw in keywords:
            if kw in pattern_lower:
                hits.append(entry)
                break  # Don't double-match same entry

    if hits:
        print("")
        print("  🔒 Critical files likely touched by this task:")
        for entry in hits:
            print(f"     [{entry['level']}] {entry['pattern']}")
            print(f"     → {entry['audit']}")
            print("")


def _load_registry_json(path: Path) -> List[dict]:
    """Load critical files registry from JSON format."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [e for e in data
                    if isinstance(e, dict) and "pattern" in e
                    and "level" in e and "audit" in e]
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _load_registry_bash(path: Path) -> List[dict]:
    """Parse critical files registry from bash parallel array format.

    Expected format:
        CRITICAL_PATTERNS+=("glob pattern")
        CRITICAL_LEVELS+=("INVARIANT|SEMANTIC")
        CRITICAL_AUDITS+=("audit instruction")
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return []

    # Filter out commented lines before parsing
    lines = [ln for ln in content.splitlines() if not ln.lstrip().startswith("#")]
    active = "\n".join(lines)
    patterns = re.findall(r'CRITICAL_PATTERNS\+=\("([^"]+)"\)', active)
    levels = re.findall(r'CRITICAL_LEVELS\+=\("([^"]+)"\)', active)
    audits = re.findall(r'CRITICAL_AUDITS\+=\("([^"]+)"\)', active)

    if len(patterns) != len(levels) or len(patterns) != len(audits):
        return []

    return [
        {"pattern": p, "level": l, "audit": a}
        for p, l, a in zip(patterns, levels, audits)
    ]
