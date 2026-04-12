---
framework: coherence-system
version: 1.0
extracted_from: production project (2026-03-17)
---

# Coherence System Framework

Registry-based stale reference detection for markdown files. Zero tokens — pure shell.

## How It Works

`coherence_check.sh` scans all markdown files for deprecated patterns defined in `coherence_registry.sh`. Runs automatically on every git commit (pre-commit hook) as a soft warning.

## Architecture

**coherence_registry.sh** — Array of deprecated patterns with canonical replacements:
```bash
DEPRECATED_PATTERNS+=("exact deprecated string")
CANONICAL_LABELS+=("what it should say instead")
INTRODUCED_ON+=("date")
```

**coherence_check.sh** — Scanner that greps markdown files against the registry:
- `--quiet` mode: exit code only (for hooks)
- `--fix` mode: shows replacement hints

## When to Add Entries

When architecture changes (new system, renamed concept, migrated tool):
1. Make your changes to the relevant files
2. Add ONE entry to `coherence_registry.sh`
3. Run `coherence_check.sh --fix` to confirm old phrase is gone
4. Commit together

## Integration Points

| Trigger | Mode |
|---------|------|
| `git commit` | `--quiet` (warn, don't block) |
| Manual after core edits | `--fix` (show hints) |
| Milestone check | Full scan |

## Changelog
- 1.0: Initial extraction from production project
