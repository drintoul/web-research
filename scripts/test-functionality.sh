#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"

require_cmd curl
require_cmd python3
wait_for_gateway

info "REST functionality tests against $GATEWAY_URL"

# 1. Health and correlation ID
headers="$(mktemp)"
body="$(mktemp)"
code="$(curl -sS -D "$headers" -o "$body" -w '%{http_code}' "$GATEWAY_URL/health")"
[[ "$code" == "200" ]] || fail "GET /health returned HTTP $code: $(cat "$body")"
python3 - "$body" <<'PY'
import json,sys
p=json.load(open(sys.argv[1]))
assert p.get('services',{}).get('gateway') is True, p
PY
grep -qi '^x-request-id:' "$headers" || fail "gateway did not return x-request-id"
rm -f "$headers" "$body"
pass "gateway health and request ID"

if [[ "${SKIP_NETWORK_TESTS:-0}" != "1" ]]; then
  # 2. Search -> Firecrawl -> external SearXNG
  readarray -t r < <(http_json POST "$GATEWAY_URL/v1/search" "{\"query\":\"$SEARCH_QUERY\",\"limit\":3}")
  [[ "${r[0]}" == "200" ]] || fail "search returned HTTP ${r[0]}: ${r[*]:1}"
  printf '%s' "${r[*]:1}" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d, d'
  pass "search -> Firecrawl -> SearXNG"

  # 3. Map
  readarray -t r < <(http_json POST "$GATEWAY_URL/v1/map" "{\"url\":\"$TEST_URL\",\"limit\":10}")
  [[ "${r[0]}" == "200" ]] || fail "map returned HTTP ${r[0]}: ${r[*]:1}"
  pass "map"

  # 4. Scrape
  readarray -t r < <(http_json POST "$GATEWAY_URL/v1/scrape" "{\"url\":\"$TEST_URL\",\"formats\":[\"markdown\"]}")
  [[ "${r[0]}" == "200" ]] || fail "scrape returned HTTP ${r[0]}: ${r[*]:1}"
  pass "scrape"

  # 5. Crawl start and status (does not require waiting for completion)
  readarray -t r < <(http_json POST "$GATEWAY_URL/v1/crawl" "{\"url\":\"$TEST_URL\",\"limit\":2}")
  [[ "${r[0]}" =~ ^20[0-9]$ ]] || fail "crawl start returned HTTP ${r[0]}: ${r[*]:1}"
  crawl_json="${r[*]:1}"
  job_id="$(printf '%s' "$crawl_json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("id") or d.get("jobId") or d.get("data",{}).get("id") or "")')"
  if [[ -n "$job_id" ]]; then
    readarray -t s < <(http_json GET "$GATEWAY_URL/v1/crawl/$job_id")
    [[ "${s[0]}" =~ ^20[0-9]$ ]] || fail "crawl status returned HTTP ${s[0]}: ${s[*]:1}"
    pass "crawl start/status"
  else
    info "crawl started but response contained no recognized job id; status check skipped"
  fi
else
  info "SKIP_NETWORK_TESTS=1; skipping search/map/scrape/crawl"
fi

# 6. Extract using direct content; isolates the Ollama path from Firecrawl.
extract_payload='{"content":"Acme Example Corp was founded in 1999 and is headquartered in Vancouver.","instruction":"Extract the company name, founding year, and city.","schema":{"type":"object","properties":{"company":{"type":"string"},"year":{"type":"integer"},"city":{"type":"string"}},"required":["company","year","city"],"additionalProperties":false}}'
readarray -t r < <(http_json POST "$GATEWAY_URL/v1/extract" "$extract_payload")
[[ "${r[0]}" == "200" ]] || fail "extract returned HTTP ${r[0]}: ${r[*]:1}"
printf '%s' "${r[*]:1}" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("data",{}).get("year")==1999, d; assert d.get("provenance",{}).get("model"), d'
pass "extract -> external Ollama + JSON Schema validation"

# 7. Browser session / navigation / text / screenshot / close
readarray -t r < <(http_json POST "$GATEWAY_URL/v1/interact/sessions" '{}')
[[ "${r[0]}" == "200" ]] || fail "browser session create returned HTTP ${r[0]}: ${r[*]:1}"
session_id="$(printf '%s' "${r[*]:1}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["session_id"])')"
trap '[[ -n "${session_id:-}" ]] && curl -sS -X DELETE "${AUTH_ARGS[@]}" "$GATEWAY_URL/v1/interact/sessions/$session_id" >/dev/null 2>&1 || true' EXIT

readarray -t r < <(http_json POST "$GATEWAY_URL/v1/interact/sessions/$session_id/navigate" "{\"url\":\"$TEST_URL\"}")
[[ "${r[0]}" == "200" ]] || fail "browser navigate returned HTTP ${r[0]}: ${r[*]:1}"
pass "browser navigate"

readarray -t r < <(http_json GET "$GATEWAY_URL/v1/interact/sessions/$session_id/text")
[[ "${r[0]}" == "200" ]] || fail "browser text returned HTTP ${r[0]}: ${r[*]:1}"
printf '%s' "${r[*]:1}" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert len(d.get("text",""))>0, d'
pass "browser text"

shot="$(mktemp --suffix=.png)"
shot_code="$(curl -sS -o "$shot" -w '%{http_code}' "${AUTH_ARGS[@]}" "$GATEWAY_URL/v1/interact/sessions/$session_id/screenshot")"
[[ "$shot_code" == "200" ]] || fail "browser screenshot returned HTTP $shot_code"
python3 - "$shot" <<'PY'
import sys
with open(sys.argv[1],'rb') as f:
    assert f.read(8) == b'\x89PNG\r\n\x1a\n'
PY
rm -f "$shot"
pass "browser screenshot"

readarray -t r < <(http_json DELETE "$GATEWAY_URL/v1/interact/sessions/$session_id")
[[ "${r[0]}" == "200" ]] || fail "browser close returned HTTP ${r[0]}: ${r[*]:1}"
session_id=""
pass "browser close"

info "REST functionality tests completed successfully"
