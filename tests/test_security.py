import socket
from unittest.mock import AsyncMock

import pytest

from interact.app import _guard_route
from interact.security import UnsafeUrl, is_consequential, validate_public_url


@pytest.mark.asyncio
@pytest.mark.parametrize('url', [
    'http://127.0.0.1/',
    'http://10.0.0.1/',
    'http://192.168.1.1/',
    'http://169.254.169.254/latest/meta-data/',
    'http://[::1]/',
    'http://[::ffff:127.0.0.1]/',
    'http://[fc00::1]/',
    'http://[fd00::1]/',
    'http://[fe80::1]/',
    'http://[ff02::1]/',
    'http://[::]/',
    'http://0.0.0.0/',
    'http://255.255.255.255/',
    'http://127.0.0.1:8080/',
    'file:///etc/passwd',
    'ftp://example.com/file',
    'ws://127.0.0.1/',
    'wss://127.0.0.1/',
])
async def test_ssrf_blocks_private_and_non_http(url):
    with pytest.raises(UnsafeUrl):
        await validate_public_url(url)


@pytest.mark.asyncio
async def test_credentials_in_url_are_blocked():
    with pytest.raises(UnsafeUrl, match='Credentials'):
        await validate_public_url('https://user:password@example.com/')


@pytest.mark.asyncio
async def test_public_ip_allowed():
    assert await validate_public_url('https://1.1.1.1/') == 'https://1.1.1.1/'


@pytest.mark.asyncio
async def test_dns_rebinding_style_mixed_resolution_is_blocked(monkeypatch):
    def fake_getaddrinfo(*args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443)),
        ]

    monkeypatch.setattr(socket, 'getaddrinfo', fake_getaddrinfo)
    with pytest.raises(UnsafeUrl, match='Blocked destination'):
        await validate_public_url('https://example.test/')


@pytest.mark.asyncio
async def test_allowlist_rejects_nonmatching_host(monkeypatch):
    monkeypatch.setenv('INTERACT_HOST_ALLOWLIST', 'example.com')
    with pytest.raises(UnsafeUrl, match='ALLOWLIST'):
        await validate_public_url('https://example.org/')


def test_consequential_detection():
    for text in ('Place order', 'Delete account', 'Book now', 'Send message', 'Transfer funds'):
        assert is_consequential(text)
    assert not is_consequential('View details')
    assert not is_consequential('Read more')


@pytest.mark.asyncio
@pytest.mark.parametrize('url', [
    'http://127.0.0.1/',
    'http://169.254.169.254/latest/meta-data/',
    'http://[::1]/',
    'http://[::ffff:127.0.0.1]/',
    'http://[fc00::1]/',
])
async def test_guard_route_blocks_private_url(url):
    route = AsyncMock()
    route.request.url = url
    route.request.resource_type = 'document'
    await _guard_route(route)
    route.abort.assert_awaited_once()
    route.continue_.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('resource_type', ['document', 'xhr', 'fetch', 'other', 'websocket'])
async def test_guard_route_blocks_private_for_all_resource_types(resource_type):
    route = AsyncMock()
    route.request.url = 'http://127.0.0.1:8080/private'
    route.request.resource_type = resource_type
    await _guard_route(route)
    route.abort.assert_awaited_once()
    route.continue_.assert_not_awaited()


@pytest.mark.asyncio
async def test_guard_route_allows_public_destination():
    route = AsyncMock()
    route.request.url = 'https://1.1.1.1/'
    route.request.resource_type = 'document'
    await _guard_route(route)
    route.abort.assert_not_awaited()
    route.continue_.assert_awaited_once()
