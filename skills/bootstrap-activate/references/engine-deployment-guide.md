# Engine Deployment Guide

Reference guide for deploying the full project infrastructure using the 7-step Phase D flow.

---

## Overview: 7-Step Flow

| Step | Type | What |
|------|------|------|
| 1 | Programmatic | Deploy database + scripts |
| 2 | LLM Reasoning | Generate RULES.md (29 sections) |
| 3 | LLM Reasoning | Generate CLAUDE.md (template match) |
| 4 | LLM Reasoning | Create tracking files (from specs) |
| 5 | Programmatic | Deploy hooks, agents, settings, init, git |
| 6 | Programmatic | Fill all 41 placeholder tokens |
| 7 | Programmatic | Verify deployment (18 checks) |

Steps 1, 5, 6, 7 are single-command — no manual file copying or placeholder tables required.
Steps 2, 3, 4 require LLM reasoning because they need spec reading and contextual judgment.

---

## Step 1: Deploy Database + Scripts

```bash
bash bootstrap_project.sh "$PROJECT_NAME" "$PROJECT_PATH" \
  --phase database,scripts \
  --lifecycle full \
  --non-interactive
```

**What gets deployed:**
- SQLite database with full schema + lifecycle seed data
- specs/ directory (from lifecycle mode)
- db_queries.sh (55-command CLI wrapper)
- session_briefing.sh, coherence_check.sh, coherence_registry.sh
- milestone_check.sh, build_summarizer.sh (stub — customize after this step)
- generate_board.py, work.sh, fix.sh
- test_protocol.sh, save_session.sh, shared_signal.sh, harvest.sh
- db_queries_legacy.sh (bash fallback)
- refs/ directory scaffolding

**Post-step verification:**
```bash
bash db_queries.sh health
bash db_queries.sh next
```

**Customize build_summarizer.sh immediately after Step 1.** The template deploys a stub that exits non-zero with "Stub" output. Replace with real build/test commands for the project's tech stack. See "Tech-Stack Build Commands" section below.

---

## Step 2: Generate RULES.md

LLM reasoning step — cannot be automated because 29 sections require contextual judgment.

**All 29 sections must be present.** Content placeholders (%%PROJECT_NORTH_STAR%%, %%TECH_STACK%%, %%COMMIT_FORMAT%%, %%BUILD_TEST_INSTRUCTIONS%%, etc.) require reading specs/ and prompting the user for values not derivable automatically.

Leave mechanical placeholders (%%PROJECT_NAME%%, %%PROJECT_PATH%%, %%PROJECT_DB%%, etc.) in place — Step 6 fills those.

**Verify:** `grep -c '%%' [PROJECT]_RULES.md` — should show only mechanical placeholders remaining.

---

## Step 3: Generate CLAUDE.md

LLM reasoning step — follow the template exactly.

Key constraint: **only 3 @-imports at startup** (`session-protocol.md`, `[PROJECT]_RULES.md`, `AGENT_DELEGATION.md`). All other frameworks load on demand via hooks. This reduces per-session startup tokens by ~73%.

See SKILL.md Step 3 for the exact CLAUDE.md template content.

---

## Step 4: Create Tracking Files

LLM reasoning step — requires reading specs for initial content.

| File | Source |
|------|--------|
| `LESSONS_[PROJECT].md` | Empty table skeleton |
| `LEARNING_LOG.md` | Empty table skeleton |
| `[PROJECT]_PROJECT_MEMORY.md` | §1-4 from specs (vision, architecture, file structure) |
| `AGENT_DELEGATION.md` | Already populated by Phase C — do not recreate |
| `NEXT_SESSION.md` | Bootstrap handoff: signal=GREEN, first task from DB |

---

## Step 5: Deploy Hooks, Agents, Settings, Init, Git

```bash
bash bootstrap_project.sh "$PROJECT_NAME" "$PROJECT_PATH" \
  --phase hooks,agents,settings,init,git \
  --lifecycle full \
  --non-interactive
```

**What gets deployed:**
- `.claude/hooks/` — all 11+ hook templates copied, chmod +x applied, protected-files.conf generated
- `.claude/agents/` — implementer + worker configs
- `.claude/settings.json` — hook wiring with 7+ event types
- `.claude/settings.local.json` — minimal local overrides
- `.claude/rules/` — database-safety + workflow-scripts (universal) + tech-stack-specific rule
- `.gitignore`
- Git init + dev branch

**Tech-stack-specific permission patterns** are written into settings.json during this step. The `--phase` command detects the tech stack from specs/ and fills `%%PERMISSION_ALLOW%%` automatically. The resulting patterns follow these conventions:

| Tech Stack | Permission Patterns Added |
|-----------|--------------------------|
| Swift | `Edit(*.swift)`, `Write(*.swift)`, `Bash(bash build_summarizer.sh *)` |
| Node.js | `Edit(*.ts)`, `Edit(*.tsx)`, `Write(*.ts)`, `Write(*.tsx)`, `Bash(npm *)`, `Bash(npx *)` |
| Python | `Edit(*.py)`, `Write(*.py)`, `Bash(python *)`, `Bash(poetry *)` |
| Rust | `Edit(*.rs)`, `Write(*.rs)`, `Bash(cargo *)` |
| Go | `Edit(*.go)`, `Write(*.go)`, `Bash(go *)` |

Always included (all stacks): `Bash(bash db_queries.sh *)`, `Bash(bash build_summarizer.sh *)`, `Bash(bash save_session.sh *)`, `Bash(bash session_briefing.sh *)`, `Bash(git status*)`, `Bash(git add *)`, `Bash(git commit *)`

Always denied: `Write(*.db)`, `Write(*.sqlite)`, `Write(*.sqlite3)`

---

## Step 6: Fill All Placeholders

```bash
python3 fill_placeholders.py "$PROJECT_PATH" \
  --project-name "$PROJECT_NAME" \
  --specs-dir "$PROJECT_PATH/specs" \
  --lifecycle full \
  --non-interactive \
  --json
```

Fills all 41 placeholder tokens in one pass:
- 12 auto-derivable tokens (from specs + tech detection)
- 4 user-provided tokens (defaults applied in non-interactive mode)
- 12 sed-style tokens (from project name/path)
- 12 script-specific tokens (from lifecycle + tech detection)
- 2 framework-specific tokens (from tech stack)
- 3 Xcode-conditional tokens (if applicable)

**Post-step check:**
```bash
grep -rn '%%' *.md *.sh .claude/ 2>/dev/null | grep -v '.git/' | grep -v 'node_modules/'
# Should return zero matches
```

---

## Step 7: Verify Deployment

```bash
python3 verify_deployment.py "$PROJECT_PATH"
```

Runs 18 checks covering: DB health, session briefing, scripts executable, tracking files, @-import chain, placeholder scan, Claude Code hooks (.claude/hooks/), framework files, refs/ scaffolding, build check, global lessons file, enforcement hooks, settings.json, custom agents, path rules, hook wiring, hardcoded reference scan.

**Exit codes:**
- Exit 0 → GREEN: All 17 pass. Bootstrap complete.
- Exit 2 → YELLOW: Warnings only. Bootstrap complete with caveats.
- Exit 1 → RED: Critical failures. Fix before proceeding.

---

## Tech-Stack Build Commands

Use these when customizing `build_summarizer.sh` in Step 1, and when creating git hooks content.

### Node.js/Next.js
- Build: `npm run build`
- Test: `npm test`
- Lint: `npm run lint`
- Pre-commit: `npm run lint && npx tsc --noEmit && npm test`
- Pre-push: `npm run build`

### Python (Poetry)
- Build: `poetry run mypy .`
- Test: `poetry run pytest`
- Lint: `poetry run black . && poetry run ruff check .`
- Pre-commit: `poetry run black . && poetry run ruff check . && poetry run mypy .`
- Pre-push: `poetry run pytest`

### Rust
- Build: `cargo build`
- Test: `cargo test`
- Lint: `cargo clippy -- -D warnings && cargo fmt --check`
- Pre-commit: `cargo clippy -- -D warnings && cargo fmt --check && cargo test`
- Pre-push: `cargo build --release`

### Swift
- Build: `xcodebuild build`
- Test: `xcodebuild test`
- Lint: `swiftlint`
- Pre-commit: `swiftlint && swift format --in-place . && xcodebuild test`
- Pre-push: `xcodebuild build -configuration Release`

### Go
- Build: `go build .`
- Test: `go test ./...`
- Lint: `go fmt ./... && go vet ./...`
- Pre-commit: `go fmt ./... && go vet ./... && go test ./...`
- Pre-push: `go build .`

---

## Troubleshooting

### Placeholder debugging

If Step 6 reports unresolved tokens or `grep` finds surviving `%%` patterns after Step 6:

```bash
python3 fill_placeholders.py "$PROJECT_PATH" --dry-run --json
```

The `--dry-run --json` output lists every token with its resolution status and source. Use this to identify which tokens are unresolved and why.

### Re-running specific verification checks

If Step 7 reports failures on specific checks:

```bash
# Re-run a single check (e.g., check C06 = placeholder scan)
python3 verify_deployment.py "$PROJECT_PATH" --check C06 --verbose

# Re-run all checks with verbose output
python3 verify_deployment.py "$PROJECT_PATH" --verbose
```

Check IDs are shown in the Step 7 JSON output (C01-C17).

### Re-deploying a single phase group

If hooks, agents, or settings need to be re-deployed (e.g., after editing a template):

```bash
# Re-deploy only hooks
bash bootstrap_project.sh "$PROJECT_NAME" "$PROJECT_PATH" --phase hooks --non-interactive

# Re-deploy only settings
bash bootstrap_project.sh "$PROJECT_NAME" "$PROJECT_PATH" --phase settings --non-interactive

# Re-deploy only agents
bash bootstrap_project.sh "$PROJECT_NAME" "$PROJECT_PATH" --phase agents --non-interactive
```

### Common failures

| Issue | Cause | Fix |
|-------|-------|-----|
| `command not found: db_queries.sh` | Script not executable | `chmod +x db_queries.sh` |
| Step 7 C11 fails (build_summarizer) | build_summarizer.sh still a stub | Customize build_summarizer.sh per tech stack |
| Step 7 C06 fails (placeholder scan) | fill_placeholders.py missed tokens | Run `fill_placeholders.py --dry-run --json` to identify unresolved tokens |
| Step 7 C13 fails (hook count < 11) | Hooks not deployed or not executable | `bash bootstrap_project.sh ... --phase hooks` |
| Step 7 C14 fails (settings.json) | settings.json missing or invalid JSON | `bash bootstrap_project.sh ... --phase settings` |
| `phase_ordinal: unrecognized phase` | Phase name in task doesn't match case statement | Update phase_ordinal() in db_queries.sh |
| Pre-commit hook fails silently | Hook not executable | `chmod +x .git/hooks/pre-commit && bash -x .git/hooks/pre-commit` to debug (note: standard git hooks are optional, not deployed by the engine) |
