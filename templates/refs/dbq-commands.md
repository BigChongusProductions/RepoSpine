# dbq Command Reference
> On-demand reference. Load when you need exact syntax for a dbq command.
> Session-start cost: zero — not @-imported. Load with: `read refs/dbq-commands.md`

---

## Tier 1 — Daily Commands (6)

| Command | Synopsis | Example |
|---------|----------|---------|
| `next` | Show ready + blocked tasks | `bash db_queries.sh next` |
| `done` | Mark task complete | `bash db_queries.sh done QK-1234` |
| `check` | Pre-task gate check (GO/CONFIRM/STOP) | `bash db_queries.sh check QK-1234` |
| `quick` | Rapid task/loopback capture | `bash db_queries.sh quick "Fix bug" P3-IMPLEMENT bug` |
| `phase` | Show current active phase | `bash db_queries.sh phase` |
| `status` | Show project status summary | `bash db_queries.sh status` |

---

## Tier 2 — Periodic Commands (13)

### Inbox Pipeline

#### `inbox` — View untriaged quick captures

**Syntax:**
    bash db_queries.sh inbox

**Example:**
    bash db_queries.sh inbox    # lists all QK-xxxx items pending triage

---

#### `triage` — Promote inbox item to planned work or loopback

**Syntax:**
    bash db_queries.sh triage <task_id> <phase> [tier] [skill] [blocked_by]
    bash db_queries.sh triage <task_id> loopback <origin_phase> [--severity N]

**Examples:**
    bash db_queries.sh triage QK-1234 P3-IMPLEMENT sonnet
    bash db_queries.sh triage QK-1234 P3-IMPLEMENT sonnet auth --blocked-by QK-999
    bash db_queries.sh triage QK-1234 loopback P2-DESIGN --severity 2

**Common errors:**
- When phase is `loopback`, slot 3 is the **origin phase** (e.g. `P2-DESIGN`), NOT a model tier
- Missing tier positional causes silent default — always pass `sonnet`, `haiku`, or `opus`
- `blocked_by` is positional (5th arg), not a flag

---

### Phase Gates

#### `gate` — Show current gate status

**Syntax:**
    bash db_queries.sh gate

---

#### `gate-pass` — Record a phase gate passage

**Syntax:**
    bash db_queries.sh gate-pass <phase> [gated_by] [notes]

**Examples:**
    bash db_queries.sh gate-pass P2-DESIGN MASTER "All design tasks complete"
    bash db_queries.sh gate-pass P3-IMPLEMENT MASTER

**Common errors:**
- Phase must be exact canonical name: `P1-DISCOVER`, `P2-DESIGN`, `P3-IMPLEMENT`, `P4-VALIDATE`
- `P2`, `2`, `Design` all create orphan records silently — use full name

---

#### `confirm` — Confirm a task before execution

**Syntax:**
    bash db_queries.sh confirm <task_id> [confirmed_by] [reasons]

**Examples:**
    bash db_queries.sh confirm QK-1234
    bash db_queries.sh confirm QK-1234 MASTER "reviewed design doc"

---

#### `unblock` — Clear a stale or resolved blocker

**Syntax:**
    bash db_queries.sh unblock <task_id>

**Example:**
    bash db_queries.sh unblock QK-1234

---

### Loopback Management

#### `loopbacks` — View open loopback queue

**Syntax:**
    bash db_queries.sh loopbacks [--origin PHASE] [--severity N] [--gate-critical] [--all]

**Examples:**
    bash db_queries.sh loopbacks
    bash db_queries.sh loopbacks --origin P2-DESIGN --severity 2

---

#### `loopback-stats` — Analytics: origins, severity, hotspots

**Syntax:**
    bash db_queries.sh loopback-stats

---

#### `ack-breaker` — Acknowledge S1 circuit breaker

**Syntax:**
    bash db_queries.sh ack-breaker <task_id> <reason>

**Example:**
    bash db_queries.sh ack-breaker LB-0042 "acknowledged — fix in next sprint"

---

### Knowledge

#### `log-lesson` — Atomic lesson logging

**Syntax:**
    bash db_queries.sh log-lesson "WHAT" "PATTERN" "RULE" [--bp category "file_path"]

**Examples:**
    bash db_queries.sh log-lesson "triage loopback slot order wrong" "loopback triage" "slot 3 is origin phase not tier"
    bash db_queries.sh log-lesson "RULES_TEMPLATE bloated" "template size" "slim before session start" \
      --bp template "templates/rules/RULES_TEMPLATE.md"

**Common errors:**
- `--bp` requires the category string and file path as the two arguments immediately following
- Three positional strings are required — missing any causes silent truncation

---

### Session

#### `log` — Log a session record

**Syntax:**
    bash db_queries.sh log <session_type> <summary>

**Example:**
    bash db_queries.sh log "Agent" "Implemented Group A — refs/dbq-commands.md, RULES_TEMPLATE slim"

---

#### `delegation-md` — Regenerate AGENT_DELEGATION.md from DB

**Syntax:**
    bash db_queries.sh delegation-md

**Note:** Always run after triage or adding tasks. Never edit AGENT_DELEGATION.md by hand.

---

#### `assume` — Register an assumption for a task

**Syntax:**
    bash db_queries.sh assume <task_id> <assumption> [verify_cmd]

**Examples:**
    bash db_queries.sh assume QK-1234 "DB schema exists" "bash db_queries.sh health"
    bash db_queries.sh assume QK-1234 "Python 3.10+ available"

**Common errors (two-step workflow):**
- `assume` only registers; it does NOT verify
- After registering, run `assumptions QK-1234` to get the numeric ID, then `verify-assumption QK-1234 <N>`

---

## Tier 3 — Admin / Rare Commands (36)

| Command | Positionals | Key Flags | One-liner |
|---------|------------|-----------|-----------|
| `add-task` | `task_id phase title tier` | — | Manually add task (4 required args) |
| `task` | `task_id` | — | Show single task details |
| `start` | — | — | Initialize DB from BLUEPRINT.md |
| `skip` | `task_id reason` | — | Mark task WONTFIX / skip |
| `tag-browser` | — | — | Launch tag browser UI |
| `researched` | `task_id` | — | Mark task as researched |
| `break-tested` | `task_id` | — | Record deliberate breakage test |
| `loopback-lesson` | `task_id` | — | Generate lesson from resolved loopback |
| `verify-assumption` | `task_id n` | — | Verify assumption N for task |
| `verify-all` | `task_id` | — | Verify all assumptions for task |
| `assumptions` | `task_id` | — | List assumptions for task |
| `lessons` | — | — | Show all logged lessons |
| `promote` | `pattern rule` | — | Promote lesson to LESSONS_UNIVERSAL.md |
| `escalate` | `task_id` | — | Escalate task tier |
| `delegation` | — | — | Show delegation map |
| `sync-check` | — | — | NEXT_SESSION.md vs DB sync check |
| `snapshot` | `name` | — | Create named DB snapshot |
| `snapshot-list` | — | — | List all snapshots |
| `snapshot-show` | `name` | — | Show snapshot content |
| `snapshot-diff` | `s1 s2` | — | Diff two snapshots |
| `tag-session` | `tag` | — | Tag current session |
| `session-tags` | — | — | List session tags |
| `session-file` | `session_id` | — | Export session to markdown |
| `backup` | — | — | Backup DB |
| `restore` | `backup_path` | — | Restore from backup |
| `verify` | — | — | Data integrity audit |
| `handover` | — | — | Generate session handover doc |
| `resume` | — | — | Resume from handover |
| `board` | — | — | Generate markdown board view |
| `blockers` | — | — | List all blockers |
| `confirmations` | — | — | List milestone confirmations |
| `master` | — | — | List Master tasks |
| `sessions` | — | — | List past sessions |
| `decisions` | — | — | List recorded decisions |
| `health` | — | — | DB health check |
| `init-db` | — | — | Initialize empty DB |

---

## Error-Prone Commands — Extended Notes

### `quick` — CRITICAL RISK

Three `nargs="?"` positionals are order-dependent. `--reason` is silently discarded when `--loopback` is absent.

```bash
# Correct loopback form (all three positionals + loopback args):
bash db_queries.sh quick "Missing nil check in spec" P3-IMPLEMENT bug \
  --loopback P2-DESIGN --severity 2 --reason "spec did not cover nil input"

# Wrong — phase/tag default silently, --reason ignored:
bash db_queries.sh quick "Missing nil check" --loopback P2-DESIGN --reason "spec gap"
```

Rules:
- Positional order is `title` → `phase` → `tag` — cannot reorder
- `--loopback` takes a phase name (`P2-DESIGN`), not a task ID
- `--reason` requires `--loopback` to be set, otherwise silently ignored

---

### `triage` — HIGH RISK

When `phase == "loopback"`, position 3 (tier slot) must be an **origin phase name**, not a model name.

```bash
bash db_queries.sh triage QK-1234 P3-IMPLEMENT sonnet          # normal — tier slot = model
bash db_queries.sh triage QK-1234 loopback P2-DESIGN --severity 2  # loopback — tier slot = origin phase
```

---

### `add-task` — HIGH RISK

4 required positionals: `task_id phase title tier`. Missing any causes an error or misparse.

```bash
bash db_queries.sh add-task QK-9999 P2-DESIGN "Design auth flow" sonnet
```

Wrong (only 3 args — title defaults, tier missing):
```bash
bash db_queries.sh add-task QK-9999 P2-DESIGN sonnet  # WRONG
```

---

### `log-lesson` — MEDIUM-HIGH RISK

`--bp` requires the category string and file path as two arguments immediately after.

```bash
bash db_queries.sh log-lesson "WHAT" "PATTERN" "RULE" \
  --bp template "templates/rules/RULES_TEMPLATE.md"
```

All three positional strings are required. Missing the third causes the third to default silently.

---

### `gate-pass` — MEDIUM RISK

Phase must be the exact canonical name. Shortened forms create orphan records silently.

| Input | Result |
|-------|--------|
| `P2-DESIGN` | Correct |
| `P2`, `2`, `Design`, `design` | Orphan record — gate never recognized |

```bash
bash db_queries.sh gate-pass P2-DESIGN MASTER "All design tasks complete"
```

---

### `assume` — MEDIUM RISK (two-step workflow)

`assume` registers only. Verification is a separate command requiring the numeric assumption ID.

```bash
# Step 1: register
bash db_queries.sh assume QK-1234 "DB schema exists" "bash db_queries.sh health"

# Step 2: get the numeric ID
bash db_queries.sh assumptions QK-1234

# Step 3: verify by numeric ID
bash db_queries.sh verify-assumption QK-1234 1
```
