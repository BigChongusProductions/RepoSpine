"""
Session & decision commands: sessions, log, decisions, tag-session,
session-tags, session-file.

Display-only except `log` (DB insert) and `tag-session` (git tag).
"""
import subprocess
import sys
from datetime import datetime

from ..db import Database
from ..config import ProjectConfig
from .. import output


def _format_date() -> str:
    """Format date as 'Mon DD' matching bash."""
    now = datetime.now()
    return now.strftime("%b ") + str(now.day)


# ── sessions command ─────────────────────────────────────────────────

def cmd_sessions(db: Database):
    """List all logged sessions.

    Matches db_queries_legacy.template.sh lines 1187-1196.
    """
    output.print_section("Session log")

    rows = db.fetch_all(
        "SELECT logged_at AS date, session_type AS type, summary "
        "FROM sessions "
        "ORDER BY id DESC"
    )

    if not rows:
        print("  No sessions logged yet.")
        print("")
        return

    print(f"  {'date':<20} {'type':<16} summary")
    for r in rows:
        print(f"  {r['date']:<20} {r['type']:<16} {r['summary'] or ''}")
    print("")


# ── log command ──────────────────────────────────────────────────────

def cmd_log(db: Database, session_type: str, summary: str):
    """Log a session.

    Matches db_queries_legacy.template.sh lines 1198-1208.
    """
    db.execute(
        "INSERT INTO sessions (session_type, summary) VALUES (?, ?)",
        (session_type, summary),
    )
    db.commit()

    today = _format_date()
    print(f"✅ Session logged: {today} [{session_type}]")


# ── decisions command ────────────────────────────────────────────────

def cmd_decisions(db: Database):
    """List recent decisions.

    Matches db_queries_legacy.template.sh lines 1175-1185.
    """
    output.print_section("Decision log")

    rows = db.fetch_all(
        "SELECT decided_at AS date, "
        "COALESCE(choice, '') AS made_by, "
        "description AS decision "
        "FROM decisions "
        "ORDER BY id DESC "
        "LIMIT 15"
    )

    if not rows:
        print("  No decisions logged yet.")
        print("")
        return

    print(f"  {'date':<20} {'made_by':<12} decision")
    for r in rows:
        print(f"  {r['date']:<20} {r['made_by']:<12} {r['decision']}")
    print("")


# ── tag-session command ─────────────────────────────────────────────

def cmd_tag_session(config: ProjectConfig):
    """Create a git tag for the current session.

    Matches db_queries_legacy.template.sh lines 2103-2108.
    """
    git_dir = str(config.project_dir)

    # Count existing session tags
    result = subprocess.run(
        ["git", "-C", git_dir, "tag", "-l", "session/*"],
        capture_output=True, text=True, timeout=5,
    )
    existing = [t for t in result.stdout.strip().splitlines() if t]
    session_num = len(existing) + 1

    today = datetime.now().strftime("%Y-%m-%d")
    tag_name = f"session/{today}/{session_num}"

    result = subprocess.run(
        ["git", "-C", git_dir, "tag", tag_name, "HEAD"],
        capture_output=True, text=True, timeout=5,
    )
    if result.returncode != 0:
        print(f"❌ Failed to create tag: {result.stderr.strip()}")
        sys.exit(1)

    print(f"✅ Tagged: {tag_name}")


# ── session-tags command ────────────────────────────────────────────

def cmd_session_tags(config: ProjectConfig):
    """List session git tags with commit info.

    Matches db_queries_legacy.template.sh lines 2110-2123.
    """
    git_dir = str(config.project_dir)

    output.print_section("Session Tags")

    result = subprocess.run(
        ["git", "-C", git_dir, "tag", "-l", "session/*", "--sort=-creatordate"],
        capture_output=True, text=True, timeout=5,
    )
    tags = [t for t in result.stdout.strip().splitlines() if t]

    if not tags:
        print("  No session tags yet.")
        print("")
        return

    for tag in tags:
        # Get commit date and short sha
        date_result = subprocess.run(
            ["git", "-C", git_dir, "log", "-1", "--format=%ai", tag],
            capture_output=True, text=True, timeout=5,
        )
        date_str = " ".join(date_result.stdout.strip().split()[:2]) if date_result.returncode == 0 else "?"

        sha_result = subprocess.run(
            ["git", "-C", git_dir, "rev-parse", "--short", tag],
            capture_output=True, text=True, timeout=5,
        )
        sha = sha_result.stdout.strip() if sha_result.returncode == 0 else "?"

        print(f"  {tag}  ({sha}, {date_str})")
    print("")


# ── session-file command ────────────────────────────────────────────

def cmd_session_file(config: ProjectConfig, session_num: str, file_path: str):
    """Show a file at a specific session tag.

    Matches db_queries_legacy.template.sh lines 2126-2141.
    """
    git_dir = str(config.project_dir)

    # Find tag matching session number
    result = subprocess.run(
        ["git", "-C", git_dir, "tag", "-l", f"session/*/{session_num}"],
        capture_output=True, text=True, timeout=5,
    )
    tags = [t for t in result.stdout.strip().splitlines() if t]

    if not tags:
        print(f"❌ No tag found for session {session_num}")
        print("Available tags:")
        all_result = subprocess.run(
            ["git", "-C", git_dir, "tag", "-l", "session/*"],
            capture_output=True, text=True, timeout=5,
        )
        if all_result.stdout.strip():
            print(all_result.stdout.strip())
        sys.exit(1)

    tag = tags[0]
    print(f"── {file_path} at {tag} ──")

    show_result = subprocess.run(
        ["git", "-C", git_dir, "show", f"{tag}:{file_path}"],
        capture_output=True, text=True, timeout=10,
    )
    if show_result.returncode != 0:
        print(f"❌ {file_path} not found at {tag}")
    else:
        print(show_result.stdout)
