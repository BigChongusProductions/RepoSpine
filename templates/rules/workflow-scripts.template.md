---
description: Rules for shell scripts and framework docs — error handling, cascading changes
paths:
  - "*.sh"
  - "frameworks/*.md"
---

# Workflow Script Rules — %%PROJECT_NAME%%

## Error Handling
- Never silence errors with `2>/dev/null || true` on critical paths (DB inserts, state updates)
- Use `set -e` in scripts that must succeed end-to-end (build scripts, coherence checks)
- Use `set +e` only for scripts that are best-effort (session-end-safety.sh)
- If a command can legitimately fail, handle it explicitly with `if/then` — don't swallow it

## Infrastructure Cascades
Changes to these files cascade and require extra care:
- **db_queries.sh**: Schema changes affect DatabaseReader.swift and all view models
- **build scripts**: Build pipeline changes affect every task
- **coherence_check.sh / coherence_registry.sh**: Adding entries affects commit flow
- **session_briefing.sh / save_session.sh**: Affects session lifecycle

After modifying any infrastructure script, test it against the actual live state:
```bash
bash <script>.sh  # actually run it, don't just read it
```

## Framework Documents
- Frameworks in `frameworks/` are loaded on demand, not at startup
- Archived frameworks in `frameworks/archive/` are superseded by hooks/agents — don't reference them
- When editing a framework, check if a hook or agent now enforces that rule — if so, trim the prose

## Testing Scripts
- After editing a .sh file, run it once to verify it works
- For db_queries.sh subcommands, test with a real query: `bash db_queries.sh next`
- For build scripts: run the build command to verify
