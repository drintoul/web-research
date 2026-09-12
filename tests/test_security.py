import socket

import pytest

from interact.security import UnsafeUrl, is_consequential, validate_public_url


@pytest.mark.asyncio
@pytest.mark.parametrize('url', [
    'http://127.0.0.1/',
    'http://10.0.0.1/',
    'http://192.168.1.1/',
    'http://169.254.169.254/latest/meta-data/',
    'file:///etc/passwd',
    'ftp://example.com/file',
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
