"""
Output formatting — defines the output contracts that callers depend on.

CRITICAL: Several callers parse our output with grep/tail/head.
The exact line format of certain outputs is a WIRE PROTOCOL.
Changes here can break session_briefing.sh, test_bootstrap_suite.sh, etc.

Output contracts documented inline with the caller that depends on them.
"""
import sys
from typing import List, Optional


def section_header(title: str) -> str:
    """Format: ── Title ─────────────────────────────────────────────"""
    padding = max(0, 60 - len(title) - 4)
    return f"── {title} " + "─" * padding


def print_section(title: str):
    """Print a section header with surrounding blank lines."""
    print("")
    print(section_header(title))


def severity_icon(sev: Optional[int]) -> str:
    """Emoji for severity level."""
    return {1: "🔴", 2: "🟡", 3: "🟢", 4: "⚪"}.get(sev, "?")


# ── Output contracts ──────────────────────────────────────────────────
#
# These functions produce output that is PARSED by external scripts.
# Changing the format will break callers. Each contract documents
# which caller depends on it and how.
#

def health_verdict(criticals: int, warnings: int):
    """Print health verdict in the EXACT format callers expect.

    CONTRACT — session_briefing.template.sh:53 does:
        echo "$HEALTH_OUT" | tail -3 | head -2
    This extracts the last 3 lines, takes the first 2 of those.
    So the last 3 lines of health output MUST be:
        \\n  {emoji} {VERDICT} — {details}\\n\\n

    CONTRACT — session-start-check.template.sh:62 does:
        grep -qi "error|fail|corrupt"
    So healthy output must NOT contain those words.
    Critical/degraded output SHOULD contain them for detection.
    """
    print("")
    if criticals > 0:
        print(
            f"  🔴 CRITICAL — {criticals} critical, {warnings} warning(s). "
            f"Pipeline cannot proceed."
        )
        print(
            f"  Recovery: bash db_queries.sh restore "
            f"(or: git checkout -- project.db)"
        )
    elif warnings > 0:
        print(
            f"  🟡 DEGRADED — 0 critical, {warnings} warning(s). "
            f"Non-blocking, should address."
        )
    else:
        print("  🟢 HEALTHY — 0 critical, 0 warnings.")
    print("")


def task_done_message(task_id: str, date: str):
    """Print done confirmation.

    CONTRACT — test_bootstrap_suite.sh:1541 does:
        grep -q "Committed|DONE"
    So the output MUST contain the word "DONE".
    """
    print(f"✅ Marked DONE: {task_id} ({date})")


def commit_success_message(msg: str):
    """Print commit success.

    CONTRACT — test_bootstrap_suite.sh:1541 does:
        grep -q "Committed|DONE"
    So the output MUST contain the word "Committed".
    """
    print(f"  ✅ Committed: {msg}")


def quick_task_message(task_id: str, title: str):
    """Print quick task creation.

    CONTRACT — test_bootstrap_suite.sh:1527 does:
        grep -oE 'QK-[0-9a-f]+'
    So the output MUST contain the task ID in that regex format.
    """
    print(f"📥 {task_id}: {title}")


def quick_loopback_message(
    task_id: str, title: str, origin: str, severity: int, gate_critical: bool
):
    """Print loopback task creation.

    CONTRACT — test_bootstrap_suite.sh extracts ID via:
        grep -oE 'LB-[0-9a-f]+'
    """
    icon = severity_icon(severity)
    gc_text = "YES" if gate_critical else "no"
    print(f"{icon} LB {task_id}: {title}")
    print(
        f"   Origin: {origin} | Severity: S{severity} | "
        f"Gate-critical: {gc_text}"
    )


def error(msg: str):
    """Print error to stderr."""
    print(f"❌ {msg}", file=sys.stderr)


def warn(msg: str):
    """Print warning."""
    print(f"  ⚠️  {msg}")


# ── Evaluation output ────────────────────────────────────────────────
#
# NOT a wire protocol — no external scripts parse this output.
# Format may evolve freely.
#

def _score_indicator(score):
    """Return icon for a score value."""
    if score is None:
        return "—"
    if score >= 90:
        return "✅"
    if score > 0:
        return "⚠️"
    return "❌"


def eval_scorecard(
    project_name: str,
    version,
    phase,
    l1_score,
    l1_results: dict,
    l2_score,
    l2_results: dict,
    l3_score,
    l3_results: dict,
    composite,
    recommendations: list,
):
    """Print full evaluation scorecard with all layers."""
    from datetime import datetime

    date_str = datetime.now().strftime("%Y-%m-%d")
    version_str = f" · {version}" if version else ""
    phase_str = f" · {phase}" if phase else ""

    print(f"══ EVALUATION SCORECARD ════════════════════════════════════")
    print(f"   {project_name}{version_str} · {date_str}{phase_str}")
    print("")

    # Layer 1
    l1_str = f"{l1_score:.0f}/100" if l1_score is not None else "—"
    print(f"  DEPLOYMENT QUALITY      {l1_str}")
    for k in sorted(l1_results):
        r = l1_results[k]
        icon = _score_indicator(r.score)
        score_str = f"{r.score:.0f}" if r.score is not None else "—"
        print(f"    {r.id} {r.name:<25} {score_str:>4}  {icon} {r.details}")
    print("")

    # Layer 2
    l2_str = f"{l2_score:.0f}/100" if l2_score is not None else "—"
    print(f"  PROCESS HEALTH           {l2_str}")
    for k in sorted(l2_results):
        r = l2_results[k]
        icon = _score_indicator(r.score)
        score_str = f"{r.score:.0f}" if r.score is not None else "—"
        label = f"({r.details})" if r.score is None else r.details
        print(f"    {r.id} {r.name:<25} {score_str:>4}  {icon} {label}")
    print("")

    # Layer 3
    l3_str = f"{l3_score:.0f}/100" if l3_score is not None else "—"
    print(f"  IMPROVEMENT VELOCITY     {l3_str}")
    for k in sorted(l3_results):
        r = l3_results[k]
        icon = _score_indicator(r.score)
        score_str = f"{r.score:.0f}" if r.score is not None else "—"
        label = f"({r.details})" if r.score is None else r.details
        print(f"    {r.id} {r.name:<25} {score_str:>4}  {icon} {label}")

    print("")
    print(f"  ─────────────────────────────────────────────────────────")
    comp_str = f"{composite:.0f}/100" if composite is not None else "—"
    print(f"  COMPOSITE                {comp_str}")
    print(f"══════════════════════════════════════════════════════════════")

    # Recommendations
    if recommendations:
        print("")
        print(f"  RECOMMENDATIONS")
        for rec in recommendations:
            icon = {1: "🔴", 2: "🟡", 3: "🟢"}.get(rec.priority, "·")
            print(f"    {icon} [{rec.trigger}] {rec.message}")
            if rec.auto_task:
                print(f"       Fix: {rec.auto_task}")


def eval_comparison(eval1, eval2):
    """Print side-by-side comparison of two evaluations."""
    v1 = eval1["version"] or "—"
    v2 = eval2["version"] or "—"
    d1 = eval1["evaluated_at"][:10] if eval1["evaluated_at"] else "—"
    d2 = eval2["evaluated_at"][:10] if eval2["evaluated_at"] else "—"

    print(f"══ EVALUATION COMPARISON ═══════════════════════════════════")
    print(f"   {v1} ({d1})  →  {v2} ({d2})")
    print("")

    pairs = [
        ("DEPLOYMENT QUALITY", "artifact_score"),
        ("PROCESS HEALTH", "process_score"),
        ("IMPROVEMENT VELOCITY", "velocity_score"),
        ("COMPOSITE", "composite_score"),
    ]

    for label, field in pairs:
        s1 = eval1[field]
        s2 = eval2[field]
        s1_str = f"{s1:.0f}" if s1 is not None else "—"
        s2_str = f"{s2:.0f}" if s2 is not None else "—"

        if s1 is not None and s2 is not None:
            delta = s2 - s1
            delta_str = f"({delta:+.0f})"
            arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "─")
        elif s1 is None and s2 is not None:
            delta_str = "(new)"
            arrow = "★"
        else:
            delta_str = ""
            arrow = ""

        is_composite = field == "composite_score"
        if is_composite:
            print(f"  {'─' * 50}")
        print(
            f"  {label:<25} {s1_str:>4}  →  {s2_str:>4}   "
            f"{delta_str} {arrow}"
        )

    print(f"══════════════════════════════════════════════════════════════")
