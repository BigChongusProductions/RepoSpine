"""
Snapshot commands: snapshot, snapshot-list, snapshot-show, snapshot-diff.

All self-contained within the db_snapshots table. No external file manipulation.
"""
import json
import subprocess
import sys

from ..db import Database
from .. import output


def _git_sha() -> str:
    """Get current git short SHA, or 'no-git' if not in a repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else "no-git"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "no-git"


# ── snapshot command ────────────────────────────────────────────────

def cmd_snapshot(db: Database, label: str = ""):
    """Capture current DB state as JSON into db_snapshots table.

    Matches db_queries_legacy.template.sh lines 1963-2001.
    """
    from datetime import datetime

    if not label:
        label = datetime.now().strftime("%Y-%m-%d-%H%M")

    git_sha = _git_sha()

    # Build task summary JSON
    task_rows = db.fetch_all(
        "SELECT id, phase, title, status, assignee FROM tasks"
    )
    task_summary = json.dumps([
        {
            "id": r["id"],
            "phase": r["phase"],
            "title": r["title"],
            "status": r["status"],
            "assignee": r["assignee"],
        }
        for r in task_rows
    ])

    # Build phase gates JSON
    gate_rows = db.fetch_all(
        "SELECT phase, gated_on FROM phase_gates"
    )
    phase_gates = json.dumps([
        {"phase": r["phase"], "gated_on": r["gated_on"]}
        for r in gate_rows
    ])

    # Build stats JSON
    total = db.fetch_scalar("SELECT COUNT(*) FROM tasks")
    done = db.fetch_scalar("SELECT COUNT(*) FROM tasks WHERE status='DONE'")
    todo = db.fetch_scalar("SELECT COUNT(*) FROM tasks WHERE status='TODO'")
    blocked = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks "
        "WHERE blocked_by IS NOT NULL AND blocked_by != '' AND status != 'DONE'"
    )

    by_phase_rows = db.fetch_all(
        "SELECT phase, COUNT(*) AS total, "
        "SUM(CASE WHEN status='DONE' THEN 1 ELSE 0 END) AS done "
        "FROM tasks GROUP BY phase"
    )
    by_phase = [
        {"phase": r["phase"], "total": r["total"], "done": r["done"]}
        for r in by_phase_rows
    ]

    stats = json.dumps({
        "total": total,
        "done": done,
        "todo": todo,
        "blocked": blocked,
        "by_phase": by_phase,
    })

    db.execute(
        "INSERT INTO db_snapshots (label, git_sha, task_summary, phase_gates, stats) "
        "VALUES (?, ?, ?, ?, ?)",
        (label, git_sha, task_summary, phase_gates, stats),
    )
    db.commit()

    snap_id = db.fetch_scalar(
        "SELECT id FROM db_snapshots ORDER BY id DESC LIMIT 1"
    )
    print(f'✅ Snapshot #{snap_id} saved: "{label}" ({git_sha})')


# ── snapshot-list command ───────────────────────────────────────────

def cmd_snapshot_list(db: Database):
    """List all snapshots.

    Matches db_queries_legacy.template.sh lines 2003-2010.
    """
    output.print_section("DB Snapshots")

    rows = db.fetch_all(
        "SELECT id, created_at, label, git_sha, stats "
        "FROM db_snapshots ORDER BY id DESC"
    )

    if not rows:
        print("  No snapshots found.")
        print("")
        return

    print(f"  {'id':>4} {'created_at':<20} {'label':<25} {'sha':<10} progress")
    for r in rows:
        stats = json.loads(r["stats"]) if r["stats"] else {}
        done_ct = stats.get("done", "?")
        total_ct = stats.get("total", "?")
        print(
            f"  {r['id']:>4} {r['created_at'] or '':<20} "
            f"{r['label'] or '':<25} {r['git_sha'] or '':<10} "
            f"{done_ct}/{total_ct}"
        )
    print("")


# ── snapshot-show command ───────────────────────────────────────────

def cmd_snapshot_show(db: Database, snap_id: int):
    """Show a specific snapshot in detail.

    Matches db_queries_legacy.template.sh lines 2012-2048.
    """
    row = db.fetch_one(
        "SELECT label, created_at, git_sha, task_summary, phase_gates, stats "
        "FROM db_snapshots WHERE id=?",
        (snap_id,),
    )
    if row is None:
        print(f"❌ Snapshot #{snap_id} not found")
        sys.exit(1)

    print("")
    print(f"── Snapshot #{snap_id}: {row['label']} ({row['created_at']}, {row['git_sha']}) ──")
    print("")

    # Stats
    stats = json.loads(row["stats"]) if row["stats"] else {}
    print("Stats:")
    print(f"  {'total':>8} {'done':>8} {'todo':>8} {'blocked':>8}")
    print(
        f"  {stats.get('total', '?'):>8} {stats.get('done', '?'):>8} "
        f"{stats.get('todo', '?'):>8} {stats.get('blocked', '?'):>8}"
    )
    print("")

    # By phase
    by_phase = stats.get("by_phase", [])
    if by_phase:
        print("By phase:")
        print(f"  {'phase':<20} progress")
        for p in by_phase:
            print(f"  {p['phase']:<20} {p['done']}/{p['total']}")
        print("")

    # Tasks
    tasks = json.loads(row["task_summary"]) if row["task_summary"] else []
    if tasks:
        print("Tasks:")
        print(f"  {'id':<12} {'status':<15} {'phase':<15} title")
        tasks.sort(key=lambda t: (t.get("phase", ""), t.get("id", "")))
        for t in tasks:
            title = t.get("title", "")[:50]
            print(
                f"  {t.get('id',''):<12} {t.get('status',''):<15} "
                f"{t.get('phase',''):<15} {title}"
            )
    print("")


# ── snapshot-diff command ───────────────────────────────────────────

def cmd_snapshot_diff(db: Database, id1: int, id2: int):
    """Diff two snapshots — show task status changes and progress delta.

    Matches db_queries_legacy.template.sh lines 2051-2101.
    """
    row1 = db.fetch_one(
        "SELECT label, task_summary, stats FROM db_snapshots WHERE id=?",
        (id1,),
    )
    row2 = db.fetch_one(
        "SELECT label, task_summary, stats FROM db_snapshots WHERE id=?",
        (id2,),
    )

    if row1 is None or row2 is None:
        print("❌ One or both snapshot IDs not found")
        sys.exit(1)

    print("")
    print(f"── Snapshot Diff: #{id1} ({row1['label']}) → #{id2} ({row2['label']}) ──")
    print("")

    # Parse task summaries
    tasks1 = {t["id"]: t for t in json.loads(row1["task_summary"] or "[]")}
    tasks2 = {t["id"]: t for t in json.loads(row2["task_summary"] or "[]")}

    all_ids = sorted(set(list(tasks1.keys()) + list(tasks2.keys())))

    changes = []
    for tid in all_ids:
        t1 = tasks1.get(tid)
        t2 = tasks2.get(tid)
        if t1 is None:
            changes.append(f"+ {tid:<12} {'NEW':<15} {t2.get('title', '')}")
        elif t2 is None:
            changes.append(f"- {tid:<12} {'REMOVED':<15} {t1.get('title', '')}")
        elif t1.get("status") != t2.get("status"):
            changes.append(
                f"~ {tid:<12} {t1['status']:<7} → {t2['status']:<7} "
                f"{t2.get('title', '')}"
            )

    if not changes:
        print("No task status changes between snapshots.")
    else:
        for c in changes:
            print(f"  {c}")

    # Stats comparison
    stats1 = json.loads(row1["stats"] or "{}")
    stats2 = json.loads(row2["stats"] or "{}")
    p1 = f"{stats1.get('done', '?')}/{stats1.get('total', '?')}"
    p2 = f"{stats2.get('done', '?')}/{stats2.get('total', '?')}"
    print("")
    print(f"Progress: #{id1}={p1} → #{id2}={p2}")
    print("")
