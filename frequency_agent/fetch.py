"""Public page fetch. No login walls; cached in SQLite."""

from __future__ import annotations

import httpx
import trafilatura
from bs4 import BeautifulSoup

from .memory import Memory

HEADERS = {
    "User-Agent": "FrequencyLeadAgent/1.0 (public-research prototype; +https://frequency.cx)"
}


def fetch_text(url: str, memory: Memory | None = None, timeout: float = 12.0) -> tuple[str, str]:
    if memory:
        cached = memory.get_cached_page(url)
        if cached and cached.get("text"):
            return cached.get("title") or "", cached["text"]
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout, headers=HEADERS) as client:
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
