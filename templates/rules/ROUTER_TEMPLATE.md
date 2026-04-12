# Context Router — Reference
> This table lists on-demand context files. You don't need to memorize this.
> Hooks will remind you when to load these. Consult this table if unsure.

## On-Demand Frameworks

| Framework | File | Loaded By |
|-----------|------|-----------|
| Correction protocol | `frameworks/correction-protocol.md` | Hook: correction-detector.sh |
| Delegation rules | `frameworks/delegation.md` | Hook: pre-edit-check.sh (delegation gate) |
| Loopback system | `frameworks/loopback-system.md` | Hook: session-start (when loopbacks exist) |
| Phase gates | `frameworks/phase-gates.md` | Manual: before pre-task check |
| Coherence system | `frameworks/coherence-system.md` | Manual: coherence audits |
| Falsification | `frameworks/falsification.md` | Manual: assumption testing |
| Quality gates | `frameworks/quality-gates.md` | Manual: pre-gate quality audit |
| Development discipline | `frameworks/development-discipline.md` | Manual: code changes, bugfixes, or when prompted by `db_queries.sh check` |

## On-Demand Project Context

| Context | Source | When |
|---------|--------|------|
| Active delegation map | `bash db_queries.sh delegation-md --active-only` | Before assigning tasks |
| Extended rules | `refs/rules-extended.md` | Blocker detection, merge gate, code standards |
| Architecture context | `%%PROJECT_MEMORY_FILE%%` | Architectural questions |
| Recent lessons | `%%LESSONS_FILE%%` (tail -50) | Before similar work |
