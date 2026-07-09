"""chataiq — SSRF guard for server-side fetches of user-supplied URLs.

The crawler (and the handoff webhook) fetch/POST to addresses the user controls.
Without a guard those can hit internal services, localhost, or cloud-metadata
(169.254.169.254). `is_public_url` enforces http(s) + a public, non-reserved IP.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


def _ip_is_public(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified)


def validated_ip(host: str, port: int | None, scheme: str) -> str | None:
    """Resolve `host` and return ONE public IP, only if EVERY resolved address is
    public; else None. Pin the connection to this IP to defeat DNS-rebinding
    (the resolve-then-connect TOCTOU between is_public_url and the actual fetch)."""
    try:
        infos = socket.getaddrinfo(host, port or (443 if scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError):
        return None
    if not infos:
        return None
    chosen = None
    for *_unused, sockaddr in infos:
        if not _ip_is_public(sockaddr[0]):
            return None
        chosen = chosen or sockaddr[0]
    return chosen


def is_public_url(url: str) -> bool:
    """True only for http/https URLs whose host resolves entirely to public IPs."""
    try:
        p = urlparse(url)
    except ValueError:
        return False
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    return validated_ip(p.hostname, p.port, p.scheme) is not None
