# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.16.x  | Yes       |
| < 0.16  | No        |

## Reporting a Vulnerability

Do **not** open a public GitHub issue for security vulnerabilities. Instead, email your report to:

**security@example.com**

Please include:
- Description of the vulnerability
- Steps to reproduce (if applicable)
- Affected component(s) and version(s)

We will acknowledge receipt within 48 hours and provide updates as we work on a fix.

## Security Considerations

This toolkit bootstraps development workflows and executes shell scripts and Python code. Be aware of the following:

- **Script Execution** — The bootstrapper executes shell scripts and Python code. Only run this tool on trusted source repositories.
- **Template Injection** — The `fill_placeholders.py` script performs string substitution on templates. User-provided input flows through placeholders and should be validated before bootstrapping.
- **Hook Scripts** — Hooks in `.claude/hooks/` execute shell commands during workflows. Review hook scripts before installing or executing them.
- **SQLite Databases** — Project databases are stored locally with no network exposure or external connectivity.
- **Static Analysis** — Semgrep SAST scanning is integrated for automated code quality checks.

## Scope

Security fixes are prioritized for:

- Template injection vulnerabilities in placeholder substitution
- Command injection in hook scripts or utility scripts
- Path traversal in `bootstrap_project.sh` or file operations
- Security-relevant issues in `templates/` that could be exploited when deployed

Non-security improvements (feature requests, documentation, styling) should be submitted as regular GitHub issues.
