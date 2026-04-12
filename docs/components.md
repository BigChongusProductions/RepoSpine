# Components

All component counts and definitions are derived from `SYSTEMS_MANIFEST.json`.

## Overview

A bootstrapped project consists of 111 total systems across frameworks, hooks, scripts, and rules. These components work together to provide a governed, high-discipline development environment optimized for LLM-based engineering.

For details on how these components are applied, see [getting-started.md](getting-started.md) and [workflow.md](workflow.md).

## Frameworks

The system includes 10 core frameworks that define behavioral standards and automated governance.

| Name | Description |
| :--- | :--- |
| coherence-system.md | Registry-based stale reference detection for markdown files using pure shell. |
| correction-protocol.md | Mandatory hook-enforced gate that forces lesson logging before diagnosing or fixing any correction. |
| delegation.md | Six-tier model for assigning tasks to the right model tier with escalation and failure protocols. |
| development-discipline.md | TDD iron law and debugging discipline rules adapted from Superpowers plugin. |
| falsification.md | Scientific method for code: prove correctness by failing to disprove, not by hoping things work. |
| loopback-system.md | Parallel backward-fix track for handling defects discovered in earlier phases without blocking forward progress. |
| phase-gates.md | GO/CONFIRM/STOP verdict system for phase transitions and pre-task checks. |
| quality-gates.md | Automated code quality gates including lint, type check, SAST, and secrets scanning. |
| session-protocol.md | Mandatory session start orientation, model self-report gate, and lesson extraction protocol. |
| visual-verification.md | Playwright-based visual verification pipeline for tasks tagged needs_browser=1. |

## Behavioral Hooks

There are 19 behavioral hooks wired to specific lifecycle events in the Claude Code environment.

| Name | Event Type | Description |
| :--- | :--- | :--- |
| .semgrepignore.template | config | Semgrep ignore patterns to suppress false positives. |
| agent-spawn-gate.template.sh | PreToolUse | Blocks sub-agent spawns if delegation approval or pre-task check is stale. |
| check-pbxproj.template.sh | PostToolUse | Warns if a modified Swift file is missing from the Xcode project. |
| correction-detector.template.sh | UserPromptSubmit | Scans for correction signals and injects a hard gate reminder. |
| end-of-turn-check.template.sh | Stop | Checks for session hygiene issues after response completion. |
| escalation-tracker.template.sh | SubagentStop | Detects failures and increments per-tier counters for escalation. |
| framework-contamination-check.template.sh | PostToolUse | Prevents project-specific strings from entering generic framework files. |
| framework-contamination-patterns.template.conf | config | Configuration for project-specific patterns to exclude from frameworks. |
| generate-protected-files.template.sh | utility | Auto-generates protected-files.conf from project rules and infrastructure. |
| mark_delegation_approved.template.sh | utility | Resets delegation edit counter and records fresh approval timestamp. |
| permission-denied-tracker.template.sh | PermissionDenied | Increments failure counters when a sub-agent Bash call is denied. |
| post-compact-recovery.template.sh | PostCompact | Re-injects critical behavioral rules after context compaction. |
| pre-edit-check.template.sh | PreToolUse | Combined gate for Edit/Write calls and architecture file protection. |
| protect-databases.template.sh | PreToolUse | Denies sqlite3 write operations targeting external project databases. |
| protected-files.template.conf | config | List of architecture files requiring human confirmation to edit. |
| session-end-safety.template.sh | SessionEnd | Auto-saves session state if no manual save was performed. |
| session-start-check.template.sh | SessionStart | Runs full briefing and injects DB state at session start. |
| static-analysis-gate.template.sh | PostToolUse | Runs Semgrep on modified files and reports findings. |
| subagent-delegation-check.template.sh | SubagentStart | Verifies delegation approval before sub-agent execution. |

## Agent Definitions

The system defines 4 specialized agents for different task complexities.

| Name | Tier | Description |
| :--- | :--- | :--- |
| explorer.template.md | haiku | Read-only research and codebase exploration. |
| implementer.template.md | sonnet | Multi-file feature implementation and complex logic. |
| verifier.template.md | haiku | Post-implementation review and test validation. |
| worker.template.md | haiku | Single-file configuration and boilerplate tasks. |

## Deployment Checks

Deployment quality is verified via 18 checks (C01-C18) executed by `verify_deployment.py`.

| ID | Description |
| :--- | :--- |
| C01 | Runs db_queries.sh health and verifies success. |
| C02 | Verifies task queue accessibility. |
| C03 | Verifies session_briefing.sh execution. |
| C04 | Verifies coherence check detects no stale references. |
| C05 | Verifies all @-import references in CLAUDE.md resolve. |
| C06 | Scans for unfilled %%PLACEHOLDER%% tokens. |
| C07 | Verifies all hook commands in settings.json are wired. |
| C08 | Verifies all 10 framework files are present project-local. |
| C09 | Verifies presence of LESSONS, LEARNING_LOG, etc. |
| C10 | Verifies refs/ directory is scaffolded. |
| C11 | Verifies build_summarizer.sh build succeeds. |
| C12 | Verifies LESSONS_UNIVERSAL.md exists. |
| C13 | Verifies minimum executable hook scripts are deployed. |
| C14 | Verifies .claude/settings.json validity and wiring. |
| C15 | Verifies custom agent directories and templates. |
| C16 | Verifies .claude/rules/ directory is scaffolded. |
| C17 | Scans templates for hardcoded project-specific references. |
| C18 | Verifies drift detection score is >= 80. |

## Rule Templates

There are 12 rule templates covering project logic and language-specific standards.

| Name | Scope | Description |
| :--- | :--- | :--- |
| AGENT_DELEGATION_TEMPLATE.md | project | Tier model and task mapping protocol. |
| CLAUDE_TEMPLATE.md | project | Entry point with framework imports. |
| ROUTER_TEMPLATE.md | project | Context routing table for on-demand frameworks. |
| RULES_EXTENDED_TEMPLATE.md | project | Blocker detection and code standards. |
| RULES_TEMPLATE.md | project | Phase gates and tech stack configuration. |
| database-safety.template.md | language | Path-scoped rules for database access. |
| go-standards.template.md | language | Path-scoped Go coding standards. |
| node-standards.template.md | language | Path-scoped Node.js and TypeScript standards. |
| python-standards.template.md | language | Path-scoped Python coding standards. |
| rust-standards.template.md | language | Path-scoped Rust coding standards. |
| swift-standards.template.md | language | Path-scoped Swift coding standards. |
| workflow-scripts.template.md | workflow | Error handling for shell scripts and frameworks. |

## dbq Commands

The `dbq` CLI provides 15 modules for managing the project state and workflow.

| Module | Description |
| :--- | :--- |
| delegation.py | Task tier mapping and AGENT_DELEGATION.md synchronization. |
| doctor.py | Environment health, prerequisites, and platform capabilities. |
| drift.py | Unified coherence checking and drift scoring. |
| eval.py | Deployment quality and process health scoring. |
| falsification.py | Assumption tracking and scientific verification. |
| handover.py | Session continuity and handoff notes. |
| health.py | Database initialization, backup, and restoration. |
| knowledge.py | Lesson pipeline management and harvesting. |
| lint.py | Structural lint checks for configuration files. |
| loopbacks.py | Management of parallel backward-fix tracks. |
| next_cmd.py | Task queue with circuit breaker and loopback priority. |
| phases.py | Phase gate management and verdict system. |
| sessions.py | Session logging and decision tracking. |
| snapshots.py | Database state snapshotting and diffing. |
| tasks.py | Task lifecycle management and quick actions. |

## Workflow Scripts

Core scripts that manage the daily development lifecycle.

### Root Scripts
- `bootstrap_project.sh`: Main entry point for creating new projects.
- `db_queries.sh`: Dispatcher for all database and workflow commands.
- `session_briefing.sh`: Generates the status digest at session start.
- `save_session.sh`: Snapshots state for session handoff.
- `work.sh`: Launches the governed work environment.

### Template Scripts
- `build_summarizer.template.sh`: Wraps build, test, and SAST into a digest.
- `coherence_check.template.sh`: Scans for deprecated patterns.
- `milestone_check.template.sh`: Merge-readiness gate for main branch promotion.
- `pre-commit.template.sh`: Executes Gate 1 quality checks.
- `verify_deployment.py`: Orchestrates C01-C18 verification checks.

## Deployment Profiles

### Standard
The default profile includes all core frameworks, hooks, scripts, and rules required for a fully governed project environment.

### Extended
Adds advanced automation and scaffolding components beyond the standard profile for complex, multi-platform projects.

---
See also: [how-it-works.md](how-it-works.md), [migration.md](migration.md), [troubleshooting.md](troubleshooting.md)
