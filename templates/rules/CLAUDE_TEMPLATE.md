# %%PROJECT_NAME%% — Project Entry Point
> Frameworks load on demand via hooks — do NOT @-import them at startup.

@frameworks/session-protocol.md
@%%RULES_FILE%%
@AGENT_DELEGATION.md
@ROUTER.md

> **On-demand frameworks** (loaded automatically by hooks when triggered):
> - `correction-protocol.md` — injected by correction-detector hook on correction signal
> - `delegation.md` — injected by pre-edit-check hook at delegation gate
> - `phase-gates.md` — load manually before pre-task check (`db_queries.sh check <id>`)
>
> **Optional frameworks** (add @import lines above to enable):
> `coherence-system`, `falsification`, `loopback-system`, `quality-gates`, `visual-verification`
> Example: `@frameworks/quality-gates.md`

> LESSONS file (`%%LESSONS_FILE%%`) is NOT @-imported — it grows unboundedly.
> The session-start hook injects recent lessons. Read full file on demand for correction protocol.
> Path-specific rules in `.claude/rules/` auto-inject when touching matching files.
> Hooks in `.claude/hooks/` enforce behavioral gates. Custom agents in `.claude/agents/`.
