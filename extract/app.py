import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field

from common.http import RequestContextMiddleware
from common.logging import configure_logging

configure_logging("extract")

OLLAMA = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip("/")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120"))
MAX_RETRIES = int(os.getenv("EXTRACT_MAX_RETRIES", "2"))
MAX_CONTENT = int(os.getenv("EXTRACT_MAX_CONTENT_CHARS", "250000"))

app = FastAPI(title="Structured Extract Service", version="0.1.0")
app.add_middleware(RequestContextMiddleware)


class ExtractRequest(BaseModel):
    content: str = Field(min_length=1)
    schema_: dict[str, Any] = Field(alias="schema")
    instruction: str = "Extract the requested fields from the supplied content."
    source_url: str | None = None
    model: str | None = None
    max_retries: int | None = Field(default=None, ge=0, le=5)


@app.get("/health")
async def health():
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{OLLAMA}/api/tags")
        return {"ok": r.status_code == 200, "ollama": r.status_code == 200}
    except Exception:
        return {"ok": False, "ollama": False}


@app.post("/v1/extract")
async def extract(req: ExtractRequest):
    content = req.content[:MAX_CONTENT]
    model = req.model or DEFAULT_MODEL
    retries = MAX_RETRIES if req.max_retries is None else req.max_retries
    validator = Draft202012Validator(req.schema_)

    system = (
        "You are a deterministic information extraction engine. Use only the supplied content. "
        "Do not use prior knowledge. If the source does not support a requested field, use null, "
        "an empty collection, or the schema-appropriate missing representation. Return JSON only."
    )

    last_error = None
    for attempt in range(1, retries + 2):
        user = (
            f"Instruction:\n{req.instruction}\n\n"
            f"Content:\n{content}\n\n"
            "Return an object conforming exactly to the provided JSON schema."
        )
        if last_error:
            user += f"\n\nPrevious output failed validation: {last_error}. Correct it."

        payload = {
            "model": model,
            "stream": False,
            "format": req.schema_,
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.post(f"{OLLAMA}/api/chat", json=payload)
            response.raise_for_status()
            raw = response.json()["message"]["content"]
            data = json.loads(raw)
            errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
            if errors:
                last_error = "; ".join(e.message for e in errors[:5])
                continue
            return {
                "data": data,
                "provenance": {
                    "source_url": req.source_url,
                    "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    "content_chars": len(content),
                    "truncated": len(req.content) > len(content),
                    "model": model,
                    "attempts": attempt,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                },
            }
        except (httpx.HTTPError, KeyError, json.JSONDecodeError) as exc:
            last_error = str(exc)

    raise HTTPException(422, detail={"message": "Extraction failed validation", "error": last_error})
