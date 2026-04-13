# project-bootstrap v1.2.0

Describe your idea, get a complete development workflow engine. Turns an empty folder into a fully operational Claude Code environment with 111 integrated components — from discovery interview to deployed task system.

## What This Does

Two-step bootstrap:

1. **In Cowork** (`/new-project`): Collaborative discovery — you describe your idea, Claude researches feasibility, evaluates tech stacks, proposes architecture, and debates trade-offs with you. Produces 4 spec files (VISION, RESEARCH, BLUEPRINT, INFRASTRUCTURE) with zero TODOs.

2. **In Claude Code** (`/activate-engine`): Reads specs, generates requirements and design docs (with review cycles), breaks design into phased tasks, populates a SQLite task database, then deploys the full engine — workflow scripts, CLAUDE.md with framework imports, AGENT_DELEGATION.md, refs/ progressive disclosure directory, behavioral hooks, custom agents, settings, tracking files, and launch scripts. Runs 18-check verification at the end.

## What You Get

| Component | Count | What it covers |
|-----------|-------|----------------|
| Frameworks | 10 | Session protocol, phase gates, delegation, loopback system, correction protocol, quality gates, falsification, coherence, development discipline, visual verification |
| Behavioral hooks | 19 | Pre/post edit gates, delegation enforcement, session start/end, static analysis, correction detection, sub-agent checks |
| Agent definitions | 4 | Explorer (research), implementer (multi-file), verifier (post-implementation), worker (single-file) |
| Deployment checks | 18 | C01–C18: DB health, hook wiring, framework files, placeholder scan, drift score, and more |
| Rule templates | 12 | CLAUDE.md, RULES, AGENT_DELEGATION, ROUTER, plus language standards (Python, Swift, Go, Rust, Node, SQL) |
| dbq commands | 15 | Task lifecycle, phase gates, loopbacks, delegation, sessions, knowledge, eval, drift, snapshots |
| **Total** | **111** | Integrated components deployed to every bootstrapped project |

## Quick Start

### Prerequisites

- Claude Max plan (or Claude Code + Cowork access)
- Python 3.10+
- sqlite3
- jq
- git (initialized in project directory)
- Bash 4.0+

### Steps

```
1. Create a folder: ~/Desktop/MyProject
2. Open Cowork, select the folder
3. Say "new project" or run /new-project
4. Answer the interview questions (~10 minutes)
5. Open Claude Code in the same folder
6. Run /activate-engine
7. Review generated requirements and design docs
8. Approve the task breakdown
9. Engine deploys — start building
```

## Commands

| Command | Where | What |
|---------|-------|------|
| `/new-project` | Cowork | Start discovery interview |
| `/activate-engine` | Claude Code | Deploy full engine from specs |
| `/spec-status` | Either | Check bootstrap progress |

## Architecture

```
project-bootstrap/                      ← This repo (single source of truth)
  ├── .claude-plugin/plugin.json        ← Plugin manifest
  ├── bootstrap_project.sh              ← Main orchestrator script
  ├── skills/                           ← 3 public skills + 6 internal
  ├── templates/                        ← Canonical templates
  │   ├── scripts/                      ← Workflow scripts + Python CLI (dbq/)
  │   ├── frameworks/                   ← 10 framework files (project-agnostic)
  │   ├── rules/                        ← RULES, CLAUDE, AGENT_DELEGATION templates
  │   ├── hooks/                        ← 16 behavioral enforcement hooks
  │   ├── agents/                       ← 4 sub-agent definitions
  │   └── settings/                     ← settings.json templates
  ├── tests/                            ← Bootstrap test suite
  └── backlog/                          ← Development backlog + apply script

~/Desktop/MyProject/                    ← Your project (after /activate-engine)
  ├── CLAUDE.md                         ← Entry point (framework imports + @RULES + @DELEGATION)
  ├── PROJECT_RULES.md                  ← Deduped — references frameworks, not inlines them
  ├── AGENT_DELEGATION.md               ← 6-tier model + task delegation map
  ├── refs/                             ← Progressive disclosure (on-demand)
  ├── specs/                            ← 6 spec files from bootstrap
  ├── .claude/hooks/                    ← 16 behavioral enforcement hooks
  ├── .claude/agents/                   ← implementer + worker sub-agents
  ├── .claude/settings.json             ← Permissions + hook wiring
  ├── db_queries.sh                     ← 15 command modules across task lifecycle
  ├── session_briefing.sh               ← Signal computation (GREEN/YELLOW/RED)
  ├── project.db                        ← SQLite task database
  └── (10+ more workflow scripts)
```

## Documentation

- [Getting Started](docs/getting-started.md) — Prerequisites, installation, first project
- [Workflow Guide](docs/workflow.md) — Daily task management and phase gates
- [How It Works](docs/how-it-works.md) — Architecture deep dive
- [Components](docs/components.md) — Full inventory of frameworks, hooks, scripts, and agents
- [Troubleshooting](docs/troubleshooting.md) — Common issues and diagnostics
- [Migration](docs/migration.md) — Upgrading between versions

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history.
