"""
Knowledge commands: lessons, log-lesson, promote, escalate, harvest.

All modify markdown files outside the DB using marker-based insertion.
Pattern: content.replace(marker, new_text + "\n" + marker) — proven in loopbacks.py.
"""
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from ..db import Database
from ..config import ProjectConfig
from .. import output


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _find_backlog() -> Path:
    """Resolve backlog path via fallback chain: project backlog/ → project root."""
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent.parent.parent
    candidates = [
        project_root / "backlog" / "BOOTSTRAP_BACKLOG.md",
        project_root / "BOOTSTRAP_BACKLOG.md",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    # Default fallback (will be created if needed)
    return project_root / "backlog" / "BOOTSTRAP_BACKLOG.md"


# ── lessons command ─────────────────────────────────────────────────

def cmd_lessons(config: ProjectConfig):
    """Display LESSONS.md contents with staleness and violation tracking.

    Matches db_queries_legacy.template.sh lines 1226-1267.
    """
    lessons_file = config.lessons_file
    if not lessons_file:
        print("❌ No LESSONS file found in project directory")
        sys.exit(1)

    lf = Path(lessons_file)
    if not lf.exists():
        print(f"❌ {lf.name} not found")
        sys.exit(1)

    output.print_section("Lessons & Corrections")
    print("")

    content = lf.read_text()
    lines = content.splitlines()
    today_ts = datetime.now().timestamp()

    # Detect column positions from header row
    pattern_col = 3  # default for Bootstrap 5-col format
    rule_col = 4
    last_ref_col = -1
    violations_col = -1
    for line in lines:
        if line.startswith("| Date") or line.startswith("| #"):
            cols = [c.strip().lower() for c in line.split("|")]
            for idx, col in enumerate(cols):
                if col in ("pattern", "what happened", "what went wrong", "lesson"):
                    pattern_col = idx
                elif col in ("prevention rule", "prevention", "rule"):
                    rule_col = idx
                elif col in ("last ref", "last referenced", "last_ref"):
                    last_ref_col = idx
                elif col in ("violations", "violation count"):
                    violations_col = idx
            break

    # Display table rows (variable column count)
    count = 0
    for line in lines:
        if not line.startswith("| 20"):
            continue
        parts = line.split("|")
        if len(parts) < 4:
            continue
        if count >= 20:
            break

        date = parts[1].strip()
        pattern = parts[pattern_col].strip() if pattern_col < len(parts) else ""
        rule = parts[rule_col].strip() if rule_col > 0 and rule_col < len(parts) else ""
        last_ref = parts[last_ref_col].strip() if last_ref_col > 0 and last_ref_col < len(parts) else ""
        violations = parts[violations_col].strip() if violations_col > 0 and violations_col < len(parts) else ""

        # Staleness check
        stale = ""
        if last_ref and last_ref != "—":
            try:
                ref_dt = datetime.strptime(last_ref, "%Y-%m-%d")
                days_ago = int((today_ts - ref_dt.timestamp()) / 86400)
                if days_ago > 30:
                    stale = f" ⚠️  STALE ({days_ago} days)"
            except ValueError:
                pass
        elif last_ref == "—":
            stale = " ⚠️  NEVER REFERENCED"

        # Violation warning
        viol_warn = ""
        try:
            viol_count = int(violations)
            if viol_count >= 2:
                viol_warn = f" 🔴 VIOLATED {viol_count}x — rewrite prevention rule!"
        except (ValueError, TypeError):
            pass

        print(f"  [{date}] {pattern}")
        print(f"    → {rule}")
        if last_ref or violations:
            print(f"    Last ref: {last_ref or '—'} | Violations: {violations or '0'}{stale}{viol_warn}")
        print("")
        count += 1

    # Display ### block entries
    i = 0
    while i < len(lines):
        if lines[i].strip().startswith("### 20") and count < 20:
            heading = lines[i].strip()[4:]
            pattern = ""
            rule = ""
            promoted = ""
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith("### ") and not lines[j].strip().startswith("## "):
                bl = lines[j].strip()
                if bl.startswith("**Pattern:**"):
                    pattern = bl[len("**Pattern:**"):].strip()
                elif bl.startswith("**Prevention:**"):
                    rule = bl[len("**Prevention:**"):].strip()
                elif bl.startswith("**Promoted:**"):
                    promoted = bl[len("**Promoted:**"):].strip()
                j += 1
            # Extract date from heading (### YYYY-MM-DD — ...)
            date = heading[:10] if len(heading) >= 10 else "?"
            display = pattern or heading
            prom_label = f" [{promoted}]" if promoted else ""
            print(f"  [{date}] {display}{prom_label}")
            if rule:
                print(f"    → {rule}")
            print("")
            count += 1
            i = j
        else:
            i += 1


# ── log-lesson command ──────────────────────────────────────────────

def cmd_log_lesson(
    config: ProjectConfig,
    what_wrong: str,
    pattern: str,
    prevention: str,
    bp_category: str = "",
    bp_file: str = "",
):
    """Atomically append a correction to LESSONS file.

    Matches db_queries_legacy.template.sh lines 1269-1383.
    Uses anchor-based insertion: finds CORRECTIONS-ANCHOR or ## Insights/Universal Patterns.
    """
    lessons_file = config.lessons_file
    if not lessons_file:
        print("❌ No LESSONS file found in project directory")
        sys.exit(1)

    lf = Path(lessons_file)
    if not lf.exists():
        print(f"❌ {lf.name} not found")
        sys.exit(1)

    today = _today()
    lines = lf.read_text().splitlines()

    # Find anchor line — two modes:
    # 1. CORRECTIONS-ANCHOR: insert AFTER anchor (anchor stays above entries)
    # 2. Fallback (## Insights/Universal): insert BEFORE section header
    insert_idx = None
    for i, line in enumerate(lines):
        if "<!-- CORRECTIONS-ANCHOR -->" in line:
            insert_idx = i + 1  # after anchor
    if insert_idx is None:
        for i, line in enumerate(lines):
            if line.startswith("## Insights") or line.startswith("## Universal Patterns"):
                insert_idx = i  # before section header
                break

    if insert_idx is None:
        print("❌ Could not find insertion point in LESSONS file")
        print("   Add <!-- CORRECTIONS-ANCHOR --> where new corrections should appear.")
        sys.exit(1)

    # Build entry
    entry_lines = [
        "",
        f"### {today} — {what_wrong}",
        f"**Pattern:** {pattern}",
        f"**Prevention:** {prevention}",
        f"**Promoted:** No",
    ]

    new_lines = lines[:insert_idx] + entry_lines + lines[insert_idx:]
    lf.write_text("\n".join(new_lines) + "\n")

    # Verify
    content = lf.read_text()
    if what_wrong in content:
        print(f"✅ Lesson logged: {pattern}")
        print(f"   → {prevention}")
    else:
        print("❌ Failed to write lesson to file")
        sys.exit(1)

    # --bp escalation
    if bp_category:
        _escalate_to_backlog(
            description=pattern,
            category=bp_category,
            affected_file=bp_file or "unknown (review needed)",
            priority="P2",
            project_name=config.project_name,
        )


def _mark_source_promoted(config: ProjectConfig, pattern: str, date: str,
                          source_file: str = ""):
    """Mark the source lesson entry as promoted in the project LESSONS file.

    Uses keyword overlap scoring to find the best-matching unpromoted entry,
    since the promoted text is often a summary rather than a verbatim copy.
    Handles both table rows ('| No |' → '| Yes (date) |') and
    ### blocks ('**Promoted:** No' → '**Promoted:** Yes (date)').

    Args:
        source_file: Override path to LESSONS file. When set, marks the entry
                     in this file instead of config.lessons_file. Enables
                     cross-project promotion.
    """
    lessons_file = source_file or config.lessons_file
    if not lessons_file:
        return
    lf = Path(lessons_file)
    if not lf.exists():
        return

    content = lf.read_text()
    lines = content.splitlines()
    pattern_keywords = set(re.findall(r"[a-zA-Z]{4,}", pattern.lower()))
    if not pattern_keywords:
        print("   ⚠️  Could not find source entry to mark — update manually in LESSONS*.md")
        return

    best_score = 0
    best_line_idx = -1  # line index to modify
    best_kind = ""      # "table" or "block"

    # Score table rows with "| No |"
    for i, line in enumerate(lines):
        if line.startswith("|") and ("| No |" in line or "| No —" in line):
            if line.startswith("| Date") or line.startswith("|---"):
                continue
            row_keywords = set(re.findall(r"[a-zA-Z]{4,}", line.lower()))
            score = len(pattern_keywords & row_keywords)
            if score > best_score:
                best_score = score
                best_line_idx = i
                best_kind = "table"

    # Score ### blocks with **Promoted:** No
    i = 0
    while i < len(lines):
        if lines[i].strip().startswith("### "):
            block_text = lines[i]
            promoted_line_idx = -1
            j = i + 1
            while j < len(lines) and j < i + 6:
                block_text += " " + lines[j]
                if lines[j].strip().startswith("**Promoted:** No"):
                    promoted_line_idx = j
                if lines[j].strip().startswith("### ") or lines[j].strip().startswith("## "):
                    break
                j += 1
            if promoted_line_idx >= 0:
                block_keywords = set(re.findall(r"[a-zA-Z]{4,}", block_text.lower()))
                score = len(pattern_keywords & block_keywords)
                if score > best_score:
                    best_score = score
                    best_line_idx = promoted_line_idx
                    best_kind = "block"
            i = j
        else:
            i += 1

    if best_score >= 3 and best_line_idx >= 0:
        if best_kind == "table":
            lines[best_line_idx] = lines[best_line_idx].replace(
                "| No |", f"| Yes ({date}) |"
            ).replace("| No —", f"| Yes ({date}) —")
        else:
            lines[best_line_idx] = f"**Promoted:** Yes ({date})"
        lf.write_text("\n".join(lines) + "\n")
        print("   ✅ Source entry marked as promoted")
    else:
        print("   ⚠️  Could not find source entry to mark — update manually in LESSONS*.md")


# ── harvest helpers ────────────────────────────────────────────────


def _extract_keywords(text: str) -> set:
    """Extract 4+ letter keywords from text for fuzzy matching."""
    return set(re.findall(r"[a-zA-Z]{4,}", text.lower()))


def _parse_unpromoted(filepath: str) -> list:
    """Parse unpromoted entries from a LESSONS file.

    Handles both table rows (``| No |``) and ### blocks (``**Promoted:** No``).
    Returns list of dicts: {date, pattern, prevention, raw_text, source_file}.
    """
    fp = Path(filepath)
    if not fp.exists():
        return []

    lines = fp.read_text().splitlines()
    results: list = []
    basename = fp.name

    # Detect column positions from header row
    pattern_col = 3
    rule_col = 4
    promoted_col = -1
    for line in lines:
        if line.startswith("| Date") or line.startswith("| #"):
            cols = [c.strip().lower() for c in line.split("|")]
            for idx, col in enumerate(cols):
                if col in ("pattern", "what happened", "what went wrong", "lesson"):
                    pattern_col = idx
                elif col in ("prevention rule", "prevention", "rule"):
                    rule_col = idx
                elif col == "promoted":
                    promoted_col = idx
            break

    # Table rows with "| No |" or "| No —"
    for line in lines:
        if not line.startswith("| 20"):
            continue
        if line.startswith("| Date") or line.startswith("|---"):
            continue
        parts = line.split("|")
        if len(parts) < 4:
            continue
        # Check promoted column or any column for "No" (skip "No — project-specific")
        is_unpromoted = False
        if promoted_col > 0 and promoted_col < len(parts):
            val = parts[promoted_col].strip()
            if (val == "No" or val.startswith("No —") or val.startswith("No —")) and "project-specific" not in val:
                is_unpromoted = True
        else:
            # Fallback: check any column
            stripped = [c.strip() for c in parts if c.strip()]
            if any((c == "No" or c.startswith("No —") or c.startswith("No —")) and "project-specific" not in c for c in stripped):
                is_unpromoted = True

        if is_unpromoted:
            date = parts[1].strip() if len(parts) > 1 else "?"
            pattern = parts[pattern_col].strip() if pattern_col < len(parts) else ""
            prevention = parts[rule_col].strip() if rule_col > 0 and rule_col < len(parts) else ""
            results.append({
                "date": date,
                "pattern": pattern,
                "prevention": prevention,
                "raw_text": line,
                "source_file": basename,
            })

    # ### blocks with **Promoted:** No
    i = 0
    while i < len(lines):
        if lines[i].strip().startswith("### "):
            heading = lines[i].strip()[4:]
            block_text = lines[i]
            pattern = ""
            prevention = ""
            promoted_no = False
            j = i + 1
            while j < len(lines) and j < i + 8:
                bl = lines[j].strip()
                block_text += " " + bl
                if bl.startswith("**Pattern:**"):
                    pattern = bl[len("**Pattern:**"):].strip()
                elif bl.startswith("**Prevention:**"):
                    prevention = bl[len("**Prevention:**"):].strip()
                elif bl.startswith("**Promoted:** No") and "project-specific" not in bl:
                    promoted_no = True
                if bl.startswith("### ") or bl.startswith("## "):
                    break
                j += 1
            if promoted_no:
                date = heading[:10] if len(heading) >= 10 else "?"
                results.append({
                    "date": date,
                    "pattern": pattern or heading,
                    "prevention": prevention,
                    "raw_text": block_text,
                    "source_file": basename,
                })
            i = j
        else:
            i += 1

    return results


def _load_universal_entries(config: ProjectConfig) -> list:
    """Load all entries from LESSONS_UNIVERSAL.md for dedup scoring.

    Returns list of dicts: {pattern, prevention, keywords, raw_text}.
    Returns empty list if file doesn't exist (graceful degradation).
    """
    universal = Path.home() / ".claude" / "LESSONS_UNIVERSAL.md"
    if not universal.exists():
        project_local = config.project_dir / "LESSONS_UNIVERSAL.md"
        if project_local.exists():
            universal = project_local
        else:
            return []

    entries: list = []
    for line in universal.read_text().splitlines():
        if not line.startswith("| 20"):
            continue
        parts = line.split("|")
        if len(parts) < 5:
            continue
        pattern = parts[2].strip()
        prevention = parts[4].strip() if len(parts) > 4 else ""
        combined = f"{pattern} {prevention}"
        entries.append({
            "pattern": pattern,
            "prevention": prevention,
            "keywords": _extract_keywords(combined),
            "raw_text": combined,
        })
    return entries


def _score_dedup(entry_keywords: set, universal_entries: list) -> tuple:
    """Score an unpromoted entry against all universal entries.

    Returns (best_score, best_match_dict_or_None, overlapping_keywords_set).
    """
    best_score = 0
    best_match = None
    best_overlap: set = set()

    for entry in universal_entries:
        overlap = entry_keywords & entry["keywords"]
        score = len(overlap)
        if score > best_score:
            best_score = score
            best_match = entry
            best_overlap = overlap

    return best_score, best_match, best_overlap


# ── harvest command ────────────────────────────────────────────────

_DEDUP_THRESHOLD = 4  # higher than promote's 3 to reduce false positives in review


def _mark_promoted_in_file(filepath: str, pattern: str, date: str) -> bool:
    """Mark a single entry as promoted in a LESSONS file by keyword matching.

    Returns True if an entry was marked, False otherwise.
    """
    lf = Path(filepath)
    if not lf.exists():
        return False

    content = lf.read_text()
    lines = content.splitlines()
    pattern_keywords = set(re.findall(r"[a-zA-Z]{4,}", pattern.lower()))
    if not pattern_keywords:
        return False

    best_score = 0
    best_line_idx = -1
    best_kind = ""

    for i, line in enumerate(lines):
        if line.startswith("|") and ("| No |" in line or "| No —" in line):
            if line.startswith("| Date") or line.startswith("|---"):
                continue
            row_keywords = set(re.findall(r"[a-zA-Z]{4,}", line.lower()))
            score = len(pattern_keywords & row_keywords)
            if score > best_score:
                best_score = score
                best_line_idx = i
                best_kind = "table"

    i = 0
    while i < len(lines):
        if lines[i].strip().startswith("### "):
            block_text = lines[i]
            promoted_line_idx = -1
            j = i + 1
            while j < len(lines) and j < i + 6:
                block_text += " " + lines[j]
                if lines[j].strip().startswith("**Promoted:** No"):
                    promoted_line_idx = j
                if lines[j].strip().startswith("### ") or lines[j].strip().startswith("## "):
                    break
                j += 1
            if promoted_line_idx >= 0:
                block_keywords = set(re.findall(r"[a-zA-Z]{4,}", block_text.lower()))
                score = len(pattern_keywords & block_keywords)
                if score > best_score:
                    best_score = score
                    best_line_idx = promoted_line_idx
                    best_kind = "block"
            i = j
        else:
            i += 1

    if best_score >= 3 and best_line_idx >= 0:
        if best_kind == "table":
            lines[best_line_idx] = lines[best_line_idx].replace(
                "| No |", f"| Yes ({date}) |"
            ).replace("| No —", f"| Yes ({date}) —")
        else:
            lines[best_line_idx] = f"**Promoted:** Yes ({date})"
        lf.write_text("\n".join(lines) + "\n")
        return True
    return False


def cmd_harvest(config: ProjectConfig, *paths: str, mark_dupes: bool = False) -> None:
    """Surface unpromoted LESSONS entries with fuzzy dedup detection against universal.

    Args:
        mark_dupes: When True, auto-mark entries that score above the dedup
                    threshold as promoted in their source files.
    """
    # Resolve input files
    if paths:
        file_list = list(paths)
    elif config.lessons_file:
        file_list = [config.lessons_file]
    else:
        print("❌ No LESSONS file configured and no paths given")
        sys.exit(1)

    # Validate all paths exist
    for fp in file_list:
        if not Path(fp).exists():
            print(f"❌ File not found: {fp}")
            sys.exit(1)

    # Load universal entries for dedup
    universal_entries = _load_universal_entries(config)
    no_universal = len(universal_entries) == 0

    print("━━━ Lesson Harvest ━━━")
    if no_universal:
        print("  ℹ️  No LESSONS_UNIVERSAL.md found — skipping dedup checks")
        print("")

    total = 0
    dupes = 0
    unique = 0
    marked = 0

    for fp in file_list:
        entries = _parse_unpromoted(fp)
        if not entries:
            print(f"\n📄 {Path(fp).name}: (no unpromoted entries)")
            continue

        print(f"\n📄 {Path(fp).name}:")
        for entry in entries:
            total += 1
            print(f"  [{entry['date']}] {entry['pattern']}")
            if entry["prevention"]:
                print(f"    → {entry['prevention']}")

            if no_universal:
                print("    ✅ Unique — good candidate for promotion")
                unique += 1
            else:
                entry_kw = _extract_keywords(f"{entry['pattern']} {entry['prevention']}")
                score, match, overlap = _score_dedup(entry_kw, universal_entries)
                if score >= _DEDUP_THRESHOLD:
                    dupes += 1
                    match_preview = match["pattern"][:80] if match else ""
                    if len(match["pattern"]) > 80:
                        match_preview += "..."
                    print(f"    ⚠️  Potential duplicate (score: {score})")
                    print(f"    Matches: \"{match_preview}\"")
                    print(f"    Keywords: {', '.join(sorted(overlap))}")
                    if mark_dupes:
                        if _mark_promoted_in_file(fp, entry["pattern"], _today()):
                            marked += 1
                            print(f"    ✏️  Marked as promoted in source")
                        else:
                            print(f"    ⚠️  Could not auto-mark — update manually")
                else:
                    unique += 1
                    print("    ✅ Unique — good candidate for promotion")

    summary = f"\n📊 {total} unpromoted | {dupes} potential duplicates | {unique} unique candidates"
    if mark_dupes and marked > 0:
        summary += f" | {marked} auto-marked"
    print(summary)


# ── promote command ─────────────────────────────────────────────────

def cmd_promote(config: ProjectConfig, pattern: str, rule: str = "",
                method: str = "", source_file: str = "",
                source_project: str = ""):
    """Quick-promote a universal pattern to LESSONS_UNIVERSAL.md.

    Appends to LESSONS_UNIVERSAL.md and auto-marks the source entry
    in the project's LESSONS file (both table rows and ### blocks).

    Args:
        method: Discovery method for provenance tracking. One of:
                correction, audit, harvest, manual. Appended to the
                Source Project column as ``ProjectName (method)``.
        source_file: Path to LESSONS file to mark as promoted. Overrides
                     config.lessons_file, enabling cross-project promote.
        source_project: Project name for provenance. Overrides
                        config.project_name for the Source Project column.
    """
    universal = Path.home() / ".claude" / "LESSONS_UNIVERSAL.md"
    if not universal.exists():
        # Fallback: check project root (works when symlink is missing)
        project_local = config.project_dir / "LESSONS_UNIVERSAL.md"
        if project_local.exists():
            universal = project_local
        else:
            print(f"❌ LESSONS_UNIVERSAL.md not found at project root")
            print(f"   Ensure LESSONS_UNIVERSAL.md exists at the project root")
            sys.exit(1)

    today = _today()
    prevention = rule or "See source project LESSONS.md"

    # Provenance: embed discovery method in Source Project column
    project_name = source_project or config.project_name
    source = project_name
    if method:
        source = f"{project_name} ({method})"

    with open(str(universal), "a") as f:
        f.write(f"| {today} | {pattern} | {source} | {prevention} |\n")

    print(f"✅ Promoted to LESSONS_UNIVERSAL.md{f' (via {method})' if method else ''}")

    # Auto-mark source entry as promoted (use override file if given)
    _mark_source_promoted(config, pattern, today, source_file=source_file)


# ── escalate command ────────────────────────────────────────────────

def cmd_escalate(
    config: ProjectConfig,
    description: str,
    category: str = "template",
    affected_file: str = "unknown (review needed)",
    priority: str = "P2",
):
    """Escalate to bootstrap backlog for template/framework improvement.

    Matches db_queries_legacy.template.sh lines 2703-2782.
    """
    # Validate category
    valid_cats = ("template", "framework", "process", "system")
    if category not in valid_cats:
        print(f"⚠️  Unknown category '{category}' — using 'template'")
        category = "template"

    _escalate_to_backlog(
        description=description,
        category=category,
        affected_file=affected_file,
        priority=priority,
        project_name=config.project_name,
    )


def _escalate_to_backlog(
    description: str,
    category: str,
    affected_file: str,
    priority: str,
    project_name: str,
):
    """Shared escalation logic used by both escalate and log-lesson --bp."""
    backlog = _find_backlog()
    if not backlog.exists():
        print(f"❌ {backlog} not found")
        sys.exit(1)

    content = backlog.read_text()
    lines = content.splitlines()

    # Derive next BP-ID
    bp_ids = re.findall(r"BP-(\d+)", content)
    if bp_ids:
        next_id = max(int(x) for x in bp_ids) + 1
    else:
        next_id = 1
    bp_id = f"BP-{next_id:03d}"

    today = _today()

    # Check for duplicates
    if affected_file != "unknown (review needed)":
        dup_count = content.count(affected_file)
        if dup_count > 0:
            print(f"⚠️  Backlog already has {dup_count} item(s) mentioning {affected_file}")
            print("   Adding anyway — review for duplicates with: apply_backlog.sh in your bootstrap repo (backlog/ dir)")

    # Find anchor: <!-- PENDING-ANCHOR or ## Applied
    anchor_idx = None
    for i, line in enumerate(lines):
        if "<!-- PENDING-ANCHOR" in line:
            anchor_idx = i
    if anchor_idx is None:
        for i, line in enumerate(lines):
            if line.startswith("## Applied"):
                anchor_idx = i
                break

    if anchor_idx is None:
        print("❌ Could not find insertion point in BOOTSTRAP_BACKLOG.md")
        sys.exit(1)

    entry_lines = [
        "",
        f"### {bp_id} [{category}] {description}",
        f"- **Escalated:** {today}",
        f"- **Source:** {project_name}",
        f"- **Priority:** {priority}",
        f"- **Affected:** {affected_file}",
        f"- **Description:** {description}",
        "- **Change:** (to be determined during review)",
        "- **Status:** pending",
        "",
    ]

    new_lines = lines[:anchor_idx] + entry_lines + lines[anchor_idx:]
    backlog.write_text("\n".join(new_lines) + "\n")

    print(f"✅ Escalated to bootstrap backlog as {bp_id} [{category}] ({priority})")
    print(f"   Review: apply_backlog.sh in your bootstrap repo (backlog/ dir) {bp_id}")
