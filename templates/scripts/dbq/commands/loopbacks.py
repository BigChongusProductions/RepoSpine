"""
Loopback management commands: loopbacks, loopback-stats, loopback-lesson, ack-breaker.
"""
import sys
from datetime import datetime

from ..db import Database
from ..config import ProjectConfig
from .. import output


def _format_date() -> str:
    now = datetime.now()
    return now.strftime("%b ") + str(now.day)


def _iso_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# ── loopbacks command ────────────────────────────────────────────────

def cmd_loopbacks(
    db: Database,
    origin: str = "",
    severity: int = 0,
    gate_critical_only: bool = False,
    show_all: bool = False,
):
    """List loopback tasks with optional filters.

    Matches db_queries_legacy.template.sh lines 2409-2465.
    """
    output.print_section("Loopback Tasks")

    # Summary counts
    lb_open = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks WHERE track='loopback' "
        "AND status NOT IN ('DONE','SKIP')"
    )
    lb_done = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks WHERE track='loopback' AND status='DONE'"
    )
    lb_skip = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks WHERE track='loopback' AND status='SKIP'"
    )
    print(f"  Open: {lb_open} | Done: {lb_done} | Skipped: {lb_skip}")
    print("")

    # Severity breakdown
    s1 = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks WHERE track='loopback' "
        "AND status NOT IN ('DONE','SKIP') AND severity=1"
    )
    s2 = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks WHERE track='loopback' "
        "AND status NOT IN ('DONE','SKIP') AND severity=2"
    )
    s3 = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks WHERE track='loopback' "
        "AND status NOT IN ('DONE','SKIP') AND severity=3"
    )
    s4 = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks WHERE track='loopback' "
        "AND status NOT IN ('DONE','SKIP') AND severity=4"
    )
    print(f"  Severity: S1:{s1} S2:{s2} S3:{s3} S4:{s4}")
    print("")

    # Build filter
    conditions = ["track='loopback'"]
    params = []

    if not show_all:
        conditions.append("status NOT IN ('DONE','SKIP')")

    if origin:
        conditions.append("origin_phase=?")
        params.append(origin)

    if severity > 0:
        conditions.append("severity=?")
        params.append(severity)

    if gate_critical_only:
        conditions.append("gate_critical=1")

    where = " AND ".join(conditions)
    rows = db.fetch_all(
        f"SELECT id, title, severity, "
        f"COALESCE(origin_phase,'?') AS origin, "
        f"COALESCE(discovered_in,'?') AS disc, "
        f"gate_critical, status "
        f"FROM tasks WHERE {where} "
        f"ORDER BY severity ASC, sort_order ASC",
        tuple(params),
    )

    if not rows:
        print("  (none matching filters)")
    else:
        for r in rows:
            sev_label = {1: "🔴 S1", 2: "🟡 S2", 3: "🟢 S3", 4: "⚪ S4"}.get(
                r["severity"], "   ??"
            )
            gc_tag = " | GATE-CRITICAL" if r["gate_critical"] else ""
            status_tag = f" | {r['status']}" if r["status"] in ("DONE", "SKIP") else ""
            print(
                f"  {sev_label} | {r['id']} | {r['title']} | "
                f"origin: {r['origin']} | found: {r['disc']}{gc_tag}{status_tag}"
            )
    print("")


# ── loopback-stats command ───────────────────────────────────────────

def cmd_loopback_stats(db: Database, config: ProjectConfig):
    """Loopback analytics dashboard.

    Matches db_queries_legacy.template.sh lines 2841-2942.
    """
    print("")
    print("══ LOOPBACK ANALYTICS ══════════════════════════════════════════")

    total = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks WHERE track='loopback'"
    )
    if total == 0:
        print("\n  No loopback tasks.")
        print("\n══════════════════════════════════════════════════════════════════")
        print("")
        return

    lb_open = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks WHERE track='loopback' "
        "AND status NOT IN ('DONE','SKIP')"
    )
    lb_done = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks WHERE track='loopback' AND status='DONE'"
    )
    lb_skip = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks WHERE track='loopback' AND status='SKIP'"
    )
    print(f"\n  Total: {total} | Open: {lb_open} | Done: {lb_done} | Skipped: {lb_skip}")

    # By origin phase
    print("\n  By origin phase:")
    origin_rows = db.fetch_all(
        "SELECT COALESCE(origin_phase,'?') AS origin, COUNT(*) AS cnt, "
        "SUM(CASE WHEN severity=1 THEN 1 ELSE 0 END) AS s1, "
        "SUM(CASE WHEN severity=2 THEN 1 ELSE 0 END) AS s2, "
        "SUM(CASE WHEN severity=3 THEN 1 ELSE 0 END) AS s3, "
        "SUM(CASE WHEN severity=4 THEN 1 ELSE 0 END) AS s4 "
        "FROM tasks WHERE track='loopback' "
        "GROUP BY origin_phase ORDER BY cnt DESC"
    )
    for r in origin_rows:
        print(f"    {r['origin']}: {r['cnt']} "
              f"(S1:{r['s1']} S2:{r['s2']} S3:{r['s3']} S4:{r['s4']})")

    # Severity distribution
    print("\n  Severity distribution:")
    sev_rows = db.fetch_all(
        "SELECT severity, COUNT(*) AS cnt "
        "FROM tasks WHERE track='loopback' AND severity IS NOT NULL "
        "GROUP BY severity ORDER BY severity"
    )
    for r in sev_rows:
        pct = round(r["cnt"] * 100.0 / total)
        print(f"    S{r['severity']}: {r['cnt']} ({pct}%)")

    # Discovery lag
    lag_rows = db.fetch_all(
        "SELECT origin_phase, discovered_in "
        "FROM tasks WHERE track='loopback' "
        "AND origin_phase IS NOT NULL AND discovered_in IS NOT NULL"
    )
    if lag_rows and config.phases:
        lags = []
        for r in lag_rows:
            o_ord = config.phase_ordinal(r["origin_phase"])
            d_ord = config.phase_ordinal(r["discovered_in"])
            if o_ord < 99 and d_ord < 99:
                lags.append(d_ord - o_ord)
        if lags:
            avg_lag = sum(lags) / len(lags)
            print(f"\n  Discovery lag:")
            print(f"    Avg {avg_lag:.1f} phases between origin and discovery "
                  f"({len(lags)} samples)")

    # Top reasons
    reason_rows = db.fetch_all(
        "SELECT COALESCE(loopback_reason,'unspecified') AS reason, "
        "COUNT(*) AS cnt "
        "FROM tasks WHERE track='loopback' "
        "GROUP BY loopback_reason ORDER BY cnt DESC LIMIT 5"
    )
    if reason_rows:
        print("\n  Top reasons:")
        for r in reason_rows:
            print(f"    {r['reason']}: {r['cnt']}")

    # Gate-critical status
    gc_total = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks WHERE track='loopback' AND gate_critical=1"
    )
    gc_done = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks WHERE track='loopback' AND gate_critical=1 "
        "AND status IN ('DONE','SKIP')"
    )
    gc_open = gc_total - gc_done
    print(f"\n  Gate-critical status:")
    print(f"    Total: {gc_total} | Resolved: {gc_done} | Open: {gc_open}")

    # Iteration hotspot
    hotspot = db.fetch_one(
        "SELECT origin_phase, COUNT(*) AS cnt "
        "FROM tasks WHERE track='loopback' "
        "GROUP BY origin_phase HAVING cnt >= 3 "
        "ORDER BY cnt DESC LIMIT 1"
    )
    if hotspot:
        print(f"\n  ⚠️  Iteration hotspot: {hotspot['origin_phase']} "
              f"({hotspot['cnt']} loopbacks)")

    print("\n══════════════════════════════════════════════════════════════════")
    print("")


# ── loopback-lesson command ──────────────────────────────────────────

def cmd_loopback_lesson(db: Database, config: ProjectConfig, task_id: str):
    """Log a lesson from a loopback task into LESSONS file.

    Matches db_queries_legacy.template.sh lines 2944-2985.
    """
    row = db.fetch_one(
        "SELECT title, COALESCE(origin_phase,'?') AS origin, "
        "COALESCE(discovered_in,'?') AS disc, "
        "COALESCE(severity,'?') AS sev, "
        "COALESCE(loopback_reason,'unspecified') AS reason, "
        "COALESCE(completed_on,'?') AS completed "
        "FROM tasks WHERE id=? AND track='loopback'",
        (task_id,),
    )
    if row is None:
        print(f"❌ Task '{task_id}' not found or not a loopback task")
        sys.exit(1)

    today = _format_date()
    lesson_entry = (
        f"| {today} | Loopback {task_id}: {row['title']} — "
        f"discovered in {row['disc']}, origin {row['origin']} "
        f"(S{row['sev']}, reason: {row['reason']}). "
        f"Gate should have caught this at {row['origin']} phase. |"
    )

    lessons_file = config.lessons_file
    if not lessons_file:
        print(f"⚠️  No LESSONS file found in project directory")
        print(f"   Lesson entry: {lesson_entry}")
        return

    from pathlib import Path
    lf = Path(lessons_file)
    if not lf.exists():
        print(f"⚠️  LESSONS file not found: {lessons_file}")
        print(f"   Lesson entry: {lesson_entry}")
        return

    content = lf.read_text()
    marker = "## Universal Patterns"
    if marker in content:
        content = content.replace(marker, f"{lesson_entry}\n{marker}")
        lf.write_text(content)
        print(f"✅ Lesson inserted into {lf.name} (before Universal Patterns)")
    else:
        with open(str(lf), "a") as f:
            f.write(f"\n{lesson_entry}\n")
        print(f"✅ Lesson appended to {lf.name}")

    print(f"   {lesson_entry}")


# ── ack-breaker command ──────────────────────────────────────────────

def cmd_ack_breaker(db: Database, task_id: str, reason: str):
    """Acknowledge a circuit breaker (S1 gate-critical loopback).

    Matches db_queries_legacy.template.sh lines 2796-2818.
    """
    track = db.fetch_one(
        "SELECT track FROM tasks WHERE id=?", (task_id,),
    )
    if track is None:
        print(f"❌ Task '{task_id}' not found")
        sys.exit(1)
    if track != "loopback":
        print(f"❌ Task '{task_id}' is not a loopback task (track: {track})")
        sys.exit(1)

    today = _iso_date()
    db.execute(
        "INSERT OR REPLACE INTO loopback_acks "
        "(loopback_id, acked_on, acked_by, reason) "
        "VALUES (?, ?, 'MASTER', ?)",
        (task_id, today, reason),
    )
    db.commit()

    print(f"✅ Circuit breaker acknowledged: {task_id}")
    print(f"   Reason: {reason}")
    print("   Forward tasks will no longer show CONFIRM for this loopback.")


# ── loopback-count command ──────────────────────────────────────────

def cmd_loopback_count(db: Database) -> None:
    """Print count of open loopback tasks. Used by hooks for routing decisions."""
    count = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks WHERE track='loopback' "
        "AND status NOT IN ('DONE','SKIP')"
    )
    print(count)


# ── loopback-summary command ────────────────────────────────────────

def cmd_loopback_summary(db: Database) -> None:
    """Print one-line severity summary of open loopbacks. Used by hooks for routing hints."""
    parts = []
    for sev in (1, 2, 3, 4):
        count = db.fetch_scalar(
            "SELECT COUNT(*) FROM tasks WHERE track='loopback' "
            "AND status NOT IN ('DONE','SKIP') AND severity=?",
            (sev,),
        )
        if count > 0:
            parts.append(f"S{sev}:{count}")
    if parts:
        print(" ".join(parts))
    else:
        print("none")
