# Getting Started

> Full installation and first-run guide for project-bootstrap.
> See [README](../README.md) for a quick overview.

## Prerequisites

### Required

*   **Claude Max Plan:** Required for both Cowork and Claude Code access.
*   **Python 3.10+:** Powers the `dbq` CLI and deployment verification scripts.
*   **sqlite3:** Local task database storage.
*   **jq:** Required for hook wiring and manifest processing.
*   **git:** Must be initialized in your project directory before bootstrapping.
*   **Bash 4.0+:** Required for infrastructure scripts (macOS users may need `brew install bash`).

### Optional

*   **Cowork:** Recommended for the Phase 1 Discovery interview.
*   **Semgrep:** Required if you enable the static analysis quality gates.

## Installation

### Via Cowork Plugin

1.  Download the `project-bootstrap.zip` from the [latest GitHub Release](https://github.com/user/project-bootstrap/releases).
2.  In **Cowork**, navigate to `Settings` > `Plugins`.
3.  Click `Install from File` and select the downloaded `.zip`.
4.  The `/new-project` and `/spec-status` commands are now available.

### Via Claude Code CLI

1.  Clone this repository to your local machine:
    ```bash
    git clone https://github.com/user/project-bootstrap.git
    cd project-bootstrap
    ```
2.  The `bootstrap_project.sh` script is the main entry point for manual deployments.

## First Bootstrap

### Step 1: Discovery (`/new-project`)

Open **Cowork** in an empty folder and run the discovery command:
```
/new-project
```
Claude will conduct a ~10 minute interview to understand your project vision, tech stack, and architecture. This produces four spec files in the `specs/` directory: `VISION.md`, `RESEARCH.md`, `BLUEPRINT.md`, and `INFRASTRUCTURE.md`.

### Step 2: Engine Deployment (`/activate-engine`)

Open **Claude Code** in the same folder and run the activation command:
```
/activate-engine
```
Claude will read your specs, generate finalized requirements and design documents, and then deploy the full workflow engine consisting of 111 integrated components (hooks, agents, rules, and scripts).

### Step 3: Verify

Once deployment is complete, run the automated health check to verify the wiring:
```bash
python3 scripts/verify_deployment.py
```
This runs 18 checks (C01–C18) covering database health, hook permissions, and framework connectivity.

## Commands Reference

| Command | Where | What it does |
| :--- | :--- | :--- |
| `/new-project` | Cowork | Starts the collaborative discovery interview |
| `/activate-engine` | Claude Code | Deploys the workflow engine from generated specs |
| `/spec-status` | Either | Displays current bootstrap progress |
| `bash work.sh` | Project Root | Launches a work session with signal check and backup |
| `bash fix.sh` | Project Root | Launches "fix mode" for rapid, targeted bug fixing |
| `bash db_queries.sh` | Project Root | Entry point for 15 task/phase management modules |

## Next Steps

*   **Daily Workflow:** Read [workflow.md](workflow.md) to learn about the GREEN/YELLOW/RED signal and task management.
*   **Internal Architecture:** See [how-it-works.md](how-it-works.md) for details on the placeholder engine and hook lifecycle.
*   **Component Inventory:** See [components.md](components.md) for a full list of the 111 deployed systems.
*   **Issues:** Consult [troubleshooting.md](troubleshooting.md) if you encounter database locks or permission errors.
