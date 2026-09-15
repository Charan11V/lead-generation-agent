"""Public page fetch. No login walls; cached in SQLite."""

from __future__ import annotations

import threading

import httpx
import trafilatura
from bs4 import BeautifulSoup

from .branding import brand_name, brand_url
from .memory import Memory
from .parallel import map_parallel, worker_count

def _headers() -> dict[str, str]:
    slug = "".join(ch for ch in brand_name() if ch.isalnum()) or "Lead"
    return {
        "User-Agent": f"{slug}LeadAgent/1.0 (public-research prototype; +{brand_url()})"
    }

_thread_local = threading.local()


def _get_client(timeout: float) -> httpx.Client:
    client = getattr(_thread_local, "http_client", None)
    if client is None:
        client = httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers=_headers(),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        _thread_local.http_client = client
    return client


def fetch_text(url: str, memory: Memory | None = None, timeout: float = 10.0) -> tuple[str, str]:
    if memory:
        cached = memory.get_cached_page(url)
        if cached and cached.get("text"):
            return cached.get("title") or "", cached["text"]
    try:
        client = _get_client(timeout)
        resp = client.get(url)
        if resp.status_code >= 400:
            return "", ""
        html = resp.text
    except Exception:
        return "", ""
    title = ""
    try:
        soup = BeautifulSoup(html, "lxml")
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
    except Exception:
        pass
    text = trafilatura.extract(html) or ""
    if not text:
        try:
            soup = BeautifulSoup(html, "lxml")
            text = soup.get_text(" ", strip=True)
        except Exception:
            text = ""
    text = text[:14000]
    if memory and text:
        memory.cache_page(url, title, text)
    return title, text


def fetch_many(
    urls: list[str],
    memory: Memory | None = None,
    *,
    timeout: float = 10.0,
    max_workers: int | None = None,
) -> dict[str, tuple[str, str]]:
    """Parallel fetch; returns url → (title, text). Skips empty URLs."""
    unique = list(dict.fromkeys(u.strip() for u in urls if u and u.strip()))
    if not unique:
        return {}

    def _one(url: str) -> tuple[str, tuple[str, str]]:
        return url, fetch_text(url, memory, timeout)

    workers = max_workers or worker_count("FETCH_WORKERS", 10)
    pairs = map_parallel(unique, _one, max_workers=workers, env_name="FETCH_WORKERS", default_workers=10)
    return dict(pairs)


def hydrate_search_hits(hits: list, memory: Memory | None = None) -> None:
    """Fill missing raw_content on SearchHit-like objects in place (parallel)."""
    need = [h for h in hits if not getattr(h, "raw_content", None) and getattr(h, "url", None)]
    if not need:
        return
    fetched = fetch_many([h.url for h in need], memory)
    for h in need:
        title, text = fetched.get(h.url, ("", ""))
        if text:
            h.raw_content = text
            if title:
                h.title = h.title or title
