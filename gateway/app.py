import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field, model_validator

from common.http import OptionalApiKeyMiddleware, RequestContextMiddleware
from common.logging import configure_logging

configure_logging("gateway")

FIRECRAWL = os.getenv("FIRECRAWL_BASE_URL", "http://firecrawl-api:3002").rstrip("/")
EXTRACT = os.getenv("EXTRACT_BASE_URL", "http://extract:8090").rstrip("/")
INTERACT = os.getenv("INTERACT_BASE_URL", "http://interact:8091").rstrip("/")
TIMEOUT = float(os.getenv("SERVICE_TIMEOUT_SECONDS", "180"))

app = FastAPI(title="Web Research Stack Gateway", version="0.1.0")
app.add_middleware(RequestContextMiddleware)
app.add_middleware(OptionalApiKeyMiddleware)


class ExtractGatewayRequest(BaseModel):
    url: str | None = None
    content: str | None = None
    schema_: dict[str, Any] = Field(alias="schema")
    instruction: str = "Extract the requested fields from the supplied content."
    model: str | None = None
    max_retries: int | None = None

    @model_validator(mode="after")
    def require_source(self):
        if not self.url and not self.content:
            raise ValueError("Provide either url or content")
        return self


async def _json_proxy(method: str, url: str, request: Request, payload: Any | None = None):
    headers = {"x-request-id": request.state.request_id}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.request(method, url, json=payload, headers=headers)
    try:
        body = r.json()
    except Exception:
        raise HTTPException(r.status_code, r.text[:2000])
    if r.is_error:
        raise HTTPException(r.status_code, body)
    return body


@app.get("/health")
async def health():
    checks = {}
    async with httpx.AsyncClient(timeout=5) as client:
        for name, url in {
            "extract": f"{EXTRACT}/health",
            "interact": f"{INTERACT}/health",
        }.items():
            try:
                checks[name] = (await client.get(url)).status_code == 200
            except Exception:
                checks[name] = False
    checks["gateway"] = True
    return {"ok": all(checks.values()), "services": checks}


@app.post("/v1/search")
async def search(payload: dict[str, Any], request: Request):
    return await _json_proxy("POST", f"{FIRECRAWL}/v2/search", request, payload)


@app.post("/v1/map")
async def map_site(payload: dict[str, Any], request: Request):
    return await _json_proxy("POST", f"{FIRECRAWL}/v2/map", request, payload)


@app.post("/v1/scrape")
async def scrape(payload: dict[str, Any], request: Request):
    return await _json_proxy("POST", f"{FIRECRAWL}/v2/scrape", request, payload)


@app.post("/v1/crawl")
async def crawl(payload: dict[str, Any], request: Request):
    return await _json_proxy("POST", f"{FIRECRAWL}/v2/crawl", request, payload)


@app.get("/v1/crawl/{job_id}")
async def crawl_status(job_id: str, request: Request):
    return await _json_proxy("GET", f"{FIRECRAWL}/v2/crawl/{job_id}", request)


@app.post("/v1/extract")
async def extract(req: ExtractGatewayRequest, request: Request):
    content = req.content
    source_url = req.url

    if content is None and req.url:
        scraped = await _json_proxy(
            "POST",
            f"{FIRECRAWL}/v2/scrape",
            request,
            {"url": req.url, "formats": ["markdown"]},
        )
        data = scraped.get("data", scraped)
        content = data.get("markdown") or data.get("content")
        if not content:
            raise HTTPException(502, "Firecrawl returned no extractable markdown/content")

    payload: dict[str, Any] = {
        "content": content,
        "schema": req.schema_,
        "instruction": req.instruction,
        "source_url": source_url,
    }
    if req.model:
        payload["model"] = req.model
    if req.max_retries is not None:
        payload["max_retries"] = req.max_retries
    return await _json_proxy("POST", f"{EXTRACT}/v1/extract", request, payload)


@app.post("/v1/interact/sessions")
async def create_session(payload: dict[str, Any] | None, request: Request):
    return await _json_proxy("POST", f"{INTERACT}/v1/sessions", request, payload or {})


@app.delete("/v1/interact/sessions/{session_id}")
async def close_session(session_id: str, request: Request):
    return await _json_proxy("DELETE", f"{INTERACT}/v1/sessions/{session_id}", request)


@app.post("/v1/interact/sessions/{session_id}/navigate")
async def navigate(session_id: str, payload: dict[str, Any], request: Request):
    return await _json_proxy("POST", f"{INTERACT}/v1/sessions/{session_id}/navigate", request, payload)


@app.post("/v1/interact/sessions/{session_id}/action")
async def action(session_id: str, payload: dict[str, Any], request: Request):
    return await _json_proxy("POST", f"{INTERACT}/v1/sessions/{session_id}/action", request, payload)


@app.get("/v1/interact/sessions/{session_id}/text")
async def page_text(session_id: str, request: Request):
    return await _json_proxy("GET", f"{INTERACT}/v1/sessions/{session_id}/text", request)


@app.get("/v1/interact/sessions/{session_id}/screenshot")
async def screenshot(session_id: str, request: Request):
    headers = {"x-request-id": request.state.request_id}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.get(f"{INTERACT}/v1/sessions/{session_id}/screenshot", headers=headers)
    if r.is_error:
        raise HTTPException(r.status_code, r.text[:2000])
    return Response(content=r.content, media_type=r.headers.get("content-type", "image/png"))
