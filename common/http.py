import os
import uuid
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response


class OptionalApiKeyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, env_var: str = "GATEWAY_API_KEY"):
        super().__init__(app)
        self.env_var = env_var

    async def dispatch(self, request: Request, call_next):
        expected = os.getenv(self.env_var, "").strip()
        if expected and request.url.path not in {"/health", "/docs", "/openapi.json"} and not request.url.path.startswith("/ui"):
            supplied = request.headers.get("authorization", "")
            if supplied.startswith("Bearer "):
                supplied = supplied[7:]
            else:
                supplied = request.headers.get("x-api-key", "")
            if supplied != expected:
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return await call_next(request)
