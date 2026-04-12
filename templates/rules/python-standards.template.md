---
description: Python coding standards for %%PROJECT_NAME%%
paths:
  - "**/*.py"
---

# Python Standards — %%PROJECT_NAME%%

## Type Hints
- All function signatures must have type hints (parameters and return types)
- Use `typing` module for complex types (`Optional`, `Union`, `List`, `Dict`)
- Run mypy in strict mode — no `# type: ignore` without explanation

## Error Handling
- Use specific exception types — never bare `except:` or `except Exception:`
- Custom exceptions inherit from project-specific base exception class
- Log exceptions with traceback at the boundary, not at every level

## Async
- Use `asyncio` for I/O-bound concurrency
- Use `aiohttp`/`httpx` for async HTTP — not `requests` in async context
- Never mix sync and async database access in the same codebase

## Dependencies
- Use `pyproject.toml` (PEP 621) for dependency management
- Pin versions in lock file (Poetry: poetry.lock, pip: requirements.txt with hashes)
- Virtual environments required — never install to system Python

## Formatting
- Black for formatting (line length 88)
- Ruff for linting (replaces flake8, isort, and more)
- Import order: stdlib → third-party → local (enforced by ruff)

## Testing
- pytest for all tests — no unittest
- Fixtures over setup/teardown
- `conftest.py` for shared fixtures — keep test files focused

## SAST
- Run: `%%SAST_CONFIG%%`
- Block PRs on any HIGH or CRITICAL finding
