#!/bin/bash
# lib-scope-counter.sh — scope tracker for delegation gate.
#
# Replaces the stateless EDIT_COUNT-based delegation advisory with a
# scope-aware tracker. Records each edit's (file, sha1(old_string), lines).
# Fires advisory once per task-boundary when scope crosses thresholds.
#
# Public API:
#   scope_read                              → stdout: state JSON (or "{}")
#   scope_record  <file> <old> <new>        → record Edit
#   scope_record_write <file> <new_content> → record Write
#   scope_reset   [boundary_id]             → clear records, set boundary
#   scope_should_fire                       → stdout: reason, exit 0=fire, 1=silent
#   scope_mark_fired                        → set fired_this_boundary=true
#
# State file (overridable via SCOPE_STATE_FILE env):
#   .claude/hooks/.delegation_scope.json
#
# Concurrency: RMW functions (scope_record, scope_record_write, scope_reset,
# scope_mark_fired) run under _scope_with_lock. Uses flock if available
# (2s timeout). Falls back to a noclobber-sentinel on systems without flock
# (e.g. macOS base). Writes are atomic via mktemp + mv (same-filesystem rename).
#
# Fail-soft: if jq or sha1 tool missing, functions become no-ops (silent).
# Lock contention, flock absence, atomic-rename failure — all swallowed
# without disturbing the calling hook.

# ── Dependency checks (fail-soft) ──────────────────────────────────────────

_SCOPE_JQ_OK=true
_SCOPE_SHA_TOOL=""
_SCOPE_FLOCK_OK=false

if ! command -v jq >/dev/null 2>&1; then
    _SCOPE_JQ_OK=false
fi

if command -v sha1sum >/dev/null 2>&1; then
    _SCOPE_SHA_TOOL="sha1sum"
elif command -v shasum >/dev/null 2>&1; then
    _SCOPE_SHA_TOOL="shasum"
fi

if command -v flock >/dev/null 2>&1; then
    _SCOPE_FLOCK_OK=true
fi

# ── Config (overridable via env) ───────────────────────────────────────────

: "${SCOPE_STATE_FILE:=${CLAUDE_PROJECT_DIR:-$PWD}/.claude/hooks/.delegation_scope.json}"
: "${SCOPE_HISTORY_FILE:=${CLAUDE_PROJECT_DIR:-$PWD}/.claude/hooks/.scope_history.jsonl}"
: "${SCOPE_FILES_THRESHOLD:=3}"
: "${SCOPE_FILES_ONLY_THRESHOLD:=4}"
: "${SCOPE_LINES_THRESHOLD:=50}"
: "${SCOPE_LARGE_FILE_THRESHOLD:=100}"
: "${SCOPE_BOUNDARY_MAX_AGE:=14400}"  # 4h

# ── Internal helpers ───────────────────────────────────────────────────────

_scope_ready() {
    [ "$_SCOPE_JQ_OK" = "true" ] && [ -n "$_SCOPE_SHA_TOOL" ]
}

_scope_sha1() {
    if [ "$_SCOPE_SHA_TOOL" = "sha1sum" ]; then
        printf '%s' "$1" | sha1sum | awk '{print $1}'
    else
        printf '%s' "$1" | shasum -a 1 | awk '{print $1}'
    fi
}

# Count lines in a string (at least 1 if nonempty)
_scope_line_count() {
    local s="$1"
    [ -z "$s" ] && { echo 0; return; }
    local n
    n=$(printf '%s' "$s" | awk 'END{print NR}')
    [ -z "$n" ] && n=0
    [ "$n" -lt 1 ] && n=1
    echo "$n"
}

# Atomic write: tempfile in same dir as target, then mv. Rename within a
# single filesystem is atomic on POSIX, so readers never see a partial file.
_scope_write() {
    local state="$1"
    mkdir -p "$(dirname "$SCOPE_STATE_FILE")"
    local tmp
    tmp=$(mktemp "${SCOPE_STATE_FILE}.XXXXXX") || return 1
    printf '%s\n' "$state" > "$tmp" || { rm -f "$tmp"; return 1; }
    mv -f "$tmp" "$SCOPE_STATE_FILE" 2>/dev/null || { rm -f "$tmp"; return 1; }
}

# Run <fn> <args...> under an exclusive lock. Silent skip on contention
# timeout — correctness of the hook's primary job (not breaking tool
# execution) trumps scope-tracking completeness.
#
# Portability note: zsh and bash both support `trap EXIT` in subshells,
# but `trap RETURN` is bash-only. We use a subshell + `trap EXIT` so the
# cleanup fires exactly when the locked section ends, in either shell.
_scope_with_lock() {
    local lockfile="${SCOPE_STATE_FILE}.lock"
    local fn="$1"; shift
    mkdir -p "$(dirname "$lockfile")"

    if [ "$_SCOPE_FLOCK_OK" = "true" ]; then
        (
            flock -w 2 9 || exit 0    # timeout → silent skip
            "$fn" "$@"
        ) 9>"$lockfile"
    else
        # flock missing (macOS base): noclobber-sentinel fallback.
        # Realistic contention in a single Claude session is 0-4 concurrent
        # writers (parallel tool calls). Budget sized for ~100 concurrent
        # writers as a safety margin: 1000 attempts × 10-50ms ≈ 10-50s.
        # Stale sentinels are stolen ONLY when the owner PID is verifiably
        # dead (kill -0 fails). The mtime >30s check is a secondary fallback
        # for exotic cases where PID verification isn't possible.
        local sentinel="${lockfile}.sentinel"
        local attempts=0
        while ! ( set -C; echo $$ > "$sentinel" ) 2>/dev/null; do
            attempts=$((attempts + 1))
            if [ "$attempts" -ge 1000 ]; then
                # Last resort: try to steal the sentinel if its owner is dead.
                if [ -f "$sentinel" ]; then
                    local holder_pid sentinel_mtime now age
                    # Prefer PID-based liveness check over mtime — mtime alone
                    # can falsely accuse a slow-but-live critical section.
                    holder_pid=$(head -1 "$sentinel" 2>/dev/null \
                        | tr -dc '0-9' | head -c 20)
                    if [ -n "$holder_pid" ] && ! kill -0 "$holder_pid" 2>/dev/null; then
                        rm -f "$sentinel"
                        continue
                    fi
                    # Secondary fallback: mtime-based steal (>30s) only when
                    # PID check is inconclusive (empty PID, or recycled/alive).
                    now=$(date +%s)
                    sentinel_mtime=$(stat -f %m "$sentinel" 2>/dev/null \
                        || stat -c %Y "$sentinel" 2>/dev/null \
                        || echo "$now")
                    age=$(( now - sentinel_mtime ))
                    if [ -z "$holder_pid" ] && [ "$age" -gt 30 ]; then
                        rm -f "$sentinel"
                        continue
                    fi
                fi
                return 0    # give up silently
            fi
            sleep "0.0$(( 1 + RANDOM % 5 ))"
        done

        # Hold the lock in a subshell so trap EXIT reliably cleans up
        # the sentinel no matter how the function body returns (success,
        # early-return, or signal). Portable across bash and zsh.
        (
            trap 'rm -f "$sentinel"' EXIT
            "$fn" "$@"
        )
    fi
}

# Shared jq prelude — normalizes state in-place. Used inside larger pipelines
# so we don't spawn a second jq for normalization.
_SCOPE_JQ_NORMALIZE='
    . = {
        task_boundary: (.task_boundary // ""),
        boundary_set_at: (.boundary_set_at // $ts),
        records: (.records // []),
        fired_this_boundary: (.fired_this_boundary // false)
    }'

# Fused normalize + dedup-merge in a single jq invocation (halves latency
# vs. the two-pass design).
_scope_merge_record() {
    local file="$1" hash="$2" lines="$3"
    local now=$(date +%s)
    local input
    input=$(scope_read)
    printf '%s' "$input" | jq \
        --arg f "$file" --arg h "$hash" \
        --argjson l "$lines" --argjson ts "$now" \
        "$_SCOPE_JQ_NORMALIZE"'
        | if any(.records[]; .file == $f and .hash == $h) then
            .records = (.records | map(
                if .file == $f and .hash == $h then
                    .lines = (if .lines > $l then .lines else $l end)
                else . end
            ))
          else
            .records += [{file: $f, hash: $h, lines: $l}]
          end'
}

# ── Public API: read-only (lock-free) ──────────────────────────────────────

scope_read() {
    _scope_ready || { echo '{}'; return 0; }
    if [ ! -f "$SCOPE_STATE_FILE" ] || [ ! -s "$SCOPE_STATE_FILE" ]; then
        echo '{}'
        return 0
    fi
    if ! jq empty "$SCOPE_STATE_FILE" >/dev/null 2>&1; then
        echo '{}'
        return 0
    fi
    cat "$SCOPE_STATE_FILE"
}

# ── Public API: read-modify-write (under lock) ─────────────────────────────

_scope_reset_impl() {
    _scope_ready || return 0
    local boundary="${1:-}"
    local now=$(date +%s)
    local state
    state=$(jq -n --arg b "$boundary" --argjson ts "$now" '
        {
            task_boundary: $b,
            boundary_set_at: $ts,
            records: [],
            fired_this_boundary: false
        }')
    _scope_write "$state" || return 0
}
scope_reset() { _scope_with_lock _scope_reset_impl "$@"; }

_scope_record_impl() {
    _scope_ready || return 0
    local file="$1" old_string="$2" new_string="$3"

    local hash old_lines new_lines lines
    hash=$(_scope_sha1 "$old_string") || return 0
    old_lines=$(_scope_line_count "$old_string")
    new_lines=$(_scope_line_count "$new_string")
    lines=$(( old_lines > new_lines ? old_lines : new_lines ))
    [ "$lines" -lt 1 ] && lines=1

    _scope_write "$(_scope_merge_record "$file" "$hash" "$lines")" || return 0
}
scope_record() { _scope_with_lock _scope_record_impl "$@"; }

_scope_record_write_impl() {
    _scope_ready || return 0
    local file="$1" new_content="$2"

    local lines hash
    if [ -f "$file" ]; then
        local diff_lines
        diff_lines=$(diff <(cat "$file" 2>/dev/null) <(printf '%s' "$new_content") 2>/dev/null \
            | grep -cE '^[<>]' || true)
        [ -z "$diff_lines" ] && diff_lines=0
        lines="$diff_lines"
    else
        lines=$(_scope_line_count "$new_content")
    fi
    [ "$lines" -lt 1 ] && lines=1

    hash=$(_scope_sha1 "W:$new_content") || return 0

    _scope_write "$(_scope_merge_record "$file" "$hash" "$lines")" || return 0
}
scope_record_write() { _scope_with_lock _scope_record_write_impl "$@"; }

_scope_mark_fired_impl() {
    _scope_ready || return 0
    local now=$(date +%s)
    local state
    state=$(scope_read | jq --argjson ts "$now" \
        "$_SCOPE_JQ_NORMALIZE"' | .fired_this_boundary = true')
    _scope_write "$state" || return 0
}
scope_mark_fired() { _scope_with_lock _scope_mark_fired_impl "$@"; }

# Append a line to scope_history.jsonl for data-driven threshold tuning.
# Append-only + single-line + <PIPE_BUF (4KB) → O_APPEND is atomic, no lock.
_scope_log_history() {
    _scope_ready || return 0
    local fired="$1" reason="$2"
    local state files lines boundary ts
    state=$(scope_read)
    files=$(printf '%s' "$state" | jq '[.records[].file] | unique | length')
    lines=$(printf '%s' "$state" | jq '[.records[].lines] | add // 0')
    boundary=$(printf '%s' "$state" | jq -r '.task_boundary // ""')
    ts=$(date +%s)
    mkdir -p "$(dirname "$SCOPE_HISTORY_FILE")"
    jq -nc --argjson ts "$ts" --arg b "$boundary" \
        --argjson f "$files" --argjson l "$lines" \
        --argjson fired "$fired" --arg r "$reason" '
        {ts: $ts, boundary: $b, files: $f, lines: $l, fired: $fired, reason: $r}' \
        >> "$SCOPE_HISTORY_FILE"
}

# Read-only verdict. Stale boundary triggers implicit scope_reset (which
# acquires its own lock). No lock needed on the read path itself.
scope_should_fire() {
    _scope_ready || { echo "lib_unavailable"; return 1; }

    # Single jq invocation produces all summary fields at once.
    # Output: TSV line: rec_count\tboundary_ts\tfired\tfiles_touched\ttotal_lines\tlargest_file_lines
    local summary
    summary=$(scope_read | jq -r '
        . as $s
        | ($s.records // []) as $recs
        | [
            ($recs | length),
            ($s.boundary_set_at // 0),
            ($s.fired_this_boundary // false),
            ([$recs[].file] | unique | length),
            ([$recs[].lines] | add // 0),
            (if ($recs | length) == 0 then 0
             else [$recs | group_by(.file)[] | map(.lines) | add] | max
             end)
          ]
        | @tsv')

    local rec_count boundary_ts fired files_touched total_lines largest_file_lines
    IFS=$'\t' read -r rec_count boundary_ts fired files_touched total_lines largest_file_lines <<< "$summary"

    if [ "$rec_count" -eq 0 ]; then
        echo "empty_state"
        return 1
    fi

    # Stale boundary → implicit reset, advisory silent this turn
    local now age
    now=$(date +%s)
    age=$((now - boundary_ts))
    if [ "$age" -gt "$SCOPE_BOUNDARY_MAX_AGE" ]; then
        scope_reset ""
        echo "stale_reset"
        _scope_log_history false "stale_reset"
        return 1
    fi

    # Already fired this boundary → suppress
    if [ "$fired" = "true" ]; then
        echo "already_fired"
        return 1
    fi

    if [ "$files_touched" -ge "$SCOPE_FILES_THRESHOLD" ] && \
       [ "$total_lines" -ge "$SCOPE_LINES_THRESHOLD" ]; then
        echo "files_and_lines"
        _scope_log_history true "files_and_lines"
        return 0
    fi
    if [ "$files_touched" -ge "$SCOPE_FILES_ONLY_THRESHOLD" ]; then
        echo "files_only"
        _scope_log_history true "files_only"
        return 0
    fi
    if [ "$largest_file_lines" -ge "$SCOPE_LARGE_FILE_THRESHOLD" ]; then
        echo "large_file"
        _scope_log_history true "large_file"
        return 0
    fi

    echo "below_threshold"
    return 1
}
