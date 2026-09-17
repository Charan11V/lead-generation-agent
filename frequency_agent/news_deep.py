"""Deep research for news-list articles → full Frequency lead payloads."""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import parse_qs, unquote, urlparse

from .graph import _enrich_cluster
from .llm import LLM
from .memory import Memory, icp_fingerprint
from .news_lists import NewsListStore
from .schemas import ICP
from .search import SearchClient

NEWS_EVENT_TAG = "[News Event]"
_JUNK_HOST_PARTS = (
    "news.google.com",
    "google.com/rss",
    "googleapis.com",
    "news.yahoo.com/rss",
)


def news_event_search_name(list_name: str = "", article_title: str = "") -> str:
    base = (list_name or "").strip() or (article_title or "").strip()[:80] or "News list"
    return f"{NEWS_EVENT_TAG} {base}"


def news_event_icp_text(article: dict, *, list_name: str = "") -> str:
    title = (article.get("title") or "").strip()
    url = (article.get("url") or "").strip()
    snip = (article.get("snippet") or article.get("why_relevant") or "").strip()
    source = (article.get("source") or "").strip()
    parts = [NEWS_EVENT_TAG]
    if list_name:
        parts.append(f"List: {list_name}")
    if title:
        parts.append(title)
    if source:
        parts.append(f"Source: {source}")
    if url and not is_junk_news_url(url):
        parts.append(url)
    if snip:
        parts.append(snip)
    return "\n".join(parts)


def is_news_event_item(item: dict | None) -> bool:
    if not item:
        return False
    if (item.get("source_kind") or "").strip() == "news_event":
        return True
    blob = f"{item.get('search_name') or ''} {item.get('icp_text') or ''}"
    return NEWS_EVENT_TAG in blob


def is_junk_news_url(url: str) -> bool:
    low = (url or "").strip().lower()
    if not low:
        return True
    return any(part in low for part in _JUNK_HOST_PARTS)


def unwrap_article_url(url: str, description: str = "") -> str:
    """Prefer a real publisher URL over Google News / RSS wrappers."""
    href = re.search(r'href="(https?://[^"]+)"', description or "")
    if href:
        candidate = href.group(1)
        if not is_junk_news_url(candidate):
            return candidate
    parsed = urlparse(url or "")
    qs = parse_qs(parsed.query)
    for key in ("url", "q"):
        vals = qs.get(key) or []
        if vals and str(vals[0]).startswith("http") and not is_junk_news_url(str(vals[0])):
            return unquote(str(vals[0]))
    return (url or "").strip()


def _service_line(article: dict) -> str:
    line = (article.get("service_line") or "").strip()
    if line in {"exec_search", "fractional_cxo", "capital_advisory"}:
        return line
    return "exec_search"


def build_news_icp(article: dict, *, list_name: str = "") -> ICP:
    return ICP(
        raw_text=news_event_icp_text(article, list_name=list_name),
        service_line=_service_line(article),  # type: ignore[arg-type]
        geo="India",
        sectors=[],
        stages=[],
        buying_signals=[
            "funding",
            "leadership change",
            "expansion",
            "hiring",
            "product launch",
            "capital raise",
        ],
        target_contacts=["CEO", "Founder", "CHRO", "CFO", "COO", "CTO"],
        notes="Deep research from Signal Desk news list — article is the brief.",
    )


def guess_company_from_title(title: str) -> str:
    """Fast heuristic — skip an LLM round-trip when the headline is clear."""
    t = (title or "").strip()
    if not t:
        return ""
    t = re.sub(r"\s+[-|–—].*$", "", t).strip()
    patterns = [
        r"(?:platform|startup|company|firm)\s+([A-Z][A-Za-z0-9&.\'-]{1,40}(?:\s+[A-Z][A-Za-z0-9&.\'-]{0,20}){0,3})\s+"
        r"(?:raises|raised|secures|secured|appoints|appointed|launches|launched|closes|closed|hires|hired)",
        r"^([A-Z0-9][A-Za-z0-9&.\'-]{1,40}(?:\s+[A-Z0-9][A-Za-z0-9&.\'-]{0,20}){0,3})\s+"
        r"(?:raises|raised|secures|secured|appoints|appointed|launches|launched|closes|closed|hires|hired)",
    ]
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            name = m.group(1).strip(" ,.-")
            if len(name) >= 2 and name.lower() not in {"the", "a", "an", "india", "indian"}:
                return name[:120]
    return ""


def extract_company_name(llm: LLM | None, article: dict) -> str:
    title = (article.get("title") or "").strip()
    guessed = guess_company_from_title(title)
    if guessed:
        return guessed
    if llm is None:
        cleaned = re.sub(r"[\|:–—].*$", "", title).strip()
        return (cleaned or title)[:120] or "Unknown company"
    snippet = (article.get("snippet") or "").strip()
    source = (article.get("source") or "").strip()
    prompt = f"""Extract the primary company name this news story is about.
Return JSON only: {{"company": "Name"}} or {{"company": ""}} if unclear.

Title: {title}
Source: {source}
Snippet: {snippet[:600]}
"""
    try:
        raw = llm.text(
            [
                {
                    "role": "system",
                    "content": "You extract company names from headlines. Never invent. JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0,
        )
        m = re.search(r"\{.*\}", raw or "", re.S)
        if m:
            data = json.loads(m.group(0))
            name = (data.get("company") or "").strip()
            if name and name.lower() not in {"unknown", "n/a", "none"}:
                return name
    except Exception:
        pass
    cleaned = re.sub(r"[\|:–—].*$", "", title).strip()
    return (cleaned or title)[:120] or "Unknown company"


def article_to_cluster(article: dict, company: str, *, list_name: str = "") -> dict:
    title = (article.get("title") or "").strip()
    raw_url = (article.get("url") or "").strip()
    snip = (article.get("snippet") or article.get("why_relevant") or "").strip()
    published = (article.get("published_at") or "").strip()
    url = unwrap_article_url(raw_url, snip)
    mentions: list[dict] = []
    # Never seed enrich with Google News / RSS wrapper URLs — they pollute website + channels.
    if url and not is_junk_news_url(url):
        mentions.append(
            {
                "name": title or company,
                "source_url": url,
                "evidence_quote": snip,
                "signal_summary": snip or title,
                "signal_date": published,
            }
        )
    elif snip or title:
        # Seed evidence without a junk URL; enrich_cluster will web-search the company.
        mentions.append(
            {
                "name": title or company,
                "source_url": "",
                "evidence_quote": snip or title,
                "signal_summary": snip or title,
                "signal_date": published,
            }
        )
    return {
        "name": company,
        "website": "not_found",
        "domain": "unknown",
        "industry": "unknown",
        "country": "unknown",
        "city": "unknown",
        "stage": "unknown",
        "discovery_web_query": news_event_search_name(list_name, title),
        "mentions": mentions,
    }


def sanitize_news_lead(payload: dict) -> dict:
    """Strip aggregator URLs that should never be company website / approach channel."""
    if is_junk_news_url(str(payload.get("website") or "")):
        payload["website"] = "not_found"
        payload["domain"] = "unknown"
    channels = []
    for ch in payload.get("approach_channels") or []:
        if not isinstance(ch, dict):
            continue
        val = str(ch.get("value") or "")
        if is_junk_news_url(val):
            continue
        channels.append(ch)
    payload["approach_channels"] = channels
    best = str(payload.get("best_approach_channel") or "")
    if is_junk_news_url(best) or (best.startswith("url:") and is_junk_news_url(best[4:])):
        payload["best_approach_channel"] = ""
        if channels:
            kind = channels[0].get("kind") or "other"
            payload["best_approach_channel"] = f"{kind}:{channels[0].get('value') or ''}"
    sources = []
    for s in (payload.get("signal") or {}).get("sources") or []:
        if isinstance(s, dict) and not is_junk_news_url(str(s.get("url") or "")):
            sources.append(s)
    if isinstance(payload.get("signal"), dict) and sources:
        payload["signal"]["sources"] = sources
    return payload


def deep_research_article(
    article: dict,
    *,
    openai_key: str,
    tavily_key: str = "",
    memory: Memory,
    list_name: str = "",
    list_id: str = "",
    news_id: str = "",
    llm: LLM | None = None,
    client: SearchClient | None = None,
) -> dict:
    """
    Run full Frequency enrich path for one news article.
    Returns lead payload dict (same shape as ICP Results).
    Raises on hard failure.
    """
    if not (openai_key or "").strip() and llm is None:
        raise RuntimeError("OPENAI_API_KEY is required for deep research.")
    llm = llm or LLM(api_key=openai_key)
    client = client or SearchClient(tavily_key=tavily_key or "")
    icp = build_news_icp(article, list_name=list_name)
    company = extract_company_name(llm, article)
    cluster = article_to_cluster(article, company, list_name=list_name)
    run_id = "news_" + uuid.uuid4().hex[:10]
    query_id = f"news:{(list_id or 'list')}:{(news_id or article.get('news_id') or '')}"
    icp_hash = icp_fingerprint(icp.service_line, icp.raw_text)
    payload, skipped = _enrich_cluster(
        cluster,
        llm=llm,
        client=client,
        memory=memory,
        icp=icp,
        icp_hash=icp_hash,
        seen_domains=set(),
        seen_names=set(),
        discovery_queries=[],
        query_id=query_id,
        run_id=run_id,
    )
    if not payload:
        raise RuntimeError(
            "Could not enrich this story (no usable web evidence or company skipped)."
            if not skipped
            else "Company skipped by dedupe rules."
        )
    payload = sanitize_news_lead(payload)
    payload["source_kind"] = "news_event"
    payload["news_id"] = (news_id or article.get("news_id") or "").strip()
    payload["news_list_id"] = (list_id or "").strip()
    payload["news_title"] = (article.get("title") or "").strip()
    payload["news_url"] = unwrap_article_url(
        (article.get("url") or "").strip(),
        (article.get("snippet") or "").strip(),
    )
    payload["search_name"] = news_event_search_name(list_name, article.get("title") or "")
    _seed_queue_selection(payload)
    return payload


def _seed_queue_selection(lead: dict) -> None:
    people = lead.get("contacts") or lead.get("verified_contacts") or []
    if isinstance(people, list) and people:
        for person in people:
            if not isinstance(person, dict):
                continue
            if (person.get("email_draft") or "").strip():
                person["queue_email"] = True
            if (person.get("linkedin_note") or "").strip():
                person["queue_linkedin"] = True
        primary = next((p for p in people if isinstance(p, dict) and p.get("is_primary")), people[0])
        if isinstance(primary, dict):
            lead["contact"] = primary
    else:
        if (lead.get("email_draft") or "").strip():
            lead["queue_company_email"] = True
        if (lead.get("linkedin_note") or "").strip():
            lead["queue_company_linkedin"] = True


def deep_research_pending_on_list(
    *,
    list_id: str,
    list_store: NewsListStore,
    memory: Memory,
    openai_key: str,
    tavily_key: str = "",
    on_progress: Callable[[int, int, str], None] | None = None,
) -> dict:
    """
    Deep-research only articles not yet enriched on this list.
    Articles run in parallel (default 3 workers) — same quality path per story.
    Returns {attempted, ok, failed, errors: [...]}.
    """
    meta = list_store.get_list(list_id) or {}
    list_name = (meta.get("name") or "").strip()
    pending = list_store.pending_deep_research_ids(list_id)
    ok = 0
    failed = 0
    errors: list[str] = []
    items_by_id = {
        (i.get("news_id") or "").strip(): i for i in list_store.list_items_with_news(list_id)
    }
    if not pending:
        return {"attempted": 0, "ok": 0, "failed": 0, "errors": [], "pending_before": 0}

    workers = max(1, min(int(os.getenv("NEWS_DEEP_WORKERS", "3") or "3"), len(pending)))
    done = 0

    def _one(nid: str) -> tuple[str, dict | None, str]:
        article = items_by_id.get(nid) or {}
        try:
            lead = deep_research_article(
                article,
                openai_key=openai_key,
                tavily_key=tavily_key,
                memory=memory,
                list_name=list_name,
                list_id=list_id,
                news_id=nid,
            )
            return nid, lead, ""
        except Exception as exc:
            return nid, None, str(exc)[:240]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_one, nid): nid for nid in pending}
        for fut in as_completed(futures):
            nid = futures[fut]
            article = items_by_id.get(nid) or {}
            done += 1
            if on_progress:
                on_progress(done, len(pending), article.get("title") or nid)
            try:
                nid_out, lead, err = fut.result()
            except Exception as exc:
                failed += 1
                msg = str(exc)[:240]
                errors.append(f"{article.get('title') or nid}: {msg}")
                list_store.save_deep_research(list_id, nid, None, error=msg)
                continue
            if lead:
                list_store.save_deep_research(list_id, nid_out, lead)
                try:
                    memory.upsert_lead(lead, icp_hash=lead.get("icp_hash") or "")
                except Exception:
                    pass
                ok += 1
            else:
                failed += 1
                errors.append(f"{article.get('title') or nid_out}: {err}")
                list_store.save_deep_research(list_id, nid_out, None, error=err)

    return {
        "attempted": len(pending),
        "ok": ok,
        "failed": failed,
        "errors": errors,
        "pending_before": len(pending),
    }
