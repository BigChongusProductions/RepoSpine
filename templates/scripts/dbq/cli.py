"""
CLI entry point — argparse wiring for all commands.

Tests Assumption #8: can argparse handle the complex argument patterns?
Specifically: quick with mixed positional+flag args, done with --skip-break.
"""
import argparse
import sys
from typing import List, Optional

from .config import detect_config
from .db import Database, DatabaseError, open_db


def main(argv: Optional[List[str]] = None):
    parser = argparse.ArgumentParser(
        prog="dbq",
        description="Project SQLite Query Helpers (Python PoC)",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ── init-db ──
    subparsers.add_parser("init-db", help="Create all tables (idempotent)")

    # ── health ──
    subparsers.add_parser("health", help="Pipeline health diagnostic")

    # ── done ──
    p_done = subparsers.add_parser("done", help="Mark a task DONE")
    p_done.add_argument("task_id", help="Task ID")
    p_done.add_argument(
        "--skip-break", action="store_true",
        help="Skip breakage test nag",
    )
    p_done.add_argument(
        "--files", nargs="+", default=None,
        help="Specific files to stage (avoids git add -A cross-contamination in parallel work)",
    )
    p_done.add_argument(
        "--research", action="store_true",
        help="Research-only task — skip auto-commit (no code changes to commit)",
    )

    # ── check ──
    p_check = subparsers.add_parser("check", help="Pre-task safety check")
    p_check.add_argument("task_id", help="Task ID")

    # ── quick ──
    p_quick = subparsers.add_parser(
        "quick", help="Quick ad-hoc task capture",
    )
    p_quick.add_argument("title", help="Task title")
    p_quick.add_argument("phase", nargs="?", default="INBOX", help="Phase")
    p_quick.add_argument("tag", nargs="?", default="", help="Tag")
    p_quick.add_argument(
        "--loopback", dest="loopback_origin", default="",
        help="Create loopback task targeting ORIGIN_PHASE",
    )
    p_quick.add_argument(
        "--severity", type=int, default=3,
        help="Severity 1-4 (default: 3)",
    )
    p_quick.add_argument(
        "--gate-critical", action="store_true",
        help="Mark as gate-critical",
    )
    p_quick.add_argument(
        "--reason", default="",
        help="Loopback reason text",
    )

    # ── task (detail view) ──
    p_task = subparsers.add_parser("task", help="Show task details")
    p_task.add_argument("task_id", help="Task ID")

    # ── start ──
    p_start = subparsers.add_parser("start", help="Mark task IN_PROGRESS")
    p_start.add_argument("task_id", help="Task ID")

    # ── skip ──
    p_skip = subparsers.add_parser("skip", help="Mark task as SKIP")
    p_skip.add_argument("task_id", help="Task ID")
    p_skip.add_argument("reason", nargs="?", default="", help="Skip reason")

    # ── unblock ──
    p_unblock = subparsers.add_parser("unblock", help="Clear blocked_by")
    p_unblock.add_argument("task_id", help="Task ID")

    # ── tag-browser ──
    p_tagb = subparsers.add_parser("tag-browser", help="Toggle needs_browser")
    p_tagb.add_argument("task_id", help="Task ID")
    p_tagb.add_argument("value", nargs="?", type=int, default=1, help="0 or 1")

    # ── researched ──
    p_res = subparsers.add_parser("researched", help="Mark task as researched")
    p_res.add_argument("task_id", help="Task ID")

    # ── break-tested ──
    p_bt = subparsers.add_parser("break-tested", help="Mark as breakage-tested")
    p_bt.add_argument("task_id", help="Task ID")

    # ── inbox ──
    subparsers.add_parser("inbox", help="Show inbox tasks")

    # ── triage ──
    p_tri = subparsers.add_parser("triage", help="Triage inbox task to phase")
    p_tri.add_argument("task_id", help="Task ID")
    p_tri.add_argument("phase", help="Target phase (or 'loopback')")
    p_tri.add_argument("tier", nargs="?", default="", help="Tier (or origin_phase for loopback)")
    p_tri.add_argument("skill", nargs="?", default="", help="Skill tag")
    p_tri.add_argument("blocked_by", nargs="?", default="", help="Blocked by task ID")
    p_tri.add_argument("--severity", type=int, default=3, help="Loopback severity")
    p_tri.add_argument("--gate-critical", action="store_true", help="Loopback gate-critical")
    p_tri.add_argument("--reason", default="", help="Loopback reason")

    # ── add-task ──
    p_at = subparsers.add_parser("add-task", help="Add task with full fields")
    p_at.add_argument("task_id", help="Task ID")
    p_at.add_argument("phase", help="Phase")
    p_at.add_argument("title", help="Task title")
    p_at.add_argument("tier", help="Tier (haiku/sonnet/opus/gemini/skip)")
    p_at.add_argument("skill", nargs="?", default="", help="Skill tag")
    p_at.add_argument("blocked_by", nargs="?", default="", help="Blocked by")
    p_at.add_argument("sort_order", nargs="?", type=int, default=999, help="Sort order")

    # ── phase ──
    subparsers.add_parser("phase", help="Show current phase")

    # ── gate ──
    subparsers.add_parser("gate", help="Show phase gate status")

    # ── gate-pass ──
    p_gp = subparsers.add_parser("gate-pass", help="Record phase gate pass")
    p_gp.add_argument("phase", help="Phase name")
    p_gp.add_argument("gated_by", nargs="?", default="MASTER", help="Who gated")
    p_gp.add_argument("--notes", default="Phase gate review passed",
                       help="Gate notes")

    # ── status ──
    subparsers.add_parser("status", help="Show project status by phase")

    # ── blockers ──
    subparsers.add_parser("blockers", help="Show tasks blocking Claude")

    # ── confirm ──
    p_conf = subparsers.add_parser("confirm", help="Confirm a milestone")
    p_conf.add_argument("task_id", help="Task ID")
    p_conf.add_argument("confirmed_by", nargs="?", default="MASTER",
                         help="Who confirmed")
    p_conf.add_argument("reasons", nargs="?", default="Milestone confirmed",
                         help="Confirmation reasons")

    # ── confirmations ──
    subparsers.add_parser("confirmations", help="Show milestone confirmations")

    # ── master ──
    subparsers.add_parser("master", help="Show Master/Gemini TODO tasks")

    # ── next ──
    p_next = subparsers.add_parser("next", help="Task queue — what to work on")
    p_next.add_argument("--ready-only", action="store_true",
                         help="Skip blocked/stale sections")
    p_next.add_argument("--smart", action="store_true",
                         help="Score forward tasks by impact")

    # ── sessions ──
    subparsers.add_parser("sessions", help="List session log")

    # ── log ──
    p_log = subparsers.add_parser("log", help="Log a session")
    p_log.add_argument("session_type", help="Session type")
    p_log.add_argument("summary", help="Session summary")

    # ── decisions ──
    subparsers.add_parser("decisions", help="List decision log")

    # ── loopbacks ──
    p_lb = subparsers.add_parser("loopbacks", help="List loopback tasks")
    p_lb.add_argument("--origin", default="", help="Filter by origin phase")
    p_lb.add_argument("--severity", type=int, default=0, help="Filter by severity")
    p_lb.add_argument("--gate-critical", action="store_true", help="Gate-critical only")
    p_lb.add_argument("--all", dest="show_all", action="store_true",
                       help="Include DONE/SKIP")

    # ── loopback-stats ──
    subparsers.add_parser("loopback-stats", help="Loopback analytics")

    # ── loopback-count ──
    subparsers.add_parser("loopback-count", help="Count open loopback tasks")

    # ── loopback-summary ──
    subparsers.add_parser("loopback-summary", help="One-line severity summary of open loopbacks")

    # ── loopback-lesson ──
    p_ll = subparsers.add_parser("loopback-lesson", help="Log lesson from loopback")
    p_ll.add_argument("task_id", help="Loopback task ID")

    # ── ack-breaker ──
    p_ab = subparsers.add_parser("ack-breaker", help="Acknowledge circuit breaker")
    p_ab.add_argument("task_id", help="Loopback task ID")
    p_ab.add_argument("reason", help="Acknowledgment reason")

    # ── assume ──
    p_assume = subparsers.add_parser("assume", help="Record an assumption")
    p_assume.add_argument("task_id", help="Task ID")
    p_assume.add_argument("assumption", help="Assumption text")
    p_assume.add_argument("verify_cmd", nargs="?", default="",
                           help="Verification command")

    # ── verify-assumption ──
    p_va = subparsers.add_parser("verify-assumption", help="Verify one assumption")
    p_va.add_argument("task_id", help="Task ID")
    p_va.add_argument("assumption_id", type=int, help="Assumption ID")

    # ── verify-all ──
    p_vall = subparsers.add_parser("verify-all", help="Verify all assumptions")
    p_vall.add_argument("task_id", help="Task ID")

    # ── assumptions ──
    p_asms = subparsers.add_parser("assumptions", help="List assumptions")
    p_asms.add_argument("task_id", help="Task ID")

    # ── Knowledge commands ──
    subparsers.add_parser("lessons", help="Show LESSONS.md with staleness")

    p_ll2 = subparsers.add_parser("log-lesson", help="Log a correction to LESSONS file")
    p_ll2.add_argument("what_wrong", help="What went wrong")
    p_ll2.add_argument("pattern", help="Pattern identified")
    p_ll2.add_argument("prevention", help="Prevention rule")
    p_ll2.add_argument("--bp", dest="bp_category", default="",
                        help="Also escalate to bootstrap backlog (category)")
    p_ll2.add_argument("--bp-file", dest="bp_file", default="",
                        help="Affected file for bootstrap escalation")

    p_promote = subparsers.add_parser("promote", help="Promote pattern to universal")
    p_promote.add_argument("pattern", help="Pattern text")
    p_promote.add_argument("rule", nargs="?", default="", help="Prevention rule")
    p_promote.add_argument(
        "--method", default="",
        help="Discovery method for provenance (correction/audit/harvest/manual)",
    )
    p_promote.add_argument(
        "--source-file", dest="source_file", default="",
        help="LESSONS file to mark as promoted (default: project lessons file)",
    )
    p_promote.add_argument(
        "--source-project", dest="source_project", default="",
        help="Project name for provenance (default: current project)",
    )

    p_esc = subparsers.add_parser("escalate", help="Escalate to bootstrap backlog")
    p_esc.add_argument("description", help="Description")
    p_esc.add_argument("category", nargs="?", default="template",
                        help="Category (template/framework/process/system)")
    p_esc.add_argument("affected_file", nargs="?", default="unknown (review needed)",
                        help="Affected file")
    p_esc.add_argument("--priority", default="P2", help="Priority P0-P3")

    p_harvest = subparsers.add_parser("harvest", help="Surface unpromoted lessons with dedup detection")
    p_harvest.add_argument("paths", nargs="*", help="LESSONS file paths (default: project lessons file)")
    p_harvest.add_argument(
        "--mark-dupes", action="store_true", dest="mark_dupes",
        help="Auto-mark duplicate entries as promoted in source files",
    )

    # ── Delegation commands ──
    p_deleg = subparsers.add_parser("delegation", help="Delegation table from DB")
    p_deleg.add_argument("phase", nargs="?", default="", help="Filter by phase")

    p_dmd = subparsers.add_parser("delegation-md", help="Regenerate AGENT_DELEGATION.md §8")
    p_dmd.add_argument("--active-only", action="store_true", help="Filter out DONE/WONTFIX/SKIP rows")

    subparsers.add_parser("sync-check", help="DB ↔ AGENT_DELEGATION.md drift check")

    p_tu = subparsers.add_parser("tier-up", help="Escalate task to higher tier")
    p_tu.add_argument("task_id", help="Task ID")
    p_tu.add_argument("new_tier", help="Target tier (haiku/sonnet/opus/gemini)")
    p_tu.add_argument("reason", help="Reason: prompt|context|ceiling|environment")

    # ── Snapshot commands ──
    p_snap = subparsers.add_parser("snapshot", help="Save DB state snapshot")
    p_snap.add_argument("label", nargs="?", default="", help="Snapshot label")

    subparsers.add_parser("snapshot-list", help="List all snapshots")

    p_ss = subparsers.add_parser("snapshot-show", help="Show snapshot details")
    p_ss.add_argument("snap_id", type=int, help="Snapshot ID")

    p_sd = subparsers.add_parser("snapshot-diff", help="Diff two snapshots")
    p_sd.add_argument("id1", type=int, help="First snapshot ID")
    p_sd.add_argument("id2", type=int, help="Second snapshot ID")

    # ── Session git commands ──
    subparsers.add_parser("tag-session", help="Create session git tag")
    subparsers.add_parser("session-tags", help="List session git tags")

    p_sf = subparsers.add_parser("session-file", help="Show file at session tag")
    p_sf.add_argument("session_num", help="Session number")
    p_sf.add_argument("file_path", help="File to show")

    # ── Health extras ──
    subparsers.add_parser("backup", help="Backup DB to backups/")

    p_restore = subparsers.add_parser("restore", help="Restore DB from backup")
    p_restore.add_argument("restore_file", nargs="?", default=None,
                            help="Backup file (omit to list)")

    subparsers.add_parser("verify", help="Verify DB is populated")

    # ── export / import ──
    p_exp = subparsers.add_parser("export", help="Export DB as JSON")
    p_exp.add_argument("--table", default="", help="Comma-separated table names")
    p_exp.add_argument("--pretty", action="store_true", help="Indented JSON")
    p_exp.add_argument("-o", "--output", default="", dest="output_file",
                        help="Output file (default: stdout)")

    p_imp = subparsers.add_parser("import", help="Import DB from JSON")
    p_imp.add_argument("input_file", help="JSON file path (or - for stdin)")
    p_imp.add_argument("--replace", action="store_true",
                        help="Delete existing rows before importing")

    # ── Handover ──
    p_ho = subparsers.add_parser("handover", help="Save handover notes for a task")
    p_ho.add_argument("task_id", help="Task ID")
    p_ho.add_argument("notes", help="Handover notes (file refs, arch context)")

    p_resume = subparsers.add_parser(
        "resume", help="Session resume — compact context for next task",
    )
    p_resume.add_argument(
        "--task", default="", help="Override: resume specific task ID",
    )

    # ── Board ──
    subparsers.add_parser("board", help="Generate TASK_BOARD.md")

    # ── Eval ──
    p_eval = subparsers.add_parser("eval", help="Run 3-layer project evaluation")
    p_eval.add_argument("--version", default=None, help="Version tag (e.g. v0.8.0)")
    p_eval.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    p_eval.add_argument("--layer", choices=["artifact", "process", "velocity"], help="Run one layer")
    p_eval.add_argument("--auto-fix", action="store_true", help="Show auto-fixable commands")
    p_eval.add_argument("--yes", action="store_true", help="Execute auto-fix without prompt")
    p_eval.add_argument("--no-store", action="store_true", dest="no_store",
                         help="Run eval without storing to DB (for dashboards)")

    p_el = subparsers.add_parser("eval-last", help="Read last stored eval score (no re-run)")
    p_el.add_argument("--json", action="store_true", dest="json_output", help="JSON output")

    p_eg = subparsers.add_parser("eval-gate", help="P4-VALIDATE gate check across projects")
    p_eg.add_argument("--min-score", type=int, default=70, dest="min_score",
                       help="Minimum composite score to pass (default: 70)")
    p_eg.add_argument("--max-age", type=int, default=7, dest="max_age",
                       help="Maximum eval age in days (default: 7)")
    p_eg.add_argument("--bootstrap-min", type=int, default=85, dest="bootstrap_min",
                       help="Minimum score for bootstrap itself (default: 85)")

    p_er = subparsers.add_parser("eval-report", help="Show evaluation report")
    p_er.add_argument("--id", type=int, default=None, dest="eval_id", help="Evaluation ID")
    p_er.add_argument("--all", action="store_true", dest="show_all", help="List all evaluations")

    p_ec = subparsers.add_parser("eval-compare", help="Compare two evaluations")
    p_ec.add_argument("id1", nargs="?", type=int, default=None, help="First eval ID")
    p_ec.add_argument("id2", nargs="?", type=int, default=None, help="Second eval ID")
    p_ec.add_argument("--last", type=int, default=None, dest="last_n", help="Compare last N evals")

    # ── Drift ──
    p_drift = subparsers.add_parser("drift", help="Run drift detection (coherence checks)")
    p_drift.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    p_drift.add_argument("--quiet", action="store_true", help="One-line summary")

    # ── Upgrade drift ──
    p_ud = subparsers.add_parser(
        "upgrade-drift",
        help="Report upgrade drift for a generated project (.bootstrap_profile + .bootstrap_manifest)",
    )
    p_ud.add_argument(
        "project_path", nargs="?", default="",
        help="Path to generated project (default: current project root)",
    )
    p_ud.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    p_ud.add_argument("--all", action="store_true", dest="show_all",
                      help="Show all files, not just missing ones")

    # ── Upgrade drift settings ──
    p_uds = subparsers.add_parser(
        "upgrade-drift-settings",
        help="Three-way merge .claude/settings.json for v1.2→v1.3 router migration",
    )
    p_uds.add_argument(
        "--project-dir", dest="project_dir", default="",
        help="Path to the project (default: CWD)",
    )
    p_uds.add_argument(
        "--bootstrap-root", dest="bootstrap_root", default="",
        help="Path to the project-bootstrap plugin root (default: plugin install path)",
    )
    mode_group = p_uds.add_mutually_exclusive_group()
    mode_group.add_argument("--apply", action="store_true",
                            help="Apply the merge (refuses if conflicts exist)")
    mode_group.add_argument("--emit-patch", action="store_true", dest="emit_patch",
                            help="Write settings.json.v1.3-proposed without touching settings.json")

    # ── Rollback settings ──
    p_rs = subparsers.add_parser(
        "rollback-settings",
        help="Restore .claude/settings.json from pre-v1.3 backup",
    )
    p_rs.add_argument(
        "--project-dir", dest="project_dir", default="",
        help="Path to the project (default: CWD)",
    )

    # ── lint ──
    p_lint = subparsers.add_parser("lint", help="Structural lint checks")
    p_lint.add_argument("--fix", action="store_true", help="Auto-fix where possible")

    # ── Doctor ──
    p_doctor = subparsers.add_parser("doctor", help="Environment health check")
    p_doctor.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    p_doctor.add_argument("--quiet", action="store_true", help="One-line summary")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    # Detect config — allow init-db to work without existing DB
    try:
        config = detect_config()
    except SystemExit:
        if args.command == "init-db":
            import os
            from pathlib import Path
            db_override = os.environ.get("DB_OVERRIDE")
            if db_override:
                from .config import ProjectConfig
                config = ProjectConfig(db_path=db_override)
            else:
                raise
        else:
            raise

    # Dispatch
    try:
        with open_db(str(config.db_path)) as db:
            # Auto-migrate on every invocation (matches bash behavior)
            if config.db_path.exists() and db.table_exists("tasks"):
                db.migrate()

            _dispatch(args, db, config)

    except DatabaseError as e:
        print(f"❌ Database error: {e}", file=sys.stderr)
        sys.exit(1)


def _dispatch(args, db, config):
    """Route command to handler."""
    cmd = args.command

    # ── Health & init ──
    if cmd == "init-db":
        from .commands.health import cmd_init_db
        cmd_init_db(db)

    elif cmd == "health":
        from .commands.health import cmd_health
        cmd_health(db, config)

    # ── Core task commands (PoC) ──
    elif cmd == "done":
        from .commands.tasks import cmd_done
        cmd_done(db, config, args.task_id, args.skip_break, args.files,
                getattr(args, 'research', False))

    elif cmd == "check":
        from .commands.tasks import cmd_check
        cmd_check(db, config, args.task_id)

    elif cmd == "quick":
        from .commands.tasks import cmd_quick
        cmd_quick(
            db,
            title=args.title,
            phase=args.phase,
            tag=args.tag,
            loopback_origin=args.loopback_origin,
            severity=args.severity,
            gate_critical=args.gate_critical,
            reason=args.reason,
        )

    # ── Simple CRUD commands ──
    elif cmd == "task":
        from .commands.tasks import cmd_task
        cmd_task(db, args.task_id)

    elif cmd == "start":
        from .commands.tasks import cmd_start
        cmd_start(db, args.task_id, config=config)

    elif cmd == "skip":
        from .commands.tasks import cmd_skip
        cmd_skip(db, args.task_id, args.reason)

    elif cmd == "unblock":
        from .commands.tasks import cmd_unblock
        cmd_unblock(db, args.task_id)

    elif cmd == "tag-browser":
        from .commands.tasks import cmd_tag_browser
        cmd_tag_browser(db, args.task_id, args.value)

    elif cmd == "researched":
        from .commands.tasks import cmd_researched
        cmd_researched(db, args.task_id)

    elif cmd == "break-tested":
        from .commands.tasks import cmd_break_tested
        cmd_break_tested(db, args.task_id)

    # ── Inbox pipeline ──
    elif cmd == "inbox":
        from .commands.tasks import cmd_inbox
        cmd_inbox(db)

    elif cmd == "triage":
        from .commands.tasks import cmd_triage
        cmd_triage(
            db, args.task_id, args.phase, args.tier,
            args.skill, args.blocked_by,
            severity=args.severity,
            gate_critical=args.gate_critical,
            reason=args.reason,
        )

    elif cmd == "add-task":
        from .commands.tasks import cmd_add_task
        cmd_add_task(
            db, args.task_id, args.phase, args.title, args.tier,
            args.skill, args.blocked_by, args.sort_order,
        )

    # ── Phase & gate commands ──
    elif cmd == "phase":
        from .commands.phases import cmd_phase
        cmd_phase(db)

    elif cmd == "gate":
        from .commands.phases import cmd_gate
        cmd_gate(db)

    elif cmd == "gate-pass":
        from .commands.phases import cmd_gate_pass
        cmd_gate_pass(db, args.phase, args.gated_by, args.notes)

    elif cmd == "status":
        from .commands.phases import cmd_status
        cmd_status(db)

    elif cmd == "blockers":
        from .commands.phases import cmd_blockers
        cmd_blockers(db)

    elif cmd == "confirm":
        from .commands.phases import cmd_confirm
        cmd_confirm(db, config, args.task_id, args.confirmed_by, args.reasons)

    elif cmd == "confirmations":
        from .commands.phases import cmd_confirmations
        cmd_confirmations(db)

    elif cmd == "master":
        from .commands.phases import cmd_master
        cmd_master(db)

    # ── next command ──
    elif cmd == "next":
        from .commands.next_cmd import cmd_next
        cmd_next(db, config, args.ready_only, args.smart)

    # ── Sessions & decisions ──
    elif cmd == "sessions":
        from .commands.sessions import cmd_sessions
        cmd_sessions(db)

    elif cmd == "log":
        from .commands.sessions import cmd_log
        cmd_log(db, args.session_type, args.summary)

    elif cmd == "decisions":
        from .commands.sessions import cmd_decisions
        cmd_decisions(db)

    # ── Loopback management ──
    elif cmd == "loopbacks":
        from .commands.loopbacks import cmd_loopbacks
        cmd_loopbacks(db, args.origin, args.severity,
                      args.gate_critical, args.show_all)

    elif cmd == "loopback-stats":
        from .commands.loopbacks import cmd_loopback_stats
        cmd_loopback_stats(db, config)

    elif cmd == "loopback-count":
        from .commands.loopbacks import cmd_loopback_count
        cmd_loopback_count(db)

    elif cmd == "loopback-summary":
        from .commands.loopbacks import cmd_loopback_summary
        cmd_loopback_summary(db)

    elif cmd == "loopback-lesson":
        from .commands.loopbacks import cmd_loopback_lesson
        cmd_loopback_lesson(db, config, args.task_id)

    elif cmd == "ack-breaker":
        from .commands.loopbacks import cmd_ack_breaker
        cmd_ack_breaker(db, args.task_id, args.reason)

    # ── Falsification ──
    elif cmd == "assume":
        from .commands.falsification import cmd_assume
        cmd_assume(db, args.task_id, args.assumption, args.verify_cmd)

    elif cmd == "verify-assumption":
        from .commands.falsification import cmd_verify_assumption
        cmd_verify_assumption(db, args.task_id, args.assumption_id)

    elif cmd == "verify-all":
        from .commands.falsification import cmd_verify_all
        cmd_verify_all(db, args.task_id)

    elif cmd == "assumptions":
        from .commands.falsification import cmd_assumptions
        cmd_assumptions(db, args.task_id)

    # ── Knowledge ──
    elif cmd == "lessons":
        from .commands.knowledge import cmd_lessons
        cmd_lessons(config)

    elif cmd == "log-lesson":
        from .commands.knowledge import cmd_log_lesson
        cmd_log_lesson(
            config, args.what_wrong, args.pattern, args.prevention,
            bp_category=args.bp_category, bp_file=args.bp_file,
        )

    elif cmd == "promote":
        from .commands.knowledge import cmd_promote
        cmd_promote(config, args.pattern, args.rule, args.method,
                    source_file=args.source_file,
                    source_project=args.source_project)

    elif cmd == "escalate":
        from .commands.knowledge import cmd_escalate
        cmd_escalate(
            config, args.description, args.category,
            args.affected_file, args.priority,
        )

    elif cmd == "harvest":
        from .commands.knowledge import cmd_harvest
        cmd_harvest(config, *args.paths, mark_dupes=args.mark_dupes)

    # ── Delegation ──
    elif cmd == "delegation":
        from .commands.delegation import cmd_delegation
        cmd_delegation(db, args.phase)

    elif cmd == "delegation-md":
        from .commands.delegation import cmd_delegation_md
        cmd_delegation_md(db, config, active_only=args.active_only)

    elif cmd == "sync-check":
        from .commands.delegation import cmd_sync_check
        cmd_sync_check(db, config)

    elif cmd == "tier-up":
        from .commands.delegation import cmd_tier_up
        cmd_tier_up(db, args.task_id, args.new_tier, args.reason)

    # ── Snapshots ──
    elif cmd == "snapshot":
        from .commands.snapshots import cmd_snapshot
        cmd_snapshot(db, args.label)

    elif cmd == "snapshot-list":
        from .commands.snapshots import cmd_snapshot_list
        cmd_snapshot_list(db)

    elif cmd == "snapshot-show":
        from .commands.snapshots import cmd_snapshot_show
        cmd_snapshot_show(db, args.snap_id)

    elif cmd == "snapshot-diff":
        from .commands.snapshots import cmd_snapshot_diff
        cmd_snapshot_diff(db, args.id1, args.id2)

    # ── Session git ──
    elif cmd == "tag-session":
        from .commands.sessions import cmd_tag_session
        cmd_tag_session(config)

    elif cmd == "session-tags":
        from .commands.sessions import cmd_session_tags
        cmd_session_tags(config)

    elif cmd == "session-file":
        from .commands.sessions import cmd_session_file
        cmd_session_file(config, args.session_num, args.file_path)

    # ── Health extras ──
    elif cmd == "backup":
        from .commands.health import cmd_backup
        cmd_backup(db, config)

    elif cmd == "restore":
        from .commands.health import cmd_restore
        cmd_restore(db, config, args.restore_file)

    elif cmd == "verify":
        from .commands.health import cmd_verify
        cmd_verify(db)

    elif cmd == "export":
        from .commands.health import cmd_export
        cmd_export(db, config, tables=args.table, pretty=args.pretty,
                   output_file=args.output_file)

    elif cmd == "import":
        from .commands.health import cmd_import
        cmd_import(db, config, input_file=args.input_file,
                   replace=args.replace)

    # ── Handover ──
    elif cmd == "handover":
        from .commands.handover import cmd_handover
        cmd_handover(db, args.task_id, args.notes)

    elif cmd == "resume":
        from .commands.handover import cmd_resume
        cmd_resume(db, config, task_override=args.task)

    elif cmd == "board":
        from .commands.health import cmd_board
        cmd_board(config)

    # ── Eval ──
    elif cmd == "eval":
        from .commands.eval import cmd_eval
        cmd_eval(
            db, config,
            version=args.version,
            json_output=args.json_output,
            layer=args.layer,
            auto_fix=args.auto_fix,
            auto_fix_yes=args.yes,
            no_store=args.no_store,
        )

    elif cmd == "eval-report":
        from .commands.eval import cmd_eval_report
        cmd_eval_report(db, config, eval_id=args.eval_id, show_all=args.show_all)

    elif cmd == "eval-last":
        from .commands.eval import cmd_eval_last
        cmd_eval_last(db, config, json_output=args.json_output)

    elif cmd == "eval-gate":
        from .commands.eval import cmd_eval_gate
        cmd_eval_gate(
            db, config,
            min_score=args.min_score,
            max_age=args.max_age,
            bootstrap_min=args.bootstrap_min,
        )

    elif cmd == "eval-compare":
        from .commands.eval import cmd_eval_compare
        cmd_eval_compare(db, config, id1=args.id1, id2=args.id2, last_n=args.last_n)

    # ── Drift ──
    elif cmd == "drift":
        from .commands.drift import cmd_drift
        cmd_drift(db, config, json_output=args.json_output, quiet=args.quiet)

    elif cmd == "upgrade-drift":
        from .commands.upgrade_drift import cmd_upgrade_drift
        cmd_upgrade_drift(
            db, config,
            project_path=args.project_path,
            json_output=args.json_output,
            show_all=args.show_all,
        )

    elif cmd == "upgrade-drift-settings":
        from .commands.upgrade_drift_settings import cmd_upgrade_drift_settings
        cmd_upgrade_drift_settings(args)

    elif cmd == "rollback-settings":
        from .commands.upgrade_drift_settings import cmd_rollback_settings
        cmd_rollback_settings(args)

    # ── Lint ──
    elif cmd == "lint":
        from .commands.lint import cmd_lint
        cmd_lint(config, fix=args.fix)

    # ── Doctor ──
    elif cmd == "doctor":
        from .commands.doctor import cmd_doctor
        cmd_doctor(config, json_output=args.json_output, quiet=args.quiet)
