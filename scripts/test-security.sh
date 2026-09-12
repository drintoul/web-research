#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"

require_cmd curl
require_cmd python3
wait_for_gateway

info "Live security tests against $GATEWAY_URL"

# Authentication should reject bad credentials when a gateway key is configured.
if [[ -n "${GATEWAY_API_KEY:-}" ]]; then
  code="$(curl -sS -o /dev/null -w '%{http_code}' -H 'Authorization: Bearer definitely-wrong' "$GATEWAY_URL/v1/search")"
  [[ "$code" == "401" ]] || fail "bad API key was not rejected (HTTP $code)"
  pass "gateway rejects invalid API key"
else
  info "GATEWAY_API_KEY is empty; authentication rejection test skipped"
fi

# Create a browser session for SSRF tests.
readarray -t r < <(http_json POST "$GATEWAY_URL/v1/interact/sessions" '{}')
[[ "${r[0]}" == "200" ]] || fail "could not create browser session: ${r[*]}"
session_id="$(printf '%s' "${r[*]:1}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["session_id"])')"
trap 'curl -sS -X DELETE "${AUTH_ARGS[@]}" "$GATEWAY_URL/v1/interact/sessions/$session_id" >/dev/null 2>&1 || true' EXIT

for blocked in \
  'http://127.0.0.1/' \
  'http://10.0.0.1/' \
  'http://169.254.169.254/latest/meta-data/' \
  'http://192.168.1.1/' \
  'file:///etc/passwd'; do
  payload="$(python3 -c 'import json,sys; print(json.dumps({"url":sys.argv[1]}))' "$blocked")"
  readarray -t r < <(http_json POST "$GATEWAY_URL/v1/interact/sessions/$session_id/navigate" "$payload")
  [[ "${r[0]}" == "400" ]] || fail "SSRF/non-HTTP target was not blocked: $blocked (HTTP ${r[0]})"
done
pass "browser blocks private, link-local, loopback, and non-HTTP destinations"

# Credentials embedded in URLs are prohibited.
readarray -t r < <(http_json POST "$GATEWAY_URL/v1/interact/sessions/$session_id/navigate" '{"url":"https://user:password@example.com/"}')
[[ "${r[0]}" == "400" ]] || fail "credential-bearing URL was not blocked (HTTP ${r[0]})"
pass "browser blocks credentials embedded in URLs"

# Unknown sessions should not leak details or succeed.
readarray -t r < <(http_json GET "$GATEWAY_URL/v1/interact/sessions/00000000-0000-0000-0000-000000000000/text")
[[ "${r[0]}" == "404" ]] || fail "unknown browser session did not return 404 (HTTP ${r[0]})"
pass "unknown browser sessions are rejected"

# Unit-level security regression suite runs inside the already-built gateway image.
(
  cd "$ROOT_DIR"
  docker compose run --rm --no-deps gateway pytest -q tests/test_security.py tests/test_http_security.py
)
pass "unit security regression suite"

info "Security tests completed successfully"
