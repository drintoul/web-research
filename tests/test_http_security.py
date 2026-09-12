import os

from fastapi import FastAPI
from fastapi.testclient import TestClient

from common.http import OptionalApiKeyMiddleware, RequestContextMiddleware


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(OptionalApiKeyMiddleware)

    @app.get('/health')
    async def health():
        return {'ok': True}

    @app.get('/private')
    async def private():
        return {'ok': True}

    return app


def test_health_bypasses_auth_and_has_request_id(monkeypatch):
    monkeypatch.setenv('GATEWAY_API_KEY', 'secret')
    with TestClient(_app()) as client:
        response = client.get('/health')
    assert response.status_code == 200
    assert response.headers.get('x-request-id')


def test_private_route_requires_key(monkeypatch):
    monkeypatch.setenv('GATEWAY_API_KEY', 'secret')
    with TestClient(_app()) as client:
        assert client.get('/private').status_code == 401
        assert client.get('/private', headers={'Authorization': 'Bearer wrong'}).status_code == 401
        assert client.get('/private', headers={'Authorization': 'Bearer secret'}).status_code == 200
        assert client.get('/private', headers={'x-api-key': 'secret'}).status_code == 200


def test_request_id_is_preserved(monkeypatch):
    monkeypatch.delenv('GATEWAY_API_KEY', raising=False)
    with TestClient(_app()) as client:
        response = client.get('/private', headers={'x-request-id': 'test-correlation-id'})
    assert response.status_code == 200
    assert response.headers['x-request-id'] == 'test-correlation-id'
