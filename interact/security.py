import asyncio
import ipaddress
import os
import socket
from urllib.parse import urlparse


class UnsafeUrl(ValueError):
    pass


def _is_blocked_ip(ip_text: str) -> bool:
    ip = ipaddress.ip_address(ip_text)
    return any([
        ip.is_private,
        ip.is_loopback,
        ip.is_link_local,
        ip.is_multicast,
        ip.is_reserved,
        ip.is_unspecified,
    ])


def _allowlist() -> set[str]:
    return {h.strip().lower() for h in os.getenv("INTERACT_HOST_ALLOWLIST", "").split(",") if h.strip()}


async def validate_public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeUrl("Only http and https URLs are allowed")
    if not parsed.hostname:
        raise UnsafeUrl("URL must contain a hostname")
    if parsed.username or parsed.password:
        raise UnsafeUrl("Credentials in URLs are not allowed")

    hostname = parsed.hostname.lower().rstrip(".")
    allowed = _allowlist()
    if allowed and hostname not in allowed and not any(hostname.endswith("." + h) for h in allowed):
        raise UnsafeUrl("Hostname is not in INTERACT_HOST_ALLOWLIST")

    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise UnsafeUrl(f"DNS resolution failed: {exc}") from exc

    ips = {item[4][0] for item in infos}
    if not ips:
        raise UnsafeUrl("Hostname resolved to no addresses")
    for ip in ips:
        if _is_blocked_ip(ip):
            raise UnsafeUrl(f"Blocked destination address: {ip}")
    return url


CONSEQUENTIAL_TERMS = {
    "buy", "purchase", "checkout", "pay", "place order", "book", "reserve",
    "submit", "send", "delete", "remove account", "confirm", "transfer",
    "publish", "post", "sign", "accept", "agree"
}


def is_consequential(text: str) -> bool:
    t = (text or "").lower()
    return any(term in t for term in CONSEQUENTIAL_TERMS)
