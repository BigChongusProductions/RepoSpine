"""
Falsification commands: assume, verify-assumption, verify-all, assumptions.

These implement the assumption tracking and verification system.
"""
import subprocess
import sys
from datetime import datetime

from ..db import Database
from .. import output


def _iso_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# ── assume command ───────────────────────────────────────────────────

def cmd_assume(db: Database, task_id: str, assumption: str,
               verify_cmd: str = ""):
    """Record an assumption for a task.

    Matches db_queries_legacy.template.sh lines 2147-2177.
    """
    task = db.fetch_one(
        "SELECT id FROM tasks WHERE id=?", (task_id,),
    )
    if task is None:
        print(f"❌ Task '{task_id}' not found")
        sys.exit(1)

    if verify_cmd:
        db.execute(
            "INSERT INTO assumptions (task_id, assumption, verify_cmd) "
            "VALUES (?, ?, ?)",
            (task_id, assumption, verify_cmd),
        )
    else:
        db.execute(
            "INSERT INTO assumptions (task_id, assumption) "
            "VALUES (?, ?)",
            (task_id, assumption),
        )
    db.commit()

    new_id = db.fetch_scalar(
        "SELECT MAX(id) FROM assumptions WHERE task_id=?",
        (task_id,),
    )
    print(f"✅ Assumption #{new_id} registered for {task_id}: {assumption}")
    if verify_cmd:
        print(f"   Verify: {verify_cmd}")
    else:
        print("   Verify: manual")


# ── verify-assumption command ────────────────────────────────────────

def cmd_verify_assumption(db: Database, task_id: str, assumption_id: int):
    """Verify a single assumption.

    Matches db_queries_legacy.template.sh lines 2179-2212.
    """
    row = db.fetch_one(
        "SELECT assumption, COALESCE(verify_cmd,'') AS verify_cmd "
        "FROM assumptions WHERE task_id=? AND id=?",
        (task_id, assumption_id),
    )
    if row is None:
        print(f"❌ Assumption #{assumption_id} not found for task {task_id}")
        sys.exit(1)

    assumption_text = row["assumption"]
    verify_cmd = row["verify_cmd"]
    today = _iso_date()

    print(f"🔬 Verifying: {assumption_text}")

    if not verify_cmd:
        print("   Manual verification required. Mark result:")
        print(f"   Pass: sqlite3 $DB \"UPDATE assumptions SET verified=1, "
              f"verified_on='{today}' WHERE id={assumption_id};\"")
        print(f"   Fail: sqlite3 $DB \"UPDATE assumptions SET verified=-1, "
              f"verified_on='{today}' WHERE id={assumption_id};\"")
        return

    print(f"   Running: {verify_cmd}")
    result = subprocess.run(
        verify_cmd, shell=True, capture_output=True, text=True,
    )
    result_output = (result.stdout + result.stderr).strip()
    if result_output:
        print(f"   Output: {result_output}")

    if result.returncode == 0:
        print("   ✅ PASSED")
        db.execute(
            "UPDATE assumptions SET verified=1, verified_on=? WHERE id=?",
            (today, assumption_id),
        )
    else:
        print(f"   ❌ FAILED (exit code {result.returncode})")
        db.execute(
            "UPDATE assumptions SET verified=-1, verified_on=? WHERE id=?",
            (today, assumption_id),
        )
    db.commit()


# ── verify-all command ───────────────────────────────────────────────

def cmd_verify_all(db: Database, task_id: str):
    """Verify all unverified assumptions for a task.

    Matches db_queries_legacy.template.sh lines 2214-2259.
    """
    rows = db.fetch_all(
        "SELECT id, assumption, COALESCE(verify_cmd,'') AS verify_cmd "
        "FROM assumptions WHERE task_id=? AND verified=0 ORDER BY id",
        (task_id,),
    )

    if not rows:
        print(f"  No unverified assumptions for {task_id}")
        return

    print("")
    print(output.section_header(f"Verifying assumptions for {task_id}"))

    pass_count = 0
    fail_count = 0
    manual_count = 0
    today = _iso_date()

    for r in rows:
        aid = r["id"]
        atext = r["assumption"]
        acmd = r["verify_cmd"]

        if not acmd:
            print(f"  #{aid}: {atext} → [manual]")
            manual_count += 1
            continue

        result = subprocess.run(
            acmd, shell=True, capture_output=True, text=True,
        )

        if result.returncode == 0:
            print(f"  #{aid}: {atext} → ✅ PASSED")
            db.execute(
                "UPDATE assumptions SET verified=1, verified_on=? WHERE id=?",
                (today, aid),
            )
            pass_count += 1
        else:
            result_output = (result.stdout + result.stderr).strip()
            print(f"  #{aid}: {atext} → ❌ FAILED")
            if result_output:
                print(f"         Output: {result_output}")
            db.execute(
                "UPDATE assumptions SET verified=-1, verified_on=? WHERE id=?",
                (today, aid),
            )
            fail_count += 1

    db.commit()

    print("")
    print(f"  Results: {pass_count} passed, {fail_count} failed, "
          f"{manual_count} manual")
    if fail_count > 0:
        print("  ⚠️  Fix failed assumptions before proceeding")


# ── assumptions command ──────────────────────────────────────────────

def cmd_assumptions(db: Database, task_id: str):
    """List all assumptions for a task.

    Matches db_queries_legacy.template.sh lines 2261-2288.
    """
    count = db.fetch_scalar(
        "SELECT COUNT(*) FROM assumptions WHERE task_id=?",
        (task_id,),
    )

    if count == 0:
        print(f"No assumptions registered for {task_id}")
        return

    print("")
    print(output.section_header(f"Assumptions for {task_id}"))

    rows = db.fetch_all(
        "SELECT id, assumption, verified, verified_on "
        "FROM assumptions WHERE task_id=? ORDER BY id",
        (task_id,),
    )

    for r in rows:
        icon = {1: "✅", -1: "❌"}.get(r["verified"], "⏳")
        date_tag = f" ({r['verified_on']})" if r["verified_on"] else ""
        print(f"  {icon} #{r['id']}: {r['assumption']}{date_tag}")
    print("")
