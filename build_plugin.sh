#!/usr/bin/env bash
# build_plugin.sh — Build and optionally install the Cowork plugin
# Mirrors the structure of the working Cowork plugin:
#   .claude-plugin/plugin.json, commands/, skills/, hooks/, README.md
#
# Usage:
#   bash build_plugin.sh              # Build zip only
#   bash build_plugin.sh --install    # Build zip + install directly to Claude app
#   bash build_plugin.sh [output_path] # Build zip to custom path
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION=$(cat "$SCRIPT_DIR/VERSION" 2>/dev/null || echo "0.0.0")

INSTALL_MODE=false
OUTPUT=""
for arg in "$@"; do
  case "$arg" in
    --install) INSTALL_MODE=true ;;
    *) OUTPUT="$arg" ;;
  esac
done
[ -z "$OUTPUT" ] && OUTPUT="$SCRIPT_DIR/project-bootstrap-v${VERSION}.zip"

# Find ALL installed plugin locations (Claude Mac app has local + remote copies)
PLUGIN_INSTALL_DIRS=()
MARKETPLACE_JSON=""
# NOTE: These paths depend on Anthropic's internal Claude app directory structure.
# If Anthropic changes the layout in a future update, the --install hook will break.
# The guard below ensures graceful degradation (empty PLUGIN_INSTALL_DIRS → skip).
CLAUDE_SESSIONS="$HOME/Library/Application Support/Claude/local-agent-mode-sessions"
if [ -d "$CLAUDE_SESSIONS" ]; then
  # Local copy
  local_dir=$(find "$CLAUDE_SESSIONS" -path "*/local-desktop-app-uploads/project-bootstrap/.claude-plugin/plugin.json" -print -quit 2>/dev/null | sed 's|/.claude-plugin/plugin.json$||' || true)
  [ -n "$local_dir" ] && PLUGIN_INSTALL_DIRS+=("$local_dir")
  # Remote copy (synced from server)
  remote_dir=$(find "$CLAUDE_SESSIONS" -path "*/remote_cowork_plugins/*/project-bootstrap" -prune -print -quit 2>/dev/null || true)
  [ -z "$remote_dir" ] && remote_dir=$(find "$CLAUDE_SESSIONS" -path "*/remote_cowork_plugins/*/.claude-plugin/plugin.json" -exec grep -l '"project-bootstrap"' {} \; 2>/dev/null | head -1 | sed 's|/.claude-plugin/plugin.json$||' || true)
  [ -n "$remote_dir" ] && PLUGIN_INSTALL_DIRS+=("$remote_dir")
  # Marketplace registry
  MARKETPLACE_JSON=$(find "$CLAUDE_SESSIONS" -path "*/local-desktop-app-uploads/.claude-plugin/marketplace.json" -print -quit 2>/dev/null || true)
fi

PLUGIN_DIR="project-bootstrap"

echo "Building Cowork plugin zip v${VERSION}..."

# Remove old zip if it exists at the target path
rm -f "$OUTPUT"

# Create a temp staging directory with the plugin name as wrapper
STAGING=$(mktemp -d)
PLUGIN_STAGE="$STAGING/$PLUGIN_DIR"
mkdir -p "$PLUGIN_STAGE"

# 1. Manifest (auto-stamp version from VERSION file)
cp -r "$SCRIPT_DIR/.claude-plugin" "$PLUGIN_STAGE/"
python3 -c "
import json
with open('$PLUGIN_STAGE/.claude-plugin/plugin.json') as f:
    data = json.load(f)
data['version'] = '$VERSION'
with open('$PLUGIN_STAGE/.claude-plugin/plugin.json', 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')
"

# 2. Skills (public skill allowlist)
ALLOWED_SKILLS=(bootstrap-activate bootstrap-discovery spec-status)

mkdir -p "$PLUGIN_STAGE/skills"
for skill_name in "${ALLOWED_SKILLS[@]}"; do
  skill_src="$SCRIPT_DIR/skills/$skill_name"
  if [ -d "$skill_src" ]; then
    cp -r "$skill_src" "$PLUGIN_STAGE/skills/$skill_name"
  else
    echo "WARNING: Allowed skill '$skill_name' not found at $skill_src" >&2
  fi
done

# 3. Commands (flat .md files for Cowork slash commands — allowed skills only)
mkdir -p "$PLUGIN_STAGE/commands"
for skill_name in "${ALLOWED_SKILLS[@]}"; do
  skill_dir="$SCRIPT_DIR/skills/$skill_name"
  if [ -f "$skill_dir/SKILL.md" ]; then
    # Extract full multi-line description from SKILL.md frontmatter
    # Captures 'description: >' through all indented continuation lines
    desc=$(awk '
      /^description:/ { sub(/^description: *>? */, ""); if ($0 != "") print; capturing=1; next }
      capturing && /^  / { sub(/^  */, ""); print; next }
      capturing { exit }
    ' "$skill_dir/SKILL.md" | tr '\n' ' ' | sed 's/  */ /g; s/ *$//')
    [ -z "$desc" ] && desc="Run the $skill_name skill"
    # Extract first heading line from SKILL.md body as the command summary
    body_line=$(sed -n '/^# /{s/^# *//; p; q;}' "$skill_dir/SKILL.md")
    [ -z "$body_line" ] && body_line="Activate the $skill_name skill"
    # Escape description for YAML: wrap in double quotes, escape internal quotes
    desc_yaml=$(echo "$desc" | sed 's/"/\\"/g')
    cat > "$PLUGIN_STAGE/commands/$skill_name.md" << CMDEOF
---
description: "$desc_yaml"
---

$body_line
CMDEOF
  fi
done

# 4. Hooks (hooks.json referencing skill hook scripts)
mkdir -p "$PLUGIN_STAGE/hooks"
cat > "$PLUGIN_STAGE/hooks/hooks.json" << 'HOOKEOF'
{
  "SessionStart": [
    {
      "matcher": "",
      "hooks": [
        {
          "type": "command",
          "command": "bash ${CLAUDE_PLUGIN_ROOT}/skills/bootstrap-activate/references/hooks/preflight-check.sh",
          "timeout": 10
        }
      ]
    }
  ]
}
HOOKEOF

# 5. Prerequisites manifest
cp "$SCRIPT_DIR/prerequisites.json" "$PLUGIN_STAGE/"

# 6. README
cp "$SCRIPT_DIR/README.md" "$PLUGIN_STAGE/"

# 7. Build-time validation: verify all hook script references resolve
for hook_script in $(grep -o 'references/hooks/[^"]*\.sh' "$PLUGIN_STAGE/hooks/hooks.json"); do
  target="$PLUGIN_STAGE/skills/bootstrap-activate/$hook_script"
  if [ ! -f "$target" ]; then
    echo "BUILD ERROR: hooks.json references '$hook_script' but file not found at:" >&2
    echo "  $target" >&2
    rm -rf "$STAGING"
    exit 1
  fi
done

# Clean up any __pycache__ or .pyc that snuck in
find "$PLUGIN_STAGE" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$PLUGIN_STAGE" -name "*.pyc" -delete 2>/dev/null || true

# ── Engine bundle ─────────────────────────────────────────────────────────────
echo "Bundling engine..."
ENGINE_DIR="$PLUGIN_STAGE/engine"
mkdir -p "$ENGINE_DIR"

# Core engine files
cp "$SCRIPT_DIR/bootstrap_project.sh" "$ENGINE_DIR/"
cp "$SCRIPT_DIR/VERSION" "$ENGINE_DIR/"
[ -f "$SCRIPT_DIR/SYSTEMS_MANIFEST.json" ] && cp "$SCRIPT_DIR/SYSTEMS_MANIFEST.json" "$ENGINE_DIR/"

# Templates tree (the full asset set)
cp -r "$SCRIPT_DIR/templates" "$ENGINE_DIR/templates"

# Prune dev-only artifacts from bundled templates
find "$ENGINE_DIR/templates" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$ENGINE_DIR/templates" -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true
find "$ENGINE_DIR/templates" -name "*.pyc" -delete 2>/dev/null || true
find "$ENGINE_DIR/templates" -name "test_*.py" -delete 2>/dev/null || true

ENGINE_SIZE=$(du -sh "$ENGINE_DIR" | cut -f1)
echo "  Engine bundled (${ENGINE_SIZE})"

# 8. Build-time validation: verify engine bundle contents
VALIDATION_ERRORS=0

if [ ! -f "$ENGINE_DIR/bootstrap_project.sh" ]; then
  echo "BUILD ERROR: engine/bootstrap_project.sh not found in bundle" >&2
  VALIDATION_ERRORS=$((VALIDATION_ERRORS + 1))
fi

if [ ! -f "$ENGINE_DIR/templates/scripts/dbq/__main__.py" ]; then
  echo "BUILD ERROR: engine/templates/scripts/dbq/__main__.py not found in bundle" >&2
  VALIDATION_ERRORS=$((VALIDATION_ERRORS + 1))
fi

FRAMEWORK_MD_COUNT=$(find "$ENGINE_DIR/templates/frameworks" -name "*.md" 2>/dev/null | wc -l | tr -d ' ')
if [ "${FRAMEWORK_MD_COUNT}" -lt 5 ]; then
  echo "BUILD ERROR: engine/templates/frameworks/ has only ${FRAMEWORK_MD_COUNT} .md files (expected >= 5)" >&2
  VALIDATION_ERRORS=$((VALIDATION_ERRORS + 1))
fi

if [ "$VALIDATION_ERRORS" -gt 0 ]; then
  rm -rf "$STAGING"
  exit 1
fi

# Build zip from staging
cd "$STAGING"
zip -r "$OUTPUT" "$PLUGIN_DIR/"

# Clean up
rm -rf "$STAGING"

echo ""
echo "✓ Built: $OUTPUT (${#ALLOWED_SKILLS[@]} skills + engine)"
echo "  Size: $(du -h "$OUTPUT" | cut -f1)"
echo "  Files: $(unzip -l "$OUTPUT" | tail -1 | awk '{print $2}')"

# Direct install to Claude app if requested or if --install flag
if [ "$INSTALL_MODE" = true ]; then
  if [ ${#PLUGIN_INSTALL_DIRS[@]} -eq 0 ]; then
    echo ""
    echo "⚠ Cannot auto-install: Claude app plugin directory not found."
    echo "  Upload the zip manually: Claude.ai → Customize → Browse plugins → Local uploads → +"
  else
    echo ""
    echo "Installing to Claude app..."
    INSTALL_STAGING=$(mktemp -d)
    unzip -qo "$OUTPUT" -d "$INSTALL_STAGING"
    for target_dir in "${PLUGIN_INSTALL_DIRS[@]}"; do
      rm -rf "$target_dir/skills" "$target_dir/commands" "$target_dir/hooks"
      cp -r "$INSTALL_STAGING/$PLUGIN_DIR/." "$target_dir/"
      echo "  ✓ Updated: $(echo "$target_dir" | sed "s|.*local-agent-mode-sessions/[^/]*/[^/]*/||")"
    done
    rm -rf "$INSTALL_STAGING"
    # Update marketplace.json version
    if [ -n "$MARKETPLACE_JSON" ] && [ -f "$MARKETPLACE_JSON" ]; then
      python3 -c "
import json, sys
with open('$MARKETPLACE_JSON') as f:
    data = json.load(f)
for p in data.get('plugins', []):
    if p['name'] == 'project-bootstrap':
        p['version'] = '$VERSION'
with open('$MARKETPLACE_JSON', 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')
" 2>/dev/null && echo "  ✓ Updated marketplace registry"
    fi
    echo ""
    echo "✓ Installed v${VERSION} to Claude app (${#PLUGIN_INSTALL_DIRS[@]} locations)"
    echo "  Restart Claude app to pick up changes."
  fi
else
  echo ""
  echo "To install directly: bash build_plugin.sh --install"
fi
