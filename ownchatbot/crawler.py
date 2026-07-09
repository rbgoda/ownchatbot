"""chataiq — minimal website crawler (stdlib HTML parsing + httpx).

docaiq's `from-link` only pulls PDFs/Drive/zip, so HTML crawling is ours. This is
deliberately small: fetch same-domain pages up to a depth/page cap, strip
script/style/nav, and return clean visible text per page. No heavy deps
(readability/trafilatura) — good enough to feed the FAQ generator.
"""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlparse, urlsplit, urlunsplit

import httpx

from .netsafe import is_public_url, validated_ip

_SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "nav", "footer", "header", "form"}
_BLOCK_TAGS = {"p", "div", "section", "article", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}


class _Extract(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.links: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "a":
            for k, v in attrs:
                if k == "href" and v:
                    self.links.append(v)
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skip:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title and not self.title:
            self.title = text
        self.parts.append(text + " ")


def _clean(parts: list[str]) -> str:
    text = "".join(parts)
    lines = [ln.strip() for ln in text.splitlines()]
    out, blank = [], False
    for ln in lines:
        if ln:
            out.append(ln)
            blank = False
        elif not blank:
            out.append("")
            blank = True
    return "\n".join(out).strip()


_MIN_TEXT = 80  # below this a page is treated as "no readable content"


def extract(html: str) -> tuple[str, str, list[str]]:
    """Return (title, clean_text, hrefs) for one HTML document."""
    p = _Extract()
    try:
        p.feed(html)
    except Exception:  # noqa: BLE001 — malformed HTML shouldn't crash a crawl
        pass
    return p.title, _clean(p.parts), p.links


def is_spa_shell(html: str, text: str) -> bool:
    """Heuristic: a JS-rendered single-page app — an empty root div + a script
    bundle, with almost no static text. Static crawling can't read these."""
    low = html.lower()
    has_root = any(s in low for s in ('id="root"', "id='root'", 'id="app"', 'id="__next"', "data-reactroot"))
    return len(text) < 200 and has_root and "<script" in low


def render_available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def _render_html(url: str, timeout: float) -> str:
    """Run the page in a headless browser and return the post-JS HTML.

    Uses domcontentloaded + a short settle wait rather than `networkidle`, which
    never fires on pages with persistent connections (chat widgets, analytics)."""
    from playwright.sync_api import sync_playwright  # lazy — optional dependency
    goto_ms = int(max(timeout, 20) * 1000)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=goto_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=4000)
            except Exception:  # noqa: BLE001 — fine if it never goes idle
                pass
            page.wait_for_timeout(1500)  # let client-side rendering settle
            return page.content()
        finally:
            browser.close()


class RenderUnavailable(RuntimeError):
    """Raised when render=True but Playwright/Chromium isn't installed."""


def crawl(start_url: str, max_pages: int = 8, timeout: float = 15.0, render: bool = False) -> list[dict]:
    """Breadth-first, same-domain crawl. Returns [{url, title, text}, ...].

    `render=True` executes JS via headless Chromium (needed for SPAs) — requires
    the optional `playwright` package + `playwright install chromium`."""
    if render and not render_available():
        raise RenderUnavailable(
            "headless rendering requested but Playwright isn't installed. Run: "
            "pip install playwright && playwright install chromium"
        )
    def _norm(u: str) -> str:
        u, _ = urldefrag(u)
        return u.rstrip("/") or u

    start_url = _norm(start_url)
    origin = urlparse(start_url).netloc
    seen: set[str] = set()
    queue = [start_url]
    pages: list[dict] = []
    headers = {"User-Agent": "chataiq-crawler/0.1 (+https://github.com/rbgoda/aifaqchat)"}
    # follow_redirects=False so we validate EACH redirect target against the SSRF
    # guard (an allowed host can otherwise 302 us to an internal address).
    with httpx.Client(follow_redirects=False, timeout=timeout, headers=headers) as client:
        while queue and len(pages) < max_pages:
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            html = None
            if not render:
                html = _safe_fetch(client, url)
            if html is None:
                # static fetch failed or skipped — render if requested, else skip
                if not (render and is_public_url(url)):
                    continue
                try:
                    html = _render_html(url, timeout)
                except Exception:  # noqa: BLE001
                    continue
            title, text, links = extract(html)
            if len(text) <= _MIN_TEXT and not render and render_available() and is_public_url(url):
                # static read was thin and we *can* render — upgrade this page
                try:
                    title, text, links = extract(_render_html(url, timeout))
                except Exception:  # noqa: BLE001
                    pass
            if len(text) > _MIN_TEXT:
                pages.append({"url": url, "title": title or url, "text": text})
            for href in links:
                nxt = _norm(urljoin(url, href))
                if urlparse(nxt).netloc == origin and nxt.startswith(("http://", "https://")) and nxt not in seen:
                    queue.append(nxt)
    return pages


_MAX_BYTES = 4 * 1024 * 1024  # cap each page read to keep memory bounded


def _pinned(url: str):
    """Return (request_url, host_header) that pins an http connection to the
    validated IP — defeats DNS-rebinding. For https we keep the hostname (TLS
    cert verification blocks rebinding to an internal service). Returns None if
    the host doesn't resolve to an all-public address."""
    p = urlsplit(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        return None
    ip = validated_ip(p.hostname, p.port, p.scheme)
    if not ip:
        return None
    if p.scheme == "https":
        return url, None  # TLS verification pins identity for https
    netloc = (f"[{ip}]" if ":" in ip else ip) + (f":{p.port}" if p.port else "")
    return urlunsplit((p.scheme, netloc, p.path or "/", p.query, "")), p.hostname


def _safe_fetch(client, url: str, max_redirects: int = 4) -> str | None:
    """Fetch HTML with SSRF protection: refuse non-public targets, pin http to the
    validated IP, validate every redirect hop, and cap the response body. → HTML|None."""
    for _ in range(max_redirects + 1):
        pin = _pinned(url)
        if pin is None:
            return None
        req_url, host_hdr = pin
        req_headers = {"Host": host_hdr} if host_hdr else {}
        try:
            with client.stream("GET", req_url, headers=req_headers) as r:
                if r.status_code in (301, 302, 303, 307, 308):
                    loc = r.headers.get("location")
                    if not loc:
                        return None
                    url = urljoin(url, loc)  # validated at the top of the next loop
                    continue
                if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
                    return None
                clen = r.headers.get("content-length")
                if clen and clen.isdigit() and int(clen) > _MAX_BYTES:
                    return None
                chunks, total = [], 0
                for chunk in r.iter_bytes():
                    total += len(chunk)
                    if total > _MAX_BYTES:
                        return None
                    chunks.append(chunk)
                return b"".join(chunks).decode(r.encoding or "utf-8", errors="replace")
        except httpx.HTTPError:
            return None
    return None


def diagnose(url: str, timeout: float = 15.0) -> str:
    """Why did a crawl come back empty? Returns 'spa' | 'empty' | 'unreachable'.

    Uses the SAME SSRF-safe fetch as the crawler (no auto-redirects; every hop
    and connected IP re-validated) so an allowed host can't 302 us internally.
    """
    headers = {"User-Agent": "chataiq-crawler/0.1 (+https://github.com/rbgoda/aifaqchat)"}
    with httpx.Client(follow_redirects=False, timeout=timeout, headers=headers) as client:
        html = _safe_fetch(client, url)
    if html is None:
        return "unreachable"
    _, text, _ = extract(html)
    return "spa" if is_spa_shell(html, text) else "empty"
