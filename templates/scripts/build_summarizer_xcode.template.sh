#!/usr/bin/env bash
# %%PROJECT_NAME%% — Xcode Build Summarizer
# ─────────────────────────────────────────────────────────────────────────────
# PURPOSE: Wrap xcodebuild and return a compact digest.
#          Claude reads ~5 lines instead of 150-500 lines of raw xcodebuild.
#
# USAGE:
#   bash build_summarizer.sh build   → build only
#   bash build_summarizer.sh test    → build + run tests
#   bash build_summarizer.sh clean   → clean + build
#
# OUTPUT:  Pass/fail summary with only errors/warnings/failures listed
# TOKENS:  ~100 (vs 1,000-5,000 reading raw xcodebuild output)
#
# PLACEHOLDERS:
#   %%XCODE_PROJECT_PATH%%  — relative path to .xcodeproj (e.g. MyApp/MyApp.xcodeproj)
#   %%XCODE_SCHEME%%        — build scheme name (e.g. MyApp)
#   %%XCODE_TEST_SCHEME%%   — test scheme name (e.g. MyAppTests)
#   %%PROJECT_NAME%%        — project display name for output headers
# ─────────────────────────────────────────────────────────────────────────────

DIR="$(dirname "$0")"
PROJECT="$DIR/%%XCODE_PROJECT_PATH%%"
SCHEME="%%XCODE_SCHEME%%"
TEST_SCHEME="%%XCODE_TEST_SCHEME%%"
MODE="${1:-build}"

# Auto-detect an available iOS simulator
SIMULATOR_ID=$(xcrun simctl list devices available -j 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
for runtime, devices in data.get('devices', {}).items():
    if 'iOS' in runtime:
        for d in devices:
            if d.get('isAvailable'):
                print(d['udid']); sys.exit(0)
" 2>/dev/null || echo "")

if [ -z "$SIMULATOR_ID" ]; then
    echo "  No available iOS simulator found. Install one via Xcode > Settings > Platforms."
    exit 1
fi

DESTINATION="platform=iOS Simulator,id=$SIMULATOR_ID"

if [ ! -d "$PROJECT" ]; then
    echo "  Project not found: $PROJECT"
    exit 1
fi

# ── BUILD ────────────────────────────────────────────────────────────────────
run_build() {
    local clean_flag=""
    [ "$MODE" = "clean" ] && clean_flag="clean"

    BUILD_OUTPUT=$(xcodebuild $clean_flag build \
        -project "$PROJECT" \
        -scheme "$SCHEME" \
        -destination "$DESTINATION" \
        -quiet \
        2>&1)
    BUILD_EXIT=$?

    # Extract errors and warnings
    ERRORS=$(echo "$BUILD_OUTPUT" | grep -E "^.+error:" | grep -v "^note:" | head -10)
    WARNINGS=$(echo "$BUILD_OUTPUT" | grep -E "^.+warning:" | grep -v "^note:" | head -5)
    ERROR_COUNT=$(echo "$BUILD_OUTPUT" | grep -cE "error:" || true)
    WARNING_COUNT=$(echo "$BUILD_OUTPUT" | grep -cE "warning:" || true)

    if [ $BUILD_EXIT -eq 0 ]; then
        echo "  Build: CLEAN  (${WARNING_COUNT} warning(s))"
        if [ -n "$WARNINGS" ] && [ "$WARNING_COUNT" -gt 0 ]; then
            echo "$WARNINGS" | while IFS= read -r line; do
                short=$(echo "$line" | sed "s|.*/%%PROJECT_NAME%%/||")
                echo "     $short"
            done
        fi
    else
        echo "  Build: FAILED  ($ERROR_COUNT error(s), $WARNING_COUNT warning(s))"
        if [ -n "$ERRORS" ]; then
            echo "$ERRORS" | while IFS= read -r line; do
                short=$(echo "$line" | sed "s|.*/%%PROJECT_NAME%%/||")
                echo "     $short"
            done
        fi
        return 1
    fi
    return 0
}

# ── TESTS ────────────────────────────────────────────────────────────────────
run_tests() {
    TEST_OUTPUT=$(xcodebuild test \
        -project "$PROJECT" \
        -scheme "$TEST_SCHEME" \
        -destination "$DESTINATION" \
        -quiet \
        2>&1)
    TEST_EXIT=$?

    # Count pass/fail
    PASS_COUNT=$(echo "$TEST_OUTPUT" | grep -c "Test Case.*passed" || true)
    FAIL_COUNT=$(echo "$TEST_OUTPUT" | grep -c "Test Case.*failed" || true)
    FAILURES=$(echo "$TEST_OUTPUT" | grep -E "Test Case.*failed|FAILED|error:" | head -8)

    if [ $TEST_EXIT -eq 0 ]; then
        echo "  Tests: $PASS_COUNT passed, 0 failed"
    else
        echo "  Tests: $PASS_COUNT passed, $FAIL_COUNT FAILED"
        if [ -n "$FAILURES" ]; then
            echo "$FAILURES" | while IFS= read -r line; do
                short=$(echo "$line" | sed "s|.*/%%PROJECT_NAME%%/||" | cut -c1-100)
                echo "     $short"
            done
        fi
        return 1
    fi
    return 0
}

# ── MAIN ─────────────────────────────────────────────────────────────────────
echo ""
echo "  %%PROJECT_NAME%% Build — $(date '+%H:%M:%S')"
echo "  ─────────────────────────────────────────"

BUILD_OK=0
TEST_OK=0

case "$MODE" in
    build|clean)
        run_build || BUILD_OK=1
        ;;
    test)
        run_build && run_tests || BUILD_OK=1
        ;;
    *)
        echo "  Usage: bash build_summarizer.sh [build|test|clean]"
        exit 1
        ;;
esac

echo "  ─────────────────────────────────────────"
echo ""

# Exit code: 0=success, 1=build failed, 2=tests failed
if [ $BUILD_OK -ne 0 ]; then exit 1; fi
if [ $TEST_OK -ne 0 ]; then exit 2; fi
exit 0
