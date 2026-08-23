"""Deterministic, explainable scoring. LLM never picks the number."""

from __future__ import annotations

from datetime import datetime, timezone

from .schemas import CompanyLead, ScoreBreakdown

STRONG_SIGNALS = {
    "funding",
    "leadership_departure",
    "new_executive",
    "expansion",
    "hiring_surge",
    "new_business_line",
    "acquisition",
    "product_launch",
}


def _norm(value: str) -> str:
    return (value or "").strip().lower()


def parse_date(value: str | None) -> datetime | None:
    if not value or value in {"unknown", "not_found"}:
        return None
    value = value.strip()[:10]
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    if len(value) == 7 and value[4] == "-":
        try:
            return datetime.strptime(value + "-01", "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def recency_days(date_str: str | None, now: datetime | None = None) -> int | None:
    parsed = parse_date(date_str)
    if not parsed:
        return None
    now = now or datetime.now(timezone.utc)
    return max(0, (now - parsed).days)


def _contains_any(haystack: str, needles: list[str]) -> bool:
    h = _norm(haystack)
    return any(_norm(n) and _norm(n) in h for n in needles)


def score_lead(lead: CompanyLead, icp: dict, now: datetime | None = None) -> ScoreBreakdown:
    now = now or datetime.now(timezone.utc)
    reasons: list[str] = []

    icp_fit = 0
    sectors = icp.get("sectors") or []
    blob = " ".join(
        [
            lead.industry,
            lead.name,
            lead.signal.summary,
        ]
    )
    if sectors and _contains_any(blob, sectors):
        icp_fit += 12
        reasons.append(f"ICP fit +12: sector match ({', '.join(sectors[:3])}).")
    elif sectors:
        reasons.append("ICP fit +0: sector not clearly matched.")
    else:
        icp_fit += 6
        reasons.append("ICP fit +6: no explicit sector in ICP; partial credit.")

    geo = icp.get("geo") or "India"
    cities = icp.get("cities") or []
    geo_blob = f"{lead.country} {lead.city}"
    if _contains_any(geo_blob, [geo] + cities) or (
        _norm(lead.country) in {"india", "in"} and _norm(geo) == "india"
    ):
        icp_fit += 10
        reasons.append(f"ICP fit +10: geo match ({lead.city or lead.country}).")
    elif lead.country in {"unknown", "not_found"}:
        icp_fit += 4
        reasons.append("ICP fit +4: country unknown — not assumed.")
    else:
        reasons.append(f"ICP fit +0: geo mismatch ({lead.country}).")

    stages = icp.get("stages") or []
    stage_blob = f"{lead.funding_stage} {lead.signal.summary}".replace("_", " ")
    stage_needles = [s.replace("_", " ") for s in stages] + ["series b", "series c", "series d", "growth"]
    if stages and _contains_any(stage_blob, stage_needles):
        icp_fit += 10
        reasons.append("ICP fit +10: stage language matches ICP.")
    elif not stages:
        icp_fit += 5
        reasons.append("ICP fit +5: stage not specified in ICP.")
    else:
        icp_fit += 3
        reasons.append("ICP fit +3: stage not explicit in sources.")

    if lead.website not in {"unknown", "not_found", ""}:
        icp_fit += 8
        reasons.append("ICP fit +8: public website resolved.")
    else:
        reasons.append("ICP fit +0: website not_found.")

    icp_fit = min(40, icp_fit)

    sig = lead.signal
    strength = 0
    if sig.type in STRONG_SIGNALS:
        strength += 15
        reasons.append(f"Signal +15: strong type ({sig.type}).")
    elif sig.type not in {"none", "other"}:
        strength += 8
        reasons.append(f"Signal +8: moderate type ({sig.type}).")
    else:
        strength += 3
        reasons.append("Signal +3: weak / unspecified type.")

    conf_pts = {"HIGH": 10, "MEDIUM": 6, "LOW": 2, "UNVERIFIED": 0}
    strength += conf_pts.get(sig.confidence, 0)
    reasons.append(f"Signal +{conf_pts.get(sig.confidence, 0)}: confidence {sig.confidence}.")
    strength = min(25, strength)

    days = sig.recency_days
    if days is None:
        days = recency_days(sig.date, now)
        sig.recency_days = days
    window = int(icp.get("recency_days") or 90)
    if days is None:
        recency = 6
        reasons.append("Recency +6: date unknown — not treated as fresh.")
    elif days <= 30:
        recency = 20
        reasons.append(f"Recency +20: {days} days ago.")
    elif days <= window:
        recency = 14
        reasons.append(f"Recency +14: {days} days ago (inside {window}d window).")
    elif days <= window * 2:
        recency = 6
        reasons.append(f"Recency +6: {days} days ago — decaying.")
    else:
        recency = 0
        reasons.append(f"Recency +0: stale ({days} days).")

    contact_pts = 3
    c = lead.contact
    named = c.name not in {"not_found", "unknown", ""}
    all_contacts = lead.contacts or []
    usable_named = [x for x in all_contacts if x.usable_in_outreach and x.name not in {"not_found", "unknown", ""}]
    if c.inferred:
        contact_pts = 2
        reasons.append("Contact +2: name is inferred — not usable in outreach.")
    elif named and c.usable_in_outreach:
        contact_pts = 15
        reasons.append(f"Contact +15: primary target {c.role} ({c.name}).")
    elif named:
        contact_pts = 9
        reasons.append(f"Contact +9: named but lower confidence ({c.role}).")
    elif c.role not in {"unknown", ""}:
        contact_pts = 7
        reasons.append(f"Contact +7: role suggested ({c.role}), name not_found.")
    else:
        reasons.append("Contact +3: no public contact found.")

    if len(usable_named) >= 2:
        bonus = min(3, len(usable_named) - 1)
        contact_pts = min(15, contact_pts + bonus)
        names = ", ".join(f"{x.name} ({x.role})" for x in usable_named[:3])
        reasons.append(f"Contact +{bonus}: {len(usable_named)} sourced decision-makers ({names}).")

    # Reachability bonus inside the 15-pt contact budget
    reach = 0
    if c.email:
        reach += 2
        reasons.append("Contact +2: public email on file.")
    elif c.phone:
        reach += 2
        reasons.append("Contact +2: public phone on file.")
    elif c.linkedin_url:
        reach += 1
        reasons.append("Contact +1: LinkedIn profile URL for plugin enrichment.")
    contact_pts = min(15, contact_pts + reach)

    total = icp_fit + strength + recency + contact_pts
    why = (
        f"Score {total}/100 because ICP fit {icp_fit}/40, signal {strength}/25, "
        f"recency {recency}/20, contact {contact_pts}/15. "
        + ("Signal is usable in outreach." if sig.usable_in_outreach else "Signal is NOT cleared for outreach.")
    )
    return ScoreBreakdown(
        icp_fit=icp_fit,
        signal_strength=strength,
        recency=recency,
        contact_relevance=contact_pts,
        total=total,
        reasons=reasons,
        why=why,
    )
