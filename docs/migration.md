# Migration Guide

Upgrading between versions of project-bootstrap.
For version history, see [CHANGELOG](../CHANGELOG.md).

## Version Compatibility

The following environment is required for all versions of project-bootstrap:

| Component | Requirement | Note |
| :--- | :--- | :--- |
| **OS** | macOS 14+ | Optimized for Apple Silicon (M1-M4) |
| **Python** | 3.10+ | Required for `db_queries` and placeholder engines |
| **Bash** | 4.0+ | Required for framework hooks and automation |
| **SQLite** | 3.37+ | Required for project state tracking |
| **Tools** | `jq`, `git`, `sed` | Standard BSD/macOS versions supported |

## Upgrading

### From v0.x to v1.0

The v1.0 release introduces a **self-contained runtime**. Projects no longer rely on global templates in `~/.claude/`.

**Major Changes:**
- **Local Frameworks:** All 10 framework files are now deployed to `.claude/frameworks/` within the project.
- **Local Runtime:** The `dbq` engine and support scripts are contained within the project's `templates/scripts/` and `.claude/hooks/`.
- **Deployment Profiles:** Introduction of `standard` and `extended` profiles in `SYSTEMS_MANIFEST.json`.
- **Agent Templates:** 4 specialized agent tiers (Explorer, Implementer, Verifier, Worker) replace generic sub-agents.

**Step-by-Step Upgrade:**
1. **Backup:** Create a snapshot of your current project database using `db_queries.sh backup`.
2. **Re-bootstrap:** Run the v1.0 `bootstrap_project.sh` in your existing project root. Use `--phase scripts --phase hooks --phase rules` to refresh infrastructure.
3. **Verify Deployment:** Run `python3 templates/scripts/verify_deployment.py` to ensure all C01-C18 checks pass.
4. **Update CLAUDE.md:** Replace old inlined rules with the new `@-import` structure defined in `templates/rules/CLAUDE_TEMPLATE.md`.
5. **Session Refresh:** Start a new session to trigger the `session-start-check.sh` hook and re-preflight the environment.

### Between Minor Versions

Minor version upgrades typically refresh scripts and hooks without altering your project database schema.

1. Pull the latest `project-bootstrap` repository.
2. Execute `bootstrap_project.sh --phase scripts --phase hooks`.
3. Run `db_queries.sh health` to check for any required schema migrations (automatically handled by `init-db`).

## Breaking Changes

| Version | Change | Migration Action |
| :--- | :--- | :--- |
| **v1.0.0** | Self-contained runtime | Remove references to `~/.claude/` in `settings.json`. |
| **v0.14.0** | SAST Integration | Install `semgrep` and `gitleaks` to satisfy new quality gates. |
| **v0.13.0** | Prerequisite System | Run `preflight-check.sh --full` before bootstrapping. |
| **v0.11.0** | Delegation Enforcement | Approve delegation tables via `mark_delegation_approved.sh` before spawning agents. |
| **v0.9.2** | Context Routing | Update `CLAUDE.md` to use `@-import` for frameworks. |
| **v0.6.0** | Unified Engine | Remove `_lite` suffixes from scripts and settings. |

## Deprecations

| Feature | Replacement | Removal Version |
| :--- | :--- | :--- |
| Global `~/.claude/` templates | Project-local `.claude/` directory | v1.0.0 |
| `db_queries_lite` | Unified `db_queries.sh` | v0.6.0 |
| `RULES_TEMPLATE_LITE` | `RULES_TEMPLATE.md` with @imports | v0.6.0 |
| `delegation-reminder.sh` | `preflight-check.sh` | v0.13.0 |

---
**See Also:**
- [Workflow Guide](workflow.md)
- [Getting Started](getting-started.md)
- [Troubleshooting](troubleshooting.md)
