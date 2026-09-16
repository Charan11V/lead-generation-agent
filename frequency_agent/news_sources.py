"""Harvest last-24h public news from free APIs and RSS. Optional keys are extra.

Always-on (no key): Google News RSS, GDELT, curated publisher RSS, DuckDuckGo News.
Publisher RSS is keyword-gated (funding, CXO, fractional, capital, expansion, deals).
Optional: NewsAPI, GNews, NewsData, Guardian — used when env keys exist.
Signal desk never calls Tavily.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Callable
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx

from .news_relevance import has_frequency_trigger
from .parallel import map_parallel
from .util import domain_of

HEADERS = {
    "User-Agent": "FrequencySignalDesk/1.0 (local research; +https://frequency.cx)",
    "Accept": "application/rss+xml, application/xml, application/json, text/xml, */*",
}

GOOGLE_QUERIES = (
    # Funding / rounds
    'India startup funding "Series A" OR "Series B" OR "Series C" OR "Series D" when:1d',
    'India startup (seed OR "pre-series" OR "bridge round" OR "growth round") (raised OR funding) when:1d',
    "India startup raised OR funding OR fundraise OR \"closes round\" when:1d",
    # CXO in / out / hiring
    "India (CEO OR CFO OR COO OR CTO OR CHRO OR CMO OR CPO OR CISO OR CGO) (appointed OR named OR joins) (startup OR GCC) when:1d",
    'India (CEO OR CFO OR COO OR CTO OR CHRO OR CMO) (resigns OR "steps down" OR departs OR exits OR ousted) (startup OR company) when:1d',
    'India hiring (CEO OR CFO OR COO OR CHRO OR CTO OR CXO OR "Head of" OR "Vice President" OR "chief of staff") (startup OR GCC) when:1d',
    'India ("chief of staff" OR "Head of Talent" OR "Head of People" OR "managing director") (appointed OR named OR hiring) when:1d',
    'India ("first CFO" OR "first CMO" OR "first CHRO" OR "leadership team" OR "leadership hiring" OR "executive search") startup when:1d',
    # Fractional / interim
    '(fractional OR interim OR "part-time") (CFO OR CMO OR CTO OR CHRO OR COO OR CXO OR CEO) (India OR startup) when:1d',
    # Expansion / GCC
    'India (startup OR GCC OR GIC) (expansion OR "new office" OR "market entry" OR "new vertical" OR "US expansion") when:1d',
    '(Bengaluru OR Bangalore OR Hyderabad OR Gurugram) (GCC OR "global capability centre" OR GIC OR captive) (hiring OR VP OR expansion) when:1d',
    # Capital advisory
    'India ("venture debt" OR "structured credit" OR "structured debt" OR "private credit" OR "working capital" OR "capital stack" OR "equity raise") startup when:1d',
    'India (startup OR founder) ("pre-IPO" OR secondary OR "growth equity" OR "debt raise" OR "capital raise") when:1d',
    # Sectors Frequency actually works
    "India (fintech OR payments OR SaaS OR AI OR \"deep tech\" OR semiconductor) (funding OR CEO OR hiring) when:1d",
    "India (D2C OR \"consumer brand\" OR retail OR \"quick commerce\") (funding OR CEO OR CMO OR transformation) when:1d",
    # PE / VC / portfolio operators
    'India (PE OR "private equity" OR VC OR "venture capital" OR "portfolio company") (CEO OR CFO OR hiring OR appointed) when:1d',
    '(VC OR "private equity") (India OR portfolio) ("closed fund" OR "final close" OR "Fund III") when:1d',
    # Deals
    "India startup (acquisition OR acqui-hire OR merger OR buyout) when:1d",
)

GDELT_QUERIES = (
    '(startup OR founder) (funding OR "series A" OR "series B" OR "series C" OR "series D" OR seed OR raised) (India OR Bengaluru OR Bangalore OR Mumbai)',
    '(CEO OR CFO OR COO OR CHRO OR CTO OR CMO OR CPO OR CISO) (appointed OR named OR resigns OR "steps down" OR joins OR exits) (startup OR India OR GCC)',
    '("chief of staff" OR "head of talent" OR "vice president" OR "managing director") (appointed OR hiring OR named) (India OR startup)',
    '(fractional OR interim OR "part-time") (CFO OR CMO OR CTO OR CHRO OR COO OR CXO OR CEO)',
    '("venture debt" OR "structured credit" OR "structured debt" OR "capital raise" OR "private credit" OR "working capital" OR "pre-IPO" OR "growth equity") (India OR startup)',
    '(expansion OR GCC OR GIC OR "capability centre" OR "new office" OR "market entry" OR "new vertical") (India OR Bengaluru OR Hyderabad OR Gurugram)',
    '(fintech OR payments OR SaaS OR "artificial intelligence" OR "deep tech" OR D2C OR semiconductor) (funding OR hiring OR CEO) (India OR startup)',
    '(acquisition OR acqui-hire OR merger OR "private equity" OR "portfolio company") (startup OR India)',
    '("executive search" OR "leadership hiring" OR CXO OR "leadership team") (startup OR India OR GCC)',
)

DDG_QUERIES = (
    "India startup funding announced",
    "India startup Series B OR Series C OR Series D",
    "India startup seed OR pre-series raised",
    "India CEO appointed startup",
    "India CFO OR COO resigns OR appointed",
    "India CHRO OR CTO OR CMO appointed startup",
    "India chief of staff OR Head of Talent hiring",
    "India executive search OR leadership hiring CXO",
    "fractional CFO OR interim CFO India",
    "fractional CMO OR part-time CXO India",
    "venture debt OR structured credit India startup",
    "India pre-IPO OR growth equity startup",
    "India GCC OR GIC expansion hiring VP",
    "India US market entry startup",
    "India fintech OR SaaS OR AI funding",
    "India D2C OR consumer brand CEO",
    "India PE OR VC portfolio CEO appointed",
    "India startup acquisition OR acqui-hire",
)

NEWSAPI_QUERY = (
    "India AND (startup OR fintech OR SaaS OR GCC OR D2C) AND "
    "(funding OR CEO OR CFO OR COO OR CHRO OR CXO OR "
    '"Series A" OR "Series B" OR appointed OR resigns OR '
    '"venture debt" OR fractional OR interim OR GCC OR acquisition OR '
    '"executive search" OR "pre-IPO")'
)
GNEWS_QUERY = (
    'India (startup OR GCC) (funding OR CEO OR CFO OR CHRO OR COO OR '
    '"Series B" OR fractional OR "venture debt" OR acquisition)'
)
NEWSDATA_QUERY = (
    "startup funding OR CEO appointed OR CFO OR CHRO OR fractional OR "
    "GCC OR venture debt India"
)
GUARDIAN_QUERY = 'startup OR funding OR CEO OR fintech OR "venture capital" OR GCC'

RSS_FEEDS = (
    ("Inc42", "https://inc42.com/feed/"),
    ("YourStory", "https://yourstory.com/feed"),
    ("TechCrunch", "https://techcrunch.com/feed/"),
    ("Entrackr", "https://entrackr.com/feed/"),
    ("VCCircle", "https://www.vccircle.com/feed"),
    ("Economic Times Startups", "https://economictimes.indiatimes.com/tech/startups/rssfeeds/13357270.cms"),
    ("Moneycontrol", "https://www.moneycontrol.com/rss/business.xml"),
    ("Crunchbase News", "https://news.crunchbase.com/feed/"),
    ("LiveMint Companies", "https://www.livemint.com/rss/companies"),
    ("DealStreetAsia", "https://www.dealstreetasia.com/feed"),
    (
        "Google Business IN",
        "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-IN&gl=IN&ceid=IN:en",
    ),
    (
        "Google Technology IN",
        "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-IN&gl=IN&ceid=IN:en",
    ),
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_when(raw: str | None) -> datetime | None:
    text = (raw or "").strip()
    if not text:
        return None
    compact = re.match(r"^(\d{8})T(\d{6})(?:Z|[+-]\d{2}:?\d{2})?$", text)
    if compact:
        try:
            return datetime.strptime(compact.group(1) + compact.group(2), "%Y%m%d%H%M%S").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            pass
    iso = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def iso_when(raw: str | None) -> str:
    dt = parse_when(raw)
    return dt.isoformat(timespec="seconds") if dt else (raw or "").strip()


def in_window(published_at: str, *, hours: int = 36, provider: str = "") -> bool:
    dt = parse_when(published_at)
    if dt is None:
        # Time-bounded APIs already constrain the query; RSS feeds do not.
        return provider in {
            "google_news",
            "gdelt",
            "newsapi",
            "gnews",
            "newsdata",
            "duckduckgo",
            "guardian",
        }
    return dt >= utcnow() - timedelta(hours=hours)


def _client() -> httpx.Client:
    return httpx.Client(follow_redirects=True, timeout=12.0, headers=HEADERS)


def _get(client: httpx.Client, url: str) -> httpx.Response | None:
    try:
        resp = client.get(url)
        if resp.status_code >= 400:
            return None
        return resp
    except Exception:
        return None


def _unwrap_google_url(url: str, description: str = "") -> str:
    href = re.search(r'href="(https?://[^"]+)"', description or "")
    if href:
        candidate = href.group(1)
        if "news.google.com" not in candidate:
            return candidate
    parsed = urlparse(url or "")
    qs = parse_qs(parsed.query)
    for key in ("url", "q"):
        vals = qs.get(key) or []
        if vals and str(vals[0]).startswith("http") and "news.google.com" not in str(vals[0]):
            return unquote(str(vals[0]))
    return url


def _source_from_rss_item(item: ET.Element) -> str:
    src = item.find("source")
    if src is not None and (src.text or "").strip():
        return src.text.strip()
    return ""


def _parse_rss(xml_text: str, *, provider: str, default_source: str = "") -> list[dict]:
    if not (xml_text or "").strip():
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out: list[dict] = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip()
        pub = (item.findtext("pubDate") or item.findtext("published") or "").strip()
        if provider == "google_news":
            link = _unwrap_google_url(link, desc)
        source = _source_from_rss_item(item) or default_source or domain_of(link)
        snippet = re.sub(r"<[^>]+>", " ", desc)
        snippet = re.sub(r"\s+", " ", snippet).strip()[:400]
        if not title or not link:
            continue
        out.append(
            {
                "url": link,
                "title": title,
                "snippet": snippet,
                "source": source,
                "published_at": iso_when(pub),
                "provider": provider,
            }
        )
    return out


def fetch_google_news(client: httpx.Client) -> list[dict]:
    del client

    def _one(query: str) -> list[dict]:
        with _client() as c:
            url = (
                "https://news.google.com/rss/search?q="
                + quote_plus(query)
                + "&hl=en-IN&gl=IN&ceid=IN:en"
            )
            resp = _get(c, url)
            if resp is None:
                return []
            return _parse_rss(resp.text, provider="google_news")

    batches = map_parallel(
        list(GOOGLE_QUERIES),
        _one,
        env_name="NEWS_WORKERS",
        default_workers=8,
        return_exceptions=True,
    )
    hits: list[dict] = []
    for batch in batches:
        if isinstance(batch, BaseException):
            continue
        hits.extend(batch)
    return hits


def fetch_gdelt(client: httpx.Client) -> list[dict]:
    del client

    def _one(query: str) -> list[dict]:
        with _client() as c:
            url = (
                "https://api.gdeltproject.org/api/v2/doc/doc"
                f"?query={quote_plus(query)}"
                "&mode=ArtList&maxrecords=75&timespan=24h&format=json&sort=DateDesc"
            )
            resp = _get(c, url)
            if resp is None:
                return []
            try:
                payload = resp.json()
            except Exception:
                return []
            hits: list[dict] = []
            for art in payload.get("articles") or []:
                url_v = (art.get("url") or "").strip()
                title = (art.get("title") or "").strip()
                if not url_v or not title:
                    continue
                hits.append(
                    {
                        "url": url_v,
                        "title": title,
                        "snippet": (art.get("seendate") or "") + " " + (art.get("sourcecountry") or ""),
                        "source": art.get("domain") or domain_of(url_v),
                        "published_at": iso_when(art.get("seendate") or ""),
                        "provider": "gdelt",
                    }
                )
            return hits

    batches = map_parallel(
        list(GDELT_QUERIES),
        _one,
        env_name="NEWS_WORKERS",
        default_workers=6,
        return_exceptions=True,
    )
    hits: list[dict] = []
    for batch in batches:
        if isinstance(batch, BaseException):
            continue
        hits.extend(batch)
    return hits


def fetch_rss_feeds(client: httpx.Client) -> list[dict]:
    del client

    def _one(pair: tuple[str, str]) -> list[dict]:
        name, url = pair
        with _client() as c:
            resp = _get(c, url)
            if resp is None:
                return []
            provider = "google_news" if "news.google.com" in url else "rss"
            rows = _parse_rss(resp.text, provider=provider, default_source=name)
            return [
                row
                for row in rows
                if has_frequency_trigger(row.get("title") or "", row.get("snippet") or "")
            ]

    batches = map_parallel(
        list(RSS_FEEDS),
        _one,
        env_name="NEWS_WORKERS",
        default_workers=8,
        return_exceptions=True,
    )
    hits: list[dict] = []
    for batch in batches:
        if isinstance(batch, BaseException):
            continue
        hits.extend(batch)
    return hits


def fetch_ddg_news() -> list[dict]:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        try:
            from ddgs import DDGS  # type: ignore
        except ImportError:
            return []
    hits: list[dict] = []
    try:
        with DDGS() as ddgs:
            for query in DDG_QUERIES:
                try:
                    raw = ddgs.news(query, max_results=20, timelimit="d")
                except TypeError:
                    raw = ddgs.news(query, max_results=20)
                except Exception:
                    continue
                for item in raw or []:
                    url = (item.get("url") or item.get("href") or "").strip()
                    title = (item.get("title") or "").strip()
                    if not url or not title:
                        continue
                    hits.append(
                        {
                            "url": url,
                            "title": title,
                            "snippet": (item.get("body") or item.get("excerpt") or "")[:400],
                            "source": item.get("source") or domain_of(url),
                            "published_at": iso_when(item.get("date") or ""),
                            "provider": "duckduckgo",
                        }
                    )
    except Exception:
        return hits
    return hits


def fetch_newsapi(client: httpx.Client, api_key: str) -> list[dict]:
    key = (api_key or "").strip()
    if not key:
        return []
    q = NEWSAPI_QUERY
    url = (
        "https://newsapi.org/v2/everything"
        f"?q={quote_plus(q)}&language=en&sortBy=publishedAt&pageSize=40&apiKey={quote_plus(key)}"
    )
    resp = _get(client, url)
    if resp is None:
        return []
    try:
        payload = resp.json()
    except Exception:
        return []
    hits = []
    for art in payload.get("articles") or []:
        url_v = ((art.get("url") or "").strip())
        title = (art.get("title") or "").strip()
        if not url_v or not title:
            continue
        src = art.get("source") or {}
        hits.append(
            {
                "url": url_v,
                "title": title,
                "snippet": (art.get("description") or "")[:400],
                "source": (src.get("name") if isinstance(src, dict) else "") or domain_of(url_v),
                "published_at": iso_when(art.get("publishedAt") or ""),
                "provider": "newsapi",
            }
        )
    return hits


def fetch_gnews(client: httpx.Client, api_key: str) -> list[dict]:
    key = (api_key or "").strip()
    if not key:
        return []
    q = GNEWS_QUERY
    url = (
        "https://gnews.io/api/v4/search"
        f"?q={quote_plus(q)}&lang=en&max=25&from="
        + (utcnow() - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
        + f"&apikey={quote_plus(key)}"
    )
    resp = _get(client, url)
    if resp is None:
        return []
    try:
        payload = resp.json()
    except Exception:
        return []
    hits = []
    for art in payload.get("articles") or []:
        url_v = (art.get("url") or "").strip()
        title = (art.get("title") or "").strip()
        if not url_v or not title:
            continue
        src = art.get("source") or {}
        hits.append(
            {
                "url": url_v,
                "title": title,
                "snippet": (art.get("description") or "")[:400],
                "source": (src.get("name") if isinstance(src, dict) else "") or domain_of(url_v),
                "published_at": iso_when(art.get("publishedAt") or ""),
                "provider": "gnews",
            }
        )
    return hits


def fetch_newsdata(client: httpx.Client, api_key: str) -> list[dict]:
    key = (api_key or "").strip()
    if not key:
        return []
    q = NEWSDATA_QUERY
    url = (
        "https://newsdata.io/api/1/latest"
        f"?apikey={quote_plus(key)}&q={quote_plus(q)}&language=en"
    )
    resp = _get(client, url)
    if resp is None:
        return []
    try:
        payload = resp.json()
    except Exception:
        return []
    hits = []
    for art in payload.get("results") or []:
        url_v = (art.get("link") or art.get("url") or "").strip()
        title = (art.get("title") or "").strip()
        if not url_v or not title:
            continue
        hits.append(
            {
                "url": url_v,
                "title": title,
                "snippet": (art.get("description") or "")[:400],
                "source": art.get("source_id") or domain_of(url_v),
                "published_at": iso_when(art.get("pubDate") or ""),
                "provider": "newsdata",
            }
        )
    return hits


def fetch_guardian(client: httpx.Client, api_key: str) -> list[dict]:
    key = (api_key or "").strip()
    if not key:
        return []
    url = (
        "https://content.guardianapis.com/search"
        f"?api-key={quote_plus(key)}&q={quote_plus(GUARDIAN_QUERY)}"
        "&section=business&page-size=25&order-by=newest"
        "&show-fields=trailText"
    )
    resp = _get(client, url)
    if resp is None:
        return []
    try:
        payload = resp.json()
    except Exception:
        return []
    hits = []
    for art in (payload.get("response") or {}).get("results") or []:
        url_v = (art.get("webUrl") or "").strip()
        title = (art.get("webTitle") or "").strip()
        if not url_v or not title:
            continue
        fields = art.get("fields") or {}
        hits.append(
            {
                "url": url_v,
                "title": title,
                "snippet": (fields.get("trailText") or "")[:400],
                "source": "The Guardian",
                "published_at": iso_when(art.get("webPublicationDate") or ""),
                "provider": "guardian",
            }
        )
    return hits


def _dedupe(rows: list[dict]) -> list[dict]:
    from .news_relevance import canonicalize_url, news_fingerprint

    seen: set[str] = set()
    out: list[dict] = []
    for row in rows:
        fp = news_fingerprint(row.get("url") or "", row.get("title") or "")
        if not fp or fp in seen:
            continue
        seen.add(fp)
        row = dict(row)
        row["url"] = canonicalize_url(row.get("url") or "") or (row.get("url") or "")
        row["fingerprint"] = fp
        out.append(row)
    return out


def harvest_news(
    *,
    extra_keys: dict[str, str] | None = None,
    hours: int = 36,
) -> tuple[list[dict], dict[str, int]]:
    """Pull from free news sources only. Never calls Tavily."""
    keys = extra_keys or {}
    stats: dict[str, int] = {}

    def _run(name: str, fn: Callable[[], list[dict]]) -> list[dict]:
        try:
            rows = fn() or []
        except Exception:
            rows = []
        stats[name] = len(rows)
        return rows

    jobs: list[tuple[str, Callable[[], list[dict]]]] = []

    def google_job() -> list[dict]:
        with _client() as client:
            return fetch_google_news(client)

    def gdelt_job() -> list[dict]:
        with _client() as client:
            return fetch_gdelt(client)

    def rss_job() -> list[dict]:
        with _client() as client:
            return fetch_rss_feeds(client)

    jobs.append(("google_news", google_job))
    jobs.append(("gdelt", gdelt_job))
    jobs.append(("rss", rss_job))
    jobs.append(("duckduckgo", fetch_ddg_news))

    newsapi = (keys.get("newsapi") or os.getenv("NEWSAPI_KEY") or "").strip()
    gnews = (keys.get("gnews") or os.getenv("GNEWS_API_KEY") or "").strip()
    newsdata = (keys.get("newsdata") or os.getenv("NEWSDATA_API_KEY") or "").strip()
    guardian = (keys.get("guardian") or os.getenv("GUARDIAN_API_KEY") or "").strip()

    def _keyed(fn, key: str) -> list[dict]:
        with _client() as client:
            return fn(client, key)

    if newsapi:
        jobs.append(("newsapi", lambda: _keyed(fetch_newsapi, newsapi)))
    if gnews:
        jobs.append(("gnews", lambda: _keyed(fetch_gnews, gnews)))
    if newsdata:
        jobs.append(("newsdata", lambda: _keyed(fetch_newsdata, newsdata)))
    if guardian:
        jobs.append(("guardian", lambda: _keyed(fetch_guardian, guardian)))

    batches = map_parallel(
        jobs,
        lambda pair: _run(pair[0], pair[1]),
        env_name="NEWS_WORKERS",
        default_workers=8,
        return_exceptions=True,
    )
    merged: list[dict] = []
    for batch in batches:
        if isinstance(batch, BaseException):
            continue
        merged.extend(batch)
    windowed = [
        r
        for r in merged
        if in_window(
            r.get("published_at") or "",
            hours=hours,
            provider=r.get("provider") or "",
        )
    ]
    unique = _dedupe(windowed)
    stats["raw"] = len(merged)
    stats["windowed"] = len(windowed)
    stats["unique"] = len(unique)
    return unique, stats
