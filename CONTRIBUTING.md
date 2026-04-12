# Contributing to Project Bootstrap

Thank you for contributing to project-bootstrap. This guide explains how to set up, structure work, and validate changes.

## Getting Started

1. **Clone the repo:**
   ```bash
   git clone https://github.com/your-org/project-bootstrap.git
   cd project-bootstrap
   ```

2. **Verify prerequisites:**
   - Python 3.10+
   - SQLite 3
   - Bash 4.0+
   - jq

   Run the health check to confirm setup:
   ```bash
   bash db_queries.sh health
   ```

3. **Run tests to verify your environment:**
   ```bash
   bash tests/test_bootstrap_suite.sh --regression
   ```

## Project Structure

- **`templates/`** — The product: frameworks (10 reusable protocols), hooks, scripts, agents, rules, and settings that ship to bootstrapped projects.
- **`templates/scripts/dbq/`** — Python CLI for task and phase management via SQLite.
- **`.claude/`** — Meta-project configuration: hooks, agents, rules, and settings (specific to this repo's self-management).
- **`docs/internal/`** — Archived internal development documentation.
- **Root `.sh` files** — Meta-project management scripts (`db_queries.sh`, `session_briefing.sh`, etc.).
- **`tests/`** — Bootstrap test suite (Bash).
- **`backlog/`** — Development backlog and task import scripts.

See `META_PROJECT.md` for the dogfood model explanation.

## Development Workflow

Work is tracked in SQLite via `db_queries.sh`. A task flows through four phases:

1. **P1-DISCOVER** — Research, spec writing, and decision-making.
2. **P2-DESIGN** — Architecture and detailed design.
3. **P3-IMPLEMENT** — Code and feature implementation.
4. **P4-VALIDATE** — Testing and verification.

### Task Workflow

1. **Find next work:**
   ```bash
   bash db_queries.sh next
   ```

2. **Check task readiness before starting:**
   ```bash
   bash db_queries.sh check <task-id>
   ```
   Verdicts: GO (proceed), CONFIRM (approve milestone first), STOP (blocker exists).

3. **Work on the task** — Modify files in `templates/` or `.claude/` as assigned.

4. **Mark task complete:**
   ```bash
   bash db_queries.sh done <task-id>
   ```

### Quickly Capture Work

During development, capture bugs or follow-up items:

```bash
bash db_queries.sh quick "Fix placeholder in template" P1-DISCOVER template
```

This creates an INBOX task. Triage it later:

```bash
bash db_queries.sh triage QK-1234 P1-DISCOVER sonnet
```

## Testing

- **Health check** (quick validation):
  ```bash
  bash db_queries.sh health
  ```

- **Regression test** (before commit):
  ```bash
  bash tests/test_bootstrap_suite.sh --regression
  ```

- **Full test suite** (end-to-end):
  ```bash
  bash tests/test_bootstrap_suite.sh
  ```

- **Python CLI tests** (dbq changes):
  ```bash
  bash tests/test_bootstrap_suite.sh --python-cli
  ```

## Commit Conventions

Format: `category: description`

Examples:
- `fix: correct placeholder in session_briefing.sh`
- `feature: add loopback severity levels to dbq`
- `docs: expand delegation framework`

Commit after each completed task. Keep commits atomic where practical.

## Code Standards

- **Bash scripts:** Use `set -euo pipefail`, quote variables, avoid external paths.
- **Python (dbq):** Follow PEP 8. Unit tests required for new commands.
- **Markdown:** Match existing formatting. No TODOs in shipped content.

## Questions?

Read `BOOTSTRAP_RULES.md` for project-specific rules and `ROUTER.md` for on-demand reference files.
