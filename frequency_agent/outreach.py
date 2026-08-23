"""Outreach drafting + code QA gate. Unverified facts never go out as fact."""

from __future__ import annotations

import re

from .llm import LLM, load_json
from .schemas import CompanyLead


def load_tone() -> dict:
    data = load_json("tone_guide.json")
    return dict(data)


def _banned_hits(text: str, banned: list[str]) -> list[str]:
    low = text.lower()
    return [b for b in banned if b.lower() in low]


def qa_outreach(lead: CompanyLead, email: str, linkedin: str) -> list[str]:
    tone = load_tone()
    flags: list[str] = []
    banned = tone.get("avoid") or []
    flags.extend([f"Banned phrase in email: '{b}'" for b in _banned_hits(email, banned)])
    flags.extend([f"Banned phrase in LinkedIn: '{b}'" for b in _banned_hits(linkedin, banned)])

    words = len(email.split())
    lo, hi = tone.get("email_word_range") or [110, 190]
    if words and (words < lo - 30 or words > hi + 40):
        flags.append(f"Email length {words} words is outside the intended range.")

    proof_names = [p.company.lower() for p in lead.proofs]
    present = sum(1 for n in proof_names if n and n in email.lower())
    if present < min(2, len(proof_names)):
        flags.append("Email does not cite at least two matched Frequency proof points.")

    if lead.signal.usable_in_outreach:
        # The hook should mention something from the signal summary (token overlap)
        tokens = [t for t in re.findall(r"[A-Za-z]{4,}", lead.signal.summary) if t.lower() not in {"that", "with", "from", "this", "their"}]
        if tokens and not any(t.lower() in email.lower() for t in tokens[:8]):
            flags.append("Email hook does not clearly reference the sourced signal.")
    else:
        flags.append("Signal is not cleared for outreach — draft should not be sent.")

    if lead.contact.inferred and lead.contact.name.lower() in email.lower() and lead.contact.name not in {"not_found", "unknown"}:
        flags.append("Draft uses an inferred contact name as if it were fact.")

    # Numbers in the draft must appear in signal sources or matched proof outcomes
    allowed_numeric = " ".join(
        [lead.signal.summary, lead.signal.evidence_quote]
        + [s.snippet for s in lead.signal.sources]
        + [p.outcome for p in lead.proofs]
    )
    for num in re.findall(r"₹?\s?\d[\d,]*(?:\.\d+)?\s?(?:cr|crore|million|m|bn|billion)?", email, flags=re.I):
        compact = re.sub(r"\s+", "", num.lower())
        hay = re.sub(r"\s+", "", allowed_numeric.lower())
        digits = re.sub(r"[^\d]", "", num)
        if digits and digits not in hay and compact not in hay:
            flags.append(f"Unsourced number in email: '{num.strip()}'.")

    if not re.search(r"\?", email) and not re.search(
        r"(15 minute|15-min|worth a|if useful|on the agenda|happy to)", email, re.I
    ):
        flags.append("CTA looks missing or high-friction.")

    return flags


def draft_outreach(llm: LLM, lead: CompanyLead, icp: dict) -> tuple[str, str, list[str]]:
    tone = load_tone()
    if not lead.signal.usable_in_outreach:
        blocked = (
            f"[BLOCKED — DO NOT SEND]\n"
            f"Signal for {lead.name} is {lead.signal.confidence}. "
            f"A human should verify the source before any outreach is drafted as sendable.\n"
            f"Signal note: {lead.signal.summary or 'none'}"
        )
        return blocked, blocked, ["Signal not usable in outreach"]

    proofs = "\n".join(
        f"- {p.company}: placed {', '.join(p.roles_placed)}. {p.outcome} ({p.why_matched})"
        for p in lead.proofs
    )
    sources = "\n".join(
        f"- {s.title or s.url} | {s.date or 'date unknown'} | {s.url}"
        for s in lead.signal.sources
    )
    contact_line = (
        f"{lead.contact.name}, {lead.contact.role}"
        if lead.contact.usable_in_outreach and lead.contact.name not in {"not_found"}
        else f"Role only: {lead.contact.role or 'Founder/CEO'} (name not_found — do not invent a name)"
    )
    if lead.contact.email:
        contact_line += f" · email {lead.contact.email}"
    elif lead.contact.linkedin_url:
        contact_line += f" · LinkedIn {lead.contact.linkedin_url}"
    elif lead.contact.twitter_url:
        contact_line += f" · X {lead.contact.twitter_url}"
    alt_contacts = ""
    alts = [c for c in (lead.contacts or []) if not c.is_primary and c.usable_in_outreach]
    if alts:
        alt_contacts = "\nAlternate outreach targets (for human routing — do not invent):\n" + "\n".join(
            f"- {c.name}, {c.role}: {c.why} (score {c.relevance_score})"
            + (f" · {c.email}" if c.email else "")
            + (f" · {c.linkedin_url}" if c.linkedin_url else "")
            for c in alts[:4]
        )

    system = (
        "You write first-touch BD email for Frequency, a Bengaluru boutique "
        "(retained executive search, fractional CXO, capital advisory). "
        "Tone: precision, poise, intrigue. Sharp, credible, not salesy.\n"
        "Structure EXACTLY: hook (the sourced signal) → 2-3 Frequency proof points → low-friction CTA.\n"
        "Rules:\n"
        "- Use only facts in the lead brief. If unknown, omit.\n"
        "- Never invent numbers, titles, or people.\n"
        "- Do not use: " + "; ".join(tone.get("avoid") or []) + "\n"
        "- Short paragraphs. No flattery. No 'we are a leading'.\n"
        "- Proof points must be the ones listed, with outcomes.\n"
        "- CTA is a 15-minute conversation or an offer to share a tighter read — not a demo booking hard sell.\n"
        "Return two blocks labelled exactly:\nEMAIL:\n... \nLINKEDIN:\n..."
    )
    user = f"""
ICP: {icp.get('raw_text')}
Service line: {icp.get('service_line')}

Company: {lead.name}
Website: {lead.website}
Industry: {lead.industry}
Location: {lead.city}, {lead.country}
Stage: {lead.funding_stage}

Contact: {contact_line}
Why this contact: {lead.contact.why}
{alt_contacts}

Signal ({lead.signal.confidence}, {lead.signal.type}, date={lead.signal.date}):
{lead.signal.summary}
Evidence quote: {lead.signal.evidence_quote}
Sources:
{sources}

Matched Frequency proof points (ONLY these):
{proofs}

Write the email ({tone['email_word_range'][0]}-{tone['email_word_range'][1]} words)
and a tighter LinkedIn note ({tone['linkedin_word_range'][0]}-{tone['linkedin_word_range'][1]} words).
If the contact name is not_found, open with the role or 'Hello'.
"""
    raw = llm.text(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.45,
    )
    email, linkedin = _split_blocks(raw)
    flags = qa_outreach(lead, email, linkedin)
    return email.strip(), linkedin.strip(), flags


def _split_blocks(raw: str) -> tuple[str, str]:
    text = raw.replace("```", "").strip()
    email = text
    linkedin = ""
    if re.search(r"LINKEDIN\s*:", text, re.I):
        parts = re.split(r"LINKEDIN\s*:", text, maxsplit=1, flags=re.I)
        email = re.sub(r"^EMAIL\s*:", "", parts[0], flags=re.I).strip()
        linkedin = parts[1].strip()
    elif re.search(r"^EMAIL\s*:", text, re.I):
        email = re.sub(r"^EMAIL\s*:", "", text, flags=re.I).strip()
    return email, linkedin
