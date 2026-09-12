#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"

require_cmd docker

info "MCP smoke tests against $MCP_URL"
cd "$ROOT_DIR"
# Execute from the running MCP container so FastMCP is guaranteed to be installed.
docker compose exec -T \
  -e MCP_TEST_URL="http://127.0.0.1:8081/mcp" \
  mcp python /app/tests/live_mcp.py
pass "MCP initialize, tool discovery, and about tool call"
