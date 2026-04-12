# Workflow Guide

This guide describes day-to-day usage patterns after bootstrapping a project. For initial setup, see [getting-started](getting-started.md).

## After Bootstrap

### First Session
After running `bootstrap_project.sh`, your first session begins by executing `./work.sh`. This script initializes the environment and launches the specialized Claude session.

The first action in any session is reading the `NEXT_SESSION.md` file and running the session briefing.

```bash
cat NEXT_SESSION.md
bash session_briefing.sh
```

### Understanding the Signal (GREEN/YELLOW/RED)
The `session_briefing.sh` script computes a status signal that determines if it is safe to proceed with the next task.

*   **GREEN**: All clear. Prior phases are gated, and no high-level blockers exist.
*   **YELLOW**: Advisory warning. There may be same-phase blockers or unresolved non-critical decisions. Recommend caution.
*   **RED**: Hard stop. A prior phase is ungated, a cross-phase blocker is active, or a Master/Gemini task is required before proceeding.

## Task Management

The system uses a SQLite-backed task engine accessed via `db_queries.sh` (aliased as `dbq` in many environments).

### Adding Tasks
Tasks can be added to the inbox or directly to a phase.

```bash
# Quick add to inbox
bash db_queries.sh quick "Implement login validation logic"

# Add detailed task to a specific phase
bash db_queries.sh add-task "T-001" "P02-CORE" "Feature Name" "sonnet"
```

### Working Through Tasks
The workflow follows a strict Check-Act-Done cycle.

1.  **Identify next task**: `bash db_queries.sh next`
2.  **Pre-task check**: `bash db_queries.sh check <task-id>`
    *   **GO**: Proceed with the task.
    *   **CONFIRM**: A milestone (e.g., first task in phase). Present progress to Master and wait for approval before running `bash db_queries.sh confirm <task-id>`.
    *   **STOP**: Hard blocker detected. Resolve the blocker or prior phase gate first.
3.  **Mark complete**: `bash db_queries.sh done <task-id>`

### Phase Gates
When all Claude tasks in a phase are complete, a phase gate review is required.

1.  **Audit**: Review completed tasks against the phase spec.
2.  **Categorize**: Identify "Must-fix" vs "Follow-up" items.
3.  **Pass Gate**: Run `bash db_queries.sh gate-pass <PHASE_NAME>` to unlock the next phase.

## Customization

The system is designed to be extended through hooks, rules, and frameworks.

### Adding Hooks
Hooks are executable scripts in `.claude/hooks/` wired to events in `.claude/settings.json`.
*   **Events**: `PreToolUse`, `PostToolUse`, `SessionStart`, `SessionEnd`, `UserPromptSubmit`.
*   **Wiring**: Add the script path to the corresponding event array in `settings.json`.

### Modifying Rules
Rules are injected into the context based on path or task type.
*   **Global Rules**: Found in the `RULES` file in the root.
*   **Path Rules**: Add `.md` files to `.claude/rules/` to apply specific standards to directories (e.g., `python-standards.md` for `.py` files).

### Adding Frameworks
Frameworks are reusable protocol documents in `.claude/frameworks/`. They are imported into `CLAUDE.md` or referenced by the `ROUTER.md` to provide high-level guidance for specific workflows like TDD, visual verification, or delegation.

## Multi-Agent Workflow

Complex tasks are delegated to specialized sub-agents to preserve the orchestrator's context window.

### Delegation Tiers
The system uses a 4-tier model to match task complexity to the most cost-effective model:

| Tier | Model | Usage |
| :--- | :--- | :--- |
| **Opus** | `claude-opus-4-6` | Architecture, orchestration, gate reviews, complex debugging. |
| **Sonnet** | `claude-sonnet-4-6` | Feature implementation, multi-file reasoning, cross-file changes. |
| **Haiku** | `claude-haiku-4-5` | Single-file edits, config updates, docs, boilerplate. |
| **Master** | Human | Phase gates, version bumps, sign-off, cross-project validation. |

### Sub-Agent Patterns
Before spawning an agent, the orchestrator must produce a delegation table:

```markdown
| Task ID | Title | Tier | Why |
| :--- | :--- | :--- | :--- |
| T-01 | Add Button Component | Haiku | Single file, pure display. |
| T-02 | Integrate API Store | Sonnet | Multi-file, state management. |
```

**Escalation**: If a sub-agent fails twice at a lower tier (e.g., Haiku), it is escalated to the next tier (e.g., Sonnet).

## Session Protocol

### Starting a Session
1.  **Read State**: Check `NEXT_SESSION.md`.
2.  **Run Briefing**: Execute `bash session_briefing.sh`.
3.  **Self-Report**: State your model tier and the current session signal.
4.  **Wait for Go**: Present the recommended task and wait for Master confirmation.

### Ending a Session
1.  **Lesson Extraction**: Scan the session for corrections or new insights.
2.  **Save State**: Run `bash save_session.sh`. This updates `NEXT_SESSION.md` and snapshots the database.
3.  **Handoff**: Ensure `NEXT_SESSION.md` clearly states what was done and what the very next step is.

### Handoffs
Handoffs occur between sessions or when switching models. The `NEXT_SESSION.md` acts as the source of truth for the transition, containing active overrides, current task ID, and pending blockers.
