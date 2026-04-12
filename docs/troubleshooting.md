# Troubleshooting

> Common problems, error messages, and fixes for the project-bootstrap workflow.
> For architecture context, see [how-it-works](how-it-works.md).

## Quick Diagnostics

### Health Check
Run `dbq health` to verify the state of the project database and its schema.
- **Checks:** Database connectivity, file integrity, and schema version consistency.
- **Interpreting Output:** A `PASS` indicates the DB is ready. A `FAIL` typically requires running `dbq health --init` to repair missing tables or `dbq health --backup` before manual recovery.

### Doctor Command
Run `dbq doctor` to audit the local environment and project scaffolding.
- **Checks:** Prerequisites (python3, sqlite3, git, npm), template availability, framework file presence, and platform-specific capabilities (e.g., macOS sandbox status).
- **Remediation:** Follow the "Action Required" section in the doctor report to install missing dependencies or restore deleted framework files.

### Drift Score
Run `dbq drift` to measure how much the project configuration has diverged from the base templates.
- **Metric:** Returns a score from 0 to 100.
- **Thresholds:** A score >= 80 is considered healthy. Scores below 80 trigger a `YELLOW` or `RED` session signal, indicating that core workflow files have been modified in ways that may break automated updates.
- **Fix:** Use `dbq drift --diff` to see specific divergences and revert unauthorized changes to framework files.

## Common Issues

### Bootstrap Fails
- **Missing Prerequisites:** Ensure `python3` and `sqlite3` are installed and in your PATH.
- **Template Path:** The bootstrapper must be run from the root of the project-bootstrap repository or provided with a valid `--template-dir`.
- **DB Init Errors:** Usually caused by permission issues in the target directory. Ensure you have write access to the project root.

### Hooks Not Firing
- **Wiring:** Check `.claude/settings.json` to ensure the hook event (e.g., `PreToolUse`) is correctly mapped to the script path.
- **Permissions:** Hook scripts must be executable. Run `chmod +x .claude/hooks/*.sh` to ensure all hooks can run.
- **Execution Policy:** If using a managed environment, ensure scripts are allowed to execute via the `run_shell_command` tool.

### Database Errors
- **Locked Database:** SQLite may throw "database is locked" if multiple Claude sessions or scripts attempt to write simultaneously. Close redundant sessions.
- **Missing Tables:** If `dbq` commands fail with "no such table," run `dbq health --init` to recreate the schema.
- **Corruption:** If the DB file is corrupted, restore from the latest backup in `.claude/backlogs/`.

### Permission Issues
- **Sandbox Restrictions:** Some hooks or scripts may be blocked by Claude's sandbox. Check `dbq doctor` for platform-specific notes.
- **Protected Files:** If an edit is blocked by `pre-edit-check`, ensure you have updated `AGENT_DELEGATION.md` or that you are not trying to modify a file listed in `protected-files.conf` without explicit instruction.

### Placeholder Residue
- **Unfilled Tokens:** If you see `%%PLACEHOLDER%%` in generated files, the `fill_placeholders.py` script failed or was skipped.
- **Fix:** Run `python3 templates/scripts/fill_placeholders.py --spec prerequisites.json` manually to re-run the replacement engine.

## Error Messages

| Error Message | Likely Cause | Fix |
| :--- | :--- | :--- |
| `database is locked` | Concurrent SQLite access | Close other Claude windows/terminals. |
| `command not found: dbq` | Missing alias or PATH | Use `./db_queries.sh` or add to shell profile. |
| `Hook 'pre-edit-check' failed` | Delegation/Protection gate | Approve delegation table or check `protected-files.conf`. |
| `Template directory not found` | Incorrect working directory | Run bootstrap from the tool's root directory. |
| `Permission denied` | Missing execution bit | Run `chmod +x .claude/hooks/*.sh`. |
| `Invalid JSON in settings.json` | Syntax error in config | Validate `.claude/settings.json` with a JSON linter. |

## Getting Help

If diagnostics do not resolve the issue:
1. Run `dbq doctor > doctor_report.txt`.
2. Run `dbq health >> doctor_report.txt`.
3. Open a GitHub Issue and attach `doctor_report.txt` along with the command that failed.

## See Also

- [Getting Started](getting-started.md) — First-time setup and bootstrap.
- [Workflow Guide](workflow.md) — Daily task management and phase gates.
- [How It Works](how-it-works.md) — Architectural deep-dive and component map.
- [Migration](migration.md) — Upgrading existing projects to the latest version.
- [Components](components.md) — Detailed inventory of scripts, hooks, and frameworks.
