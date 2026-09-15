"""Canonical entity IDs and similarity matching across queued pipeline results.

Company and person IDs are global (not owner-scoped) so two users — or two ICP
searches — that land on the same firm or decision-maker share an identity.
Matching is exact-ID first, then fuzzy name/domain/email/LinkedIn.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlparse

from .util import normalize_name, slug_id

PIPELINE_STATUSES = (
    "queued",
    "outreach_sent",
    "ongoing",
    "success",
    "failure",
)

PIPELINE_STATUS_LABELS = {
    "queued": "Queued",
    "outreach_sent": "Outreach sent",
    "ongoing": "Ongoing",
    "success": "Success",
    "failure": "Failure",
}

# Legacy value from the first pipeline build — treat as ongoing.
_STATUS_ALIASES = {"response_received": "ongoing"}

# Linear flow, then a close branch. Users cannot skip.
_NEXT_ACTIONS: dict[str, list[tuple[str, str]]] = {
    "queued": [("outreach_sent", "Outreach sent")],
    "outreach_sent": [("ongoing", "Response received")],
    "ongoing": [("success", "Success"), ("failure", "Failure")],
    "success": [],
    "failure": [],
}

_PLACEHOLDER_NAMES = frozenset(
    {"", "not_found", "unknown", "n/a", "none", "null", "unnamed"}
)
_PLACEHOLDER_DOMAINS = frozenset({"", "unknown", "not_found", "none", "null"})


def clean_domain(domain: str | None) -> str:
    raw = (domain or "").strip().lower()
    if not raw or raw in _PLACEHOLDER_DOMAINS:
        return ""
    raw = raw.replace("https://", "").replace("http://", "")
    raw = raw.split("/")[0].split("?")[0]
    if raw.startswith("www."):
        raw = raw[4:]
    return raw.strip(".")


def normalize_linkedin(url: str | None) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parsed = urlparse(raw)
        host = (parsed.netloc or "").lower().replace("www.", "")
        path = (parsed.path or "").rstrip("/").lower()
    except Exception:
        return (url or "").strip().lower().split("?")[0].rstrip("/")
    if not host:
        return ""
    return f"{host}{path}"


def normalize_person_name(name: str | None) -> str:
    n = re.sub(r"[^a-z0-9]+", " ", (name or "").strip().lower())
    n = re.sub(r"\s+", " ", n).strip()
    if n in _PLACEHOLDER_NAMES:
        return ""
    return n


def normalize_email(email: str | None) -> str:
    e = (email or "").strip().lower()
    if "@" not in e or e.startswith("not_found"):
        return ""
    return e


def company_entity_id(domain: str | None, name: str | None) -> str:
    """Stable global company ID. Prefer domain; fall back to normalized name."""
    d = clean_domain(domain)
    if d:
        return "c_" + slug_id("company", d)
    n = normalize_name(name or "")
    if n:
        return "c_" + slug_id("company", n)
    return "c_" + slug_id("company", "unknown")


def person_entity_id(
    *,
    email: str | None = "",
    linkedin: str | None = "",
    name: str | None = "",
    company_id: str = "",
) -> str:
    """Stable global person ID. Prefer email, then LinkedIn, then company+name."""
    e = normalize_email(email)
    if e:
        return "p_" + slug_id("person", e)
    li = normalize_linkedin(linkedin)
    if li:
        return "p_" + slug_id("person", li)
    n = normalize_person_name(name)
    if n and company_id:
        return "p_" + slug_id("person", company_id, n)
    if n:
        return "p_" + slug_id("person", n)
    return ""


def _primary_person(lead: dict) -> dict:
    contact = lead.get("contact") if isinstance(lead.get("contact"), dict) else {}
    people = [
        p
        for p in (lead.get("contacts") or [])
        if isinstance(p, dict) and normalize_person_name(p.get("name") or "")
    ]
    primary = next((p for p in people if p.get("is_primary")), None)
    if primary:
        return primary
    if people:
        return people[0]
    return contact or {}


def identity_from_lead(lead: dict) -> dict[str, str]:
    """Canonical identity fields extracted from a CompanyLead payload."""
    company = (lead.get("name") or lead.get("company") or "").strip()
    domain = clean_domain(lead.get("domain") or "")
    person = _primary_person(lead)
    person_name = (person.get("name") or "").strip()
    person_role = (person.get("role") or "").strip()
    person_email = normalize_email(person.get("email") or "")
    person_linkedin = person.get("linkedin_url") or ""
    cid = company_entity_id(domain, company)
    pid = person_entity_id(
        email=person_email,
        linkedin=person_linkedin,
        name=person_name,
        company_id=cid,
    )
    return {
        "company": company,
        "domain": domain,
        "person_name": person_name if normalize_person_name(person_name) else "",
        "person_role": person_role if person_role.lower() not in _PLACEHOLDER_NAMES else "",
        "person_email": person_email,
        "person_linkedin": normalize_linkedin(person_linkedin),
        "company_entity_id": cid,
        "person_entity_id": pid,
    }


def identity_from_pipeline(row: dict) -> dict[str, str]:
    return {
        "company": (row.get("company") or "").strip(),
        "domain": clean_domain(row.get("domain") or ""),
        "person_name": (row.get("person_name") or "").strip(),
        "person_role": (row.get("person_role") or "").strip(),
        "person_email": normalize_email(row.get("person_email") or ""),
        "person_linkedin": normalize_linkedin(row.get("person_linkedin") or ""),
        "company_entity_id": row.get("company_entity_id") or company_entity_id(
            row.get("domain"), row.get("company")
        ),
        "person_entity_id": row.get("person_entity_id") or "",
    }


def company_name_score(a: str, b: str) -> float:
    na, nb = normalize_name(a or ""), normalize_name(b or "")
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    ca, cb = na.replace(" ", ""), nb.replace(" ", "")
    compact = SequenceMatcher(None, ca, cb).ratio() if ca and cb else 0.0
    ta, tb = set(na.split()), set(nb.split())
    jaccard = (len(ta & tb) / len(ta | tb)) if ta and tb else 0.0
    contain = 0.0
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(shorter) >= 4 and shorter in longer:
        contain = 0.9
    c_short, c_long = (ca, cb) if len(ca) <= len(cb) else (cb, ca)
    if len(c_short) >= 4 and c_short in c_long:
        contain = max(contain, 0.88)
    return max(ratio, compact, jaccard * 0.95, contain)


def person_name_score(a: str, b: str) -> float:
    na, nb = normalize_person_name(a), normalize_person_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    pa, pb = na.split(), nb.split()
    if pa and pb and pa[-1] == pb[-1] and len(pa[-1]) >= 4:
        if pa[0][:1] == pb[0][:1]:
            return max(ratio, 0.86)
        return max(ratio, 0.7)
    return ratio


def _company_score(left: dict, right: dict) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    lid = left.get("company_entity_id") or ""
    rid = right.get("company_entity_id") or ""
    if lid and rid and lid == rid:
        reasons.append("same company id")
        score = 1.0
    ld, rd = clean_domain(left.get("domain")), clean_domain(right.get("domain"))
    if ld and rd and ld == rd:
        reasons.append(f"same domain ({ld})")
        score = max(score, 1.0)
    name_s = company_name_score(left.get("company") or "", right.get("company") or "")
    if name_s >= 0.86:
        reasons.append("similar company name")
        score = max(score, name_s)
    elif name_s >= 0.72:
        score = max(score, name_s)
    return score, reasons


def _person_score(left: dict, right: dict) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    le, re_ = normalize_email(left.get("person_email")), normalize_email(right.get("person_email"))
    if le and re_ and le == re_:
        reasons.append("same email")
        score = 1.0
    ll, rl = normalize_linkedin(left.get("person_linkedin")), normalize_linkedin(
        right.get("person_linkedin")
    )
    if ll and rl and ll == rl:
        reasons.append("same LinkedIn")
        score = max(score, 1.0)
    lid, rid = left.get("person_entity_id") or "", right.get("person_entity_id") or ""
    if lid and rid and lid == rid:
        reasons.append("same person id")
        score = max(score, 1.0)
    name_s = person_name_score(left.get("person_name") or "", right.get("person_name") or "")
    if name_s >= 0.86:
        reasons.append("similar person name")
        score = max(score, name_s)
    elif name_s >= 0.7:
        score = max(score, name_s)
    return score, reasons


def similarity_verdict(left: dict, right: dict) -> dict[str, Any] | None:
    """Return a match payload if left/right refer to the same company and/or person."""
    c_score, c_reasons = _company_score(left, right)
    p_score, p_reasons = _person_score(left, right)

    kind = ""
    if p_score >= 0.99 and p_reasons:
        kind = "person"
    if c_score >= 0.86:
        kind = "company_and_person" if p_score >= 0.8 else "company"
    elif c_score >= 0.72 and p_score >= 0.85:
        kind = "company_and_person"

    if not kind:
        return None

    reasons = c_reasons + p_reasons
    if not reasons:
        reasons = ["similar company"]
    return {
        "kind": kind,
        "score": round(max(c_score, p_score), 3),
        "company_score": round(c_score, 3),
        "person_score": round(p_score, 3),
        "reasons": reasons,
        "company_entity_id": left.get("company_entity_id") or right.get("company_entity_id") or "",
        "person_entity_id": left.get("person_entity_id") or right.get("person_entity_id") or "",
    }


def find_similar(
    identity: dict,
    candidates: list[dict],
    *,
    exclude_pipeline_id: int | None = None,
    exclude_owner_lead: tuple[str, str] | None = None,
) -> list[dict]:
    """Score candidates against identity. Each hit includes the original row plus match meta."""
    hits: list[dict] = []
    for row in candidates:
        pid = row.get("id")
        if exclude_pipeline_id is not None and pid is not None and int(pid) == int(exclude_pipeline_id):
            continue
        if exclude_owner_lead:
            owner = (row.get("owner_email") or "").strip().lower()
            lead_id = row.get("lead_id") or ""
            if owner == exclude_owner_lead[0] and lead_id == exclude_owner_lead[1]:
                continue
        other = identity_from_pipeline(row)
        verdict = similarity_verdict(identity, other)
        if not verdict:
            continue
        hit = dict(row)
        hit["match_kind"] = verdict["kind"]
        hit["match_score"] = verdict["score"]
        hit["match_reasons"] = verdict["reasons"]
        hits.append(hit)
    hits.sort(key=lambda h: (-float(h.get("match_score") or 0), str(h.get("updated_at") or "")))
    return hits


def status_label(status: str) -> str:
    return PIPELINE_STATUS_LABELS.get(normalize_pipeline_status(status), status or "Queued")


def normalize_pipeline_status(status: str) -> str:
    s = (status or "queued").strip().lower()
    s = _STATUS_ALIASES.get(s, s)
    if s not in PIPELINE_STATUSES:
        return "queued"
    return s


def next_pipeline_actions(status: str) -> list[tuple[str, str]]:
    """Allowed (status, button label) pairs from the current step."""
    return list(_NEXT_ACTIONS.get(normalize_pipeline_status(status), []))


def can_transition(from_status: str, to_status: str) -> bool:
    allowed = {code for code, _label in next_pipeline_actions(from_status)}
    return normalize_pipeline_status(to_status) in allowed


def require_comment(status: str) -> bool:
    return normalize_pipeline_status(status) in {"success", "failure"}


def is_closed_status(status: str) -> bool:
    return normalize_pipeline_status(status) in {"success", "failure"}
