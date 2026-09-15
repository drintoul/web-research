import base64
import os
from typing import Any

import httpx
from fastmcp import FastMCP

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


@mcp.tool
def about() -> str:
    """Describe the capabilities of this self-hosted web research."""
    return "Search, map, scrape and crawl via self-hosted Firecrawl; structured extraction via Ollama; browser interaction via Playwright."


@mcp.tool
async def search(query: str, limit: int = 10, options: dict[str, Any] | None = None) -> Any:
    """Search the web through the self-hosted Firecrawl search endpoint."""
    payload = {"query": query, "limit": limit}
    if options:
        payload.update(options)
    return await _post("/v1/search", payload)


@mcp.tool
async def map_site(url: str, limit: int = 100, options: dict[str, Any] | None = None) -> Any:
    """Map discoverable URLs on a website."""
    payload = {"url": url, "limit": limit}
    if options:
        payload.update(options)
    return await _post("/v1/map", payload)


@mcp.tool
async def scrape(url: str, formats: list[str] | None = None, options: dict[str, Any] | None = None) -> Any:
    """Scrape a URL and return LLM-friendly content."""
    payload = {"url": url, "formats": formats or ["markdown"]}
    if options:
        payload.update(options)
    return await _post("/v1/scrape", payload)


@mcp.tool
async def crawl(url: str, limit: int = 100, options: dict[str, Any] | None = None) -> Any:
    """Start a crawl job."""
    payload = {"url": url, "limit": limit}
    if options:
        payload.update(options)
    return await _post("/v1/crawl", payload)


@mcp.tool
async def crawl_status(job_id: str) -> Any:
    """Get the status/results of a crawl job."""
    return await _get(f"/v1/crawl/{job_id}")


@mcp.tool
async def extract(schema: dict[str, Any], instruction: str = "Extract the requested fields.", url: str | None = None, content: str | None = None, options: dict[str, Any] | None = None) -> Any:
    """Extract structured JSON from a URL or from supplied content using the provided JSON Schema."""
    payload: dict[str, Any] = {"schema": schema, "instruction": instruction}
    if url:
        payload["url"] = url
    if content:
        payload["content"] = content
    if options:
        payload.update(options)
    return await _post("/v1/extract", payload)


@mcp.tool
async def browser_create_session() -> Any:
    """Create an isolated, TTL-limited Playwright browser session."""
    return await _post("/v1/interact/sessions", {})


@mcp.tool
async def browser_navigate(session_id: str, url: str, options: dict[str, Any] | None = None) -> Any:
    """Navigate a browser session to a public HTTP(S) URL. Private/internal destinations are blocked."""
    payload = {"url": url}
    if options:
        payload.update(options)
    return await _post(f"/v1/interact/sessions/{session_id}/navigate", payload)


@mcp.tool
async def browser_action(
    session_id: str,
    action: str,
    selector: str | None = None,
    description: str | None = None,
    value: str | None = None,
    key: str | None = None,
    allow_consequential: bool = False,
    options: dict[str, Any] | None = None,
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
async def browser_text(session_id: str, options: dict[str, Any] | None = None) -> Any:
    """Read visible page text from a browser session. Options: wait_ms (int), scroll (bool)."""
    params = {k: v for k, v in (options or {}).items() if k in ("wait_ms", "scroll")}
    return await _get(f"/v1/interact/sessions/{session_id}/text", params)


@mcp.tool
async def browser_screenshot(session_id: str) -> dict[str, str]:
    """Capture a full-page PNG screenshot as base64."""
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.get(f"{GATEWAY}/v1/interact/sessions/{session_id}/screenshot", headers=_headers())
        r.raise_for_status()
        return {"media_type": "image/png", "base64": base64.b64encode(r.content).decode("ascii")}


@mcp.tool
async def browser_close_session(session_id: str) -> Any:
    """Close and destroy a browser session."""
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.delete(f"{GATEWAY}/v1/interact/sessions/{session_id}", headers=_headers())
        r.raise_for_status()
        return r.json()


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8081, path="/mcp")
