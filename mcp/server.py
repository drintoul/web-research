import base64
import json
import os
from typing import Annotated, Any, Literal, TypedDict

import httpx
from fastmcp import FastMCP
from pydantic import Field

GATEWAY = os.getenv("GATEWAY_BASE_URL", "http://gateway:8080").rstrip("/")
API_KEY = os.getenv("GATEWAY_API_KEY", "")

mcp = FastMCP("Web Research")


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}


async def _post(path: str, payload: dict[str, Any]) -> Any:
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.post(f"{GATEWAY}{path}", json=payload, headers=_headers())
        r.raise_for_status()
        return r.json()


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.get(f"{GATEWAY}{path}", params=params, headers=_headers())
        r.raise_for_status()
        return r.json()


ScrapeFormat = Literal[
    "markdown", "html", "rawHtml", "links", "images", "screenshot",
    "summary", "json", "changeTracking", "attributes", "branding",
]


class ScrapeOptions(TypedDict, total=False):
    onlyMainContent: Annotated[bool, Field(description="Return only the main content, excluding headers/footers/nav")]
    waitFor: Annotated[int, Field(description="Milliseconds to wait for the page to load before scraping")]
    includeTags: Annotated[list[str], Field(description="HTML tags to include, e.g. [\"article\", \"p\"]")]
    excludeTags: Annotated[list[str], Field(description="HTML tags to exclude, e.g. [\"nav\", \"footer\"]")]
    mobile: Annotated[bool, Field(description="Emulate a mobile device")]
    skipTlsVerification: Annotated[bool, Field(description="Skip TLS certificate verification")]
    timeout: Annotated[int, Field(description="Request timeout in milliseconds")]
    removeBase64Images: Annotated[bool, Field(description="Remove base64-encoded images from output")]
    blockAds: Annotated[bool, Field(description="Block ads and trackers")]
    proxy: Annotated[Literal["basic", "stealth", "auto"], Field(description="Proxy type for anti-bot protected sites")]
    maxAge: Annotated[int, Field(description="Max age in ms of a cached page to reuse")]
    storeInCache: Annotated[bool, Field(description="Store the result in the page cache")]
    headers: Annotated[dict[str, str], Field(description="Extra HTTP headers, e.g. {\"Cookie\": \"...\"}")]
    actions: Annotated[list[dict[str, Any]], Field(description="Browser actions before scraping, e.g. [{\"type\": \"wait\", \"milliseconds\": 1000}, {\"type\": \"click\", \"selector\": \"#accept\"}]")]
    location: Annotated[dict[str, Any], Field(description="Geo location, e.g. {\"country\": \"US\", \"languages\": [\"en-US\"]}")]
    parsers: Annotated[list[str], Field(description="Document parsers, e.g. [\"pdf\"]")]


class SearchOptions(TypedDict, total=False):
    sources: Annotated[list[Literal["web", "images", "news"]], Field(description="Result sources")]
    categories: Annotated[list[str], Field(description="Categories, e.g. [\"github\", \"research\"]")]
    tbs: Annotated[str, Field(description="Time filter: qdr:h (hour), qdr:d (day), qdr:w (week), qdr:m (month), qdr:y (year)")]
    location: Annotated[str, Field(description="Location name, e.g. \"Germany\"")]
    country: Annotated[str, Field(description="ISO country code, e.g. \"US\"")]
    timeout: Annotated[int, Field(description="Request timeout in milliseconds")]
    ignoreInvalidURLs: Annotated[bool, Field(description="Ignore invalid URLs in results")]
    scrapeOptions: Annotated[ScrapeOptions, Field(description="Scrape each result with these options")]


class MapOptions(TypedDict, total=False):
    search: Annotated[str, Field(description="Boost/rank links relevant to this term (does NOT filter results)")]
    sitemap: Annotated[Literal["include", "skip", "only"], Field(description="How to use the sitemap")]
    includeSubdomains: Annotated[bool, Field(description="Include subdomains of the URL")]
    ignoreQueryParameters: Annotated[bool, Field(description="Ignore query parameters when deduplicating")]
    ignoreCache: Annotated[bool, Field(description="Ignore the cached sitemap")]
    allowExternalLinks: Annotated[bool, Field(description="Allow links to external domains")]
    allowBackwardLinks: Annotated[bool, Field(description="Allow links to parent/sibling paths")]
    timeout: Annotated[int, Field(description="Request timeout in milliseconds")]
    location: Annotated[dict[str, Any], Field(description="Geo location, e.g. {\"country\": \"US\"}")]


class CrawlOptions(TypedDict, total=False):
    includePaths: Annotated[list[str], Field(description="Regex paths to include, e.g. [\"^/blog/\"]")]
    excludePaths: Annotated[list[str], Field(description="Regex paths to exclude")]
    maxDiscoveryDepth: Annotated[int, Field(description="Max link-discovery depth")]
    allowBackwardLinks: Annotated[bool, Field(description="Crawl parent/sibling paths")]
    allowExternalLinks: Annotated[bool, Field(description="Crawl external domains")]
    ignoreSitemap: Annotated[bool, Field(description="Ignore the sitemap when discovering pages")]
    ignoreQueryParameters: Annotated[bool, Field(description="Ignore query parameters when deduplicating")]
    deduplicateSimilarURLs: Annotated[bool, Field(description="Deduplicate similar URLs")]
    delay: Annotated[int, Field(description="Delay in seconds between page scrapes")]
    maxConcurrency: Annotated[int, Field(description="Max concurrent scrapes")]
    webhook: Annotated[dict[str, Any], Field(description="Webhook config, e.g. {\"url\": \"https://...\", \"events\": [\"completed\"]}")]
    scrapeOptions: Annotated[ScrapeOptions, Field(description="Scrape options applied to each page")]


class ExtractOptions(TypedDict, total=False):
    model: Annotated[str, Field(description="Ollama model override")]
    max_retries: Annotated[int, Field(description="Max LLM retries on invalid JSON")]
    limit: Annotated[int, Field(description="Max items to return")]


class BrowserNavigateOptions(TypedDict, total=False):
    wait_until: Annotated[Literal["commit", "domcontentloaded", "load", "networkidle"], Field(description="When to consider navigation complete")]


class BrowserActionOptions(TypedDict, total=False):
    timeout_ms: Annotated[int, Field(description="Element wait timeout in ms (100-60000)")]


class BrowserTextOptions(TypedDict, total=False):
    wait_ms: Annotated[int, Field(description="Wait time in ms before reading text (0-30000)")]
    scroll: Annotated[bool, Field(description="Scroll to the bottom of the page first")]


@mcp.tool
def about() -> str:
    """Describe the capabilities of this self-hosted web research."""
    return "Search, map, scrape and crawl via self-hosted Firecrawl; structured extraction via Ollama; browser interaction via Playwright."


@mcp.tool
async def search(
    query: Annotated[str, Field(description="Search query text")],
    limit: Annotated[int, Field(description="Max number of results")] = 10,
    options: Annotated[SearchOptions | None, Field(description="Additional search options")] = None,
) -> Any:
    """Search the web through the self-hosted Firecrawl search endpoint."""
    payload = {"query": query, "limit": limit}
    if options:
        payload.update(options)
    return await _post("/v1/search", payload)


@mcp.tool
async def map_site(
    url: Annotated[str, Field(description="Website URL to map")],
    limit: Annotated[int, Field(description="Max number of URLs to return")] = 100,
    url_contains: Annotated[str | None, Field(description="Only return links whose URL contains this substring (case-insensitive). Applied after `limit`, so matches may be fewer than `limit`.")] = None,
    options: Annotated[MapOptions | None, Field(description="Additional map options")] = None,
) -> Any:
    """Map discoverable URLs on a website."""
    payload = {"url": url, "limit": limit}
    if options:
        payload.update(options)
    result = await _post("/v1/map", payload)
    if url_contains and isinstance(result, dict) and isinstance(result.get("links"), list):
        needle = url_contains.lower()
        result["links"] = [
            link
            for link in result["links"]
            if needle in (link if isinstance(link, str) else str(link.get("url", ""))).lower()
        ]
    return result


@mcp.tool
async def scrape(
    url: Annotated[str, Field(description="URL of the page to scrape")],
    formats: Annotated[list[ScrapeFormat] | None, Field(description="Output formats")] = None,
    options: Annotated[ScrapeOptions | None, Field(description="Additional scrape options")] = None,
) -> Any:
    """Scrape a URL and return LLM-friendly content."""
    payload = {"url": url, "formats": formats or ["markdown"]}
    if options:
        payload.update(options)
    return await _post("/v1/scrape", payload)


@mcp.tool
async def crawl(
    url: Annotated[str, Field(description="Starting URL to crawl")],
    limit: Annotated[int, Field(description="Max pages to crawl")] = 100,
    options: Annotated[CrawlOptions | None, Field(description="Additional crawl options")] = None,
) -> Any:
    """Start a crawl job."""
    payload = {"url": url, "limit": limit}
    if options:
        payload.update(options)
    return await _post("/v1/crawl", payload)


@mcp.tool
async def crawl_status(
    job_id: Annotated[str, Field(description="Crawl job id returned by crawl")],
) -> Any:
    """Get the status/results of a crawl job."""
    return await _get(f"/v1/crawl/{job_id}")


@mcp.tool
async def extract(
    schema: Annotated[dict[str, Any], Field(description="JSON Schema describing the fields to extract")],
    instruction: Annotated[str, Field(description="Extraction instruction for the LLM")] = "Extract the requested fields.",
    url: Annotated[str | None, Field(description="URL to scrape, then extract from")] = None,
    content: Annotated[Any, Field(description="Raw content to extract from instead of a URL — accepts text or JSON data (e.g. {{lastData}})")] = None,
    options: Annotated[ExtractOptions | None, Field(description="Additional extract options")] = None,
) -> Any:
    """Extract structured JSON from a URL or from supplied content using the provided JSON Schema."""
    payload: dict[str, Any] = {"schema": schema, "instruction": instruction}
    if url:
        payload["url"] = url
    if content:
        payload["content"] = content if isinstance(content, str) else json.dumps(content)
    if options:
        payload.update(options)
    return await _post("/v1/extract", payload)


@mcp.tool
async def interpret(
    question: Annotated[str, Field(description="What the LLM should do with the data, e.g. 'Summarize the key findings' or 'Which URLs look most relevant to X?'")],
    content: Annotated[Any, Field(description="JSON data or text to interpret — e.g. {{lastData}} or {{lastData.links}} from a previous step")],
    model: Annotated[str | None, Field(description="Ollama model override")] = None,
) -> Any:
    """Send JSON results or text to the LLM for interpretation, summary, or analysis. Returns {analysis: string}."""
    payload: dict[str, Any] = {
        "schema": {
            "type": "object",
            "properties": {
                "analysis": {"type": "string", "description": "Free-form analysis answering the instruction"},
            },
            "required": ["analysis"],
            "additionalProperties": False,
        },
        "instruction": question,
        "content": content if isinstance(content, str) else json.dumps(content),
    }
    if model:
        payload["model"] = model
    return await _post("/v1/extract", payload)


@mcp.tool
async def browser_create_session() -> Any:
    """Create an isolated, TTL-limited Playwright browser session."""
    return await _post("/v1/interact/sessions", {})


@mcp.tool
async def browser_navigate(
    session_id: Annotated[str, Field(description="Session id from browser_create_session")],
    url: Annotated[str, Field(description="Public HTTP(S) URL to navigate to")],
    options: Annotated[BrowserNavigateOptions | None, Field(description="Additional navigate options")] = None,
) -> Any:
    """Navigate a browser session to a public HTTP(S) URL. Private/internal destinations are blocked."""
    payload = {"url": url}
    if options:
        payload.update(options)
    return await _post(f"/v1/interact/sessions/{session_id}/navigate", payload)


@mcp.tool
async def browser_action(
    session_id: Annotated[str, Field(description="Session id from browser_create_session")],
    action: Annotated[Literal["click", "type", "press", "select"], Field(description="Action type")],
    selector: Annotated[str | None, Field(description="CSS selector of the target element")] = None,
    description: Annotated[str | None, Field(description="Natural-language description of the element (used when no selector)")] = None,
    value: Annotated[str | None, Field(description="Text to type, or option to select")] = None,
    key: Annotated[str | None, Field(description="Key for press, e.g. \"Enter\"")] = None,
    allow_consequential: Annotated[bool, Field(description="Approve potentially consequential clicks")] = False,
    options: Annotated[BrowserActionOptions | None, Field(description="Additional action options")] = None,
) -> Any:
    """Perform a browser action. Consequential clicks are blocked unless explicitly approved."""
    payload = {
        "action": action,
        "selector": selector,
        "description": description,
        "value": value,
        "key": key,
        "allow_consequential": allow_consequential,
    }
    if options:
        payload.update(options)
    return await _post(f"/v1/interact/sessions/{session_id}/action", payload)


@mcp.tool
async def browser_text(
    session_id: Annotated[str, Field(description="Session id from browser_create_session")],
    options: Annotated[BrowserTextOptions | None, Field(description="wait_ms / scroll options")] = None,
) -> Any:
    """Read visible page text from a browser session. Options: wait_ms (int), scroll (bool)."""
    params = {k: v for k, v in (options or {}).items() if k in ("wait_ms", "scroll")}
    return await _get(f"/v1/interact/sessions/{session_id}/text", params)


@mcp.tool
async def browser_screenshot(
    session_id: Annotated[str, Field(description="Session id from browser_create_session")],
) -> dict[str, str]:
    """Capture a full-page PNG screenshot as base64."""
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.get(f"{GATEWAY}/v1/interact/sessions/{session_id}/screenshot", headers=_headers())
        r.raise_for_status()
        return {"media_type": "image/png", "base64": base64.b64encode(r.content).decode("ascii")}


@mcp.tool
async def browser_close_session(
    session_id: Annotated[str, Field(description="Session id from browser_create_session")],
) -> Any:
    """Close and destroy a browser session."""
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.delete(f"{GATEWAY}/v1/interact/sessions/{session_id}", headers=_headers())
        r.raise_for_status()
        return r.json()


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8081, path="/mcp")
