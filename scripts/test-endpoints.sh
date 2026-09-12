#!/usr/bin/env bash

# Load .env first so lib.sh can see ports and credentials.
set -a
source "$(dirname "$0")/../.env" 2>/dev/null || true
set +a

source "$(dirname "$0")/lib.sh"
set +e

PASS=0
FAIL=0

ok() { PASS=$((PASS+1)); printf 'PASS  %s\n' "$*"; }
ko() { FAIL=$((FAIL+1)); printf 'FAIL  %s\n' "$*" >&2; }

finish() { printf '\nENDPOINT TESTS: %d passed, %d failed\n' "$PASS" "$FAIL"; }
trap finish EXIT

require_cmd curl
require_cmd python3
wait_for_gateway

body_file="/tmp/te-body-$$"
head_file="/tmp/te-head-$$"
rm -f "$body_file" "$head_file"

cleanup() { rm -f "$body_file" "$head_file"; }
trap 'cleanup; finish' EXIT

json_get() {
  python3 -c "import json,sys; d=json.load(open('$body_file')); v=$1; print('' if v is None or v==False else str(v))" 2>/dev/null
}

png_header_ok() {
  python3 -c "import sys; open('$body_file','rb').read(8) == b'\x89PNG\r\n\x1a\n' and sys.exit(0); sys.exit(1)" 2>/dev/null
}

req() {
  local method="$1" url="$2" data="${3:-}"
  if [[ -n "$data" ]]; then
    curl -sS -o "$body_file" -D "$head_file" -w '%{http_code}' -X "$method" \
      "${AUTH_ARGS[@]}" -H 'Content-Type: application/json' --data "$data" "$url"
  else
    curl -sS -o "$body_file" -D "$head_file" -w '%{http_code}' -X "$method" \
      "${AUTH_ARGS[@]}" "$url"
  fi
  return 0
}

req_noauth() {
  local method="$1" url="$2" data="${3:-}"
  if [[ -n "$data" ]]; then
    curl -sS -o "$body_file" -D "$head_file" -w '%{http_code}' -X "$method" \
      -H 'Content-Type: application/json' --data "$data" "$url"
  else
    curl -sS -o "$body_file" -D "$head_file" -w '%{http_code}' -X "$method" "$url"
  fi
  return 0
}

info 'Testing gateway /health'
code=$(req_noauth GET "$GATEWAY_URL/health")
if [[ "$code" == "200" ]]; then
  [[ "$(json_get "d.get('ok', False)")" == "True" ]] && ok 'gateway /health public returns 200 and ok=True' \
    || ko 'gateway /health public ok is not True'
else
  ko "gateway /health public returned HTTP $code"
fi

code=$(req GET "$GATEWAY_URL/health")
[[ "$code" == "200" ]] && ok 'gateway /health with auth returns 200' \
  || ko "gateway /health with auth returned HTTP $code"
grep -qi '^x-request-id:' "$head_file" && ok 'gateway returns x-request-id header' \
  || ko 'gateway did not return x-request-id header'

info 'Testing gateway authentication'
code=$(req_noauth POST "$GATEWAY_URL/v1/scrape" '{"url":"https://example.com"}')
[[ "$code" == "401" ]] && ok 'gateway /v1/scrape without key returns 401' \
  || ko "gateway /v1/scrape without key returned HTTP $code"
code=$(curl -sS -o "$body_file" -w '%{http_code}' -X POST \
  -H 'Authorization: Bearer wrong' -H 'Content-Type: application/json' \
  --data '{"url":"https://example.com"}' "$GATEWAY_URL/v1/scrape")
[[ "$code" == "401" ]] && ok 'gateway rejects wrong API key' \
  || ko "gateway wrong API key returned HTTP $code"

info 'Testing gateway /v1/scrape'
code=$(req POST "$GATEWAY_URL/v1/scrape" '{"url":"https://example.com","formats":["markdown"]}')
if [[ "$code" == "200" ]]; then
  [[ -n "$(json_get "d.get('data',{}).get('markdown','') or ''")" ]] \
    && ok 'gateway /v1/scrape returns 200 with markdown' \
    || ko 'gateway /v1/scrape response missing markdown'
else
  ko "gateway /v1/scrape returned HTTP $code"
fi
code=$(req POST "$GATEWAY_URL/v1/scrape" '{}')
[[ "$code" == "400" ]] && ok 'gateway /v1/scrape empty body returns 400' \
  || ko "gateway /v1/scrape empty body returned HTTP $code"

info 'Testing gateway /v1/map'
code=$(req POST "$GATEWAY_URL/v1/map" '{"url":"https://example.com","limit":5}')
[[ "$code" == "200" ]] && ok 'gateway /v1/map with limit returns 200' \
  || ko "gateway /v1/map returned HTTP $code"
code=$(req POST "$GATEWAY_URL/v1/map" '{"url":"https://example.com"}')
[[ "$code" == "200" ]] && ok 'gateway /v1/map without limit returns 200' \
  || ko "gateway /v1/map without limit returned HTTP $code"

info 'Testing gateway /v1/crawl'
code=$(req POST "$GATEWAY_URL/v1/crawl" '{"url":"https://example.com","limit":2}')
if [[ "$code" =~ ^20[0-9]$ ]]; then
  job_id=$(json_get "d.get('id') or d.get('jobId') or d.get('data',{}).get('id') or ''")
  if [[ -n "$job_id" ]]; then
    code2=$(req GET "$GATEWAY_URL/v1/crawl/$job_id")
    [[ "$code2" =~ ^20[0-9]$ ]] && ok 'gateway /v1/crawl start and status return 2xx' \
      || ko "gateway /v1/crawl status returned HTTP $code2"
  else
    ko 'gateway /v1/crawl response had no job id'
  fi
else
  ko "gateway /v1/crawl returned HTTP $code"
fi

if [[ "${SKIP_NETWORK_TESTS:-0}" != "1" ]]; then
  info 'Testing gateway /v1/search'
  code=$(req POST "$GATEWAY_URL/v1/search" '{"query":"example domain","limit":3}')
  [[ "$code" == "200" ]] && ok 'gateway /v1/search returns 200' \
    || ko "gateway /v1/search returned HTTP $code"
else
  info 'SKIP_NETWORK_TESTS=1; skipping /v1/search'
fi

info 'Testing gateway /v1/extract'
payload='{"content":"Acme Example Corp was founded in 1999 and is headquartered in Vancouver.","instruction":"Extract the company name, founding year, and city.","schema":{"type":"object","properties":{"company":{"type":"string"},"year":{"type":"integer"},"city":{"type":"string"}},"required":["company","year","city"],"additionalProperties":false}}'
code=$(req POST "$GATEWAY_URL/v1/extract" "$payload")
if [[ "$code" == "200" ]]; then
  year=$(json_get "d.get('data',{}).get('year')")
  model=$(json_get "d.get('provenance',{}).get('model','')")
  if [[ "$year" == "1999" && -n "$model" ]]; then
    ok 'gateway /v1/extract direct content returns 200 with valid data'
  else
    ko "gateway /v1/extract direct content missing year/model: year=$year model=$model"
  fi
else
  ko "gateway /v1/extract direct content returned HTTP $code"
fi

code=$(req POST "$GATEWAY_URL/v1/extract" '{"url":"https://example.com","schema":{"type":"object","properties":{"title":{"type":"string"}},"required":["title"]}}')
if [[ "$code" == "200" ]]; then
  [[ -n "$(json_get "d.get('data',{}).get('title','') or ''")" ]] \
    && ok 'gateway /v1/extract from url returns 200 with title' \
    || ko 'gateway /v1/extract from url missing title'
else
  ko "gateway /v1/extract from url returned HTTP $code"
fi

code=$(req_noauth POST "$GATEWAY_URL/v1/extract" '{"url":"https://example.com","schema":{"type":"object","properties":{"title":{"type":"string"}},"required":["title"]}}')
[[ "$code" == "401" ]] && ok 'gateway /v1/extract without key returns 401' \
  || ko "gateway /v1/extract without key returned HTTP $code"
code=$(req POST "$GATEWAY_URL/v1/extract" '{"schema":{}}')
[[ "$code" == "422" ]] && ok 'gateway /v1/extract missing source returns 422' \
  || ko "gateway /v1/extract missing source returned HTTP $code"

info 'Testing gateway /v1/interact'
code=$(req POST "$GATEWAY_URL/v1/interact/sessions" '{}')
if [[ "$code" == "200" ]]; then
  sid=$(json_get "d.get('session_id','')")
  if [[ -n "$sid" ]]; then
    ok 'gateway /v1/interact/sessions creates a session'

    code=$(req POST "$GATEWAY_URL/v1/interact/sessions/$sid/navigate" '{"url":"https://example.com"}')
    if [[ "$code" == "200" ]]; then
      [[ -n "$(json_get "d.get('title','') or ''")" ]] \
        && ok 'gateway /v1/interact navigate works' \
        || ko 'gateway /v1/interact navigate missing title'
    else
      ko "gateway /v1/interact navigate returned HTTP $code"
    fi

    code=$(req GET "$GATEWAY_URL/v1/interact/sessions/$sid/text")
    if [[ "$code" == "200" ]]; then
      [[ -n "$(json_get "d.get('text','') or ''")" ]] \
        && ok 'gateway /v1/interact text works' \
        || ko 'gateway /v1/interact text missing'
    else
      ko "gateway /v1/interact text returned HTTP $code"
    fi

    code=$(curl -sS -o "$body_file" -w '%{http_code}' "${AUTH_ARGS[@]}" \
      "$GATEWAY_URL/v1/interact/sessions/$sid/screenshot")
    if [[ "$code" == "200" ]]; then
      png_header_ok && ok 'gateway /v1/interact screenshot is a PNG' \
        || ko 'gateway /v1/interact screenshot is not a PNG'
    else
      ko "gateway /v1/interact screenshot returned HTTP $code"
    fi

    code=$(req POST "$GATEWAY_URL/v1/interact/sessions/$sid/action" '{"action":"wait","value":"500"}')
    [[ "$code" == "200" ]] && ok 'gateway /v1/interact action works' \
      || ko "gateway /v1/interact action returned HTTP $code"

    code=$(req DELETE "$GATEWAY_URL/v1/interact/sessions/$sid")
    [[ "$code" == "200" ]] && ok 'gateway /v1/interact close works' \
      || ko "gateway /v1/interact close returned HTTP $code"

    code=$(req GET "$GATEWAY_URL/v1/interact/sessions/$sid/text")
    [[ "$code" == "404" ]] && ok 'gateway /v1/interact text after close returns 404' \
      || ko "gateway /v1/interact text after close returned HTTP $code"
  else
    ko 'gateway /v1/interact/sessions response had no session_id'
  fi
else
  ko "gateway /v1/interact/sessions returned HTTP $code"
fi

info 'Testing MCP endpoint'
if docker compose exec -T mcp python /app/tests/live_mcp.py >/dev/null 2>&1; then
  ok 'MCP tool discovery and about tool call'
else
  ko 'MCP tool discovery / about tool call failed'
fi

if docker compose exec -T \
  -e MCP_TEST_URL="http://127.0.0.1:8081/mcp" \
  mcp python - <<'PY' >/dev/null 2>&1
import asyncio, os
from fastmcp import Client

async def main():
    async with Client(os.environ['MCP_TEST_URL']) as client:
        result = await client.call_tool('scrape', {'url': 'https://example.com'})
        text = ''.join(str(r) for r in result.content)
        assert 'Example' in text, text
        print('ok')

asyncio.run(main())
PY
then
  ok 'MCP scrape tool call works'
else
  ko 'MCP scrape tool call failed'
fi

info 'Testing supporting services'
if docker compose exec -T redis redis-cli ping 2>/dev/null | grep -q 'PONG'; then
  ok 'redis responds to PING'
else
  ko 'redis did not respond to PING'
fi

if docker compose exec -T rabbitmq rabbitmq-diagnostics -q check_running >/dev/null 2>&1; then
  ok 'rabbitmq is running'
else
  ko 'rabbitmq is not running'
fi

if docker compose exec -T firecrawl-postgres sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; then
  ok 'firecrawl-postgres is ready'
else
  ko 'firecrawl-postgres is not ready'
fi
