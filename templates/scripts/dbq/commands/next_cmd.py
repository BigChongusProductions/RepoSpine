"""
next command — task queue with circuit breaker, loopbacks, forward ready,
blocked tasks, and stale blockers.

OUTPUT CONTRACT:
    post-compact-recovery.template.sh does `head -5` on the output.
    test_bootstrap_suite.sh does `grep CIRCUIT`.
    The first 5 lines must contain the section header + circuit breaker status.

Matches db_queries_legacy.template.sh lines 727-930.
"""
import sys
from typing import Optional

from ..db import Database
from ..config import ProjectConfig
from .. import output


def cmd_next(db: Database, config: ProjectConfig,
             ready_only: bool = False, smart: bool = False):
    """Show task queue: what to work on next."""

    print("")
    print(output.section_header("Task Queue"))

    # ── Circuit Breaker ──
    s1_gc_count = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks "
        "WHERE track='loopback' AND severity=1 AND gate_critical=1 "
        "AND status NOT IN ('DONE','SKIP')"
    )

    if s1_gc_count > 0:
        print("")
        print("  ⚠️  CIRCUIT BREAKER — S1 gate-critical loopback(s) active:")
        rows = db.fetch_all(
            "SELECT t.id, t.title, "
            "COALESCE(t.origin_phase,'?') AS origin, "
            "COALESCE(t.discovered_in,'?') AS disc, "
            "CASE WHEN la.loopback_id IS NOT NULL THEN 1 ELSE 0 END AS acked "
            "FROM tasks t "
            "LEFT JOIN loopback_acks la ON t.id = la.loopback_id "
            "WHERE t.track='loopback' AND t.severity=1 AND t.gate_critical=1 "
            "AND t.status NOT IN ('DONE','SKIP') "
            "ORDER BY t.sort_order"
        )
        for r in rows:
            ack_tag = "  (acknowledged)" if r["acked"] else ""
            print(f"    {r['id']}  {r['title']}  "
                  f"[origin: {r['origin']}, found: {r['disc']}]{ack_tag}")

        # Blast radius
        blast_rows = db.fetch_all(
            "SELECT DISTINCT t.origin_phase "
            "FROM tasks t "
            "WHERE t.track='loopback' AND t.severity=1 AND t.gate_critical=1 "
            "AND t.status NOT IN ('DONE','SKIP')"
        )
        for br in blast_rows:
            origin = br["origin_phase"] or "?"
            blast = db.fetch_scalar(
                "SELECT COUNT(DISTINCT phase) FROM tasks "
                "WHERE phase > ? AND COALESCE(track,'forward')='forward' "
                "AND status NOT IN ('DONE','SKIP')",
                (origin,),
            )
            if blast > 0:
                print(f"    Blast radius: {origin} → {blast} phase(s) downstream")

        print("")
        print("  Resolve or acknowledge: bash db_queries.sh ack-breaker <LB-ID> \"reason\"")

    # ── S2 Loopbacks (high priority) ──
    s2_count = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks t "
        "LEFT JOIN tasks b ON t.blocked_by = b.id "
        "WHERE t.track='loopback' AND t.severity=2 "
        "AND t.status NOT IN ('DONE','SKIP') "
        "AND (t.blocked_by IS NULL OR t.blocked_by = '' "
        "     OR b.status IN ('DONE','SKIP') OR b.id IS NULL)"
    )

    if s2_count > 0:
        print("")
        print(f"  🟡 S2 Loopbacks ({s2_count} ready):")
        s2_rows = db.fetch_all(
            "SELECT t.id, t.title, "
            "COALESCE(t.origin_phase,'?') AS origin, "
            "t.gate_critical "
            "FROM tasks t "
            "LEFT JOIN tasks b ON t.blocked_by = b.id "
            "WHERE t.track='loopback' AND t.severity=2 "
            "AND t.status NOT IN ('DONE','SKIP') "
            "AND (t.blocked_by IS NULL OR t.blocked_by = '' "
            "     OR b.status IN ('DONE','SKIP') OR b.id IS NULL) "
            "ORDER BY t.sort_order"
        )
        for r in s2_rows:
            gc_tag = "  gate-critical" if r["gate_critical"] else ""
            print(f"    {r['id']}  {r['title']}  "
                  f"[origin: {r['origin']}]{gc_tag}")

    # ── FORWARD Ready Tasks ──
    if smart and config.phases:
        _show_forward_smart(db, config)
    else:
        _show_forward_plain(db)

    # ── BLOCKED section (skip if --ready-only) ──
    if ready_only:
        blocked_count = db.fetch_scalar(
            "SELECT COUNT(*) FROM tasks t "
            "JOIN tasks b ON t.blocked_by = b.id "
            "WHERE t.status='TODO' AND t.assignee='CLAUDE' "
            "AND t.queue != 'INBOX' "
            "AND b.status NOT IN ('DONE','SKIP')"
        )
        if blocked_count > 0:
            print(f"\n  ({blocked_count} blocked task(s) hidden — omit --ready-only to show)")
    else:
        _show_blocked(db)

    # ── S3/S4 Loopbacks (lower priority) ──
    s34_count = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks t "
        "LEFT JOIN tasks b ON t.blocked_by = b.id "
        "WHERE t.track='loopback' AND t.severity IN (3,4) "
        "AND t.status NOT IN ('DONE','SKIP') "
        "AND (t.blocked_by IS NULL OR t.blocked_by = '' "
        "     OR b.status IN ('DONE','SKIP') OR b.id IS NULL)"
    )

    if s34_count > 0:
        print(f"\n  S3/S4 Loopbacks ({s34_count} ready):")
        s34_rows = db.fetch_all(
            "SELECT t.id, t.title, t.severity, "
            "COALESCE(t.origin_phase,'?') AS origin "
            "FROM tasks t "
            "LEFT JOIN tasks b ON t.blocked_by = b.id "
            "WHERE t.track='loopback' AND t.severity IN (3,4) "
            "AND t.status NOT IN ('DONE','SKIP') "
            "AND (t.blocked_by IS NULL OR t.blocked_by = '' "
            "     OR b.status IN ('DONE','SKIP') OR b.id IS NULL) "
            "ORDER BY t.severity ASC, t.sort_order ASC"
        )
        for r in s34_rows:
            icon = output.severity_icon(r["severity"])
            print(f"    {icon} {r['id']}  {r['title']}  "
                  f"[origin: {r['origin']}]")

    # ── Stale blockers ──
    if not ready_only:
        _show_stale_blockers(db)

    print("")


def _show_forward_plain(db: Database):
    """Show forward-track ready tasks, ordered by phase/sort_order."""
    rows = db.fetch_all(
        "SELECT t.id, t.priority, t.title, t.phase "
        "FROM tasks t "
        "LEFT JOIN tasks b ON t.blocked_by = b.id "
        "WHERE t.status='TODO' AND t.assignee='CLAUDE' "
        "AND t.queue != 'INBOX' "
        "AND COALESCE(t.track,'forward') = 'forward' "
        "AND (t.blocked_by IS NULL OR t.blocked_by = '' "
        "     OR b.status IN ('DONE','SKIP') OR b.id IS NULL) "
        "ORDER BY t.phase, t.sort_order "
        "LIMIT 8"
    )

    print(f"\n  FORWARD ({len(rows)} ready):")
    if not rows:
        print("    (none)")
        return

    for r in rows:
        print(f"    {r['id']}  {r['priority']}  {r['title']}  [{r['phase']}]")


def _show_forward_smart(db: Database, config: ProjectConfig):
    """Show forward-track ready tasks with impact scoring."""
    phase_case = config.phase_case_sql()
    if not phase_case:
        return _show_forward_plain(db)

    # Use dynamic max ordinal from config (not hardcoded 6).
    # Unknown phases get max_ord (= score 0) instead of max_ord+1 (= negative score).
    max_ord = max(len(config.phases) - 1, 0)

    rows = db.fetch_all(
        f"SELECT t.id, t.priority, t.title, t.phase, "
        f"COALESCE(ub.unblocks, 0) AS unblocks, "
        f"( "
        f"  ({max_ord} - CASE t.phase {phase_case} ELSE {max_ord} END) * 100 "
        f"  + COALESCE(ub.unblocks, 0) * 10 "
        f"  + CASE t.priority "
        f"    WHEN 'P0' THEN 50 WHEN 'P1' THEN 40 WHEN 'P2' THEN 30 "
        f"    WHEN 'P3' THEN 25 WHEN 'QK' THEN 20 WHEN 'LB' THEN 15 "
        f"    ELSE 10 END "
        f") AS score "
        f"FROM tasks t "
        f"LEFT JOIN ( "
        f"    SELECT blocked_by, COUNT(*) AS unblocks "
        f"    FROM tasks WHERE status='TODO' "
        f"    AND blocked_by IS NOT NULL AND length(blocked_by) > 0 "
        f"    GROUP BY blocked_by "
        f") ub ON ub.blocked_by = t.id "
        f"LEFT JOIN tasks b ON t.blocked_by = b.id "
        f"WHERE t.status='TODO' AND t.assignee='CLAUDE' "
        f"AND t.queue <> 'INBOX' "
        f"AND COALESCE(t.track,'forward') = 'forward' "
        f"AND (t.blocked_by IS NULL OR length(t.blocked_by) = 0 "
        f"     OR b.status IN ('DONE','SKIP') OR b.id IS NULL) "
        f"ORDER BY score DESC "
        f"LIMIT 8"
    )

    print(f"\n  FORWARD ({len(rows)} ready, smart-scored):")
    if not rows:
        print("    (none)")
        return

    for r in rows:
        unblocks_tag = f"  ↗{r['unblocks']}" if r["unblocks"] > 0 else ""
        print(f"    {r['id']}  {r['priority']}  {r['title']}  "
              f"[{r['phase']}]  score:{r['score']}{unblocks_tag}")


def _show_blocked(db: Database):
    """Show blocked tasks (supports multi-ID blocked_by fields)."""
    # Fetch all blocked tasks (those with a non-empty blocked_by)
    candidates = db.fetch_all(
        "SELECT t.id, t.title, t.blocked_by, "
        "COALESCE(t.track,'forward') AS track, t.phase, t.sort_order "
        "FROM tasks t "
        "WHERE t.status='TODO' AND t.assignee='CLAUDE' "
        "AND t.queue != 'INBOX' "
        "AND t.blocked_by IS NOT NULL AND t.blocked_by != '' "
        "ORDER BY COALESCE(t.track,'forward') DESC, t.phase, t.sort_order"
    )

    if not candidates:
        return

    # Resolve each blocker ID individually
    blocked_rows = []
    for r in candidates:
        blocker_ids = r["blocked_by"].split()
        active_blockers = []
        for bid in blocker_ids:
            blocker = db.fetch_one(
                "SELECT id, assignee, status FROM tasks WHERE id = ?", (bid,)
            )
            if blocker and blocker["status"] not in ("DONE", "SKIP"):
                active_blockers.append(blocker)
        if active_blockers:
            blocked_rows.append((r, active_blockers))

    if not blocked_rows:
        return

    print(f"\n  BLOCKED ({len(blocked_rows)}):")
    for r, blockers in blocked_rows:
        lb_tag = " (LB)" if r["track"] == "loopback" else ""
        blocker_strs = [f"{b['id']} ({b['assignee']}, {b['status']})" for b in blockers]
        print(f"    {r['id']}{lb_tag}  {r['title']}  "
              f"← {', '.join(blocker_strs)}")


def _show_stale_blockers(db: Database):
    """Show tasks blocked by nonexistent task IDs (supports multi-ID fields)."""
    rows = db.fetch_all(
        "SELECT t.id, t.title, t.blocked_by "
        "FROM tasks t "
        "WHERE t.status='TODO' AND t.blocked_by IS NOT NULL "
        "AND t.blocked_by != '' "
        "ORDER BY t.phase, t.sort_order"
    )

    stale_rows = []
    for r in rows:
        blocker_ids = r["blocked_by"].split()
        missing = []
        for bid in blocker_ids:
            exists = db.fetch_scalar(
                "SELECT COUNT(*) FROM tasks WHERE id = ?", (bid,)
            )
            if exists == 0:
                missing.append(bid)
        if missing:
            stale_rows.append((r, missing))

    if stale_rows:
        print(f"\n  ⚠️  STALE BLOCKERS ({len(stale_rows)}):")
        for r, missing in stale_rows:
            print(f"    {r['id']}  {r['title']}  ← {' '.join(missing)} (NOT FOUND)")
        print("    Fix: bash db_queries.sh unblock <task-id>")
