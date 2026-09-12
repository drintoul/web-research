#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

"$ROOT_DIR/scripts/test-security.sh"
"$ROOT_DIR/scripts/test-functionality.sh"
"$ROOT_DIR/scripts/test-mcp.sh"

printf '\nALL TESTS PASSED\n'
