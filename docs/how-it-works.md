# How It Works

This document provides a deep dive into the architecture, internals, and design decisions of the project-bootstrap system. For usage patterns, see [workflow](workflow.md). For a machine-readable inventory of components, see [components](components.md).

## Overview

Project-bootstrap follows a two-phase model designed to transform a high-level idea into a fully operational development environment. It prioritizes behavioral enforcement through hooks, progressive disclosure of context via a router system, and a multi-tier agent model to ensure high-quality, consistent output across different model capabilities. The system deploys 111 integrated components including frameworks, enforcement hooks, and specialized scripts.

## Bootstrap Pipeline

### Phase 1: Discovery

Discovery is a collaborative process between the user and the Cowork agent. Triggered by the `/new-project` command, this phase involves a structured interview where the agent researches feasibility, evaluates technology stacks, and proposes an architecture. This phase concludes with the generation of four foundational specification files:
*   **VISION**: High-level goals and project scope.
*   **RESEARCH**: Technical feasibility and competitive analysis.
*   **BLUEPRINT**: Architectural design and component mapping.
*   **INFRASTRUCTURE**: Deployment and environment requirements.

### Phase 2: Engine Deployment

Engine deployment occurs within Claude Code via the `/activate-engine` command. The deployment engine executes the following sequence:
1.  **Spec Analysis**: Reads the generated specifications to understand requirements.
2.  **Scaffolding**: Generates detailed requirements and design documents with built-in review cycles.
3.  **Task Population**: Breaks the design into phased tasks and populates a project-local SQLite database.
4.  **Engine Deployment**: Deploys the full workflow engine, including 111 components such as workflow scripts, CLAUDE.md, behavioral hooks, and custom agents.
5.  **Verification**: Executes the `verify_deployment.py` pipeline to run 18 critical health checks.

## Architecture

### Template System

The system uses a canonical template directory (`templates/`) as the single source of truth. These templates are project-agnostic and are customized during deployment.
*   **scripts/**: Workflow scripts and the Python-based `dbq` CLI.
*   **frameworks/**: 10 behavioral protocol files.
*   **rules/**: Project-specific and language-specific standard templates.
*   **hooks/**: Behavioral enforcement scripts for Claude Code events.
*   **agents/**: Multi-tier sub-agent definitions.
*   **settings/**: Claude Code configuration templates.

### Placeholder Engine

The `fill_placeholders.py` script is the core of the customization engine. It uses a 41-token registry defined in `fp_registry.py` to derive project-specific values. The engine utilizes regular expressions for substitution and supports a dry-run mode to validate replacements before writing to disk. Derivations are handled by `fp_engine.py`, which performs technology detection and spec analysis to populate tokens like `%%PROJECT_NAME%%` and `%%TECH_STACK%%`.

### Verification Pipeline

The `verify_deployment.py` script ensures the integrity of the deployed engine by running 18 automated checks (C01–C18).

| ID | Check | Description |
|---|---|---|
| C01 | DB Health | Verifies `db_queries.sh` can access and query the SQLite database. |
| C02 | Task Queue | Ensures the task queue is initialized and readable. |
| C03 | Session Briefing | Validates the session start digest script. |
| C04 | Coherence Check | Runs the coherence system to detect stale markdown references. |
| C05 | Import Chain | Verifies all @-imports in CLAUDE.md resolve to valid files. |
| C06 | Placeholder Scan | Scans for any unfilled %%PLACEHOLDER%% tokens. |
| C07 | Hook Wiring | Verifies hook commands in settings.json resolve to executable scripts. |
| C08 | Framework Files | Confirms all 10 framework files are deployed. |
| C09 | Tracking Files | Checks for LESSONS, PROJECT_MEMORY, and AGENT_DELEGATION files. |
| C10 | Refs Directory | Validates the existence of the progressive disclosure directory. |
| C11 | Build Command | Executes the build summarizer to verify environment readiness. |
| C12 | Global Lessons | Ensures a path to the cross-project LESSONS_UNIVERSAL.md is valid. |
| C13 | Enforcement Hooks | Confirms minimum core enforcement hooks are executable. |
| C14 | Settings JSON | Validates the structure and wiring of `.claude/settings.json`. |
| C15 | Custom Agents | Verifies implementer and worker agent directories and configs. |
| C16 | Path Rules | Confirms the scaffolding of the `.claude/rules/` directory. |
| C17 | Hardcoded Refs | Scans for illegal project-specific strings in generic templates. |
| C18 | Drift Score | Runs a drift audit and verifies a score >= 80. |

## Hooks

### Event Types

Hooks are wired to 10 primary Claude Code event types to enforce behavioral protocols.

| Event Type | Timing | Use Case |
|---|---|---|
| SessionStart | Session start | Injecting briefing, health checks, and recent lessons. |
| UserPromptSubmit | User sends message | Detecting correction signals and injecting protocol reminders. |
| PreToolUse | Before tool execution | Enforcing delegation gates and protecting architecture files. |
| PostToolUse | After tool execution | Running static analysis and framework contamination checks. |
| Stop | Response complete | Checking session hygiene and terminal output. |
| SubagentStart | Sub-agent spawned | Verifying delegation approval for the specific tier. |
| SubagentStop | Sub-agent finished | Tracking failures for tier-based escalation. |
| PermissionDenied | Tool call rejected | Incrementing failure counters for active tiers. |
| PostCompact | Context compaction | Re-injecting critical rules lost during summarization. |
| SessionEnd | Session termination | Auto-saving state to NEXT_SESSION.md. |

### Hook Lifecycle

Hooks are registered in `.claude/settings.json`. When an event fires, Claude Code executes the associated script. The system uses 19 distinct hooks to manage everything from database safety (`protect-databases.sh`) to Xcode project integrity (`check-pbxproj.sh`). Hooks can inject warnings, block tool use, or modify the context to ensure the model adheres to project standards.

## Agents

### Built-in Agents

The system utilizes a 4-tier model to match task complexity with model capability.

| Agent | Tier | Purpose |
|---|---|---|
| Explorer | Haiku | Read-only research, P1-DISCOVER tasks, and context gathering. |
| Implementer | Sonnet | Multi-file feature implementation, complex logic, and refactoring. |
| Verifier | Haiku | Post-implementation review, running tests, and PASS/FAIL reporting. |
| Worker | Haiku | Single-file boilerplate, config updates, and simple model changes. |

### Custom Agent Templates

Agent definitions are stored in `.claude/agents/`. These templates include `disallowedTools` patterns to enforce tier-based restrictions (e.g., preventing a research agent from writing files). During bootstrap, these templates are customized and deployed to enable specialized sub-agent spawns.

## Plugin System

### Build Process

The `build_plugin.sh` script automates the packaging of the Cowork Claude plugin. It collects skills, command definitions, and behavioral hooks into a structured archive. This process ensures that the plugin manifest (`plugin.json`) correctly references all included assets.

### Artifact Structure

The generated plugin artifact is a compressed package containing:
*   **skills/**: Specialized capabilities with their own reference documentation.
*   **commands/**: Custom CLI commands for the Cowork environment.
*   **hooks/**: Pre-configured hooks for the plugin runtime.
*   **manifest/**: Metadata defining permissions and tool availability.

## Frameworks

### What Frameworks Do

The system includes 10 project-agnostic frameworks that define behavioral protocols.

| Framework | Purpose |
|---|---|
| Session Protocol | Mandatory orientation and lesson extraction at session boundaries. |
| Phase Gates | Structured GO/CONFIRM/STOP verdict system for transitions. |
| Delegation | Six-tier task assignment model with escalation protocols. |
| Loopback System | Handling defects discovered in earlier phases without blocking progress. |
| Correction Protocol | Mandatory gate for lesson logging before fixing corrections. |
| Quality Gates | Automated linting, type checking, and security scanning. |
| Falsification | Proving correctness by attempting to fail assumptions. |
| Coherence System | Registry-based detection of stale markdown references. |
| Development Discipline | TDD enforcement and debugging rules. |
| Visual Verification | Playwright-based visual testing for browser-tagged tasks. |

### Loading Model (startup vs on-demand)

Frameworks are managed through a progressive disclosure model to keep the context window efficient.
*   **Startup**: Core frameworks like `session-protocol.md` are @-imported at the top of CLAUDE.md.
*   **On-Demand**: Behavioral frameworks like `correction-protocol.md` and `delegation.md` are injected into the context by hooks only when their specific gate is triggered.
*   **Manual**: Special-purpose frameworks like `falsification.md` or `quality-gates.md` are loaded by the user or model via the `ROUTER.md` reference table when needed for specific tasks.
