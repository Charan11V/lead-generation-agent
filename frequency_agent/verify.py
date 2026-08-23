"""Signal verification. LLM is not the source of truth."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from urllib.parse import urlparse

from .scoring import recency_days
from .schemas import CompanyLead, Signal, Source


STRONG = {
    "funding",
    "leadership_departure",
    "new_executive",
    "expansion",
    "hiring_surge",
    "new_business_line",
    "acquisition",
    "product_launch",
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def quote_supported(quote: str, corpus: str) -> bool:
    if not quote or len(quote) < 12:
        return False
    q = _norm(quote)
    t = _norm(corpus)
    if q[:48] in t or q in t:
        return True
    # token overlap on a distinctive slice
    return SequenceMatcher(None, q[:180], t[:4000]).ratio() > 0.22


def verify_signal(lead: CompanyLead, corpus: str) -> Signal:
    sig = lead.signal
    supported = quote_supported(sig.evidence_quote, corpus) or quote_supported(sig.summary, corpus)
    days = recency_days(sig.date)
    sig.recency_days = days

    if not sig.summary or sig.type in {"none"}:
        sig.confidence = "UNVERIFIED"
        sig.usable_in_outreach = False
        sig.inferred = True
        sig.inferred_reason = "No extractable public signal."
        return sig

    if not supported:
        sig.confidence = "UNVERIFIED"
        sig.usable_in_outreach = False
        sig.inferred = True
        sig.inferred_reason = "Claim not found in source text — do not use in outreach."
        return sig

    named_publisher = False
    if sig.sources:
        host = urlparse(sig.sources[0].url).netloc.lower()
        named_publisher = any(
            p in host
            for p in (
                "economictimes",
                "livemint",
                "inc42",
                "yourstory",
                "techcrunch",
                "thehindu",
                "business-standard",
                "moneycontrol",
                "reuters",
                "bloomberg",
                "forbes",
                "entrackr",
                "the-ken",
                "theken",
                "vccircle",
                "dealstreetasia",
            )
        ) or bool(sig.sources[0].url)

    if sig.type in STRONG and named_publisher and days is not None and days <= 180:
        sig.confidence = "HIGH"
    elif sig.type in STRONG and supported:
        sig.confidence = "MEDIUM"
    else:
        sig.confidence = "LOW"

    sig.usable_in_outreach = sig.confidence in {"HIGH", "MEDIUM"}
    sig.inferred = False
    return sig
