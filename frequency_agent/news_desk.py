"""Run a Frequency signal-desk scan: harvest → deterministic rank → incremental save."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from .llm import LLM
from .news_relevance import ScoredNews, deterministic_eval, score_article
from .news_sources import harvest_news
from .news_store import NewsStore
from .util import default_db_path


def _client_domains() -> set[str]:
    path = Path(__file__).resolve().parent.parent / "data" / "exclude_domains.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    return {str(d).strip().lower().replace("www.", "") for d in (payload.get("domains") or []) if d}


class _ArticleEval(BaseModel):
    relevant: bool
    why: str = ""
    service: str = "exec_search"


def evaluate_article(item: dict, openai_key: str = "") -> dict:
    """On-demand relevance check. Uses OpenAI only when the user clicks and a key exists."""
    fallback = deterministic_eval(item)
    key = (openai_key or "").strip()
    if not key:
        return fallback
    title = (item.get("title") or "").strip()
    snippet = (item.get("snippet") or "").strip()[:400]
    score = int(item.get("score") or 0)
    reasons = item.get("reasons") or []
    if isinstance(reasons, str):
        reason_txt = reasons
    else:
        reason_txt = ", ".join(str(r) for r in reasons[:6])
    system = (
        "You judge one news article for Frequency.\n"
        "Frequency is a Bengaluru boutique that operates in India. It sells:\n"
        "- retained executive search (first or next CXO/VP at founder-led and growth-stage "
        "companies, and VP+ in India GCCs)\n"
        "- fractional / interim CXO (senior ownership of finance, product, tech, GTM, or HR "
        "when a full-time CXO is not justified yet)\n"
        "- capital advisory with Onlycapital (equity, venture/structured debt, capital stack "
        "for growth-stage founders)\n"
        "It also watches PE/VC when the story is Indian portfolio companies needing operators, "
        "not generic LP or global fund news.\n"
        "\n"
        "Frequency is looking for a named company or fund PLUS a live signal that usually means "
        "leadership or capital is in play in India: a raise/round/capital event; a CXO or VP "
        "hired, departing, or being hired; a function with no senior owner (including "
        "fractional/interim language); expansion, new market, new line, or GCC/GIC build-out "
        "in India; a PE/VC portfolio leadership angle for Indian companies.\n"
        "\n"
        "Geography: only India opportunities. relevant=true only if the company, operations, "
        "GCC, raise, or mandate is in India or clearly India-linked (Indian HQ/ops, Indian "
        "founder-led company, India expansion, or a fund hiring operators for Indian portfolio "
        "companies). A matching sector (fintech, SaaS, AI, D2C) outside India with no India hook "
        "is relevant=false. Frequency does not pursue US-only or Europe-only stories.\n"
        "\n"
        "Frequency is not looking for: theme pieces, listicles, macro/policy, markets/sports/"
        "awards, product puff, unnamed “startups”, or commentary with no company-level "
        "leadership or capital hook.\n"
        "\n"
        "Start from the title and snippet, but you may use your own knowledge of the named "
        "company, fund, people, or market when you are sure (for example: it is India-HQ, "
        "founder-led, a GCC in Bengaluru, growth-stage, fintech/SaaS). Use that to fill gaps "
        "the article leaves out — geography, what the company is, whether the signal is on-brief "
        "for Frequency in India. Do not invent facts, buyers, or that they will hire. If you are "
        "not sure, ignore that knowledge and do not guess.\n"
        "relevant=true if the article plus what you are sure you know is on-brief for what "
        "Frequency is looking for in India. relevant=false if it is not. If you would have to "
        "guess why Frequency cares, or guess an India link, relevant=false.\n"
        "This is not a decision that they will buy, that a mandate exists, or that anyone "
        "should be contacted. Incomplete web info is normal. Answer only relevant or not.\n"
        "why: 2–4 sentences — why it is or is not what Frequency is looking for in India. "
        "You may mention sure known facts (e.g. Indian HQ) separately from what the article "
        "states. No “dig further”, no “send a mail”, no flattery.\n"
        "service: exec_search, fractional_cxo, or capital_advisory (best hint; does not change "
        "the yes/no)."
    )
    user = (
        f"Title: {title}\nSnippet: {snippet}\n"
        f"Deterministic rank: {score}/100\nHooks: {reason_txt or 'none'}\n"
        "Judge relevance for Frequency in India only. Use the article plus any facts "
        "you are sure you know about the named company or people."
    )
    try:
        llm = LLM(key)
        parsed = llm.parse(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            _ArticleEval,
            model=llm.extract_model,
            temperature=0.1,
        )
        why = (parsed.why or "").strip() or fallback["why"]
        svc = (parsed.service or "").strip()
        if svc not in {"exec_search", "fractional_cxo", "capital_advisory"}:
            svc = fallback.get("service_line") or "exec_search"
        return {"relevant": bool(parsed.relevant), "why": why[:800], "service_line": svc}
    except Exception:
        return fallback


def run_signal_scan(
    *,
    owner_email: str,
    db_path: str | Path | None = None,
    extra_keys: dict[str, str] | None = None,
) -> dict:
    """Fetch last-24h news. Rank with keywords only — no OpenAI on scan."""
    path = Path(db_path) if db_path else default_db_path()
    owner = (owner_email or "").strip().lower()
    store = NewsStore(path, owner_email=owner)
    prior = store.last_scan_in_window(hours=24)
    incremental = prior is not None

    raw, source_stats = harvest_news(extra_keys=extra_keys)
    clients = _client_domains()
    scored: list[ScoredNews] = []
    for row in raw:
        item = score_article(
            url=row.get("url") or "",
            title=row.get("title") or "",
            snippet=row.get("snippet") or "",
            source=row.get("source") or "",
            published_at=row.get("published_at") or "",
            provider=row.get("provider") or "",
            client_domains=clients,
        )
        if item.keep:
            scored.append(item)

    known = store.existing_fingerprints(include_deleted=True)
    newcomers = [s for s in scored if s.fingerprint not in known]
    inserted = store.upsert_new([s.to_row() for s in newcomers])
    visible = store.list_window(hours=24)
    scan_id = store.record_scan(
        added_count=len(inserted),
        considered_count=len(raw),
        total_visible=len(visible),
        incremental=incremental,
        stats=source_stats,
    )
    return {
        "scan_id": scan_id,
        "incremental": incremental,
        "considered": len(raw),
        "matched": len(scored),
        "added": len(inserted),
        "visible": len(visible),
        "items": visible,
        "added_items": inserted,
        "source_stats": source_stats,
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "prior_scan_at": (prior or {}).get("finished_at") or "",
    }
