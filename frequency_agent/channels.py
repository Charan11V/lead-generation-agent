"""Public contact channels: email/phone > LinkedIn > X > other social.

Never invents addresses or profile URLs. Only keeps values found in public text
or public search-result URLs (no login scraping).
"""

from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse

from .schemas import ContactCandidate, ContactChannel, SearchHit, fresh_channels

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
JUNK_EMAIL_LOCAL = {
    "noreply",
    "no-reply",
    "donotreply",
    "privacy",
    "support",
    "hello",
    "info",
    "careers",
    "jobs",
    "hr",
    "team",
    "admin",
    "press",
    "media",
    "contact",
    "enquiries",
    "inquiry",
    "sales",
    "marketing",
}

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


def person_windows(text: str, person: str, window: int = 180) -> str:
    """Snippets around the person's full name — not the whole company page."""
    if not text or not person:
        return ""
    tokens = _person_name_tokens(person)
    if not tokens:
        return ""
    low = text.lower()
    spans: list[tuple[int, int]] = []
    full = " ".join(tokens)
    start = 0
    while True:
        i = low.find(full, start)
        if i < 0:
            break
        spans.append((max(0, i - window), min(len(text), i + len(full) + window)))
        start = i + len(full)
    if len(tokens) >= 2:
        first, last = tokens[0], tokens[-1]
        f_pat = re.compile(rf"\b{re.escape(first)}\b", re.I)
        l_pat = re.compile(rf"\b{re.escape(last)}\b", re.I)
        for fm in f_pat.finditer(text):
            for lm in l_pat.finditer(text):
                if abs(fm.start() - lm.start()) <= 48:
                    lo = min(fm.start(), lm.start())
                    hi = max(fm.end(), lm.end())
                    spans.append((max(0, lo - window), min(len(text), hi + window)))
    if not spans:
        return ""
    spans.sort()
    merged: list[list[int]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return "\n".join(text[a:b] for a, b in merged)


def email_belongs_to_person(email: str, person: str, context: str = "") -> bool:
    """Local-part matches this person. First-name-only emails need last name in the nearby snippet."""
    email = (email or "").strip().lower()
    if "@" not in email:
        return False
    local, _, _domain = email.partition("@")
    if local in JUNK_EMAIL_LOCAL:
        return False
    tokens = _person_name_tokens(person)
    if not tokens:
        return False
    compact = re.sub(r"[^a-z0-9]", "", local)
    first = tokens[0]
    last = tokens[-1]
    if len(tokens) == 1:
        return tokens[0] in local and len(tokens[0]) >= 4
    last_in = last in local or last in compact
    first_in = first in local or first in compact
    if last_in and first_in:
        return True
    if last_in and len(last) >= 4:
        return True
    if (first + last) in compact or (len(first) >= 1 and (first[0] + last) in compact):
        return True
    if first_in and context and person_near_value(context, person, email):
        return True
    return False


def handle_belongs_to_person(url: str, person: str) -> bool:
    """Profile slug/handle must include last name (and first or initial when present)."""
    tokens = _person_name_tokens(person)
    if not url or not tokens:
        return False
    path = urlparse(_clean_url(url) or url).path.strip("/").split("/")[-1].lower()
    slug = re.sub(r"[^a-z0-9]", "", path.replace("-", "").replace("_", ""))
    first, last = tokens[0], tokens[-1]
    if len(tokens) == 1:
        return tokens[0] in slug and len(tokens[0]) >= 4
    if last not in path and last not in slug:
        return False
    if first in path or first in slug:
        return True
    if (first + last) in slug or (first[0] + last) in slug:
        return True
    return False


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


def _valid_email(email: str, *, company_domain: str = "", person_hint: str = "", context: str = "") -> bool:
    email = email.strip().lower()
    if "@" not in email:
        return False
    local, _, domain = email.partition("@")
    if domain in JUNK_EMAIL_DOMAINS:
        return False
    if local in JUNK_EMAIL_LOCAL:
        return False
    if email.endswith((".png", ".jpg", ".gif", ".svg", ".webp", ".css", ".js")):
        return False
    if person_hint:
        return email_belongs_to_person(email, person_hint, context)
    if company_domain and company_domain != "unknown":
        return domain == company_domain.lower() or domain.endswith("." + company_domain.lower())
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
    scoped = person_windows(text, person_hint) if person_hint else (text or "")
    work = scoped or (text or "")

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

    for m in EMAIL_RE.finditer(work):
        email = m.group(1)
        if _valid_email(email, company_domain=company_domain, person_hint=person_hint, context=work):
            add("email", email.lower(), "HIGH" if company_domain and company_domain in email.lower() else "MEDIUM")

    for m in PHONE_RE.finditer(work):
        phone = m.group(0).strip()
        if _valid_phone(phone) and (not person_hint or person_near_value(work, person_hint, phone)):
            digits = re.sub(r"\D", "", phone)
            if digits.startswith("91") and len(digits) == 12:
                phone = f"+91 {digits[2:7]} {digits[7:]}"
            add("phone", phone, "MEDIUM")

    urls = list(URL_RE.findall(work))
    if source_url:
        urls.append(source_url)
    if person_hint and not scoped:
        urls.extend(URL_RE.findall(text or ""))
        if source_url:
            urls.append(source_url)
    for url in urls:
        url = _clean_url(url)
        kind = classify_social(url)
        if not kind:
            continue
        if person_hint and kind in {"linkedin", "twitter", "other"}:
            if not handle_belongs_to_person(url, person_hint):
                continue
        if kind == "linkedin" and person_hint and scoped:
            if not linkedin_matches_person(
                url,
                person_hint,
                company=company_domain,
                context=work,
                company_domain=company_domain,
            ) and not handle_belongs_to_person(url, person_hint):
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
    return fresh_channels(ordered)


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


def person_near_value(text: str, person: str, value: str, window: int = 180) -> bool:
    """True if the full name (first and last) sits near the value. Never first-name-only."""
    if not text or not person or not value:
        return False
    low = text.lower()
    val = value.lower()
    vi = low.find(val)
    if vi < 0:
        return False
    tokens = _person_name_tokens(person)
    if not tokens:
        return False
    lo, hi = max(0, vi - window), min(len(low), vi + len(val) + window)
    snippet = low[lo:hi]
    if " ".join(tokens) in snippet:
        return True
    if len(tokens) == 1:
        return tokens[0] in snippet
    return tokens[0] in snippet and tokens[-1] in snippet


def filter_channels_for_person(
    channels: list[ContactChannel],
    *,
    person: str,
    corpus: str,
    company_domain: str = "",
    company: str = "",
    role: str = "",
) -> list[ContactChannel]:
    """Keep channels that belong to this person. Empty is better than a mix-up."""
    scoped = person_windows(corpus, person) or corpus
    kept: list[ContactChannel] = []
    for ch in channels:
        if ch.kind == "email":
            if email_belongs_to_person(ch.value, person, scoped):
                kept.append(ch)
        elif ch.kind == "phone":
            if person_near_value(scoped, person, ch.value):
                kept.append(ch)
        elif ch.kind == "linkedin":
            if not handle_belongs_to_person(ch.value, person):
                continue
            ctx = scoped or " ".join([corpus or "", ch.value or "", ch.source_url or ""])
            if linkedin_matches_person(
                ch.value,
                person,
                company=company or company_domain,
                role=role,
                context=ctx,
                company_domain=company_domain,
            ) or (handle_belongs_to_person(ch.value, person) and person_near_value(ctx, person, ch.value, window=220)):
                kept.append(ch)
        elif ch.kind in {"twitter", "other"}:
            if handle_belongs_to_person(ch.value, person):
                kept.append(ch)
        else:
            kept.append(ch)
    return merge_channels(kept)


def channel_owner_score(person: str, ch: ContactChannel) -> int:
    tokens = _person_name_tokens(person)
    if not tokens:
        return 0
    first, last = tokens[0], tokens[-1]
    hay = (ch.value.split("@")[0] if ch.kind == "email" else ch.value).lower()
    hay = re.sub(r"[^a-z0-9]", "", hay)
    score = 0
    if last in hay:
        score += 4
    if first in hay:
        score += 2
    if (first + last) in hay:
        score += 3
    return score


def assign_exclusive_channels(candidates: list[ContactCandidate]) -> list[ContactCandidate]:
    """Each email / profile URL belongs to at most one person."""
    if len(candidates) <= 1:
        return candidates
    claims: dict[str, tuple[int, int, ContactChannel]] = {}
    for i, cand in enumerate(candidates):
        for ch in cand.channels or []:
            key = f"{ch.kind}:{(ch.value or '').lower()}"
            score = channel_owner_score(cand.name, ch)
            if score <= 0:
                continue
            prev = claims.get(key)
            if not prev or score > prev[0] or (score == prev[0] and cand.relevance_score > candidates[prev[1]].relevance_score):
                claims[key] = (score, i, ch)
    owned: dict[int, list[ContactChannel]] = {i: [] for i in range(len(candidates))}
    for _score, idx, ch in claims.values():
        owned[idx].append(ch)
    out: list[ContactCandidate] = []
    for i, cand in enumerate(candidates):
        cleared = cand.model_copy(
            update={
                "channels": [],
                "email": "",
                "phone": "",
                "linkedin_url": "",
                "twitter_url": "",
                "other_social": [],
                "best_channel": "",
            }
        )
        out.append(apply_channels_to_candidate(cleared, owned[i]))
    return out


def confirm_channels_with_llm(
    llm,
    *,
    company: str,
    candidates: list[ContactCandidate],
    corpus: str,
) -> list[ContactCandidate]:
    """One cheap pass: confirm or drop channels we already found. Never invents new ones."""
    from .schemas import ChannelConfirmBatch

    claims_in: list[dict] = []
    for cand in candidates:
        if (cand.name or "").lower() in {"", "not_found", "unknown"}:
            continue
        snippet = person_windows(corpus, cand.name)[:500]
        for ch in cand.channels or []:
            if ch.kind not in {"email", "linkedin", "twitter", "other"}:
                continue
            claims_in.append(
                {
                    "person": cand.name,
                    "role": cand.role,
                    "kind": ch.kind,
                    "value": ch.value,
                    "snippet": snippet,
                }
            )
    if not claims_in:
        return candidates
    try:
        parsed = llm.parse(
            [
                {
                    "role": "system",
                    "content": (
                        "You verify whether public contact channels belong to the named person "
                        f"at {company}. Do not invent channels. If unsure, belongs=false. "
                        "A channel belongs only if it is clearly this person (name in email/handle/slug) "
                        "and not a colleague, journalist, or company inbox."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Confirm each channel. Return belongs true/false for every item:\n"
                        + "\n".join(
                            f"- person={c['person']} role={c['role']} kind={c['kind']} value={c['value']}\n  context: {c['snippet'][:280]}"
                            for c in claims_in
                        )
                    ),
                },
            ],
            ChannelConfirmBatch,
        )
    except Exception:
        return candidates

    rejected: set[tuple[str, str]] = set()
    for claim in parsed.claims or []:
        ident = f"{claim.kind}:{(claim.value or '').lower()}"
        if not claim.belongs:
            rejected.add((claim.person.lower(), ident))

    out: list[ContactCandidate] = []
    for cand in candidates:
        keep: list[ContactChannel] = []
        for ch in cand.channels or []:
            ident = f"{ch.kind}:{(ch.value or '').lower()}"
            if (cand.name.lower(), ident) in rejected:
                continue
            keep.append(ch)
        cleared = cand.model_copy(
            update={
                "channels": [],
                "email": "",
                "phone": "",
                "linkedin_url": "",
                "twitter_url": "",
                "other_social": [],
                "best_channel": "",
            }
        )
        out.append(apply_channels_to_candidate(cleared, keep))
    return out
