"""Public contact channels: email/phone > LinkedIn > X > other social.

Never invents addresses or profile URLs. Only keeps values found in public text
or public search-result URLs (no login scraping).
"""

from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse

from .schemas import ContactCandidate, ContactChannel, SearchHit

EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})(?![A-Za-z0-9._%+-])"
)
PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?\d{1,3}[\s\-.]?)?(?:\(?\d{2,5}\)?[\s\-.]?)?\d{3,5}[\s\-.]?\d{3,5}(?!\d)"
)
URL_RE = re.compile(r"https?://[^\s<>\"'\]\[\|\{\}\\^`]+", re.I)

JUNK_EMAIL_DOMAINS = {
    "example.com",
    "email.com",
    "domain.com",
    "sentry.io",
    "wixpress.com",
    "schema.org",
    "googleapis.com",
    "github.com",
    "gravatar.com",
}
JUNK_EMAIL_LOCAL = {"noreply", "no-reply", "donotreply", "privacy", "support", "hello", "info", "careers", "jobs"}

SOCIAL_PRIORITY = {
    "email": 100,
    "phone": 95,
    "linkedin": 80,
    "twitter": 60,
    "x": 60,
    "other": 30,
}


def _clean_url(url: str) -> str:
    url = (url or "").strip().rstrip(".,);]>\"'")
    if not url:
        return ""
    # Truncate at characters that break urllib (often appear mid-scrape)
    for bad in ("[", "]", "{", "}", "<", ">", '"', "'", " ", "\n", "\t"):
        if bad in url:
            url = url.split(bad, 1)[0]
    url = url.rstrip('.,);>/]')
    if not url or "://" not in url:
        return ""
    try:
        p = urlparse(url)
        if not p.scheme or not p.netloc:
            return ""
        # Drop tracking query/fragment for profile URLs
        host = (p.netloc or "").lower().replace("www.", "")
        if any(h in host for h in ("linkedin.com", "twitter.com", "x.com", "instagram.com", "facebook.com")):
            p = p._replace(query="", fragment="")
        cleaned = urlunparse(p)
        # Re-parse to ensure urllib accepts the result
        urlparse(cleaned)
        return cleaned
    except Exception:
        return ""


def is_linkedin_profile(url: str) -> bool:
    low = (url or "").lower()
    if not low or "[" in low or "]" in low:
        return False
    if "linkedin.com/login" in low or "linkedin.com/signup" in low:
        return False
    if any(x in low for x in ("/posts/", "/pulse/", "/company/", "/jobs/", "/school/")):
        return False
    return bool(re.search(r"linkedin\.com/(in|pub)/[^/?#]+", low))


def _person_name_tokens(person: str) -> list[str]:
    skip = {"mr", "ms", "mrs", "dr", "sir", "the", "and", "of", "at"}
    tokens = [t.lower() for t in re.split(r"[\W_]+", person or "") if len(t) >= 2]
    return [t for t in tokens if t not in skip]


def linkedin_slug(url: str) -> str:
    m = re.search(r"linkedin\.com/(?:in|pub)/([^/?#]+)", (url or "").lower())
    return (m.group(1) if m else "").replace("-", " ").replace("_", " ")


def linkedin_matches_person(
    url: str,
    person: str,
    *,
    company: str = "",
    role: str = "",
    context: str = "",
    company_domain: str = "",
) -> bool:
    """Strict: slug matches name AND context shows this person in this role at this company."""
    from .contact_policy import company_name_tokens, person_at_company_in_text, is_excluded_contact

    if not is_linkedin_profile(url) or not person:
        return False
    low_url = (url or "").lower()
    if "linkedin.com/search" in low_url or "/results/" in low_url:
        return False

    slug = linkedin_slug(url)
    if not slug or len(slug) < 3:
        return False
    tokens = _person_name_tokens(person)
    if not tokens:
        return False
    first = tokens[0]
    if len(first) >= 2 and first not in slug:
        return False
    long_tokens = [t for t in tokens if len(t) >= 3]
    if len(long_tokens) >= 2:
        if not any(t in slug for t in long_tokens):
            return False
        last = long_tokens[-1]
        if last != first and last not in slug:
            return False
    elif long_tokens and long_tokens[0] not in slug:
        return False

    ctx = (context or "").strip()
    if not ctx:
        return False

    comp = company or company_domain or ""
    comp_tokens = company_name_tokens(comp, company_domain)
    if not comp_tokens:
        return False
    ctx_low = ctx.lower()
    if not any(t in ctx_low for t in comp_tokens):
        return False

    if not _name_in_text_simple(person, ctx):
        return False

    use_role = role or ""
    if use_role and use_role.lower() not in {"unknown", "not_found"}:
        excluded, _ = is_excluded_contact(person, use_role, comp, ctx)
        if excluded:
            return False
        if not person_at_company_in_text(person, use_role, comp, ctx, domain=company_domain, window=280):
            return False
    else:
        if not person_at_company_in_text(person, "", comp, ctx, domain=company_domain, window=280):
            return False

    return True


def _name_in_text_simple(name: str, text: str) -> bool:
    if not name or not text:
        return False
    low = text.lower()
    if name.lower() in low:
        return True
    parts = [p for p in name.lower().split() if len(p) >= 2]
    return bool(parts and parts[0] in low and (len(parts) == 1 or parts[-1] in low))


def is_twitter_profile(url: str) -> bool:
    low = (url or "").lower()
    if not low or "[" in low or "]" in low:
        return False
    if any(x in low for x in ("/status/", "/i/", "/search", "/intent/", "/share")):
        return False
    return bool(re.search(r"(?:twitter\.com|x\.com)/[A-Za-z0-9_]{1,50}/?$", low.rstrip("/")))


def classify_social(url: str) -> str | None:
    try:
        url = _clean_url(url)
        if not url:
            return None
        low = url.lower()
        if is_linkedin_profile(url):
            return "linkedin"
        if is_twitter_profile(url):
            return "twitter"
        host = (urlparse(low).netloc or "").replace("www.", "")
        if not host:
            return None
        if host.endswith("instagram.com") and "/p/" not in low and "/reel/" not in low:
            return "other"
        if host.endswith("facebook.com") and "/posts/" not in low and "/photo" not in low:
            return "other"
        if host.endswith("crunchbase.com") and "/person/" in low:
            return "other"
        return None
    except Exception:
        return None


def _valid_email(email: str, *, company_domain: str = "", person_hint: str = "") -> bool:
    email = email.strip().lower()
    if "@" not in email:
        return False
    local, _, domain = email.partition("@")
    if domain in JUNK_EMAIL_DOMAINS:
        return False
    if local in JUNK_EMAIL_LOCAL and not company_domain:
        return False
    if email.endswith((".png", ".jpg", ".gif", ".svg", ".webp", ".css", ".js")):
        return False
    # Prefer company-domain emails when we know the domain
    if company_domain and company_domain != "unknown":
        if domain == company_domain.lower() or domain.endswith("." + company_domain.lower()):
            return True
        # Still allow personal emails if name tokens appear in local part
        tokens = [t for t in re.split(r"\W+", person_hint.lower()) if len(t) >= 3]
        if tokens and any(t in local for t in tokens[:2]):
            return True
        # Generic info@ without name match is weak — keep only if on company domain (already handled)
        if local in JUNK_EMAIL_LOCAL:
            return False
    return True


def _valid_phone(phone: str) -> bool:
    digits = re.sub(r"\D", "", phone)
    return 10 <= len(digits) <= 15


def extract_channels_from_text(
    text: str,
    *,
    company_domain: str = "",
    person_hint: str = "",
    source_url: str = "",
) -> list[ContactChannel]:
    """Regex-extract emails, phones, and social profile URLs from public text."""
    found: list[ContactChannel] = []
    seen: set[str] = set()

    def add(kind: str, value: str, conf: str = "MEDIUM") -> None:
        value = value.strip()
        key = f"{kind}:{value.lower()}"
        if not value or key in seen:
            return
        seen.add(key)
        found.append(
            ContactChannel(
                kind=kind,  # type: ignore[arg-type]
                value=value,
                source_url=source_url or "",
                confidence=conf,  # type: ignore[arg-type]
                priority=SOCIAL_PRIORITY.get(kind, 30),
            )
        )

    for m in EMAIL_RE.finditer(text or ""):
        email = m.group(1)
        if _valid_email(email, company_domain=company_domain, person_hint=person_hint):
            add("email", email.lower(), "HIGH" if company_domain and company_domain in email.lower() else "MEDIUM")

    for m in PHONE_RE.finditer(text or ""):
        phone = m.group(0).strip()
        if _valid_phone(phone):
            # Normalize lightly
            digits = re.sub(r"\D", "", phone)
            if digits.startswith("91") and len(digits) == 12:
                phone = f"+91 {digits[2:7]} {digits[7:]}"
            add("phone", phone, "MEDIUM")

    # URLs in text + the page URL itself
    urls = list(URL_RE.findall(text or ""))
    if source_url:
        urls.append(source_url)
    for url in urls:
        url = _clean_url(url)
        kind = classify_social(url)
        if not kind:
            continue
        if kind == "linkedin" and person_hint:
            blob = " ".join([text or "", source_url or ""])
            if not linkedin_matches_person(
                url,
                person_hint,
                company=company_domain,
                context=blob,
                company_domain=company_domain,
            ):
                continue
        if kind == "twitter":
            add("twitter", url, "HIGH")
        else:
            add(kind, url, "HIGH")

    return found


def extract_channels_from_hits(
    hits: list[SearchHit],
    *,
    company_domain: str = "",
    person_hint: str = "",
) -> list[ContactChannel]:
    channels: list[ContactChannel] = []
    for h in hits:
        blob = " ".join([h.url, h.title or "", h.snippet or "", h.raw_content or ""])
        channels.extend(
            extract_channels_from_text(
                blob,
                company_domain=company_domain,
                person_hint=person_hint,
                source_url=h.url,
            )
        )
    return merge_channels(channels)


def merge_channels(channels: list[ContactChannel]) -> list[ContactChannel]:
    """Dedupe by kind+value; keep highest confidence; sort by priority."""
    best: dict[str, ContactChannel] = {}
    for ch in channels:
        key = f"{ch.kind}:{ch.value.lower()}"
        prev = best.get(key)
        if not prev or SOCIAL_PRIORITY.get(ch.kind, 0) > SOCIAL_PRIORITY.get(prev.kind, 0):
            best[key] = ch
        elif prev and ch.confidence == "HIGH" and prev.confidence != "HIGH":
            best[key] = ch
    ordered = sorted(best.values(), key=lambda c: (-c.priority, c.kind, c.value))
    return ordered


def best_channel(channels: list[ContactChannel]) -> ContactChannel | None:
    if not channels:
        return None
    return merge_channels(channels)[0]


def channel_search_queries(person: str, company: str, domain: str = "unknown") -> list[str]:
    """Public-web queries to surface email/social profiles (URLs only — no login scrape)."""
    person = (person or "").strip()
    company = (company or "").strip()
    if len(person) < 2 or person.lower() in {"not_found", "unknown"}:
        return []
    qs = [
        f'"{person}" "{company}" email OR contact OR "@"',
        f'"{person}" "{company}" site:linkedin.com/in',
        f'"{person}" "{company}" (site:x.com OR site:twitter.com)',
        f'"{person}" "{company}" LinkedIn OR Twitter OR "follow"',
    ]
    if domain and domain != "unknown":
        qs.insert(1, f'"{person}" "@{domain}" OR site:{domain}')
    return qs[:5]


def apply_channels_to_candidate(
    cand: ContactCandidate,
    channels: list[ContactChannel],
) -> ContactCandidate:
    """Attach merged channels and bump relevance when email/phone/LinkedIn exist."""
    merged = merge_channels(list(cand.channels or []) + list(channels or []))
    email = next((c.value for c in merged if c.kind == "email"), "") or cand.email
    phone = next((c.value for c in merged if c.kind == "phone"), "") or cand.phone
    linkedin = next((c.value for c in merged if c.kind == "linkedin"), "") or cand.linkedin_url
    twitter = next((c.value for c in merged if c.kind == "twitter"), "") or cand.twitter_url
    other = [c.value for c in merged if c.kind == "other"]
    if cand.other_social:
        for o in cand.other_social:
            if o not in other:
                other.append(o)

    bonus = 0
    reasons = []
    if email:
        bonus += 18
        reasons.append("Public email found (+18).")
    if phone:
        bonus += 14
        reasons.append("Public phone found (+14).")
    if linkedin:
        bonus += 12
        reasons.append("LinkedIn profile URL found (+12).")
    elif twitter:
        bonus += 6
        reasons.append("X/Twitter profile URL found (+6).")
    elif other:
        bonus += 3
        reasons.append("Other social profile found (+3).")

    best = best_channel(merged)
    return cand.model_copy(
        update={
            "channels": merged,
            "email": email or "",
            "phone": phone or "",
            "linkedin_url": linkedin or "",
            "twitter_url": twitter or "",
            "other_social": other,
            "best_channel": f"{best.kind}:{best.value}" if best else "",
            "relevance_score": cand.relevance_score + bonus,
            "likelihood_reason": (cand.likelihood_reason + " " + " ".join(reasons)).strip(),
        }
    )


def person_near_value(text: str, person: str, value: str, window: int = 280) -> bool:
    """True if person name and value appear near each other in text."""
    if not text or not person or not value:
        return False
    low = text.lower()
    name = person.lower()
    val = value.lower()
    ni = low.find(name)
    vi = low.find(val)
    if ni < 0 or vi < 0:
        # Try first token of name
        first = name.split()[0] if name.split() else name
        ni = low.find(first)
        if ni < 0 or vi < 0:
            return False
    return abs(ni - vi) <= window


def filter_channels_for_person(
    channels: list[ContactChannel],
    *,
    person: str,
    corpus: str,
    company_domain: str = "",
    company: str = "",
    role: str = "",
) -> list[ContactChannel]:
    """Keep channels that look tied to this person (or company email domain)."""
    kept: list[ContactChannel] = []
    for ch in channels:
        if ch.kind == "email":
            if company_domain and company_domain != "unknown" and company_domain.lower() in ch.value.lower():
                tokens = [t for t in re.split(r"\W+", person.lower()) if len(t) >= 3]
                local = ch.value.split("@")[0]
                if tokens and any(t in local for t in tokens[:2]):
                    kept.append(ch)
                elif person_near_value(corpus, person, ch.value):
                    kept.append(ch)
            elif person_near_value(corpus, person, ch.value):
                kept.append(ch)
        elif ch.kind == "phone":
            if person_near_value(corpus, person, ch.value):
                kept.append(ch)
        elif ch.kind in {"linkedin", "twitter", "other"}:
            if ch.kind == "linkedin":
                ctx = " ".join([corpus or "", ch.value or "", ch.source_url or ""])
                if not linkedin_matches_person(
                    ch.value,
                    person,
                    company=company or company_domain,
                    role=role,
                    context=ctx,
                    company_domain=company_domain,
                ):
                    continue
                kept.append(ch)
                continue
            path = ch.value.lower()
            tokens = [t for t in re.split(r"\W+", person.lower()) if len(t) >= 3]
            if tokens and any(t in path for t in tokens[:2]):
                kept.append(ch)
            elif person_near_value(corpus, person, ch.value, window=400):
                kept.append(ch)
        else:
            kept.append(ch)
    return merge_channels(kept)
