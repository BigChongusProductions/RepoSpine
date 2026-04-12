# Quality Gates Guide

Setup and configuration for all four automated quality gates.

---

## Overview

Four quality gates protect code at different stages:

| Gate | Trigger | Speed | Blocks? | Contents |
|------|---------|-------|---------|----------|
| **Pre-commit** | `git commit` | <15s | YES | Lint + types + tests + coherence (warn) |
| **Pre-push** | `git push` | ~30s | YES | Production build |
| **Build Summarizer** | Manual | Variable | N/A | On-demand `build`, `test`, `verify` modes |
| **Milestone Check** | Manual | ~60s | N/A | Task audit + build + tests + merge validation |

---

## Gate 1: Pre-commit Hook

### Installation

Create `.git/hooks/pre-commit`:

```bash
#!/bin/bash
set -e

# Tech-stack-specific linter command
[LINTER_COMMAND]

# Tech-stack-specific type checker (if applicable)
[TYPE_CHECKER_COMMAND]

# Tests
[TEST_COMMAND]

# Coherence check (warn only, don't block)
bash coherence_check.sh --quiet || true

exit 0
```

Make executable: `chmod +x .git/hooks/pre-commit`

### Tech-Stack-Specific Commands

#### Node.js / Next.js
```bash
#!/bin/bash
set -e

# Lint with ESLint
npm run lint

# Type check with TypeScript
npx tsc --noEmit

# Run tests
npm test -- --passWithNoTests

# Coherence check (warn only)
bash coherence_check.sh --quiet || true

exit 0
```

#### Python (with Poetry)
```bash
#!/bin/bash
set -e

# Format check with Black
poetry run black --check .

# Lint with Ruff
poetry run ruff check .

# Type check with MyPy
poetry run mypy .

# Tests
poetry run pytest

# Coherence check
bash coherence_check.sh --quiet || true

exit 0
```

#### Python (with pip)
```bash
#!/bin/bash
set -e

# Format check with Black
python -m black --check .

# Lint with Ruff
python -m ruff check .

# Type check with MyPy
python -m mypy .

# Tests
python -m pytest

# Coherence check
bash coherence_check.sh --quiet || true

exit 0
```

#### Rust
```bash
#!/bin/bash
set -e

# Format check
cargo fmt -- --check

# Lint with Clippy
cargo clippy -- -D warnings

# Tests
cargo test

# Coherence check
bash coherence_check.sh --quiet || true

exit 0
```

#### Swift
```bash
#!/bin/bash
set -e

# Lint with SwiftLint
swiftlint lint --strict

# Format check with SwiftFormat
swift format --in-place --diagnose . > /dev/null

# Build
xcodebuild build -scheme [SCHEME]

# Tests
xcodebuild test -scheme [SCHEME]

# Coherence check
bash coherence_check.sh --quiet || true

exit 0
```

#### Go
```bash
#!/bin/bash
set -e

# Format check
go fmt ./... > /dev/null
if [ -n "$(git status --porcelain)" ]; then
  echo "Format check failed. Run: go fmt ./..."
  exit 1
fi

# Lint
golangci-lint run ./...

# Build
go build ./...

# Tests
go test ./...

# Coherence check
bash coherence_check.sh --quiet || true

exit 0
```

### Verification

Test the hook before using:

```bash
echo "test" > test.txt
git add test.txt
git commit -m "test commit" 2>&1 | head -20
# Should output: [linter] → [type checker] → [tests] → [coherence check]
# Then: commit succeeds or fails based on those results

# Clean up
git reset --soft HEAD^
rm test.txt
```

---

## Gate 2: Pre-push Hook

### Installation

Create `.git/hooks/pre-push`:

```bash
#!/bin/bash
set -e

# Run production build to catch missed compile/runtime errors
[BUILD_COMMAND]

exit 0
```

Make executable: `chmod +x .git/hooks/pre-push`

### Tech-Stack-Specific Commands

#### Node.js / Next.js
```bash
#!/bin/bash
set -e

# Production build
npm run build

# Optional: check for TypeScript errors in build
# npm run type-check

exit 0
```

#### Python
```bash
#!/bin/bash
set -e

# Build package (ensures no import errors, setup.py issues, etc.)
python -m build .

exit 0
```

#### Rust
```bash
#!/bin/bash
set -e

# Release build
cargo build --release

exit 0
```

#### Swift
```bash
#!/bin/bash
set -e

# Release build
xcodebuild build -configuration Release -scheme [SCHEME]

exit 0
```

#### Go
```bash
#!/bin/bash
set -e

# Build for all target platforms
go build ./...

# Optional: cross-compile to verify
# GOOS=darwin GOARCH=arm64 go build ./...
# GOOS=linux GOARCH=amd64 go build ./...

exit 0
```

### Verification

Test the hook:

```bash
# Make a trivial change and commit
echo "# test" >> README.md
git add README.md
git commit -m "test: verify pre-push hook"

# Now try to push (use --dry-run to avoid actual push)
git push --dry-run origin dev 2>&1 | head -20
# Should output: [build command output]
# Then: push would succeed or fail based on build result

# Clean up
git reset --soft HEAD^
git restore README.md
```

---

## Gate 3: Build Summarizer

### Usage

```bash
# Quick check: lint + types + build (no tests, faster)
bash build_summarizer.sh build

# Full check: lint + types + build + tests + coherence
bash build_summarizer.sh test

# Verify specific tool: just run that tool
bash build_summarizer.sh verify
```

### Implementation

Extract from `build_summarizer.sh`:

```bash
#!/bin/bash

MODE="${1:-test}"

case "$MODE" in
  build)
    echo "[LINTER_COMMAND]"
    [LINTER_COMMAND]
    echo "[TYPE_CHECKER_COMMAND]"
    [TYPE_CHECKER_COMMAND]
    echo "[BUILD_COMMAND]"
    [BUILD_COMMAND]
    echo "✓ Build check passed"
    ;;

  test)
    echo "[LINTER_COMMAND]"
    [LINTER_COMMAND]
    echo "[TYPE_CHECKER_COMMAND]"
    [TYPE_CHECKER_COMMAND]
    echo "[BUILD_COMMAND]"
    [BUILD_COMMAND]
    echo "[TEST_COMMAND]"
    [TEST_COMMAND]
    bash coherence_check.sh --quiet || echo "(coherence warning, non-blocking)"
    echo "✓ Full check passed"
    ;;

  verify)
    # Just run health diagnostic
    bash db_queries.sh health
    ;;

  *)
    echo "Usage: $0 {build|test|verify}"
    exit 1
    ;;
esac
```

### When to Use

- **After each task completion:** `bash build_summarizer.sh test`
- **Before phase gate:** `bash build_summarizer.sh test`
- **Quick sanity check:** `bash build_summarizer.sh build`

---

## Gate 4: Milestone Check

### Usage

```bash
bash milestone_check.sh <PHASE_NAME>
```

**Example:**
```bash
bash milestone_check.sh "Phase 1"
# Output:
# ✓ All Phase 1 tasks DONE
# ✓ Branch: dev
# ✓ Working tree clean
# ✓ Build successful
# ✓ Tests pass
# ✓ Coherence clean
#
# Ready to merge. Run:
# git checkout main
# git pull origin main
# git merge dev --ff-only
# git push origin main
```

### Implementation

The script checks (in order):

```bash
#!/bin/bash

PHASE="$1"

if [ -z "$PHASE" ]; then
  echo "Usage: $0 <PHASE_NAME>"
  exit 1
fi

echo "=== Milestone Check: $PHASE ==="

# 1. Task audit: all tasks in phase DONE
echo -n "Checking tasks... "
UNDONE=$(bash db_queries.sh task | grep "Phase: $PHASE" | grep -v "DONE" | wc -l)
if [ "$UNDONE" -gt 0 ]; then
  echo "✗ $UNDONE tasks not DONE"
  exit 1
fi
echo "✓"

# 2. Branch is dev
echo -n "Checking branch... "
BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$BRANCH" != "dev" ]; then
  echo "✗ Not on dev branch (on: $BRANCH)"
  exit 1
fi
echo "✓"

# 3. Working tree clean
echo -n "Checking working tree... "
if [ -n "$(git status --porcelain)" ]; then
  echo "✗ Uncommitted changes"
  git status --short
  exit 1
fi
echo "✓"

# 4. Build passes
echo -n "Building... "
[BUILD_COMMAND] > /dev/null 2>&1 || {
  echo "✗ Build failed"
  [BUILD_COMMAND]  # Re-run with output
  exit 1
}
echo "✓"

# 5. Tests pass
echo -n "Testing... "
[TEST_COMMAND] > /dev/null 2>&1 || {
  echo "✗ Tests failed"
  [TEST_COMMAND]  # Re-run with output
  exit 1
}
echo "✓"

# 6. Coherence clean
echo -n "Coherence check... "
bash coherence_check.sh --quiet || echo "(warning)"
echo "✓"

echo ""
echo "Ready to merge. Run:"
echo "  git checkout main"
echo "  git pull origin main"
echo "  git merge dev --ff-only"
echo "  git push origin main"
```

### When to Use

Run milestone_check.sh only when:
1. All tasks in the phase are marked DONE in the DB
2. You're ready to merge to main
3. No further work is planned for the phase

**Output:** Either merge commands (if clean) or a list of what to fix (if failures).

---

## Gate Integration in Session Workflow

### Per-Task Workflow

```
1. Read task spec
2. Implement changes
3. Run: bash build_summarizer.sh test
4. If OK: bash db_queries.sh done <task-id>
5. Commit with message
6. Proceed to next task
```

### Per-Phase Workflow

```
1. Complete all tasks in phase (all marked DONE)
2. Run: bash build_summarizer.sh test
3. Audit phase for must-fix vs follow-up issues
4. Run: bash db_queries.sh gate-pass <PHASE>
5. When ready to merge:
   - Run: bash milestone_check.sh <PHASE>
   - If OK: follow merge commands
   - If fails: fix and commit, then re-run milestone_check.sh
```

### Session Start Workflow

```
1. bash session_briefing.sh
2. If phase just finished: bash milestone_check.sh <last_phase>
3. Begin next task workflow
```

---

## Troubleshooting Gates

| Problem | Cause | Fix |
|---------|-------|-----|
| Pre-commit hook fails on every commit | Missing linter/formatter config | Create .eslintrc.json, pyproject.toml, etc. for your tech stack |
| Pre-commit hook doesn't run | Hook not executable | `chmod +x .git/hooks/pre-commit` |
| Hook runs but doesn't catch real errors | Tool not installed | `npm install --save-dev [tool]` or `poetry add --group dev [tool]` |
| `build_summarizer.sh` command not found | Script not in PATH or not executable | `chmod +x build_summarizer.sh && ./build_summarizer.sh test` |
| `bash build_summarizer.sh test` hangs | Test suite is too slow | Consider splitting into unit/integration tests; run integration separately |
| Milestone check fails but I'm sure it should pass | DB out of sync with git | Run `bash db_queries.sh sync-check` to audit and repair |
| Coherence check warns about stale refs | coherence_registry.sh needs update | Add the old phrase → new phrase entry and run `bash coherence_check.sh --fix` |

---

## Performance Targets

| Gate | Target Time | Acceptable Range | Notes |
|------|-------------|------------------|-------|
| Pre-commit | <15 seconds | <30s | If slower, tests are too slow or too many. Consider parallelization or splitting. |
| Pre-push | ~30 seconds | 20-60s | Build time varies by project size. Acceptable if production build. |
| Build Summarizer (build mode) | <20 seconds | <30s | Faster feedback cycle for quick checks. |
| Build Summarizer (test mode) | <60 seconds | <90s | Full test suite; slower acceptable if comprehensive. |
| Milestone Check | ~30 seconds | 20-60s | Task audit + build + tests. Fast if tests are optimized. |

If gates exceed targets, optimize:
1. Run subset of tests on pre-commit (full tests on pre-push/milestone)
2. Parallelize test execution
3. Use test filtering (e.g., only unit tests on commit, integration on push)
4. Cache expensive operations (node_modules, build artifacts, pip installs)

