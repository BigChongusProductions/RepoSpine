#!/usr/bin/env bash
# probe-providers.sh — capability-detection preamble for /research
#
# Checks which provider tiers are reachable and writes a status JSON.
# Always exits 0: missing providers are a valid state for optional tiers.
# Hard-fail on missing Tavily is the caller's responsibility (SKILL.md).
#
# Output: .claude/skills/research/.provider-status.json

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
STATUS_FILE="$SKILL_DIR/.provider-status.json"
CONF_FILE="${RESEARCH_PROVIDERS_CONF:-$(cd "$SKILL_DIR/../../../" && pwd)/.claude/research-providers.conf}"

tier_enabled() {
    local tier="$1"
    [ -f "$CONF_FILE" ] || { echo "true"; return; }
    local line
    # Accept leading whitespace on `enabled =` lines (common INI indentation);
    # trim surrounding whitespace from the extracted value too.
    line=$(awk -v t="$tier" '
        $0 ~ "^\\[" t "\\]" { found=1; next }
        /^\[/ { found=0 }
        found && /^[ \t]*enabled[ \t]*=/ {
            sub(/^[ \t]*enabled[ \t]*=[ \t]*/, "")
            sub(/[ \t]+$/, "")
            print; exit
        }
    ' "$CONF_FILE")
    case "$line" in
        false|0|no|off|False|FALSE|No|NO|Off|OFF) echo "false" ;;
        *) echo "true" ;;
    esac
}

probe_tavily() {
    if [ "$(tier_enabled 'T1:tavily')" = "false" ]; then
        echo '{"available": false, "reason": "disabled in research-providers.conf"}'
        return
    fi
    if [ -n "${TAVILY_API_KEY:-}" ]; then
        echo '{"available": true, "reason": "TAVILY_API_KEY present"}'
    else
        echo '{"available": false, "reason": "TAVILY_API_KEY missing"}'
    fi
}

probe_gemini() {
    if [ "$(tier_enabled 'T2:gemini')" = "false" ]; then
        echo '{"available": false, "reason": "disabled in research-providers.conf"}'
        return
    fi
    if [ -n "${GEMINI_API_KEY:-}" ]; then
        echo '{"available": true, "reason": "GEMINI_API_KEY present"}'
    elif [ -n "${GOOGLE_API_KEY:-}" ]; then
        echo '{"available": true, "reason": "GOOGLE_API_KEY present"}'
    else
        echo '{"available": false, "reason": "no GEMINI_API_KEY or GOOGLE_API_KEY; Gemini MCP may still be registered"}'
    fi
}

probe_ollama() {
    if [ "$(tier_enabled 'T3:ollama')" = "false" ]; then
        echo '{"available": false, "reason": "disabled in research-providers.conf"}'
        return
    fi
    local host="${OLLAMA_HOST:-http://localhost:11434}"
    if command -v curl >/dev/null 2>&1; then
        if curl -fsS --max-time 2 "$host/api/tags" >/dev/null 2>&1; then
            echo "{\"available\": true, \"reason\": \"Ollama reachable at $host\"}"
            return
        fi
    fi
    echo "{\"available\": false, \"reason\": \"no Ollama at $host (check OLLAMA_HOST or MCP)\"}"
}

probe_grok() {
    if [ "$(tier_enabled 'T4:grok')" = "false" ]; then
        echo '{"available": false, "reason": "disabled in research-providers.conf"}'
        return
    fi
    if [ -n "${GROK_API_KEY:-}" ] || [ -n "${XAI_API_KEY:-}" ]; then
        echo '{"available": true, "reason": "GROK_API_KEY or XAI_API_KEY present"}'
    else
        echo '{"available": false, "reason": "GROK_API_KEY/XAI_API_KEY missing"}'
    fi
}

TAVILY=$(probe_tavily)
GEMINI=$(probe_gemini)
OLLAMA=$(probe_ollama)
GROK=$(probe_grok)

mkdir -p "$(dirname "$STATUS_FILE")"
cat > "$STATUS_FILE" <<EOF
{
  "probed_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "tavily":  $TAVILY,
  "gemini":  $GEMINI,
  "ollama":  $OLLAMA,
  "grok":    $GROK
}
EOF

if command -v jq >/dev/null 2>&1; then
    jq . "$STATUS_FILE"
else
    cat "$STATUS_FILE"
fi

# Derive the hard-fail condition for the caller to act on.
if [ "$(tier_enabled 'T1:tavily')" != "false" ] && [ -z "${TAVILY_API_KEY:-}" ]; then
    echo ""
    echo "❌ T1 (Tavily) is required but TAVILY_API_KEY is missing. /research cannot run."
    exit 2
fi

exit 0
