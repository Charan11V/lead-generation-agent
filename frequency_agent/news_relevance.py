"""Score public news against Frequency's BD objective — not a typed ICP.

Keeps stories that look like exec-search, fractional-CXO, or capital-advisory
timing: funding, CXO moves, hiring, expansion, capital. Drops sports, listicles,
and generic market noise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .util import domain_of, looks_like_aggregator

MIN_RELEVANCE = 18  # rank band only — weak hits still appear, sorted lower
HIGH_RELEVANCE = 32
MID_RELEVANCE = 18

SERVICE_EXEC = "exec_search"
SERVICE_FRAC = "fractional_cxo"
SERVICE_CAP = "capital_advisory"
SERVICE_OTHER = "other"

_TRACKING = (
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "gclid",
    "fbclid",
    "mc_cid",
    "mc_eid",
    "igshid",
)

_SPORTS = (
    "cricket",
    "ipl",
    "premier league",
    "football score",
    "tennis",
    "nba",
    "fifa",
    "world cup",
    "olympics",
    "match report",
    "wicket",
    "hat-trick",
)

_NOISE = (
    "horoscope",
    "recipe",
    "celebrity wedding",
    "box office",
    "movie review",
    "weather forecast",
    "stock tips for today",
    "sensex live",
    "nifty live",
    "crypto price",
    "bitcoin price",
)

_FUNDING = (
    (r"\bseries [abcde]\b", 20, "funding round"),
    (r"\bpre-?series\b", 16, "pre-series raise"),
    (r"\bseed round\b|\braised a seed\b|\bseed funding\b", 16, "seed raise"),
    (r"\bbridge round\b|\bgrowth round\b|\bgrowth equity\b", 16, "growth round"),
    (r"\braised\b.{0,40}\b(million|mn|cr|crore)\b", 18, "raise announced"),
    (r"\bfunding\b|\bfundraised\b|\bfundraise\b", 12, "funding"),
    (r"\bcloses?\b.{0,24}\b(round|fund)\b", 14, "round closed"),
)

_CXO = r"ceo|cfo|cto|chro|cmo|coo|cpo|ciso|cgo|cro|cbo|cxo"

_LEADERSHIP = (
    (rf"\bappointed\b.{{0,30}}\b({_CXO})\b", 22, "CXO appointment"),
    (rf"\b({_CXO})\b.{{0,30}}\b(appointed|named|joins)\b", 20, "CXO appointment"),
    (rf"\b(steps down|resigns|resigned|departs|departure|exits|ousted)\b.{{0,30}}\b({_CXO})\b", 20, "CXO departure"),
    (rf"\b({_CXO})\b.{{0,30}}\b(steps down|resigns|resigned|departs|exits|ousted)\b", 20, "CXO departure"),
    (r"\bnamed\b.{0,24}\b(chief|vice president|vp|head of|chief of staff|managing director)\b", 16, "senior hire"),
    (rf"\bhiring\b.{{0,40}}\b({_CXO}|vp|vice president|head of|chief of staff|chief)\b", 16, "leadership hiring"),
    (rf"\b(first|next)\b.{{0,16}}\b({_CXO})\b", 14, "first/next CXO"),
    (r"\bchief of staff\b", 14, "chief of staff"),
    (r"\bhead of (talent|people|hr|finance|engineering|sales|marketing|product)\b", 14, "functional head"),
)

_FRACTIONAL = (
    (rf"\bfractional\b.{{0,20}}\b({_CXO})\b", 24, "fractional CXO"),
    (rf"\binterim\b.{{0,16}}\b({_CXO})\b", 18, "interim CXO"),
    (rf"\bpart-time\b.{{0,16}}\b({_CXO})\b", 16, "part-time CXO"),
    (rf"\bwithout a (full-time )?({_CXO})\b", 16, "leadership gap"),
)

_CAPITAL = (
    (r"\bventure debt\b|\bstructured (credit|debt)\b|\bprivate credit\b", 20, "venture debt"),
    (r"\bcapital (raise|advisory|stack)\b", 14, "capital move"),
    (r"\b(equity raise|debt raise)\b", 14, "capital move"),
    (r"\bworking capital\b", 10, "working capital"),
    (r"\bpre-ipo\b|\bsecondary (sale|share)\b|\bgrowth equity\b", 12, "capital event"),
)

_EXPANSION = (
    (r"\b(expands?|expansion)\b.{0,40}\b(india|us|usa|europe|sea|middle east|office)\b", 12, "expansion"),
    (r"\b(market entry|us expansion|enters the (us|uk|india))\b", 12, "market entry"),
    (r"\bopens? (a )?new (office|market|vertical)\b", 12, "new market"),
    (r"\bnew (vertical|business line)\b", 10, "new vertical"),
    (r"\bglobal capability centre\b|\bgcc\b.{0,24}\b(india|bengaluru|bangalore|hyderabad|gurugram)\b", 14, "GCC"),
    (r"\b(gic|captive centre|captive center|global in-house)\b", 12, "GCC"),
)

_CONTEXT = (
    (r"\b(startup|start-up|founder-led|growth-stage)\b", 6, "startup"),
    (r"\b(fintech|payments|saas|d2c|consumer brand|deep ?tech|ai company|semiconductor|quick commerce)\b", 8, "sector"),
    (r"\b(india|indian|bengaluru|bangalore|mumbai|delhi|hyderabad|pune|chennai|gurugram|gurgaon)\b", 6, "geo"),
    (r"\b(private equity|venture capital|\bpe\b|\bvc\b|portfolio company)\b", 6, "PE/VC"),
    (r"\b(leadership|talent|executive search|cxo)\b", 6, "leadership language"),
)


@dataclass
class ScoredNews:
    url: str
    title: str
    source: str = ""
    published_at: str = ""
    snippet: str = ""
    provider: str = ""
    fingerprint: str = ""
    score: int = 0
    service_line: str = SERVICE_EXEC
    reasons: list[str] = field(default_factory=list)
    why_relevant: str = ""
    keep: bool = True

    def to_row(self) -> dict:
        return {
            "fingerprint": self.fingerprint,
            "url": self.url,
            "title": self.title,
            "source": self.source,
            "published_at": self.published_at,
            "snippet": self.snippet,
            "provider": self.provider,
            "score": self.score,
            "service_line": self.service_line,
            "reasons": list(self.reasons),
            "why_relevant": self.why_relevant,
        }


def canonicalize_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parsed = urlparse(raw)
    except Exception:
        return raw.split("#", 1)[0].rstrip("/")
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (parsed.path or "").rstrip("/")
    query = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in _TRACKING
    ]
    query.sort()
    return urlunparse((parsed.scheme or "https", host, path, "", urlencode(query), ""))


def news_fingerprint(url: str, title: str = "") -> str:
    from .util import slug_id

    canon = canonicalize_url(url)
    if canon:
        return slug_id(canon)
    return slug_id((title or "").strip().lower())


def _blob(title: str, snippet: str) -> str:
    return f"{title or ''} {snippet or ''}".lower()


def _blocked_noise(blob: str) -> str | None:
    if any(tok in blob for tok in _SPORTS):
        return "sports"
    if any(tok in blob for tok in _NOISE):
        return "off-topic"
    return None


def _apply_patterns(blob: str, patterns: tuple, reasons: list[str]) -> int:
    total = 0
    for rx, pts, label in patterns:
        if re.search(rx, blob, flags=re.I):
            total += pts
            if label not in reasons:
                reasons.append(label)
    return total


# Fetch-aligned hooks used to gate publisher RSS (not scored into rank).
_DEAL_HOOKS = (
    (r"\bacqui-?hire\b", 1, "acqui-hire"),
    (r"\b(acquisition|acquires|acquired|merger|buyout)\b", 1, "acquisition"),
    (r"\bexecutive search\b", 1, "executive search"),
    (r"\bleadership hiring\b", 1, "leadership hiring"),
    (r"\b(final close|closed fund|fund iii)\b", 1, "fund close"),
)


def has_frequency_trigger(title: str, snippet: str = "") -> bool:
    """True when title/snippet has a Frequency fetch hook — not India/startup alone."""
    blob = _blob(title, snippet)
    if not blob.strip():
        return False
    if _blocked_noise(blob):
        return False
    reasons: list[str] = []
    if _apply_patterns(blob, _FUNDING, reasons):
        return True
    if _apply_patterns(blob, _LEADERSHIP, reasons):
        return True
    if _apply_patterns(blob, _FRACTIONAL, reasons):
        return True
    if _apply_patterns(blob, _CAPITAL, reasons):
        return True
    if _apply_patterns(blob, _EXPANSION, reasons):
        return True
    if _apply_patterns(blob, _DEAL_HOOKS, reasons):
        return True
    return False


def infer_service_line(reasons: list[str], score_frac: int, score_cap: int, score_lead: int) -> str:
    if score_frac >= 16:
        return SERVICE_FRAC
    if score_cap >= 14 and score_cap >= score_lead:
        return SERVICE_CAP
    if score_lead >= 14:
        return SERVICE_EXEC
    if "venture debt" in reasons or "capital move" in reasons:
        return SERVICE_CAP
    if "fractional CXO" in reasons or "interim CXO" in reasons:
        return SERVICE_FRAC
    return SERVICE_EXEC


def rank_band(score: int) -> str:
    if score >= HIGH_RELEVANCE:
        return "high"
    if score >= MID_RELEVANCE:
        return "mid"
    return "low"


def deterministic_eval(item: ScoredNews | dict) -> dict:
    """Keyword verdict for on-demand check when OpenAI is not used."""
    if isinstance(item, dict):
        score = int(item.get("score") or 0)
        reasons = item.get("reasons") or []
        title = (item.get("title") or "This story").rstrip(".")
        service = item.get("service_line") or SERVICE_EXEC
    else:
        score = int(item.score or 0)
        reasons = list(item.reasons)
        title = (item.title or "This story").rstrip(".")
        service = item.service_line or SERVICE_EXEC
    if isinstance(reasons, str):
        reasons = [reasons]
    hooks = ", ".join(str(r) for r in reasons[:4] if r) or "no Frequency trigger words"
    line = {
        SERVICE_EXEC: "executive search",
        SERVICE_FRAC: "fractional CXO",
        SERVICE_CAP: "capital advisory",
    }.get(service, "leadership advisory")
    if score >= MID_RELEVANCE:
        why = (
            f"{title} looks relevant for Frequency's {line} practice. "
            f"Deterministic rank {score}/100 from: {hooks}. "
            "Public timing like this is usually worth a BD look."
        )
        return {"relevant": True, "why": why, "service_line": service}
    if score > 0:
        why = (
            f"{title} is a weak match (rank {score}/100). "
            f"Partial hooks: {hooks}. It may be adjacent to Frequency's mandate, "
            "but there is no strong funding, CXO, hiring, expansion, or capital signal."
        )
        return {"relevant": False, "why": why, "service_line": service}
    why = (
        f"{title} does not show a Frequency trigger in the headline or snippet "
        f"(rank {score}/100). It was kept from the 24-hour sweep so you can judge it, "
        "but exec search / fractional CXO / capital advisory language is missing."
    )
    return {"relevant": False, "why": why, "service_line": service}


def score_article(
    *,
    url: str,
    title: str,
    snippet: str = "",
    source: str = "",
    published_at: str = "",
    provider: str = "",
    client_domains: set[str] | None = None,
) -> ScoredNews:
    item = ScoredNews(
        url=(url or "").strip(),
        title=(title or "").strip(),
        source=(source or "").strip() or domain_of(url),
        published_at=published_at or "",
        snippet=(snippet or "").strip()[:600],
        provider=provider or "",
        fingerprint=news_fingerprint(url, title),
    )
    blob = _blob(item.title, item.snippet)
    noise = _blocked_noise(blob)
    if noise:
        item.keep = False
        item.reasons = [noise]
        return item
    if looks_like_aggregator(item.title, item.url):
        item.keep = False
        item.reasons = ["listicle"]
        return item
    host = domain_of(item.url)
    if client_domains and host in client_domains:
        item.keep = False
        item.reasons = ["existing client"]
        return item

    reasons: list[str] = []
    funding = _apply_patterns(blob, _FUNDING, reasons)
    lead = _apply_patterns(blob, _LEADERSHIP, reasons)
    frac = _apply_patterns(blob, _FRACTIONAL, reasons)
    cap = _apply_patterns(blob, _CAPITAL, reasons)
    exp = _apply_patterns(blob, _EXPANSION, reasons)
    ctx = _apply_patterns(blob, _CONTEXT, reasons)
    total = min(100, funding + lead + frac + cap + exp + ctx)
    item.score = total
    item.service_line = infer_service_line(reasons, frac, cap, lead) if total else SERVICE_OTHER
    item.reasons = reasons
    item.keep = True
    item.why_relevant = ""
    return item


def service_line_label(value: str | None) -> str:
    return {
        SERVICE_EXEC: "Exec search",
        SERVICE_FRAC: "Fractional CXO",
        SERVICE_CAP: "Capital advisory",
        SERVICE_OTHER: "Unscored",
    }.get((value or "").strip(), "Frequency")
