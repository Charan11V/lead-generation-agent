"""Public web search via Tavily, with DuckDuckGo fallback. No login scraping."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from .schemas import ICP, QuerySet, SearchHit


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
        self.tavily_key = tavily_key or ""
        self._tavily = None
        if self.tavily_key:
            from tavily import TavilyClient

            self._tavily = TavilyClient(api_key=self.tavily_key)

    @property
    def provider(self) -> str:
        return "tavily" if self._tavily else "duckduckgo"

    def search(self, query: str, max_results: int = 5, advanced: bool = False, country: str | None = None) -> list[SearchHit]:
        if self._tavily:
            return self._tavily_search(query, max_results, advanced, country)
        return self._ddg_search(query, max_results)

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
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            from ddgs import DDGS  # type: ignore

        hits = []
        with DDGS() as ddgs:
            for item in ddgs.text(query, max_results=max_results):
                url = item.get("href") or item.get("url") or ""
                if not url or _blocked(url):
                    continue
                hits.append(
                    SearchHit(
                        query=query,
                        url=url,
                        title=item.get("title") or "",
                        snippet=item.get("body") or item.get("snippet") or "",
                    )
                )
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
