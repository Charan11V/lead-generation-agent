"""Company-level approach channels when a verified decision-maker was not found.

Only keeps company-domain emails and public contact/careers/press URLs.
Never attaches personal emails or someone else's profile to the company bucket.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from .channels import EMAIL_RE, URL_RE, _clean_url, _valid_phone, PHONE_RE
from .schemas import ApproachChannel, ContactChannel, fresh_approach_channels

# Locals that are company inboxes (not person-tied) — useful for approach_channels
COMPANY_INBOX_LOCALS = {
    "contact",
    "hello",
    "info",
    "careers",
    "jobs",
    "hr",
    "talent",
    "recruiting",
    "press",
    "media",
    "pr",
    "enquiries",
    "inquiry",
    "sales",
    "partnerships",
    "partners",
    "bd",
    "business",
    "team",
    "office",
    "admin",
}

URL_PATH_HINTS = (
    "/contact",
    "/contact-us",
    "/contacts",
    "/get-in-touch",
    "/reach-us",
    "/careers",
    "/jobs",
    "/join",
    "/about/contact",
    "/press",
    "/media",
    "/newsroom",
)

APPROACH_PRIORITY = {
    "email": 100,
    "phone": 70,
    "url": 60,
    "other": 20,
}


def _company_domain_match(email_domain: str, company_domain: str) -> bool:
    cd = (company_domain or "").lower().strip()
    ed = (email_domain or "").lower().strip()
    if not cd or cd in {"unknown", "not_found"} or not ed:
        return False
    return ed == cd or ed.endswith("." + cd)


def _label_for_email(local: str) -> str:
    mapping = {
        "careers": "Careers inbox",
        "jobs": "Jobs inbox",
        "hr": "HR inbox",
        "talent": "Talent inbox",
        "recruiting": "Recruiting inbox",
        "press": "Press inbox",
        "media": "Media inbox",
        "pr": "PR inbox",
        "contact": "Contact inbox",
        "hello": "Hello inbox",
        "info": "Info inbox",
        "sales": "Sales inbox",
        "partnerships": "Partnerships inbox",
    }
    return mapping.get(local, f"{local.title()} inbox")


def _label_for_url(url: str) -> str:
    low = (url or "").lower()
    if any(x in low for x in ("/career", "/job", "/join")):
        return "Careers page"
    if any(x in low for x in ("/press", "/media", "/newsroom")):
        return "Press / media page"
    if any(x in low for x in ("/contact", "get-in-touch", "reach-us")):
        return "Contact page"
    return "Company page"


def discover_company_approach_channels(
    corpus: str,
    *,
    company: str = "",
    domain: str = "unknown",
    website: str = "",
    hits: list | None = None,
    person_emails: set[str] | None = None,
) -> list[ApproachChannel]:
    """Extract company-level approach channels from public text and hit URLs."""
    person_emails = {e.lower() for e in (person_emails or set()) if e}
    blobs: list[tuple[str, str]] = [(corpus or "", "")]
    for h in hits or []:
        if hasattr(h, "url"):
            url = h.url or ""
            text = " ".join([h.title or "", h.snippet or "", h.raw_content or "", url])
            blobs.append((text, url))
        elif isinstance(h, dict):
            url = h.get("url") or ""
            text = " ".join(
                [
                    h.get("title") or "",
                    h.get("snippet") or "",
                    h.get("raw_content") or "",
                    url,
                ]
            )
            blobs.append((text, url))

    if website and website not in {"unknown", "not_found", ""}:
        blobs.append((website, website))

    found: dict[str, ApproachChannel] = {}

    def add(ch: ApproachChannel) -> None:
        key = f"{ch.kind}:{ch.value.lower()}"
        prev = found.get(key)
        if not prev or ch.priority > prev.priority or (
            ch.confidence == "HIGH" and prev.confidence != "HIGH"
        ):
            found[key] = ch

    for text, source_url in blobs:
        for m in EMAIL_RE.finditer(text or ""):
            email = m.group(1).strip().lower()
            if email in person_emails:
                continue
            local, _, edomain = email.partition("@")
            if local not in COMPANY_INBOX_LOCALS:
                continue
            if domain and domain not in {"unknown", "not_found"}:
                if not _company_domain_match(edomain, domain):
                    continue
            else:
                # Without a company domain, only keep obvious corporate inboxes
                if edomain.endswith(("gmail.com", "yahoo.com", "outlook.com", "hotmail.com")):
                    continue
            add(
                ApproachChannel(
                    kind="email",
                    value=email,
                    source_url=source_url or "",
                    confidence="HIGH" if domain and domain in edomain else "MEDIUM",
                    label=_label_for_email(local),
                    priority=APPROACH_PRIORITY["email"] + (10 if local in {"contact", "hello"} else 0),
                )
            )

        for m in PHONE_RE.finditer(text or ""):
            phone = m.group(0).strip()
            if not _valid_phone(phone):
                continue
            # Only keep phones near company-contact language to avoid random numbers
            lo = max(0, m.start() - 80)
            hi = min(len(text), m.end() + 80)
            window = (text[lo:hi] or "").lower()
            if not any(
                k in window
                for k in ("contact", "call", "phone", "tel", "reach", company.lower()[:8] if company else "___")
            ):
                continue
            digits = re.sub(r"\D", "", phone)
            if digits.startswith("91") and len(digits) == 12:
                phone = f"+91 {digits[2:7]} {digits[7:]}"
            add(
                ApproachChannel(
                    kind="phone",
                    value=phone,
                    source_url=source_url or "",
                    confidence="MEDIUM",
                    label="Company phone",
                    priority=APPROACH_PRIORITY["phone"],
                )
            )

        urls = list(URL_RE.findall(text or ""))
        if source_url:
            urls.append(source_url)
        for raw in urls:
            url = _clean_url(raw)
            if not url:
                continue
            low = url.lower()
            try:
                host = (urlparse(low).netloc or "").replace("www.", "")
                path = urlparse(low).path or ""
            except Exception:
                continue
            if domain and domain not in {"unknown", "not_found"}:
                if domain.lower() not in host and not host.endswith(domain.lower()):
                    # Allow well-known career hosts only when path hints contact
                    if not any(h in host for h in ("lever.co", "greenhouse.io", "boards.greenhouse", "workable.com")):
                        continue
            path_l = path.lower()
            if not any(hint in path_l or hint in low for hint in URL_PATH_HINTS):
                if website and _clean_url(website) == url:
                    add(
                        ApproachChannel(
                            kind="url",
                            value=url,
                            source_url=source_url or url,
                            confidence="LOW",
                            label="Company website",
                            priority=APPROACH_PRIORITY["other"],
                        )
                    )
                continue
            add(
                ApproachChannel(
                    kind="url",
                    value=url,
                    source_url=source_url or url,
                    confidence="HIGH",
                    label=_label_for_url(url),
                    priority=APPROACH_PRIORITY["url"]
                    + (15 if "/contact" in path_l else 10 if "/career" in path_l else 0),
                )
            )

    ordered = sorted(found.values(), key=lambda c: (-c.priority, c.kind, c.value))
    return fresh_approach_channels(ordered[:8])


def best_approach_channel_str(channels: list[ApproachChannel]) -> str:
    if not channels:
        return ""
    top = channels[0]
    return f"{top.kind}:{top.value}"


def company_channels_as_contact_channels(channels: list[ApproachChannel]) -> list[ContactChannel]:
    """Adapter for callers that still expect ContactChannel."""
    out: list[ContactChannel] = []
    for ch in channels:
        kind = ch.kind if ch.kind in {"email", "phone"} else "other"
        out.append(
            ContactChannel(
                kind=kind,  # type: ignore[arg-type]
                value=ch.value,
                source_url=ch.source_url,
                confidence=ch.confidence,
                priority=ch.priority,
            )
        )
    return out
