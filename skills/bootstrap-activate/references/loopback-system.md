# Loopback System Reference

Comprehensive reference for the parallel backward-fix track. Loopbacks handle defects discovered in earlier phases without reopening phase gates or blocking forward progress.

---

## Core Principle

**Phase gates never reopen.** When a bug is found in Phase 2 code while working on Phase 4, you don't go "back" to Phase 2. Instead, you create a loopback task that runs in a parallel track alongside forward work. This preserves phase integrity while ensuring defects get fixed.

---

## Severity Scale (S1–S4)

| Severity | Name | Definition | Circuit Breaker? | Gate-Critical? |
|----------|------|-----------|-------------------|----------------|
| **S1** | Critical | Blocks forward work or breaks core functionality. Cannot ship without fixing. | **YES** — must be acknowledged before ANY forward work continues | Always |
| **S2** | Major | Significant defect that affects user experience or data integrity. Does not block forward work directly. | No | Can be marked gate-critical |
| **S3** | Minor | Small defect, workaround exists. Fix when convenient. Default severity. | No | No |
| **S4** | Cosmetic | Visual polish, naming, documentation. Fix if time permits. | No | No |

### Severity Decision Guide

Ask these questions in order:
1. **Does forward work depend on the broken code?** → S1
2. **Would a user encounter this in normal use AND have no workaround?** → S2
3. **Would a user encounter this but can work around it?** → S3
4. **Would only a developer or code reviewer notice?** → S4

---

## Circuit Breaker Protocol (S1 Only)

When an S1 loopback is created, ALL forward work pauses until it's acknowledged:

1. **Detection** — A defect is found that meets S1 criteria
2. **Creation** — `bash db_queries.sh quick "Fix critical X" PHASE bug --loopback ORIGIN_PHASE --severity 1 --reason "blocks Y" --gate-critical`
3. **Circuit breaker fires** — `db_queries.sh next` shows the S1 task at the very top under "⚡ CIRCUIT BREAKER"
4. **Acknowledgment** — Before any other work: `bash db_queries.sh ack-breaker LB-xxxx "fixing now"` or `"deferring because..."`
5. **Resolution** — Fix the defect, mark done: `bash db_queries.sh done LB-xxxx`
6. **Forward work resumes**

**If the S1 is deferred** (rare — requires explicit Master override):
- Log the override reason
- The breaker remains in NEXT_SESSION.md under "Overrides (active)"
- Every session start will flag it

---

## Gate-Critical Loopbacks

A loopback is "gate-critical" when it must be resolved before the phase it was *discovered in* can pass its gate. Not all loopbacks are gate-critical — only those that would compromise the gate's quality bar.

**Marking gate-critical:**
```bash
bash db_queries.sh quick "Fix validation" P1-CORE bug --loopback P1-CORE --severity 2 --gate-critical
```

**Impact:** `db_queries.sh check` for the last task in a phase will STOP if gate-critical loopbacks targeting that phase are unresolved.

**When to mark gate-critical:**
- The defect undermines a core requirement of the phase
- The defect would cause cascading issues in later phases
- The defect affects data integrity or security

**When NOT gate-critical:**
- Visual polish or naming issues
- Performance optimizations that don't affect correctness
- Documentation gaps

---

## Loopback Task Lifecycle

```
CREATED → ACKNOWLEDGED (S1 only) → IN_PROGRESS → DONE
                                  → WONTFIX (with reason)
```

### Creating Loopbacks

```bash
# Standard loopback (S3 default)
bash db_queries.sh quick "Fix layout bug" P1-CORE bug --loopback P1-CORE

# With severity
bash db_queries.sh quick "Fix validation" P1-CORE bug --loopback P1-CORE --severity 2 --reason "wrong regex"

# Gate-critical
bash db_queries.sh quick "Fix auth bypass" P2-AUTH bug --loopback P2-AUTH --severity 1 --gate-critical --reason "security hole"
```

### ID Format

Loopback tasks get `LB-xxxx` IDs (vs `QK-xxxx` for quick captures or `P0-01` for planned tasks). This makes them instantly identifiable in task queues.

### Viewing Loopbacks

```bash
bash db_queries.sh loopbacks              # Open loopback queue (grouped by severity)
bash db_queries.sh loopback-stats         # Analytics: origins, severity, hotspots
```

### Resolving Loopbacks

```bash
bash db_queries.sh done LB-xxxx           # Normal resolution
bash db_queries.sh skip LB-xxxx "reason"  # Won't fix (with mandatory reason)
```

### Generating Lessons from Loopbacks

After resolving a loopback, extract the lesson:
```bash
bash db_queries.sh loopback-lesson LB-xxxx
```
This auto-generates a structured lesson entry: what broke, why, what prevents recurrence.

---

## Integration with Other Systems

### Task Queue (`db_queries.sh next`)

The task queue interleaves loopbacks with forward work:
```
⚡ CIRCUIT BREAKER (S1 loopbacks — must acknowledge first)
  LB-0012  Fix auth bypass [S1] [gate-critical P2-AUTH]

🔧 S2 LOOPBACKS (run before forward work when possible)
  LB-0010  Fix validation regex [S2] [P1-CORE]

▶ FORWARD (ready)
  P3-01    Implement API client [sonnet]
  P3-02    Add error handling [haiku]

📝 S3/S4 LOOPBACKS (run when convenient)
  LB-0008  Fix tooltip alignment [S3] [P1-CORE]

🚫 BLOCKED
  P3-03    Connect to external API [blocked by: P3-01]
```

### Pre-Task Check (`db_queries.sh check`)

- S1 unacknowledged → **STOP**
- Gate-critical unresolved for current phase → **STOP** (if checking last task in phase)
- S2 loopback exists for code you're about to touch → **WARN** (advisory)

### Phase Gates

Phase gates check:
1. All forward tasks DONE ✓
2. All gate-critical loopbacks for this phase DONE ✓
3. S1 loopbacks acknowledged (not necessarily resolved, but acknowledged) ✓

Non-gate-critical loopbacks (S3, S4, and non-critical S2) do NOT block phase gates.

### Session Briefing

`session_briefing.sh` reports:
- Total open loopbacks by severity
- Any unacknowledged S1 breakers → RED signal
- Gate-critical loopbacks blocking upcoming phase gate → YELLOW signal

### Lesson Promotion

Loopbacks that recur (same origin phase, same type) trigger a promotion check:
- 2+ loopbacks from the same file/module → create a `gotchas-[domain].md` ref file
- 3+ loopbacks of the same pattern → promote to LESSONS_UNIVERSAL.md

---

## Loopback Analytics

```bash
bash db_queries.sh loopback-stats
```

Outputs:
- **By origin phase:** Which phases produce the most defects? (indicates insufficient phase gates)
- **By severity:** Distribution of S1/S2/S3/S4 (healthy projects skew toward S3/S4)
- **By hotspot:** Which files/modules have the most loopbacks? (indicates architectural weakness)
- **Resolution time:** Average time from creation to done (growing times indicate tech debt)
- **Gate-critical ratio:** % of loopbacks that are gate-critical (>30% suggests scope issues)

---

## Anti-Patterns

| Anti-Pattern | Why It's Bad | What to Do Instead |
|---|---|---|
| Creating S1 for everything | Blocks all forward work constantly | Reserve S1 for true blockers. Most defects are S2-S3. |
| Never creating loopbacks | Defects accumulate, discovered late | Any defect in prior-phase code = loopback, no exceptions |
| Skipping loopback-lesson | Same bugs recur | Always extract the lesson after resolving |
| Marking everything gate-critical | Same as creating S1 for everything | Gate-critical = "would compromise the phase's quality bar" |
| Fixing loopbacks without creating them | No paper trail, no analytics | Always create the task first, then fix it. The tracking matters. |

---

## Changelog
- 1.0: Extracted from RomaniaBattles loopback-spec.md (25.9KB → condensed to essential reference)
