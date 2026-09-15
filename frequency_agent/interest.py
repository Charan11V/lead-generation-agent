"""Why this company might buy from Frequency — sourced reasoning, not fluff."""

from __future__ import annotations

from .branding import brand_name
from .llm import LLM
from .proofs import select_outreach_proofs
from .schemas import CompanyLead, ICP


def explain_interest(llm: LLM, lead: CompanyLead, icp: ICP) -> str:
    """Generate a detailed, credible interest rationale from gathered facts only."""
    signal = lead.signal
    contact = lead.contact
    proofs = select_outreach_proofs(lead.proofs or [], max_n=2)
    proof_txt = "\n".join(
        (
            f"- [{('direct' if (getattr(p, 'match_tier', '') or 'direct') == 'direct' else 'related suggestion')}] "
            f"{p.company}: {p.outcome}"
            + (f" — {p.usage_hint}" if getattr(p, "usage_hint", "") else "")
        )
        for p in proofs
    )

    system = (
        "You write a concise BD interest brief for "
        f"{brand_name()} (exec search, fractional CXO, capital advisory). "
        "Use ONLY facts in the lead brief. 4-6 sentences. Cover:\n"
        "1) What signal makes timing plausible now\n"
        f"2) Which leadership/talent/capital gap {brand_name()} could plausibly help with\n"
        "3) Why the matched proof points are relevant — if labelled related suggestion, say so "
        "and do not claim the prospect is the same kind of company\n"
        "4) Who should care internally (role) if contact name is missing\n"
        "No flattery, no invented numbers, no 'leading provider' language."
    )
    user = f"""
Service line: {icp.service_line}
ICP: {icp.raw_text}

Company: {lead.name}
Industry: {lead.industry}
Location: {lead.city}, {lead.country}
Stage: {lead.funding_stage}
Website: {lead.website}

Signal ({signal.confidence}, {signal.type}, {signal.date}):
{signal.summary}
Evidence: {signal.evidence_quote}

Primary contact: {contact.name} · {contact.role}
Contact why: {contact.why}

Matched {brand_name()} proofs:
{proof_txt or 'none'}

Score: {lead.score.total}/100 — {lead.score.why}
"""
    try:
        return llm.text(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.35,
        ).strip()
    except Exception:
        parts = []
        if signal.summary:
            parts.append(f"Recent signal: {signal.summary}")
        if contact.role and contact.role != "unknown":
            parts.append(f"Likely internal owner: {contact.role}.")
        parts.append(
            f"A {icp.service_line.replace('_', ' ')} motion fits because the public signal suggests "
            f"a leadership or growth inflection where {brand_name()} has placed similar roles."
        )
        return " ".join(parts)
