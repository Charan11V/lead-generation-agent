"""Who is an outreach target vs press/noise — and LinkedIn/employer verification."""

from __future__ import annotations

import re

# Roles we should not pitch (informational / third-party sources)
EXCLUDED_ROLE_RE = re.compile(
    r"|".join(
        [
            r"\bjournalist\b",
            r"\breporter\b",
            r"\bcorrespondent\b",
            r"\beditor\b",
            r"\bauthor\b",
            r"\bwriter\b",
            r"\bspokesperson\b",
            r"\bpublic relations\b",
            r"\bmedia relations\b",
            r"\bcommunications?\s+(?:manager|lead|director|head)\b",
            r"\bpr\s+(?:manager|lead|director|head)\b",
            r"\binvestor\b",
            r"\bventure partner\b",
            r"\bgeneral partner\b",
            r"\bpartner at\b",
            r"\bboard member\b",
            r"\bboard director\b",
            r"\banalyst at\b",
            r"\bassociate at\b",
            r"\bprincipal at\b",
            r"\bvc\b",
            r"\bventure capital\b",
            r"\bangel investor\b",
            r"\blinkedin post author\b",
            r"\bpost author\b",
            r"\bpublished by\b",
            r"\bcontributor\b",
            r"\bcolumnist\b",
            r"\bnews desk\b",
        ]
    ),
    re.I,
)

# Company-name-as-person (bad extractions)
GENERIC_NAMES = {
    "company",
    "firm",
    "startup",
    "brand",
    "team",
    "linkedin",
    "razorpay",
    "finnable",
}

DECISION_MAKER_RE = re.compile(
    r"|".join(
        [
            r"\bfounder\b",
            r"\bco-?founder\b",
            r"\bceo\b",
            r"\bcfo\b",
            r"\bcto\b",
            r"\bcoo\b",
            r"\bcro\b",
            r"\bchro\b",
            r"\bcxo\b",
            r"\bchief\b",
            r"\bpresident\b",
            r"\bmanaging director\b",
            r"\bmd\b",
            r"\bhead of\b",
            r"\bvp\b",
            r"\bsvp\b",
            r"\bevp\b",
            r"\bdirector\b",
            r"\bowner\b",
            r"\bpartner\b",  # operating partner at target co only — filtered by employer check
            r"\btalent acquisition\b",
            r"\bpeople ops\b",
            r"\bhuman resources\b",
            r"\bhr\b",
        ]
    ),
    re.I,
)

ROLE_ALIASES: dict[str, list[str]] = {
    "founder": ["founder", "co-founder", "cofounder"],
    "ceo": ["ceo", "chief executive", "managing director"],
    "chro": ["chro", "chief human resources", "chief people", "vp people", "head of people", "head of hr"],
    "head of talent": ["head of talent", "talent acquisition", "vp talent", "director talent", "recruiting"],
    "cfo": ["cfo", "chief financial"],
    "cto": ["cto", "chief technology", "chief product"],
    "vp": ["vp", "vice president", "svp", "evp"],
}


def company_name_tokens(company: str, domain: str = "") -> list[str]:
    tokens: list[str] = []
    for part in re.split(r"\W+", (company or "")):
        p = part.strip().lower()
        if len(p) >= 3:
            tokens.append(p)
    if domain and domain not in {"unknown", "not_found", "null"}:
        base = domain.lower().split(".")[0]
        if len(base) >= 3:
            tokens.append(base)
    # dedupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _name_in_text(name: str, text: str) -> bool:
    if not name or not text:
        return False
    low = text.lower()
    parts = [p for p in name.lower().split() if len(p) >= 2]
    if not parts:
        return False
    if name.lower() in low:
        return True
    if parts[0] in low and (len(parts) == 1 or parts[-1] in low):
        return True
    return False


def _role_in_text(role: str, text: str) -> bool:
    if not role or not text:
        return False
    r = role.lower()
    low = text.lower()
    if r in low:
        return True
    words = [w for w in re.split(r"\W+", r) if len(w) >= 3]
    if words and any(w in low for w in words[:4]):
        return True
    if any(k in r for k in ("founder", "ceo", "chief executive")) and any(
        k in low for k in ("founder", "founded", "co-founder", "ceo", "chief executive")
    ):
        return True
    for aliases in ROLE_ALIASES.values():
        if any(a in r for a in aliases):
            if any(a in low for a in aliases):
                return True
    return bool(DECISION_MAKER_RE.search(r) and DECISION_MAKER_RE.search(low))


def person_at_company_in_text(
    name: str,
    role: str,
    company: str,
    text: str,
    *,
    domain: str = "",
    window: int = 220,
) -> bool:
    """Name + company (+ ideally role) co-occur in source text."""
    if not text or not name or not company:
        return False
    low = text.lower()
    comp_tokens = company_name_tokens(company, domain)
    if not comp_tokens:
        return False
    if not _name_in_text(name, text):
        return False
    # Find best name anchor
    parts = [p for p in name.lower().split() if len(p) >= 2]
    anchor = low.find(name.lower())
    if anchor < 0 and parts:
        anchor = low.find(parts[0])
    if anchor < 0:
        return False
    snippet = low[max(0, anchor - window) : anchor + window]
    if not any(t in snippet for t in comp_tokens):
        return False
    # Role should appear near name when we know it
    if role and role.lower() not in {"unknown", "not_found", ""}:
        role_snippet = low[max(0, anchor - 160) : anchor + 160]
        if not _role_in_text(role, role_snippet):
            return False
    return True


def is_excluded_contact(name: str, role: str, company: str, text: str = "") -> tuple[bool, str]:
    """True if this person is press, investor, author, etc. — not an outreach target."""
    n = (name or "").strip().lower()
    r = (role or "").strip().lower()
    blob = f"{name} {role} {text}".lower()

    if not n or n in {"not_found", "unknown", "n/a"}:
        return True, "missing name"
    if n in GENERIC_NAMES or company.lower() == n:
        return True, "generic or company-as-name"
    if len(n.split()) == 1 and n == company.lower():
        return True, "company name used as person"

    if EXCLUDED_ROLE_RE.search(r) or EXCLUDED_ROLE_RE.search(blob[:500]):
        return True, "press/investor/media role"

    # Investor/partner at another firm quoted in article
    if re.search(r"\b(partner|investor|board member|general partner)\s+at\b", r):
        comp_tokens = company_name_tokens(company, "")
        if comp_tokens and not any(t in r for t in comp_tokens):
            return True, "third-party investor/partner"

    if re.search(r"\b(author|writer|journalist|reporter)\b", blob[:400]):
        if not DECISION_MAKER_RE.search(r):
            return True, "article author/journalist"

    return False, ""


def is_decision_maker_role(role: str) -> bool:
    if not role or role.lower() in {"unknown", "not_found", ""}:
        return False
    if EXCLUDED_ROLE_RE.search(role):
        return False
    return bool(DECISION_MAKER_RE.search(role))


def validate_outreach_contact(
    name: str,
    role: str,
    company: str,
    corpus: str,
    *,
    domain: str = "",
    quote: str = "",
) -> tuple[bool, str]:
    """Full gate: decision-maker at target company, not press/noise."""
    excluded, reason = is_excluded_contact(name, role, company, f"{corpus} {quote}")
    if excluded:
        return False, reason
    if not is_decision_maker_role(role):
        return False, "not a decision-maker title"
    check_text = f"{corpus}\n{quote}"
    if not person_at_company_in_text(name, role, company, check_text, domain=domain):
        return False, "name/role not tied to company in sources"
    return True, "ok"
