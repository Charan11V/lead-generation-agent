"""Why this company might buy from Frequency — sourced reasoning, not fluff."""

from __future__ import annotations

from .llm import LLM
from .schemas import CompanyLead, ICP


def explain_interest(llm: LLM, lead: CompanyLead, icp: ICP) -> str:
    """Generate a detailed, credible interest rationale from gathered facts only."""
    signal = lead.signal
    contact = lead.contact
    proofs = lead.proofs or []
    proof_txt = "\n".join(f"- {p.company}: {p.outcome}" for p in proofs[:3])

    system = (
        "You write a concise BD interest brief for Frequency (exec search, fractional CXO, capital advisory). "
        "Use ONLY facts in the lead brief. 4-6 sentences. Cover:\n"
        "1) What signal makes timing plausible now\n"
        "2) Which leadership/talent/capital gap Frequency could plausibly help with\n"
        "3) Why the matched proof points are relevant (do not invent outcomes)\n"
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

Matched Frequency proofs:
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
            "a leadership or growth inflection where Frequency has placed similar roles."
        )
        return " ".join(parts)
