#!/usr/bin/env bash
set -uo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

FAILED=0

run() {
    local name="$1"
    shift
    printf '\n--- %s ---\n' "$name"
    if "$@"; then
        printf 'OK: %s\n' "$name"
    else
        printf 'FAILED: %s\n' "$name"
        FAILED=1
    fi
}

run "security tests" "$ROOT_DIR/scripts/test-security.sh"
run "functionality tests" "$ROOT_DIR/scripts/test-functionality.sh"
run "MCP smoke test" "$ROOT_DIR/scripts/test-mcp.sh"
run "endpoint regression" "$ROOT_DIR/scripts/test-endpoints.sh"
run "Python MCP smoke" python3 "$ROOT_DIR/tests/test_mcp_smoke.py"
run "Python MCP tool tests" python3 "$ROOT_DIR/tests/test_mcp_tools.py"
run "Python gateway REST tests" python3 "$ROOT_DIR/tests/test_gateway_rest.py"
run "Python LangGraph planner tests" python3 "$ROOT_DIR/tests/test_langgraph_planner.py"

if [ "$FAILED" -ne 0 ]; then
    printf '\nSOME TESTS FAILED\n'
    exit 1
fi

printf '\nALL TESTS PASSED\n'
