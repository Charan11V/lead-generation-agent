"""Deterministic Verification-Weighted Fit Score. LLM never picks the number."""

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

# Cap total when signal is too weak for verified-people promotion
WEAK_SIGNAL_TOTAL_CAP = 55
MIN_ICP_FIT_FOR_CRITERIA = 12


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


def _is_verified_person_dict(c: dict | object) -> bool:
    """Accept ContactCandidate models or dicts already flagged / gate-passing."""
    if hasattr(c, "model_dump"):
        data = c.model_dump()
    else:
        data = dict(c) if isinstance(c, dict) else {}
    if data.get("person_verified") is True:
        return True
    name = _norm(str(data.get("name") or ""))
    if name in {"", "not_found", "unknown"}:
        return False
    if data.get("inferred"):
        return False
    if not data.get("usable_in_outreach"):
        return False
    if data.get("confidence") not in {"HIGH", "MEDIUM"}:
        return False
    if data.get("playbook_role_match") is False:
        return False
    # Legacy payloads without person_verified: require playbook match flag or omit
    return bool(data.get("playbook_role_match"))


def score_icp_fit(lead: CompanyLead, icp: dict, reasons: list[str]) -> int:
    """ICP fit pillar — max 30."""
    icp_fit = 0
    sectors = icp.get("sectors") or []
    blob = " ".join([lead.industry, lead.name, lead.signal.summary])
    if sectors and _contains_any(blob, sectors):
        icp_fit += 10
        reasons.append(f"ICP fit +10: sector match ({', '.join(sectors[:3])}).")
    elif sectors:
        reasons.append("ICP fit +0: sector not clearly matched.")
    else:
        icp_fit += 5
        reasons.append("ICP fit +5: no explicit sector in ICP; partial credit.")

    geo = icp.get("geo") or "India"
    cities = icp.get("cities") or []
    geo_blob = f"{lead.country} {lead.city}"
    if _contains_any(geo_blob, [geo] + cities) or (
        _norm(lead.country) in {"india", "in"} and _norm(geo) == "india"
    ):
        icp_fit += 8
        reasons.append(f"ICP fit +8: geo match ({lead.city or lead.country}).")
    elif lead.country in {"unknown", "not_found"}:
        icp_fit += 3
        reasons.append("ICP fit +3: country unknown — not assumed.")
    else:
        reasons.append(f"ICP fit +0: geo mismatch ({lead.country}).")

    stages = icp.get("stages") or []
    stage_blob = f"{lead.funding_stage} {lead.signal.summary}".replace("_", " ")
    stage_needles = [s.replace("_", " ") for s in stages] + ["series b", "series c", "series d", "growth"]
    if stages and _contains_any(stage_blob, stage_needles):
        icp_fit += 6
        reasons.append("ICP fit +6: stage language matches ICP.")
    elif not stages:
        icp_fit += 3
        reasons.append("ICP fit +3: stage not specified in ICP.")
    else:
        icp_fit += 2
        reasons.append("ICP fit +2: stage not explicit in sources.")

    company_types = icp.get("company_types") or []
    type_blob = f"{lead.industry} {lead.signal.summary} {lead.name}"
    if company_types and _contains_any(type_blob, company_types):
        icp_fit += 3
        reasons.append("ICP fit +3: company type language matches.")
    elif company_types:
        reasons.append("ICP fit +0: company type not matched.")

    buying = icp.get("buying_signals") or []
    if buying and _contains_any(lead.signal.summary or "", buying):
        icp_fit += 3
        reasons.append("ICP fit +3: buying-signal language matches brief.")

    return min(30, icp_fit)


def score_lead(lead: CompanyLead, icp: dict, now: datetime | None = None) -> ScoreBreakdown:
    now = now or datetime.now(timezone.utc)
    reasons: list[str] = []

    icp_fit = score_icp_fit(lead, icp, reasons)

    sig = lead.signal
    strength = 0
    if sig.type in STRONG_SIGNALS:
        strength += 12
        reasons.append(f"Signal +12: strong type ({sig.type}).")
    elif sig.type not in {"none", "other"}:
        strength += 7
        reasons.append(f"Signal +7: moderate type ({sig.type}).")
    else:
        strength += 2
        reasons.append("Signal +2: weak / unspecified type.")

    conf_pts = {"HIGH": 10, "MEDIUM": 6, "LOW": 2, "UNVERIFIED": 0}
    strength += conf_pts.get(sig.confidence, 0)
    reasons.append(f"Signal +{conf_pts.get(sig.confidence, 0)}: confidence {sig.confidence}.")
    if (sig.evidence_quote or "").strip() and len(sig.evidence_quote.strip()) >= 12:
        strength += 3
        reasons.append("Signal +3: evidence quote present.")
    if sig.sources:
        strength += min(2, len(sig.sources))
        reasons.append(f"Signal +{min(2, len(sig.sources))}: {len(sig.sources)} named source(s).")
    strength = min(25, strength)

    days = sig.recency_days
    if days is None:
        days = recency_days(sig.date, now)
        sig.recency_days = days
    window = int(icp.get("recency_days") or 90)
    if days is None:
        recency = 5
        reasons.append("Recency +5: date unknown — not treated as fresh.")
    elif days <= 30:
        recency = 15
        reasons.append(f"Recency +15: {days} days ago.")
    elif days <= window:
        recency = 11
        reasons.append(f"Recency +11: {days} days ago (inside {window}d window).")
    elif days <= window * 2:
        recency = 5
        reasons.append(f"Recency +5: {days} days ago — decaying.")
    else:
        recency = 0
        reasons.append(f"Recency +0: stale ({days} days).")

    # Approach quality — verified playbook people + person-tied channels only
    approach = 0
    verified = []
    for c in lead.verified_contacts or []:
        verified.append(c)
    if not verified:
        for c in lead.contacts or []:
            if _is_verified_person_dict(c):
                verified.append(c)
    primary = lead.contact
    primary_ok = _is_verified_person_dict(primary) if primary else False

    if verified or primary_ok:
        approach += 10
        reasons.append(
            f"Approach +10: {len(verified) or 1} verified playbook decision-maker(s)."
        )
        top = verified[0] if verified else primary
        if getattr(top, "email", None) or (isinstance(top, dict) and top.get("email")):
            approach += 5
            reasons.append("Approach +5: person-tied public email.")
        elif getattr(top, "phone", None) or (isinstance(top, dict) and top.get("phone")):
            approach += 4
            reasons.append("Approach +4: person-tied public phone.")
        elif getattr(top, "linkedin_url", None) or (isinstance(top, dict) and top.get("linkedin_url")):
            approach += 3
            reasons.append("Approach +3: verified LinkedIn profile URL.")
        if len(verified) >= 2:
            bonus = min(2, len(verified) - 1)
            approach += bonus
            reasons.append(f"Approach +{bonus}: multiple verified decision-makers.")
    elif lead.best_approach_channel or (lead.approach_channels or []):
        approach += 6
        reasons.append("Approach +6: company-level approach channel (no verified person).")
        ch = lead.best_approach_channel or ""
        if ch.startswith("email:"):
            approach += 2
            reasons.append("Approach +2: company contact email.")
        elif ch.startswith("url:") or "http" in ch:
            approach += 1
            reasons.append("Approach +1: public contact/careers URL.")
    else:
        named = primary and primary.name not in {"not_found", "unknown", ""}
        if named and not primary.inferred:
            approach += 3
            reasons.append("Approach +3: named contact but not fully verified.")
        else:
            reasons.append("Approach +0: no verified person or company channel.")
    approach = min(20, approach)

    # Evidence depth — max 10
    evidence = 0
    if lead.website not in {"unknown", "not_found", ""}:
        evidence += 3
        reasons.append("Evidence +3: public website resolved.")
    else:
        reasons.append("Evidence +0: website not_found.")
    n_sources = len(sig.sources or [])
    if n_sources:
        pts = min(4, n_sources * 2)
        evidence += pts
        reasons.append(f"Evidence +{pts}: {n_sources} source URL(s).")
    if len(verified) >= 2:
        evidence += 3
        reasons.append("Evidence +3: multiple independently verified DMs.")
    elif verified or primary_ok:
        evidence += 2
        reasons.append("Evidence +2: at least one verified DM.")
    elif lead.approach_channels:
        evidence += 1
        reasons.append("Evidence +1: company approach channel sourced.")
    evidence = min(10, evidence)

    total = icp_fit + strength + recency + approach + evidence
    capped = False
    if sig.confidence in {"UNVERIFIED", "LOW"}:
        if total > WEAK_SIGNAL_TOTAL_CAP:
            reasons.append(
                f"Cap: weak signal confidence ({sig.confidence}) — total capped at {WEAK_SIGNAL_TOTAL_CAP}."
            )
            total = WEAK_SIGNAL_TOTAL_CAP
            capped = True

    why = (
        f"Score {total}/100 because ICP fit {icp_fit}/30, signal {strength}/25, "
        f"recency {recency}/15, approach {approach}/20, evidence {evidence}/10. "
        + ("Signal is usable in outreach." if sig.usable_in_outreach else "Signal is NOT cleared for outreach.")
    )
    return ScoreBreakdown(
        icp_fit=icp_fit,
        signal_strength=strength,
        recency=recency,
        approach_quality=approach,
        evidence_depth=evidence,
        contact_relevance=approach,  # alias for older consumers
        total=total,
        capped_for_weak_signal=capped,
        reasons=reasons,
        why=why,
    )


def meets_criteria(lead: CompanyLead | dict, score: ScoreBreakdown | dict | None = None) -> bool:
    """Minimum bar to appear in results: usable signal OR solid ICP fit."""
    if hasattr(lead, "model_dump"):
        data = lead.model_dump()
        sig = data.get("signal") or {}
        sc = score.model_dump() if score and hasattr(score, "model_dump") else (score or data.get("score") or {})
    else:
        data = lead
        sig = data.get("signal") or {}
        sc = score if isinstance(score, dict) else (data.get("score") or {})
        if score and hasattr(score, "model_dump"):
            sc = score.model_dump()
    if sig.get("usable_in_outreach"):
        return True
    return int(sc.get("icp_fit") or 0) >= MIN_ICP_FIT_FOR_CRITERIA
