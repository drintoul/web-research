#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:${GATEWAY_PORT:-8080}}"
MCP_URL="${MCP_URL:-http://127.0.0.1:${MCP_PORT:-8081}/mcp}"
TEST_URL="${TEST_URL:-https://example.com}"
SEARCH_QUERY="${SEARCH_QUERY:-example domain}"

# If GATEWAY_API_KEY was not exported, read it from .env without sourcing arbitrary shell.
if [[ -z "${GATEWAY_API_KEY:-}" && -f "$ROOT_DIR/.env" ]]; then
  GATEWAY_API_KEY="$(sed -n 's/^GATEWAY_API_KEY=//p' "$ROOT_DIR/.env" | tail -n1 | tr -d '\r')"
fi

AUTH_ARGS=()
if [[ -n "${GATEWAY_API_KEY:-}" ]]; then
  AUTH_ARGS=(-H "Authorization: Bearer ${GATEWAY_API_KEY}")
fi

pass() { printf 'PASS  %s\n' "$*"; }
fail() { printf 'FAIL  %s\n' "$*" >&2; exit 1; }
info() { printf 'INFO  %s\n' "$*"; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

json_get() {
  local expr="$1"
  python3 -c "import json,sys; d=json.load(sys.stdin); print($expr)"
}

http_json() {
  # Usage: http_json METHOD URL [JSON]
  local method="$1" url="$2" body="${3:-}"
  local out status payload
  out="$(mktemp)"
  if [[ -n "$body" ]]; then
    status="$(curl -sS -o "$out" -w '%{http_code}' -X "$method" \
      "${AUTH_ARGS[@]}" -H 'Content-Type: application/json' --data "$body" "$url")"
  else
    status="$(curl -sS -o "$out" -w '%{http_code}' -X "$method" \
      "${AUTH_ARGS[@]}" "$url")"
  fi
  payload="$(cat "$out")"
  rm -f "$out"
  printf '%s\n%s' "$status" "$payload"
}

wait_for_gateway() {
  local tries="${1:-60}"
  for ((i=1; i<=tries; i++)); do
    if curl -fsS "$GATEWAY_URL/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  fail "gateway did not become reachable at $GATEWAY_URL"
}
