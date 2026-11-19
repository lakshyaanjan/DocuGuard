"""Bounded, same-origin static HTML documentation crawler.

This is deliberately not a general-purpose web scraper. It only fetches public
HTML pages from the submitted site's origin, uses conservative SSRF checks,
and writes a bounded local HTML snapshot for the existing extractor.
"""

from __future__ import annotations

import ipaddress
import socket
import time
from collections import deque
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urldefrag, urljoin, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .sources import SourceError


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(href.strip())


def _origin(url: str) -> tuple[str, str, int]:
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise SourceError("Documentation website must be an absolute HTTP(S) URL.")
    if parsed.username or parsed.password:
        raise SourceError("Documentation website URLs must not contain credentials.")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed.scheme, parsed.hostname.lower(), port


def _canonical_url(url: str) -> str:
    parsed = urlparse(url)
    scheme, host, port = _origin(url)
    default_port = 443 if scheme == "https" else 80
    netloc = host if port == default_port else f"{host}:{port}"
    path = parsed.path or "/"
    # Queries and fragments are omitted to avoid generating unbounded variants.
    return urlunparse((scheme, netloc, path, "", "", ""))


def _assert_public_host(hostname: str) -> None:
    """Reject loopback/private/link-local/reserved destinations (SSRF guard)."""
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)}
    except OSError as error:
        raise SourceError(f"Could not resolve documentation website host: {error}") from error
    if not addresses:
        raise SourceError("Documentation website host did not resolve to an IP address.")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise SourceError("Documentation website host resolves to a non-public IP; refusing to fetch it.")


def _fetch_html(url: str, *, timeout: int, max_bytes: int) -> tuple[str, str]:
    current = url
    opener = build_opener(_NoRedirect)
    for _ in range(4):
        parsed = urlparse(current)
        _assert_public_host(parsed.hostname or "")
        request = Request(
            current,
            headers={
                "User-Agent": "DocuGuard-Documentation-Ingest/1.0 (+static documentation crawler)",
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
            },
        )
        try:
            response = opener.open(request, timeout=timeout)
        except HTTPError as error:
            if error.code in {301, 302, 303, 307, 308}:
                location = error.headers.get("Location")
                if not location:
                    raise SourceError(f"Documentation page returned HTTP {error.code} without a redirect target.") from error
                redirected = _canonical_url(urljoin(current, location))
                if _origin(redirected) != _origin(url):
                    raise SourceError("Documentation website redirected outside its original origin; refusing to follow.")
                current = redirected
                continue
            raise SourceError(f"Documentation page returned HTTP {error.code}: {current}") from error
        except (URLError, TimeoutError, OSError) as error:
            raise SourceError(f"Could not fetch documentation page {current}: {error}") from error

        with response:
            final_url = _canonical_url(response.geturl())
            if _origin(final_url) != _origin(url):
                raise SourceError("Documentation response changed origin; refusing to ingest it.")
            content_type = response.headers.get_content_type().lower()
            if content_type not in {"text/html", "application/xhtml+xml"}:
                raise SourceError(f"Documentation page is not HTML (content type: {content_type}).")
            declared = response.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise SourceError(f"Documentation page exceeds the {max_bytes}-byte page limit.")
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise SourceError(f"Documentation page exceeds the {max_bytes}-byte page limit.")
            charset = response.headers.get_content_charset() or "utf-8"
            try:
                return body.decode(charset, errors="replace"), final_url
            except LookupError:
                return body.decode("utf-8", errors="replace"), final_url
    raise SourceError("Documentation website exceeded the redirect limit.")


def _local_page_path(url: str) -> Path:
    parsed = urlparse(url)
    decoded = unquote(parsed.path or "/")
    pure = PurePosixPath(decoded.lstrip("/"))
    if pure.is_absolute() or any(part in {"..", "."} for part in pure.parts):
        raise SourceError("Documentation website contains an unsafe page path.")
    pieces = [part for part in pure.parts if part not in {"", "/"}]
    if not pieces:
        return Path("index.html")
    path = Path(*pieces)
    if not path.suffix:
        path = path.with_suffix(".html")
    elif path.suffix.lower() not in {".html", ".htm", ".xhtml"}:
        raise SourceError("Documentation crawler only saves HTML pages.")
    return path


def crawl_documentation_website(
    start_url: str,
    destination: str | Path,
    *,
    max_pages: int = 100,
    max_depth: int = 3,
    timeout: int = 12,
    max_page_bytes: int = 2 * 1024 * 1024,
    delay_seconds: float = 0.15,
) -> int:
    """Download up to `max_pages` static HTML pages from one public origin."""
    if max_pages < 1 or max_depth < 0 or timeout < 1 or max_page_bytes < 1:
        raise SourceError("Website crawler limits must be positive (depth may be zero).")
    start = _canonical_url(start_url)
    site_origin = _origin(start)
    _assert_public_host(site_origin[1])
    root = Path(destination).resolve()
    root.mkdir(parents=True, exist_ok=True)

    queue = deque([(start, 0)])
    visited: set[str] = set()
    saved_paths: set[Path] = set()
    while queue and len(visited) < max_pages:
        current, depth = queue.popleft()
        current = _canonical_url(current)
        if current in visited:
            continue
        visited.add(current)
        html, response_url = _fetch_html(
            current, timeout=timeout, max_bytes=max_page_bytes
        )
        page_path = _local_page_path(response_url)
        if page_path in saved_paths:
            # Query variants are intentionally coalesced; preserve the first.
            continue
        saved_paths.add(page_path)
        target = (root / page_path).resolve()
        try:
            target.relative_to(root)
        except ValueError as error:
            raise SourceError("Resolved website page path escapes the staging directory.") from error
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")

        if depth >= max_depth:
            continue
        parser = _LinkParser()
        try:
            parser.feed(html)
            parser.close()
        except Exception:
            continue
        for href in parser.links:
            if href.startswith(("mailto:", "tel:", "javascript:", "data:")):
                continue
            candidate = urljoin(response_url, href)
            if urlparse(candidate).scheme not in {"http", "https"}:
                continue
            try:
                absolute = _canonical_url(candidate)
            except (ValueError, SourceError):
                continue
            if _origin(absolute) != site_origin:
                continue
            if absolute not in visited:
                queue.append((absolute, depth + 1))
        if delay_seconds:
            time.sleep(delay_seconds)

    if not saved_paths:
        raise SourceError("No HTML documentation pages were collected from the website.")
    return len(saved_paths)
