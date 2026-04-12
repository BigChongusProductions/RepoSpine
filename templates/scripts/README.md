# Project Bootstrap Script Templates

This directory contains templatized scripts for the bootstrap engine. Each script has been parameterized with `%%PLACEHOLDER%%` tokens to enable reuse across different projects.

## Files Included

### Core Task Management
- **db_queries.template.sh** — Thin Python CLI dispatcher for all db_queries commands
  - Delegates to the `dbq` Python package (Python 3.10+ required)
  - Placeholders: `%%PROJECT_DB%%`, `%%PROJECT_NAME%%`, `%%LESSONS_FILE%%`, `%%PHASES%%`

- **session_briefing.template.sh** (427 lines) — Compact session status digest at startup
  - Shows phase status, next tasks, blockers, git state, file health, coherence
  - Placeholders: `%%PROJECT_DB%%`, `%%PROJECT_NAME%%`, `%%LESSONS_FILE%%`, `%%PROJECT_MEMORY_FILE%%`, `%%RULES_FILE%%`

### Quality Gates
- **milestone_check.template.sh** (168 lines) — Merge-readiness gate for dev→main
  - Checks: task completion, git branch, working tree, coherence, build + tests
  - Placeholders: `%%PROJECT_DB%%`

- **coherence_check.template.sh** (98 lines) — Scan markdown files for stale references
  - Runs: --quiet (warnings only) or --fix (replacement hints)
  - Placeholders: `%%LESSONS_FILE%%`

- **coherence_registry.template.sh** (36 lines) — Define deprecated pattern mappings
  - Three parallel arrays: DEPRECATED_PATTERNS, CANONICAL_LABELS, INTRODUCED_ON
  - No placeholders required (project-specific entries added after setup)

### Build & Deploy
- **build_summarizer.template.sh** (20 lines) — Stub for project-specific build system
  - Examples provided for Next.js, Xcode, Python pytest
  - No placeholders (customize for your project)

### Workflow Launchers
- **work.template.sh** (69 lines) — Launch Claude Code in work mode
  - Checks DB health, git state, session signal before launching
  - Placeholders: `%%PROJECT_PATH%%`, `%%PROJECT_DB%%`, `%%PROJECT_NAME%%`

- **fix.template.sh** (39 lines) — Launch Claude Code in fix mode
  - Optional initial prompt parameter: `bash fix.sh "Fix this issue: ..."`
  - Placeholders: `%%PROJECT_PATH%%`, `%%PROJECT_NAME%%`

- **harvest.template.sh** (61 lines) — Scan project lessons for promotion candidates
  - Identifies unpromoted patterns in %%LESSONS_FILE%% not yet in LESSONS_UNIVERSAL.md
  - Placeholders: `%%LESSONS_FILE%%`

## Placeholder Reference

| Placeholder | Meaning | Example |
|---|---|---|
| `%%PROJECT_DB%%` | SQLite database filename | `my_project.db` |
| `%%PROJECT_DB_NAME%%` | DB name without extension | `my_project` |
| `%%PROJECT_NAME%%` | Human-readable project name | `My Project` |
| `%%PROJECT_PATH%%` | Absolute path to project root | `/Users/user/Desktop/MyProject` |
| `%%LESSONS_FILE%%` | Project lessons markdown file | `LESSONS_MYPROJECT.md` |
| `%%PROJECT_MEMORY_FILE%%` | Project memory markdown file | `MY_PROJECT_PROJECT_MEMORY.md` |
| `%%RULES_FILE%%` | Project rules markdown file | `MY_PROJECT_RULES.md` |

## Setup Instructions

1. **Copy templates to your project:**
   ```bash
   cp ~/.claude/dev-framework/templates/scripts/*.template.sh /path/to/project/
   ```

2. **For each template, apply placeholders using sed:**
   ```bash
   sed \
     -e 's/%%PROJECT_DB%%/my_project.db/g' \
     -e 's/%%PROJECT_NAME%%/My Project/g' \
     -e 's|%%PROJECT_PATH%%|/Users/user/Desktop/MyProject|g' \
     -e 's/%%LESSONS_FILE%%/LESSONS_MYPROJECT.md/g' \
     -e 's/%%PROJECT_MEMORY_FILE%%/MY_PROJECT_MEMORY.md/g' \
     -e 's/%%RULES_FILE%%/MY_PROJECT_RULES.md/g' \
     db_queries.template.sh > db_queries.sh
   ```

3. **Make scripts executable:**
   ```bash
   chmod +x *.sh
   ```

4. **Customize build_summarizer.sh** for your build system (Next.js, iOS, Python, etc.)

## Notes

- **AGENT_DELEGATION.md** remains as-is across projects (not templatized)
- **build_summarizer.sh** is a stub template — customize for your specific build system
- Phase names in **db_queries.sh** are set via the `%%PHASES%%` placeholder (space-separated list); the dbq Python CLI computes ordinals dynamically
- All templates include inline documentation in header comments

## Version History

- Origin: Extracted and generalized (March 2026)
- All replacements applied via: sed with %%PLACEHOLDER%% tokens or fill_placeholders.py
- db_queries_legacy.template.sh removed in v1.0 (legacy bash fallback superseded by dbq Python CLI)
