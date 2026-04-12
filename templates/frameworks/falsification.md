---
framework: falsification
version: 1.0
extracted_from: production project (2026-03-17)
---

# Falsification Protocol

Scientific method for code: prove correctness by failing to disprove, not by hoping things work.

## Layer 1 — Assumption Registry (hard gate)

Before starting complex tasks, register and verify assumptions:

```bash
bash db_queries.sh assume <task-id> "assumption" ["verify command"]
bash db_queries.sh verify-all <task-id>
bash db_queries.sh assumptions <task-id>
```

Pre-task check blocks with `ASSUME` verdict if unverified assumptions exist.

> **Security note:** `verify_cmd` values stored in the assumptions table are executed
> as subprocesses via `shlex.split()`. Only store commands you trust. Review assumption
> commands before running `verify-all` — especially after bulk imports or DB restores.

## Layer 2 — Research Brief (soft gate)

Pre-task check warns for complex tasks where `researched=0`. Research means: read lesson recall, query docs for APIs, grep codebase for patterns, verify types.

```bash
bash db_queries.sh researched <task-id>
```

## Layer 3 — Automated Tests (every commit)

Maintain test files for:
- Store edge cases (nonexistent IDs, rapid state changes, mutual exclusivity)
- Lesson-derived invariants (SSR guards, no console.log, named exports)
- Data integrity (valid ranges, required fields)
- Domain-specific invariants

For TDD methodology and the test-first iron law:
→ `frameworks/development-discipline.md`

## Layer 4 — Deliberate Breakage (soft gate on completion)

After a feature works, break the most critical assumption → verify graceful failure → revert.

```bash
bash db_queries.sh break-tested <task-id>
bash db_queries.sh done <task-id> --skip-break  # bypass
```

## Intent ≠ Fact Rule

Any claim about system state (DB populated, tasks done, scripts working) MUST be backed by machine-readable verification. Never write a state claim based on intent.

**Prevention checklist:**
1. Did I run the command? (not just plan to)
2. Did it return a verifiable result? (not empty string)
3. Is the result what I expected? (checked explicitly)
4. Am I writing the claim AFTER verification? (not before)

## Changelog
- 1.2: Added verify_cmd security note in Layer 1 (discovered via cross-project audit)
- 1.1: Added TDD cross-reference to development-discipline.md in Layer 3
- 1.0: Initial extraction from production project
