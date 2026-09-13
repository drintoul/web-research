import asyncio
import base64
import os
import time
import uuid
from dataclasses import dataclass
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field
from playwright.async_api import Browser, BrowserContext, Locator, Page, async_playwright

from common.http import RequestContextMiddleware
from common.logging import configure_logging
from interact.security import UnsafeUrl, is_consequential, validate_public_url

configure_logging("interact")

MAX_SESSIONS = int(os.getenv("INTERACT_MAX_SESSIONS", "6"))
TTL = int(os.getenv("INTERACT_SESSION_TTL_SECONDS", "900"))
NAV_TIMEOUT = int(os.getenv("INTERACT_NAVIGATION_TIMEOUT_MS", "30000"))
MAX_TEXT = int(os.getenv("INTERACT_MAX_TEXT_CHARS", "50000"))
USE_LLM = os.getenv("INTERACT_LLM_SELECTOR_FALLBACK", "true").lower() == "true"
BLOCK_MEDIA = os.getenv("INTERACT_BLOCK_MEDIA", "true").lower() == "true"
OLLAMA = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip("/")
MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120"))

app = FastAPI(title="Browser Interact Service", version="0.1.0")
app.add_middleware(RequestContextMiddleware)

_pw = None
_browser: Browser | None = None
_sweeper: asyncio.Task | None = None
_sessions: dict[str, "Session"] = {}
_lock = asyncio.Lock()


@dataclass
class Session:
    context: BrowserContext
    page: Page
    touched: float


class NavigateRequest(BaseModel):
    url: str
    wait_until: Literal["commit", "domcontentloaded", "load", "networkidle"] = "domcontentloaded"


class ActionRequest(BaseModel):
    action: Literal["click", "type", "press", "select", "wait", "scroll"]
    selector: str | None = None
    description: str | None = None
    value: str | None = None
    key: str | None = None
    timeout_ms: int = Field(default=10000, ge=100, le=60000)
    allow_consequential: bool = False


async def _guard_route(route):
    req = route.request
    if req.resource_type == "websocket":
        await route.abort()
        return
    if BLOCK_MEDIA and req.resource_type in {"image", "media", "font"}:
        await route.abort()
        return
    try:
        await validate_public_url(req.url)
    except UnsafeUrl:
        await route.abort()
        return
    await route.continue_()


async def _close_websocket(ws):
    try:
        await ws.close()
    except Exception:
        pass


def _on_websocket(ws):
    asyncio.create_task(_close_websocket(ws))


async def _new_session() -> tuple[str, Session]:
    if _browser is None:
        raise HTTPException(503, "Browser not ready")
    async with _lock:
        if len(_sessions) >= MAX_SESSIONS:
            raise HTTPException(429, "Maximum browser sessions reached")
        context = await _browser.new_context(
            ignore_https_errors=False,
            accept_downloads=False,
            service_workers="block",
        )
        page = await context.new_page()
        page.set_default_timeout(10000)
        page.set_default_navigation_timeout(NAV_TIMEOUT)
        await context.route("**/*", _guard_route)
        context.on("websocket", _on_websocket)
        session_id = str(uuid.uuid4())
        session = Session(context=context, page=page, touched=time.monotonic())
        _sessions[session_id] = session
        return session_id, session


def _get(session_id: str) -> Session:
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Unknown or expired browser session")
    session.touched = time.monotonic()
    return session


async def _sweep():
    while True:
        await asyncio.sleep(30)
        cutoff = time.monotonic() - TTL
        expired = [sid for sid, s in _sessions.items() if s.touched < cutoff]
        for sid in expired:
            session = _sessions.pop(sid, None)
            if session:
                await session.context.close()


@app.on_event("startup")
async def startup():
    global _pw, _browser, _sweeper
    _pw = await async_playwright().start()
    _browser = await _pw.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
    _sweeper = asyncio.create_task(_sweep())


@app.on_event("shutdown")
async def shutdown():
    if _sweeper:
        _sweeper.cancel()
    for session in list(_sessions.values()):
        await session.context.close()
    _sessions.clear()
    if _browser:
        await _browser.close()
    if _pw:
        await _pw.stop()


@app.get("/health")
async def health():
    return {"ok": _browser is not None, "sessions": len(_sessions), "max_sessions": MAX_SESSIONS}


@app.post("/v1/sessions")
async def create_session():
    sid, _ = await _new_session()
    return {"session_id": sid, "ttl_seconds": TTL}


@app.delete("/v1/sessions/{session_id}")
async def close_session(session_id: str):
    session = _sessions.pop(session_id, None)
    if not session:
        raise HTTPException(404, "Unknown browser session")
    await session.context.close()
    return {"closed": True, "session_id": session_id}


@app.post("/v1/sessions/{session_id}/navigate")
async def navigate(session_id: str, req: NavigateRequest):
    session = _get(session_id)
    try:
        await validate_public_url(req.url)
        response = await session.page.goto(req.url, wait_until=req.wait_until, timeout=NAV_TIMEOUT)
    except UnsafeUrl as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Navigation failed: {exc}")
    return {
        "url": session.page.url,
        "title": await session.page.title(),
        "status": response.status if response else None,
    }


async def _interactive_candidates(page: Page) -> list[dict]:
    return await page.locator("a,button,input,textarea,select,[role=button],[role=link]").evaluate_all(
        """els => els.slice(0,200).map((e,i) => ({
          index:i,
          tag:e.tagName.toLowerCase(),
          text:(e.innerText || e.value || e.getAttribute('aria-label') || e.getAttribute('placeholder') || '').trim().slice(0,160),
          id:e.id || null,
          name:e.getAttribute('name'),
          role:e.getAttribute('role'),
          type:e.getAttribute('type')
        }))"""
    )


async def _resolve_locator(page: Page, description: str) -> Locator:
    # Deterministic first: exact/partial accessible text.
    by_text = page.get_by_text(description, exact=False)
    count = await by_text.count()
    if count == 1:
        return by_text.first

    by_label = page.get_by_label(description, exact=False)
    count = await by_label.count()
    if count == 1:
        return by_label.first

    if not USE_LLM:
        raise HTTPException(409, "Selector is ambiguous; provide a CSS selector")

    candidates = await _interactive_candidates(page)
    if not candidates:
        raise HTTPException(404, "No interactive elements found")

    schema = {
        "type": "object",
        "properties": {"index": {"type": "integer", "minimum": 0}},
        "required": ["index"],
        "additionalProperties": False,
    }
    payload = {
        "model": MODEL,
        "stream": False,
        "format": schema,
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": "Choose the single best matching element index. Do not invent elements."},
            {"role": "user", "content": f"Desired element: {description}\nCandidates: {candidates}"},
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
            r = await client.post(f"{OLLAMA}/api/chat", json=payload)
        r.raise_for_status()
        import json
        chosen = json.loads(r.json()["message"]["content"])["index"]
    except Exception as exc:
        raise HTTPException(502, f"LLM selector resolution failed: {exc}")

    if chosen < 0 or chosen >= len(candidates):
        raise HTTPException(422, "LLM selected an invalid element")
    return page.locator("a,button,input,textarea,select,[role=button],[role=link]").nth(chosen)


@app.post("/v1/sessions/{session_id}/action")
async def action(session_id: str, req: ActionRequest):
    session = _get(session_id)
    page = session.page

    if req.action == "wait":
        await page.wait_for_timeout(int(req.value or "500"))
        return {"ok": True, "action": req.action}
    if req.action == "scroll":
        amount = int(req.value or "800")
        await page.mouse.wheel(0, amount)
        return {"ok": True, "action": req.action, "amount": amount}

    if not req.selector and not req.description:
        raise HTTPException(422, "selector or description is required")

    locator = page.locator(req.selector).first if req.selector else await _resolve_locator(page, req.description or "")
    try:
        await locator.wait_for(state="visible", timeout=req.timeout_ms)
        element_text = " ".join(filter(None, [
            req.description or "",
            await locator.inner_text(timeout=1000) if req.action == "click" else "",
            await locator.get_attribute("aria-label") or "",
            await locator.get_attribute("value") or "",
        ]))
        if req.action == "click" and is_consequential(element_text) and not req.allow_consequential:
            raise HTTPException(409, "Potentially consequential click blocked; set allow_consequential=true only after explicit approval")

        if req.action == "click":
            await locator.click(timeout=req.timeout_ms)
        elif req.action == "type":
            if req.value is None:
                raise HTTPException(422, "value is required for type")
            await locator.fill(req.value, timeout=req.timeout_ms)
        elif req.action == "press":
            await locator.press(req.key or req.value or "Enter", timeout=req.timeout_ms)
        elif req.action == "select":
            if req.value is None:
                raise HTTPException(422, "value is required for select")
            await locator.select_option(req.value, timeout=req.timeout_ms)
        else:
            raise HTTPException(422, "Unsupported action")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Browser action failed: {exc}")

    return {"ok": True, "action": req.action, "url": page.url, "title": await page.title()}


@app.get("/v1/sessions/{session_id}/text")
async def text(session_id: str):
    page = _get(session_id).page
    body = await page.locator("body").inner_text()
    return {"url": page.url, "title": await page.title(), "text": body[:MAX_TEXT], "truncated": len(body) > MAX_TEXT}


@app.get("/v1/sessions/{session_id}/screenshot")
async def screenshot(session_id: str):
    page = _get(session_id).page
    png = await page.screenshot(full_page=True, type="png")
    return Response(content=png, media_type="image/png")


@app.get("/v1/sessions/{session_id}/elements")
async def elements(session_id: str):
    page = _get(session_id).page
    return {"url": page.url, "title": await page.title(), "elements": await _interactive_candidates(page)}
