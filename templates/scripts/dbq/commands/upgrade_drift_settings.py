"""
Three-way merge for .claude/settings.json on in-place v1.2 → v1.3 upgrade.

The v1.3 router consolidation collapses multiple PreToolUse/PostToolUse
entries into single-matcher dispatchers (pre-tool-gate.sh, post-tool-check.sh).
An in-place upgrade that naïvely copies the new template would clobber any
custom hooks a user added. A bare "preserve OURS" path would orphan the new
routers.

This module implements the BASE/OURS/THEIRS merge:

  BASE   — the v1.2 template the project was originally generated from,
           read from templates/settings/history/settings.template.json.v1.2.0
  OURS   — the project's current .claude/settings.json
  THEIRS — the v1.3 template at templates/settings/settings.template.json

Classification per hook event entry:
  inherited     — present in OURS, identical to a BASE entry → drop (superseded)
  user-added    — present in OURS, not in BASE                → preserve (appended after router)
  user-modified — matcher matches a BASE entry, command differs → conflict

Modes:
  --dry-run    (default)  print classification report, no file changes
  --apply                   write merged settings (requires no conflicts)
  --emit-patch              write merged file to .claude/settings.json.v1.3-proposed

A rollback path (rollback_settings) restores .claude/settings.json from the
.pre-v1.3 backup written by --apply. The backup has a 30-day TTL; session-end-safety
may clean it (not wired in v1.3 — left for follow-up).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ── Data model ─────────────────────────────────────────────────────────────

@dataclass
class HookEntry:
    """A single hook entry (one element of a per-event array in settings.json)."""
    event: str
    matcher: Optional[str]
    commands: List[str]         # retained for reporting/rendering
    hook_payload: Tuple[str, ...]   # canonicalized full hooks[] — used for identity
    raw: Dict[str, Any]         # preserved for round-tripping

    @classmethod
    def from_raw(cls, event: str, raw: Dict[str, Any]) -> "HookEntry":
        matcher = raw.get("matcher")
        hooks_list = raw.get("hooks", [])
        commands = [h.get("command", "") for h in hooks_list]
        # Canonicalize each hook as sort_keys JSON so ANY payload difference
        # (timeout, type, env, command, ordering) changes identity. Codex review
        # for v1.3 caught that command-only identity silently dropped user
        # timeout/type customizations during --apply.
        hook_payload = tuple(json.dumps(h, sort_keys=True) for h in hooks_list)
        return cls(
            event=event,
            matcher=matcher,
            commands=commands,
            hook_payload=hook_payload,
            raw=raw,
        )

    def signature(self) -> Tuple[Optional[str], Tuple[str, ...]]:
        """Uniqueness key: matcher + full canonical hook payloads."""
        return (self.matcher, self.hook_payload)


@dataclass
class Conflict:
    event: str
    base_entry: HookEntry
    ours_entry: HookEntry
    theirs_entry: Optional[HookEntry]
    reason: str


@dataclass
class MergeReport:
    base_version: str
    dropped: List[HookEntry] = field(default_factory=list)
    preserved: List[HookEntry] = field(default_factory=list)
    router_added: List[HookEntry] = field(default_factory=list)
    conflicts: List[Conflict] = field(default_factory=list)

    def has_conflicts(self) -> bool:
        return len(self.conflicts) > 0


# ── Loading ────────────────────────────────────────────────────────────────

def _load_json(path: Path) -> Dict[str, Any]:
    with path.open() as f:
        return json.load(f)


def _collect_entries(settings: Dict[str, Any]) -> Dict[str, List[HookEntry]]:
    """Turn settings.json's per-event arrays into {event: [HookEntry, ...]}."""
    hooks = settings.get("hooks", {})
    result: Dict[str, List[HookEntry]] = {}
    for event, entries in hooks.items():
        result[event] = [HookEntry.from_raw(event, e) for e in entries]
    return result


def detect_base_version(project_dir: Path) -> str:
    """Read .bootstrap_version or fall back to 1.2.0."""
    marker = project_dir / ".bootstrap_version"
    if marker.exists():
        return marker.read_text().strip() or "1.2.0"
    return "1.2.0"


def locate_base_template(bootstrap_root: Path, version: str) -> Path:
    """Historical template matching the user's bootstrap version."""
    path = bootstrap_root / "templates" / "settings" / "history" / f"settings.template.json.v{version}"
    if not path.exists():
        # Fall back to the earliest archived version; surface warning via caller
        path = bootstrap_root / "templates" / "settings" / "history" / "settings.template.json.v1.2.0"
    return path


# ── Classification + merge ────────────────────────────────────────────────

def _same_payload(a: HookEntry, b: HookEntry) -> bool:
    """Full ordered hook payload equality. Any timeout/type/env change → False."""
    return a.hook_payload == b.hook_payload


def _classify(ours_entry: HookEntry, base_entries: List[HookEntry]) -> str:
    """Stateless classification used by unit tests.

    Caveat: when OURS has multiple entries with the same matcher at the same
    event (one inherited, one user-added), this function alone can't tell them
    apart. The real merge logic in `merge_settings` handles that with
    per-event state; this helper is kept for unit-test readability of the
    three main outcomes.
    """
    # Exact (matcher, commands) match → inherited
    for b in base_entries:
        if ours_entry.signature() == b.signature():
            return "inherited"
    # Same matcher, different commands → user-modified.
    # None-matcher counts: Stop/UserPromptSubmit entries with None matcher
    # still align slot-wise if the event in base has exactly one entry.
    for b in base_entries:
        if b.matcher == ours_entry.matcher and not _same_payload(ours_entry, b):
            return "user-modified"
    return "user-added"


def merge_settings(
    base: Dict[str, Any],
    ours: Dict[str, Any],
    theirs: Dict[str, Any],
    base_version: str,
) -> Tuple[Dict[str, Any], MergeReport]:
    """Produce merged settings.json + a classification report.

    Algorithm:
    - Start with THEIRS (new router-based structure) as the skeleton
    - For each event in OURS, classify every entry against BASE
    - Drop inherited entries (the router covers them)
    - Append user-added entries AFTER the router entry for that event
    - Record user-modified entries as conflicts (do NOT auto-apply)
    - Preserve any top-level keys outside `hooks` (permissions, etc.) from OURS
      (permissions often have project-specific additions)
    """
    report = MergeReport(base_version=base_version)

    # Start with THEIRS hooks section
    merged_hooks: Dict[str, List[Dict[str, Any]]] = {}
    theirs_entries = _collect_entries(theirs)
    for event, entries in theirs_entries.items():
        merged_hooks[event] = [e.raw for e in entries]
        report.router_added.extend(entries)

    # Walk OURS and slot user additions / collect conflicts.
    # Per-event state: track which BASE entries have been "consumed" by an
    # OURS entry so a second OURS entry at the same matcher slot is classified
    # as user-added (additional hook), not user-modified (slot replacement).
    base_entries = _collect_entries(base)
    ours_entries = _collect_entries(ours)

    for event, entries in ours_entries.items():
        base_for_event = base_entries.get(event, [])
        base_consumed: List[bool] = [False] * len(base_for_event)

        for entry in entries:
            # 1. Exact match with an un-consumed base entry → inherited
            inherited_idx = None
            for idx, b in enumerate(base_for_event):
                if not base_consumed[idx] and entry.signature() == b.signature():
                    inherited_idx = idx
                    break
            if inherited_idx is not None:
                base_consumed[inherited_idx] = True
                report.dropped.append(entry)
                continue

            # 2. Same matcher, different commands, base slot not yet consumed
            #    → user-modified (conflict). Consume the base slot to prevent
            #    double-counting.
            modified_idx = None
            for idx, b in enumerate(base_for_event):
                if not base_consumed[idx] and b.matcher == entry.matcher \
                        and not _same_payload(entry, b):
                    modified_idx = idx
                    break
            if modified_idx is not None:
                base_consumed[modified_idx] = True
                theirs_match = next(
                    (t for t in theirs_entries.get(event, []) if t.matcher == entry.matcher),
                    None,
                )
                report.conflicts.append(Conflict(
                    event=event,
                    base_entry=base_for_event[modified_idx],
                    ours_entry=entry,
                    theirs_entry=theirs_match,
                    reason=f"{event} entry with matcher={entry.matcher or '(none)'} has custom command(s); template changed",
                ))
                continue

            # 3. No remaining base slot → user-added (append after router)
            if event not in merged_hooks:
                merged_hooks[event] = []
            merged_hooks[event].append(entry.raw)
            report.preserved.append(entry)

    merged_settings: Dict[str, Any] = dict(ours)  # carry permissions etc.
    merged_settings["hooks"] = merged_hooks

    return merged_settings, report


# ── Output ─────────────────────────────────────────────────────────────────

def render_report_markdown(report: MergeReport) -> str:
    lines: List[str] = [
        f"# Settings Migration Report",
        f"",
        f"Base version: v{report.base_version} → v1.3.0",
        f"",
        f"## Summary",
        f"",
        f"- Inherited entries dropped: {len(report.dropped)}",
        f"- User-added entries preserved: {len(report.preserved)}",
        f"- Router entries added: {len(report.router_added)}",
        f"- Conflicts (manual resolution required): {len(report.conflicts)}",
        f"",
    ]
    if report.preserved:
        lines.append("## Preserved (user-added, moved after router)")
        for e in report.preserved:
            lines.append(f"- `{e.event}` matcher=`{e.matcher}` commands={e.commands}")
        lines.append("")
    if report.conflicts:
        lines.append("## Conflicts (NOT merged — resolve manually)")
        for c in report.conflicts:
            lines.append(f"### {c.event} (matcher=`{c.ours_entry.matcher or 'none'}`)")
            lines.append(f"- Yours:    {c.ours_entry.commands}")
            if c.theirs_entry is not None:
                lines.append(f"- Template: {c.theirs_entry.commands}")
            lines.append(f"- Reason:   {c.reason}")
            lines.append("")
    return "\n".join(lines)


def render_conflicts_json(report: MergeReport) -> str:
    payload = [
        {
            "event": c.event,
            "matcher": c.ours_entry.matcher,
            "ours_commands": c.ours_entry.commands,
            "theirs_commands": c.theirs_entry.commands if c.theirs_entry else None,
            "reason": c.reason,
        }
        for c in report.conflicts
    ]
    return json.dumps(payload, indent=2)


# ── Command implementation ────────────────────────────────────────────────

def _write_atomic(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content)
    tmp.replace(path)


def run_upgrade_drift_settings(
    project_dir: Path,
    bootstrap_root: Path,
    mode: str = "dry-run",
) -> int:
    """Entry point. Returns exit code 0 on success, nonzero on conflict/error."""
    ours_path = project_dir / ".claude" / "settings.json"
    if not ours_path.exists():
        print(f"❌ No settings file at {ours_path}", file=sys.stderr)
        return 2

    base_version = detect_base_version(project_dir)
    base_path = locate_base_template(bootstrap_root, base_version)
    theirs_path = bootstrap_root / "templates" / "settings" / "settings.template.json"

    if not base_path.exists() or not theirs_path.exists():
        print(f"❌ Missing template(s): base={base_path} theirs={theirs_path}", file=sys.stderr)
        return 2

    base = _load_json(base_path)
    ours = _load_json(ours_path)
    theirs = _load_json(theirs_path)

    merged, report = merge_settings(base, ours, theirs, base_version)

    # Prepare merged directory under project
    merged_dir = project_dir / ".claude" / "merged"
    merged_dir.mkdir(parents=True, exist_ok=True)
    (merged_dir / "settings.json").write_text(json.dumps(merged, indent=2) + "\n")
    (merged_dir / "migration-report.md").write_text(render_report_markdown(report))
    (merged_dir / "conflicts.json").write_text(render_conflicts_json(report))

    # Console summary
    print(render_report_markdown(report))
    print(f"\nArtifacts written to: {merged_dir}")

    if mode == "dry-run":
        if report.has_conflicts():
            print("\n⚠️ Conflicts detected. Review merged/conflicts.json and rerun with --apply after resolution.")
            return 1
        print("\n✅ Clean merge. Run with --apply to write.")
        return 0

    if mode == "emit-patch":
        proposed = project_dir / ".claude" / "settings.json.v1.3-proposed"
        proposed.write_text(json.dumps(merged, indent=2) + "\n")
        print(f"\n📝 Proposed settings written to {proposed}")
        print("   Diff against current settings.json and apply manually when ready.")
        return 1 if report.has_conflicts() else 0

    if mode == "apply":
        if report.has_conflicts():
            print("\n❌ Refusing to --apply with conflicts. Resolve first or use --emit-patch.", file=sys.stderr)
            return 1
        # Backup settings + bootstrap_version together so rollback restores BOTH.
        backup = project_dir / ".claude" / "settings.json.pre-v1.3"
        version_backup = project_dir / ".bootstrap_version.pre-v1.3"
        shutil.copy2(ours_path, backup)
        version_backup.write_text(base_version + "\n")
        _write_atomic(ours_path, json.dumps(merged, indent=2) + "\n")
        # Bump bootstrap version marker
        (project_dir / ".bootstrap_version").write_text("1.3.0\n")
        print(f"\n✅ Applied. Backup at {backup}")
        print("   Rollback: dbq rollback-settings")
        return 0

    print(f"❌ Unknown mode: {mode}", file=sys.stderr)
    return 2


def run_rollback_settings(project_dir: Path) -> int:
    backup = project_dir / ".claude" / "settings.json.pre-v1.3"
    target = project_dir / ".claude" / "settings.json"
    if not backup.exists():
        print(f"❌ No backup at {backup} — nothing to rollback", file=sys.stderr)
        return 2
    shutil.copy2(backup, target)
    print(f"✅ Restored {target} from {backup.name}")
    # Also restore .bootstrap_version if a version backup is present. Without
    # this, an apply+rollback leaves the project advertising 1.3.0 while
    # settings.json is actually v1.2 contents — misleading future upgrade tools.
    version_backup = project_dir / ".bootstrap_version.pre-v1.3"
    version_target = project_dir / ".bootstrap_version"
    if version_backup.exists():
        shutil.copy2(version_backup, version_target)
        print(f"✅ Restored {version_target.name} from {version_backup.name}")
    return 0


# ── CLI glue (wired from cli.py) ──────────────────────────────────────────

def cmd_upgrade_drift_settings(args: argparse.Namespace) -> None:
    project_dir = Path(args.project_dir).resolve() if args.project_dir else Path.cwd()
    bootstrap_root = Path(args.bootstrap_root).resolve() if args.bootstrap_root else _default_bootstrap_root()
    mode = "dry-run"
    if args.apply:
        mode = "apply"
    elif args.emit_patch:
        mode = "emit-patch"
    raise SystemExit(run_upgrade_drift_settings(project_dir, bootstrap_root, mode))


def cmd_rollback_settings(args: argparse.Namespace) -> None:
    project_dir = Path(args.project_dir).resolve() if args.project_dir else Path.cwd()
    raise SystemExit(run_rollback_settings(project_dir))


def _default_bootstrap_root() -> Path:
    """Best-effort discovery: the installed plugin dir, else the working dir."""
    # Plugin install path used by Claude Code
    candidates = [
        Path.home() / ".claude" / "plugins" / "project-bootstrap",
        Path.cwd(),
    ]
    for c in candidates:
        if (c / "templates" / "settings" / "settings.template.json").exists():
            return c
    # Last resort — current working dir even if it fails the check. The
    # settings.template.json check inside run_* will surface a clear error.
    return Path.cwd()
