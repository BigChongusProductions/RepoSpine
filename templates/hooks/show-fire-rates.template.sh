#!/bin/bash
# Analyze hook fire-rate data collected by lib-fire-counter.sh.
# Usage: bash .claude/hooks/show-fire-rates.sh [N]   # last N sessions (default 5)
#
# Output: per-hook fire counts grouped by session, plus "dead" list
# (hooks with zero fires across the observation window).

set -euo pipefail

LOG="$(dirname "${BASH_SOURCE[0]}")/.fire-counts.jsonl"
SESSIONS="${1:-5}"

if [ ! -f "$LOG" ]; then
    echo "No fire-count log yet: $LOG"
    echo "(Log is created on first hook invocation after lib-fire-counter.sh is sourced.)"
    exit 0
fi

python3 - "$LOG" "$SESSIONS" <<'PY'
import json, sys
from collections import defaultdict, OrderedDict
from pathlib import Path

log_path, sessions_n = sys.argv[1], int(sys.argv[2])

# Collect unique sessions by order of first appearance
session_order = OrderedDict()
per_session_hooks = defaultdict(lambda: defaultdict(int))
all_hooks = set()

with open(log_path) as f:
    for line in f:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        s = rec.get("session", "unknown")
        h = rec.get("hook", "unknown")
        session_order.setdefault(s, rec.get("ts", 0))
        per_session_hooks[s][h] += 1
        all_hooks.add(h)

# Keep last N sessions by first-seen order
recent_sessions = list(session_order.keys())[-sessions_n:]

print(f"=== Fire-rate analysis (last {len(recent_sessions)} session(s)) ===\n")

# Per-hook total
totals = defaultdict(int)
for s in recent_sessions:
    for h, c in per_session_hooks[s].items():
        totals[h] += c

print(f"{'Hook':35s} {'Total':>8s}  Per-session")
print("-" * 70)
for h in sorted(totals, key=lambda x: -totals[x]):
    per_s = " ".join(f"{per_session_hooks[s].get(h,0):>3d}" for s in recent_sessions)
    print(f"{h:35s} {totals[h]:>8d}  {per_s}")

# Dead hook list: hooks that have a lib-fire-counter.sh source line but never appear
hooks_dir = Path(log_path).parent
declared = {p.name for p in hooks_dir.glob("*.sh")
            if 'source "$(dirname "${BASH_SOURCE[0]}")/lib-fire-counter.sh"' in p.read_text()}
dead = declared - set(totals.keys())
if dead:
    print(f"\n=== Dead hooks ({len(dead)} zero-fire) ===")
    for h in sorted(dead):
        print(f"  {h}")
else:
    print(f"\n=== No dead hooks in this window ===")

print(f"\nSessions observed: {recent_sessions}")
PY
