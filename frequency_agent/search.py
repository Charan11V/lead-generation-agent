"""Public web search via Tavily, with DuckDuckGo fallback. No login scraping."""

from __future__ import annotations

import hashlib
import re
import threading
import time
from urllib.parse import urlparse

from .schemas import ICP, QuerySet, SearchHit

# Per-key circuit: one user's bad/exhausted key must not disable Tavily for others.
_TAVILY_DISABLED: dict[str, str] = {}
_TAVILY_LOCK = threading.Lock()
_DDG_LOCK = threading.Lock()

_TAVILY_FATAL = (
    "usage limit",
    "plan",
    "quota",
    "credit",
    "forbidden",
    "unauthorized",
    "invalid api",
    "api key",
    "payment",
)


def _tavily_key_id(key: str) -> str:
    raw = (key or "").strip()
    if not raw:
        return ""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def reset_provider_circuit() -> None:
    """Allow the next run to try Tavily again (called at the start of run_agent)."""
    with _TAVILY_LOCK:
        _TAVILY_DISABLED.clear()


def _sanitize_search_error(exc: Exception | str) -> str:
    msg = str(exc)
    msg = re.sub(r"tvly-[A-Za-z0-9_-]+", "tvly-***", msg)
    msg = re.sub(r"\s+", " ", msg).strip()
    return msg[:280]


def _tavily_is_fatal(exc: Exception) -> bool:
    blob = str(exc).lower()
    if type(exc).__name__.lower() in {"forbiddenerror", "unauthorizederror", "invalidapikeyerror"}:
        return True
    return any(token in blob for token in _TAVILY_FATAL)


def _year() -> str:
    from datetime import datetime, timezone

    return str(datetime.now(timezone.utc).year)


def template_queries(icp: ICP) -> list[str]:
    year = _year()
    sector = " ".join(icp.sectors[:2]) or "startup"
    geo = icp.geo or "India"
    cities = " OR ".join(icp.cities[:3]) if icp.cities else ""
    stage = " OR ".join(f'"{s.replace("_", " ").title()}"' for s in icp.stages[:3]) or '"Series B" OR "Series C"'
    queries = [
        f'{stage} {sector} {geo} funding {year}',
        f'{sector} {geo} "raised" {year}',
        f'{sector} {geo} funding announcement {year}',
        f'{sector} {geo} "Series B" OR "Series C" announced {year}',
        f'{sector} {geo} appointed CEO OR CFO OR CHRO OR CTO {year}',
        f'{sector} {geo} expansion {year}',
        f'{sector} {geo} hiring "VP" OR "Head of" {year}',
    ]
    if cities:
        queries.append(f'{sector} ({cities}) funding OR hiring {year}')
    if icp.service_line == "gcc" or "gcc" in (icp.company_types + icp.sectors + [icp.raw_text.lower()]):
        queries.extend(
            [
                f'GCC "global capability centre" Bengaluru OR Hyderabad hiring VP OR Director {year}',
                f'captive centre Bengaluru Hyderabad "setting up" OR expanding {year}',
            ]
        )
    if icp.service_line == "capital_advisory":
        queries.extend(
            [
                f'{sector} {geo} acquisition OR "working capital" OR "venture debt" {year}',
                f'{geo} "structured credit" OR "private credit" founder {year}',
            ]
        )
    # Unique, keep order, cap 10
    seen = set()
    out = []
    for q in queries:
        q = re.sub(r"\s+", " ", q).strip()
        if q.lower() not in seen:
            seen.add(q.lower())
            out.append(q)
    return out[:10]


def expand_queries(llm, icp: ICP) -> list[str]:
    base = template_queries(icp)
    try:
        extra = llm.parse(
            [
                {
                    "role": "system",
                    "content": (
                        "Generate 4 additional public-web search queries to find REAL companies matching the ICP. "
                        "No site:linkedin.com/login queries. Prefer news, funding, hiring, expansion language. "
                        "Do not name fake companies."
                    ),
                },
                {"role": "user", "content": f"ICP: {icp.model_dump_json()}\nExisting:\n" + "\n".join(base)},
            ],
            QuerySet,
        )
        merged = base + [q for q in extra.queries if q]
    except Exception:
        merged = base
    seen = set()
    out = []
    for q in merged:
        key = q.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(q.strip())
    return out[:10]


class SearchClient:
    def __init__(self, tavily_key: str | None = None) -> None:
        self.tavily_key = (tavily_key or "").strip()
        self._key_id = _tavily_key_id(self.tavily_key)
        self._tavily = None
        with _TAVILY_LOCK:
            disabled = _TAVILY_DISABLED.get(self._key_id, "") if self._key_id else ""
        self.fallback_reason = disabled
        if self.tavily_key and not disabled:
            from tavily import TavilyClient

            self._tavily = TavilyClient(api_key=self.tavily_key)

    def _this_key_disabled(self) -> str:
        if not self._key_id:
            return ""
        with _TAVILY_LOCK:
            return _TAVILY_DISABLED.get(self._key_id, "")

    @property
    def provider(self) -> str:
        if self._tavily and not self._this_key_disabled():
            return "tavily"
        if self.tavily_key:
            return "duckduckgo (tavily fallback)"
        return "duckduckgo"

    def _disable_tavily(self, exc: Exception) -> None:
        reason = _sanitize_search_error(exc)
        with _TAVILY_LOCK:
            if self._key_id and self._key_id not in _TAVILY_DISABLED:
                _TAVILY_DISABLED[self._key_id] = reason
            self._tavily = None
            self.fallback_reason = (
                _TAVILY_DISABLED.get(self._key_id, reason) if self._key_id else reason
            )

    def search_many(
        self,
        queries: list[str],
        *,
        max_results: int = 5,
        advanced: bool = False,
        country: str | None = None,
        max_workers: int | None = None,
    ) -> list[SearchHit]:
        """Run independent queries in parallel; dedupe by URL while preserving order."""
        from .parallel import map_parallel, worker_count

        if not queries:
            return []

        def _one(q: str) -> list[SearchHit]:
            try:
                return self.search(q, max_results=max_results, advanced=advanced, country=country)
            except Exception:
                return []

        workers = max_workers or worker_count("SEARCH_WORKERS", 6)
        if not self._tavily:
            workers = min(workers, 3)
        batches = map_parallel(
            queries,
            _one,
            max_workers=workers,
            env_name="SEARCH_WORKERS",
            default_workers=6,
        )
        seen: set[str] = set()
        out: list[SearchHit] = []
        for batch in batches:
            for h in batch:
                if h.url in seen:
                    continue
                seen.add(h.url)
                out.append(h)
        return out

    def search(self, query: str, max_results: int = 5, advanced: bool = False, country: str | None = None) -> list[SearchHit]:
        if self._tavily and not self._this_key_disabled():
            try:
                return self._tavily_search(query, max_results, advanced, country)
            except Exception as exc:
                # Never swallow into 0 hits. Quota/auth disables this key for the rest of this run.
                if _tavily_is_fatal(exc):
                    self._disable_tavily(exc)
                else:
                    self.fallback_reason = self.fallback_reason or _sanitize_search_error(exc)
        try:
            return self._ddg_search(query, max_results)
        except Exception:
            return []

    def _tavily_search(self, query: str, max_results: int, advanced: bool, country: str | None) -> list[SearchHit]:
        kwargs = dict(
            query=query,
            search_depth="advanced" if advanced else "basic",
            max_results=max_results,
            include_raw_content=True,
        )
        if country:
            kwargs["country"] = country.lower()
        resp = self._tavily.search(**kwargs)
        hits = []
        for item in resp.get("results") or []:
            url = item.get("url") or ""
            if not url or _blocked(url):
                continue
            hits.append(
                SearchHit(
                    query=query,
                    url=url,
                    title=item.get("title") or "",
                    snippet=item.get("content") or "",
                    published_date=item.get("published_date") or "",
                    raw_content=(item.get("raw_content") or "")[:12000],
                )
            )
        return hits

    def _ddg_search(self, query: str, max_results: int) -> list[SearchHit]:
        """DuckDuckGo is flaky on the first call and under parallel load — lock + retry."""
        last: list[SearchHit] = []
        with _DDG_LOCK:
            for attempt in range(3):
                last = self._ddg_once(query, max_results, use_news=False)
                if last:
                    return last
                time.sleep(0.5 * (attempt + 1))
            last = self._ddg_once(query, max_results, use_news=True) or last
        return last

    def _ddg_once(self, query: str, max_results: int, *, use_news: bool) -> list[SearchHit]:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            from ddgs import DDGS  # type: ignore

        hits: list[SearchHit] = []
        try:
            with DDGS() as ddgs:
                raw = (
                    ddgs.news(query, max_results=max_results)
                    if use_news
                    else ddgs.text(query, max_results=max_results)
                )
                for item in raw or []:
                    url = item.get("href") or item.get("url") or ""
                    if not url or _blocked(url):
                        continue
                    hits.append(
                        SearchHit(
                            query=query,
                            url=url,
                            title=item.get("title") or "",
                            snippet=item.get("body") or item.get("snippet") or "",
                            published_date=item.get("date") or "",
                        )
                    )
        except Exception:
            return []
        return hits


BLOCKED_HOST_PARTS = (
    "linkedin.com/login",
    "facebook.com",
    "instagram.com",
    "twitter.com/i/flow",
    "x.com/i/flow",
)


def _blocked(url: str) -> bool:
    low = url.lower()
    if any(p in low for p in BLOCKED_HOST_PARTS):
        return True
    host = urlparse(url).netloc.lower()
    return host.endswith("linkedin.com") and "/login" in low


def publisher_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower().replace("www.", "")
    return host
