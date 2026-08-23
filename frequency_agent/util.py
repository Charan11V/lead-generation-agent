from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse


def slug_id(*parts: str) -> str:
    raw = "|".join(p.strip().lower() for p in parts if p)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def domain_of(url: str) -> str:
    if not url:
        return "unknown"
    raw = url.strip()
    for bad in ("[", "]", " ", "\n", "\t"):
        if bad in raw:
            raw = raw.split(bad, 1)[0]
    if "://" not in raw:
        raw = "https://" + raw
    try:
        host = urlparse(raw).netloc.lower().replace("www.", "")
        return host or "unknown"
    except Exception:
        return "unknown"


def normalize_name(name: str) -> str:
    n = re.sub(r"\b(pvt|private|limited|ltd|llc|inc|corp|technologies|technology)\b", "", name, flags=re.I)
    n = re.sub(r"[^a-z0-9]+", " ", n.lower())
    return re.sub(r"\s+", " ", n).strip()


def looks_like_aggregator(title: str, url: str) -> bool:
    blob = f"{title} {url}".lower()
    needles = [
        "top 10",
        "top 20",
        "best fintech",
        "list of startups",
        "startups to watch",
        "wikipedia.org",
    ]
    return any(n in blob for n in needles)
