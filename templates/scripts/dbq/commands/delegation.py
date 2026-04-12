"""
Delegation commands: delegation, delegation-md, sync-check.

delegation: SQL query + formatted output.
delegation-md: regenerate AGENT_DELEGATION.md §8 between HTML comment markers.
sync-check: compare DB tasks vs AGENT_DELEGATION.md, report drift.
"""
import re
import subprocess
import sys
from pathlib import Path

from ..db import Database
from ..config import ProjectConfig
from .. import output


# ── delegation command ──────────────────────────────────────────────

def cmd_delegation(db: Database, phase_filter: str = ""):
    """Show delegation status for phases.

    Matches db_queries_legacy.template.sh lines 1385-1437.
    """
    print("")
    print(output.section_header("Delegation Map (from DB)"))
    print("")

    if phase_filter:
        phases = db.fetch_all(
            "SELECT DISTINCT phase FROM tasks WHERE phase=? ORDER BY phase",
            (phase_filter,),
        )
    else:
        phases = db.fetch_all(
            "SELECT DISTINCT phase FROM tasks ORDER BY phase"
        )

    if not phases:
        print("  No tasks found.")
        print("")
        return

    for phase_row in phases:
        phase = phase_row["phase"]

        remaining = db.fetch_scalar(
            "SELECT COUNT(*) FROM tasks "
            "WHERE phase=? AND status NOT IN ('DONE','SKIP','WONTFIX')",
            (phase,),
        )
        phase_status = "DONE" if remaining == 0 else "IN PROGRESS"

        print(f"### {phase} ({phase_status})")
        print("| Task | Tier | Skill | Status | Research Notes |")
        print("|------|------|-------|--------|----------------|")

        rows = db.fetch_all(
            "SELECT id, title, COALESCE(UPPER(tier), '?') AS tier, "
            "COALESCE(skill, '—') AS skill, status, "
            "COALESCE(substr(research_notes, 1, 80), '—') AS notes, "
            "CASE WHEN length(COALESCE(research_notes,'')) > 80 THEN '...' ELSE '' END AS ellipsis "
            "FROM tasks WHERE phase=? ORDER BY sort_order",
            (phase,),
        )

        for r in rows:
            notes = r["notes"] + r["ellipsis"]
            print(f"| {r['id']} {r['title']} | {r['tier']} | {r['skill']} | {r['status']} | {notes} |")

        print("")


# ── delegation-md command ───────────────────────────────────────────

def cmd_delegation_md(db: Database, config: ProjectConfig, active_only: bool = False):
    """Auto-regenerate AGENT_DELEGATION.md §8 from DB.

    Matches db_queries_legacy.template.sh lines 2583-2680.
    Replaces content between <!-- DELEGATION-START --> and <!-- DELEGATION-END --> markers.

    Args:
        active_only: If True, filter out rows where status IN ('DONE', 'WONTFIX', 'SKIP').
    """
    deleg_file = config.project_dir / "AGENT_DELEGATION.md"
    if not deleg_file.exists():
        print("❌ AGENT_DELEGATION.md not found")
        sys.exit(1)

    content = deleg_file.read_text()

    if "<!-- DELEGATION-START -->" not in content:
        print("❌ Missing <!-- DELEGATION-START --> marker in AGENT_DELEGATION.md")
        print("   Add <!-- DELEGATION-START --> and <!-- DELEGATION-END --> markers around §8 content.")
        sys.exit(1)

    if "<!-- DELEGATION-END -->" not in content:
        print("❌ Missing <!-- DELEGATION-END --> marker in AGENT_DELEGATION.md")
        sys.exit(1)

    # Build new content
    new_section_lines = []

    phases = db.fetch_all(
        "SELECT DISTINCT phase FROM tasks "
        "WHERE queue != 'INBOX' AND COALESCE(track,'forward')='forward' "
        "ORDER BY phase"
    )

    all_phase_names = [r["phase"] for r in phases]

    for phase_row in phases:
        phase = phase_row["phase"]
        done_count = db.fetch_scalar(
            "SELECT COUNT(*) FROM tasks "
            "WHERE phase=? AND COALESCE(track,'forward')='forward' AND status='DONE'",
            (phase,),
        )
        total_count = db.fetch_scalar(
            "SELECT COUNT(*) FROM tasks "
            "WHERE phase=? AND COALESCE(track,'forward')='forward' AND queue != 'INBOX'",
            (phase,),
        )

        # Check if gated and fully done — collapse to 1-line summary
        is_gated = db.fetch_scalar(
            "SELECT COUNT(*) FROM phase_gates WHERE phase=?",
            (phase,),
        )

        if is_gated > 0 and done_count == total_count:
            gate_date = db.fetch_one(
                "SELECT gated_on FROM phase_gates WHERE phase=?",
                (phase,),
            )
            new_section_lines.append(
                f"### {phase} ({done_count}/{total_count} DONE) — gated {gate_date}"
            )
            new_section_lines.append("")
            continue

        if done_count == total_count:
            new_section_lines.append(f"### {phase} (DONE — {done_count}/{total_count})")
        else:
            new_section_lines.append(f"### {phase} ({done_count}/{total_count} done)")

        new_section_lines.append("| Task | Tier | Skill | Status | Why |")
        new_section_lines.append("|------|------|-------|--------|-----|")

        # Build query with optional filtering
        query = (
            "SELECT id, title, COALESCE(tier,'—') AS tier, "
            "COALESCE(skill,'—') AS skill, status, "
            "COALESCE(research_notes,'') AS notes "
            "FROM tasks "
            "WHERE phase=? AND queue != 'INBOX' AND COALESCE(track,'forward')='forward' "
        )
        params = [phase]

        if active_only:
            query += "AND status NOT IN ('DONE','WONTFIX','SKIP') "

        query += "ORDER BY sort_order, id"

        rows = db.fetch_all(query, tuple(params))

        for r in rows:
            note_part = ""
            if r["notes"]:
                note_part = f" **RESEARCH:** {r['notes']}"
            new_section_lines.append(
                f"| {r['id']} {r['title']} | {r['tier']} | {r['skill']} | {r['status']} |{note_part} |"
            )

        new_section_lines.append("")

    # Check for INBOX items (exclude already-done tasks)
    inbox_ct = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks "
        "WHERE queue='INBOX' AND status NOT IN ('DONE','SKIP','WONTFIX')"
    )
    if inbox_ct > 0:
        new_section_lines.append(f"### INBOX ({inbox_ct} untriaged)")
        new_section_lines.append("| Task | Title | Tag |")
        new_section_lines.append("|------|-------|-----|")

        inbox_rows = db.fetch_all(
            "SELECT id, title, COALESCE(details,'') AS tag "
            "FROM tasks WHERE queue='INBOX' AND status NOT IN ('DONE','SKIP','WONTFIX') "
            "ORDER BY id"
        )
        for r in inbox_rows:
            new_section_lines.append(f"| {r['id']} | {r['title']} | {r['tag']} |")
        new_section_lines.append("")

    # Reassemble file: before START + START marker + new content + END marker + after END
    lines = content.splitlines()
    before = []
    after = []
    state = "before"
    for line in lines:
        if state == "before":
            before.append(line)
            if "<!-- DELEGATION-START -->" in line:
                state = "inside"
        elif state == "inside":
            if "<!-- DELEGATION-END -->" in line:
                after.append(line)
                state = "after"
        elif state == "after":
            after.append(line)

    result = before + new_section_lines + after
    deleg_file.write_text("\n".join(result) + "\n")

    phase_str = " ".join(all_phase_names)
    print(f"✅ Regenerated AGENT_DELEGATION.md §8 from DB")
    print(f"   Phases: {phase_str}")
    if active_only:
        print(f"   (filtered: --active-only, showing only TODO/IN_PROGRESS rows)")
    if inbox_ct > 0:
        print(f"   📥 {inbox_ct} inbox item(s) included")


# ── tier-up command ─────────────────────────────────────────────────

TIER_ORDER = {"haiku": 0, "sonnet": 1, "opus": 2, "gemini": 3}
VALID_ESCALATION_REASONS = {"prompt", "context", "ceiling", "environment"}


def cmd_tier_up(db: Database, task_id: str, new_tier: str, reason: str) -> None:
    """Escalate a task to a higher-capability tier.

    Records the escalation for tracking delegation accuracy over time.
    """
    # Validate task exists
    row = db.fetch_one(
        "SELECT id, tier, original_tier, status, escalation_count "
        "FROM tasks WHERE id=?",
        (task_id,),
    )
    if not row:
        print(f"❌ Task {task_id} not found")
        sys.exit(1)

    if row["status"] in ("DONE", "SKIP", "WONTFIX"):
        print(f"❌ Task {task_id} is already {row['status']} — cannot escalate")
        sys.exit(1)

    current_tier = (row["tier"] or "").lower()
    new_tier_lower = new_tier.lower()

    # Validate new tier
    if new_tier_lower not in TIER_ORDER:
        print(f"❌ Invalid tier '{new_tier}'. Valid: {', '.join(TIER_ORDER)}")
        sys.exit(1)

    # Validate reason
    if reason.lower() not in VALID_ESCALATION_REASONS:
        print(f"❌ Invalid reason '{reason}'. Valid: {', '.join(sorted(VALID_ESCALATION_REASONS))}")
        sys.exit(1)

    # Guard: must be an actual escalation (higher tier)
    if current_tier in TIER_ORDER and TIER_ORDER.get(new_tier_lower, 0) <= TIER_ORDER[current_tier]:
        print(f"❌ Cannot escalate from {current_tier} to {new_tier_lower} — "
              f"target must be a higher tier")
        sys.exit(1)

    # Backfill original_tier if NULL (pre-migration tasks)
    original = row["original_tier"]
    if original is None:
        original = current_tier or new_tier_lower

    esc_count = (row["escalation_count"] or 0) + 1

    db.execute(
        "UPDATE tasks SET tier=?, original_tier=?, escalation_reason=?, "
        "escalation_count=?, updated_at=datetime('now') WHERE id=?",
        (new_tier_lower, original, reason.lower(), esc_count, task_id),
    )
    db.commit()

    print(f"⬆️  Escalated {task_id}: {current_tier} → {new_tier_lower}")
    print(f"   Reason: {reason.lower()} | Count: {esc_count} | Original: {original}")


# ── sync-check command ──────────────────────────────────────────────

def cmd_sync_check(db: Database, config: ProjectConfig):
    """Detect drift between DB task list and AGENT_DELEGATION.md §8.

    Matches db_queries_legacy.template.sh lines 1439-1540.
    """
    deleg_file = config.project_dir / "AGENT_DELEGATION.md"
    drift_count = 0

    print("")
    print(output.section_header("Sync Check: DB ↔ AGENT_DELEGATION.md"))

    if not deleg_file.exists():
        print("  ❌ AGENT_DELEGATION.md not found")
        sys.exit(1)

    deleg_content = deleg_file.read_text()

    # Check 1: Tasks in DB but not mentioned in markdown
    rows = db.fetch_all(
        "SELECT id, title, COALESCE(tier,'?') AS tier "
        "FROM tasks WHERE status != 'DONE' ORDER BY sort_order"
    )

    missing_from_md = []
    for r in rows:
        if r["id"] not in deleg_content:
            missing_from_md.append(r)
            drift_count += 1

    if missing_from_md:
        print("")
        print("  ⚠️  Tasks in DB but NOT in AGENT_DELEGATION.md:")
        for r in missing_from_md:
            print(f"    {r['id']} ({r['tier']}): {r['title']}")

    # Check 2: Tasks without tier assignment
    untiered = db.fetch_all(
        "SELECT id, title FROM tasks "
        "WHERE tier IS NULL AND status NOT IN ('DONE','SKIP','WONTFIX') "
        "ORDER BY sort_order"
    )

    if untiered:
        print("  ⚠️  Tasks without tier assignment:")
        for r in untiered:
            print(f"    {r['id']}: {r['title']}")
        print("")
        drift_count += len(untiered)

    # Check 3: Research notes not reflected in markdown
    research_rows = db.fetch_all(
        "SELECT id FROM tasks "
        "WHERE research_notes IS NOT NULL AND research_notes != '' "
        "AND status NOT IN ('DONE','SKIP','WONTFIX') "
        "ORDER BY sort_order"
    )

    missing_research = []
    for r in research_rows:
        # Find the line in markdown containing this task ID
        for line in deleg_content.splitlines():
            if r["id"] in line:
                if "RESEARCH" not in line.upper():
                    missing_research.append(r["id"])
                    drift_count += 1
                break

    if missing_research:
        print("  ⚠️  Research notes not reflected in AGENT_DELEGATION.md:")
        for tid in missing_research:
            print(f"    {tid} — has research_notes in DB but no RESEARCH tag in markdown")

    # Check 4: DB totals
    db_total = db.fetch_scalar("SELECT COUNT(*) FROM tasks")
    db_phases = db.fetch_scalar("SELECT COUNT(DISTINCT phase) FROM tasks")
    print(f"  📊 DB totals: {db_total} tasks across {db_phases} phases")

    # Check 5: INBOX items pending triage (exclude already-done tasks)
    inbox_count = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks "
        "WHERE queue='INBOX' AND status NOT IN ('DONE','SKIP','WONTFIX')"
    )
    if inbox_count > 0:
        print(f"  📥 {inbox_count} task(s) in INBOX awaiting triage")
        print("     Run: bash db_queries.sh inbox")
        print("")

    # Check 6: Tasks in recent commits but not marked DONE (reverse drift)
    git_result = subprocess.run(
        ["git", "-C", str(config.project_dir), "log", "--oneline", "-50"],
        capture_output=True, text=True,
    )
    if git_result.returncode == 0 and git_result.stdout.strip():
        commit_task_ids: set[str] = set()
        for line in git_result.stdout.strip().splitlines():
            # Match auto-commit format: [P1-DISCOVER] QK-1234: title
            m = re.search(r'\[P\d+-\w+\]\s+([\w-]+):', line)
            if m:
                commit_task_ids.add(m.group(1))

        if commit_task_ids:
            not_done = []
            for tid in sorted(commit_task_ids):
                row = db.fetch_one(
                    "SELECT id, status FROM tasks WHERE id=?", (tid,)
                )
                if row and row["status"] not in ("DONE", "SKIP"):
                    not_done.append((tid, row["status"]))

            if not_done:
                print("")
                print("  ⚠️  Tasks in recent commits but NOT marked DONE (reverse drift):")
                for tid, status in not_done:
                    print(f"    {tid} — status: {status}")
                print("    Fix: bash db_queries.sh done <task-id>")
                drift_count += len(not_done)

    # Verdict
    if drift_count == 0:
        print("")
        print("  ✅ Sync check passed — DB and markdown are consistent")
    else:
        print("")
        print(f"  ⚠️  {drift_count} drift(s) detected")
        print("  Fix: run 'bash db_queries.sh delegation-md' to regenerate §8 from DB.")
    print("")
