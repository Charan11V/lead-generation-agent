"""Outreach drafting + code QA gate. Unverified facts never go out as fact."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

from .branding import brand_domain, brand_name, rewrite_frequency
from .llm import LLM, load_json
from .proofs import load_proofs, match_proofs, select_outreach_proofs
from .schemas import CompanyLead, Contact, ContactCandidate, ProofMatch, fresh_contact


def load_tone() -> dict:
    data = load_json("tone_guide.json")
    return dict(data)


@lru_cache(maxsize=1)
def load_bd_playbook() -> str:
    path = Path(__file__).resolve().parent.parent / "data" / "bd_playbook.md"
    if path.exists():
        return rewrite_frequency(path.read_text(encoding="utf-8"))
    return ""


def _banned_hits(text: str, banned: list[str]) -> list[str]:
    low = text.lower()
    return [b for b in banned if b.lower() in low]


def _ensure_matched_proofs(lead: CompanyLead, icp: dict) -> CompanyLead:
    """Refresh proof matches for this company + ICP before drafting."""
    if not icp:
        return lead
    return lead.model_copy(update={"proofs": match_proofs(lead, icp, k=3)})


def _outreach_proofs(lead: CompanyLead) -> list[ProofMatch]:
    return select_outreach_proofs(lead.proofs, max_n=2)


def qa_outreach(lead: CompanyLead, email: str, linkedin: str) -> list[str]:
    tone = load_tone()
    flags: list[str] = []
    banned = tone.get("avoid") or []
    flags.extend([f"Banned phrase in email: '{b}'" for b in _banned_hits(email, banned)])
    flags.extend([f"Banned phrase in LinkedIn: '{b}'" for b in _banned_hits(linkedin, banned)])

    words = len(email.split())
    lo, hi = tone.get("email_word_range") or [110, 190]
    if words and (words < lo - 40 or words > hi + 50):
        flags.append(f"Email length {words} words is outside the intended range.")

    citable = _outreach_proofs(lead)
    proof_names = [p.company.lower() for p in citable if (p.company or "").strip()]
    present = sum(1 for n in proof_names if n and n in email.lower())
    if proof_names and present < min(1, len(proof_names)):
        flags.append(f"Email does not cite at least one matched {brand_name()} proof point.")

    allowed = set(proof_names)
    deck_names = {
        (p.get("company") or "").strip().lower()
        for p in load_proofs()
        if (p.get("company") or "").strip()
    }
    for name in sorted(deck_names):
        if name and name in email.lower() and name not in allowed:
            flags.append(
                f"Email cites off-brief proof '{name}' — use only the company/ICP-matched proofs provided."
            )

    related_only = bool(citable) and all(
        (getattr(p, "match_tier", None) or "") == "related" for p in citable
    )
    if related_only:
        soft = re.search(
            r"(adjacent|similar (?:work|search|mandate)|related (?:work|experience)|"
            r"comparable (?:search|placement)|not (?:the )?same (?:sector|industry)|"
            r"for (?:a )?similar (?:function|mandate|search))",
            email,
            re.I,
        )
        if not soft:
            flags.append(
                "Only related (non-direct) proofs were available — email should frame them as "
                "adjacent Frequency experience, not as a same-industry analogue."
            )

    if lead.signal.usable_in_outreach:
        tokens = [
            t
            for t in re.findall(r"[A-Za-z]{4,}", lead.signal.summary)
            if t.lower() not in {"that", "with", "from", "this", "their"}
        ]
        if tokens and not any(t.lower() in email.lower() for t in tokens[:8]):
            flags.append("Email hook does not clearly reference the sourced signal.")
    else:
        flags.append("Signal is not cleared for outreach — draft should not be sent.")

    if lead.contact.inferred and lead.contact.name.lower() in email.lower() and lead.contact.name not in {
        "not_found",
        "unknown",
    }:
        flags.append("Draft uses an inferred contact name as if it were fact.")

    allowed_numeric = " ".join(
        [lead.signal.summary, lead.signal.evidence_quote]
        + [s.snippet for s in lead.signal.sources]
        + [p.outcome for p in citable]
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


def _contact_line(person: Contact | ContactCandidate | dict) -> str:
    if hasattr(person, "model_dump"):
        data = person.model_dump()
    else:
        data = dict(person)
    name = (data.get("name") or "").strip()
    role = (data.get("role") or "").strip()
    if name and name.lower() not in {"not_found", "unknown"} and data.get("usable_in_outreach", True):
        line = f"{name}, {role}"
    else:
        line = f"Role only: {role or 'Founder/CEO'} (name not_found — do not invent a name)"
    if data.get("email"):
        line += f" · email {data['email']}"
    elif data.get("linkedin_url"):
        line += f" · LinkedIn {data['linkedin_url']}"
    elif data.get("twitter_url"):
        line += f" · X {data['twitter_url']}"
    elif data.get("phone"):
        line += f" · phone {data['phone']}"
    return line


def _proofs_block(lead: CompanyLead, *, for_outreach: bool = True) -> str:
    proofs = _outreach_proofs(lead) if for_outreach else list(lead.proofs or [])
    if not proofs:
        return "(No matched proof points — omit proof names rather than inventing.)"
    has_direct = any((getattr(p, "match_tier", None) or "direct") == "direct" for p in proofs)
    header = (
        "Use ONLY the DIRECT MATCH proofs below; do not mention other Frequency case studies."
        if has_direct
        else "No direct company match — use at most these RELATED proofs as adjacent Frequency "
        "experience for this ICP/search. Never claim the prospect is the same kind of company."
    )
    lines = [header]
    for p in proofs:
        tier = (getattr(p, "match_tier", None) or "direct").lower()
        label = "DIRECT MATCH" if tier == "direct" else "RELATED SUGGESTION (not a direct company match)"
        hint = (getattr(p, "usage_hint", None) or "").strip()
        line = (
            f"- [{label}] {p.company}: placed {', '.join(p.roles_placed)}. "
            f"{p.outcome} ({p.why_matched})"
        )
        if hint:
            line += f" How to use: {hint}"
        lines.append(line)
    return "\n".join(lines)


def _sources_block(lead: CompanyLead) -> str:
    return "\n".join(
        f"- {s.title or s.url} | {s.date or 'date unknown'} | {s.url}" for s in lead.signal.sources
    )


def _split_blocks(raw: str) -> tuple[str, str]:
    text = raw.replace("```", "").strip()
    email = ""
    linkedin = ""
    if re.search(r"EMAIL\s*:", text, re.I) and re.search(r"LINKEDIN\s*:", text, re.I):
        email_parts = re.split(r"EMAIL\s*:", text, maxsplit=1, flags=re.I)
        rest = email_parts[-1]
        if re.search(r"LINKEDIN\s*:", rest, re.I):
            email_body, li_body = re.split(r"LINKEDIN\s*:", rest, maxsplit=1, flags=re.I)
            email = email_body.strip()
            linkedin = li_body.strip()
        else:
            email = rest.strip()
    elif re.search(r"LINKEDIN\s*:", text, re.I):
        parts = re.split(r"LINKEDIN\s*:", text, maxsplit=1, flags=re.I)
        email = re.sub(r"^EMAIL\s*:", "", parts[0], flags=re.I).strip()
        linkedin = parts[1].strip()
    elif re.search(r"^EMAIL\s*:", text, re.I):
        email = re.sub(r"^EMAIL\s*:", "", text, flags=re.I).strip()
    else:
        email = text
    if linkedin and re.search(r"\nEMAIL\s*:", linkedin, re.I):
        linkedin = re.split(r"\nEMAIL\s*:", linkedin, maxsplit=1, flags=re.I)[0].strip()
    return email.strip(), linkedin.strip()


def _linkedin_fallback_from_email(email: str) -> str:
    """Short note when the model omitted LINKEDIN: — keep it usable, not empty."""
    lines = [ln.strip() for ln in (email or "").splitlines() if ln.strip()]
    body = " ".join(lines[:4])
    words = body.split()
    if len(words) > 70:
        body = " ".join(words[:70]).rstrip(".,;") + "…"
    return body.strip()


def _draft_system(tone: dict, *, mode: str) -> str:
    playbook = load_bd_playbook()
    mode_note = (
        "DIRECT: write to a verified decision-maker who is the right approach person for this ICP."
        if mode == "direct"
        else "INDIRECT: no verified DM found — write a first-touch to the company's best approach channel "
        "(contact/careers/press inbox or page). Address the function/role the ICP cares about, not a invented person."
    )
    return (
        f"You write first-touch BD outreach for {brand_name()} ({brand_domain()}) — Bengaluru boutique for "
        "retained executive search, fractional CXO, and capital advisory.\n"
        f"{mode_note}\n"
        f"Use the {brand_name()} BD Playbook below as guidance, then tailor to THIS ICP, company, person/channel, "
        "and signal. Do not paste a template blindly.\n"
        "You MUST produce TWO pieces for this recipient:\n"
        "1) EMAIL — a single reusable outreach message that can be pasted into email, LinkedIn InMail, "
        "WhatsApp, or similar. Full first-touch: hook → proof → one CTA. Not channel-specific formatting.\n"
        "2) LINKEDIN — a shorter LinkedIn connection/note version of the same idea "
        f"({(tone.get('linkedin_word_range') or [40, 80])[0]}–{(tone.get('linkedin_word_range') or [40, 80])[1]} words).\n"
        "Tone: sharp, specific, human — not corporate fluff. Precision over polish.\n"
        f"Structure for EMAIL: hook (sourced signal) → 1–2 {brand_name()} proof points that fit "
        "THIS company and THIS ICP/search → one low-friction CTA.\n"
        "Rules:\n"
        "- Use only facts in the lead brief. If unknown, omit.\n"
        "- Never invent numbers, titles, or people.\n"
        "- Do not use: " + "; ".join(tone.get("avoid") or []) + "\n"
        "- Short paragraphs. No flattery. No 'we are a leading'.\n"
        "- Proof points must be from the matched list only — never pull other Frequency stories from memory.\n"
        "- Choose proofs that serve the ICP/search intent (service line, sector, role) and fit the company.\n"
        "- If DIRECT MATCH proofs are listed, cite only those.\n"
        "- If only RELATED SUGGESTION proofs are listed, frame them as adjacent Frequency experience "
        "for a similar mandate/function — never as a same-industry analogue for this company.\n"
        "- CTA is a 15-minute conversation or offer to share a tighter read / 2–3 profiles — not a hard sell.\n"
        "Return two blocks labelled exactly:\nEMAIL:\n...\nLINKEDIN:\n...\n\n"
        f"--- BD PLAYBOOK ---\n{playbook}\n--- END PLAYBOOK ---"
    )


def draft_for_person(
    llm: LLM,
    lead: CompanyLead,
    person: Contact | ContactCandidate | dict,
    icp: dict,
    *,
    mode: str = "direct",
) -> tuple[str, str, list[str]]:
    """Craft one email (+ LinkedIn note) tailored to a specific person or role."""
    tone = load_tone()
    lead = _ensure_matched_proofs(lead, icp)
    if not lead.signal.usable_in_outreach:
        blocked = (
            f"[BLOCKED — DO NOT SEND]\n"
            f"Signal for {lead.name} is {lead.signal.confidence}. "
            f"Verify the source before sending.\n"
            f"Signal note: {lead.signal.summary or 'none'}"
        )
        return blocked, blocked, ["Signal not usable in outreach"]

    contact_line = _contact_line(person)
    why = ""
    if hasattr(person, "why"):
        why = person.why or getattr(person, "likelihood_reason", "") or ""
    elif isinstance(person, dict):
        why = person.get("why") or person.get("likelihood_reason") or ""

    system = _draft_system(tone, mode=mode)
    user = f"""
ICP: {icp.get('raw_text')}
Service line: {icp.get('service_line')}

Company: {lead.name}
Website: {lead.website}
Industry: {lead.industry}
Location: {lead.city}, {lead.country}
Stage: {lead.funding_stage}

Recipient ({mode}): {contact_line}
Why this recipient: {why or 'Playbook-fit decision-maker / best approach path for this ICP.'}

Signal ({lead.signal.confidence}, {lead.signal.type}, date={lead.signal.date}):
{lead.signal.summary}
Evidence quote: {lead.signal.evidence_quote}
Sources:
{_sources_block(lead)}

Matched {brand_name()} proof points for THIS company + ICP (ONLY these — do not cite others):
{_proofs_block(lead)}

Write BOTH for this recipient:
1) EMAIL — reusable outreach message ({tone['email_word_range'][0]}-{tone['email_word_range'][1]} words)
   usable as email / LinkedIn InMail / message paste.
2) LINKEDIN — shorter LinkedIn note ({tone['linkedin_word_range'][0]}-{tone['linkedin_word_range'][1]} words).
If the contact name is not_found, open with the role or 'Hello' — never invent a name.
Make both feel written for this person/company/ICP, not a mass template.
Proofs in the message must be relevant to this company and the ICP/search above.
Label blocks exactly EMAIL: and LINKEDIN:
"""
    raw = llm.text(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.5,
    )
    email, linkedin = _split_blocks(raw)
    # QA against a temporary lead view with this person as primary
    try:
        if isinstance(person, Contact):
            probe_contact = person
        elif hasattr(person, "model_dump"):
            probe_contact = fresh_contact(person)  # type: ignore[arg-type]
        else:
            probe_contact = Contact.model_validate(
                {k: v for k, v in person.items() if k in Contact.model_fields}
            )
    except Exception:
        probe_contact = lead.contact
    probe = lead.model_copy(update={"contact": probe_contact})
    flags = qa_outreach(probe, email, linkedin)
    return email.strip(), linkedin.strip(), flags


def draft_for_approach_channel(
    llm: LLM,
    lead: CompanyLead,
    icp: dict,
) -> tuple[str, str, list[str]]:
    """Indirect: email aimed at company approach channel / role, not a named DM."""
    tone = load_tone()
    lead = _ensure_matched_proofs(lead, icp)
    if not lead.signal.usable_in_outreach:
        blocked = (
            f"[BLOCKED — DO NOT SEND]\n"
            f"Signal for {lead.name} is {lead.signal.confidence}. "
            f"Verify the source before sending.\n"
            f"Signal note: {lead.signal.summary or 'none'}"
        )
        return blocked, blocked, ["Signal not usable in outreach"]

    channel = lead.best_approach_channel or ""
    chans = lead.approach_channels or []
    chan_lines = "\n".join(
        f"- {(c.label if hasattr(c, 'label') else c.get('label', ''))}: "
        f"{(c.kind if hasattr(c, 'kind') else c.get('kind'))} = "
        f"{(c.value if hasattr(c, 'value') else c.get('value'))}"
        for c in chans[:5]
    )
    role_hint = lead.contact.role if lead.contact and lead.contact.role not in {"unknown", ""} else "Founder / CEO"
    system = _draft_system(tone, mode="indirect")
    user = f"""
ICP: {icp.get('raw_text')}
Service line: {icp.get('service_line')}

Company: {lead.name}
Website: {lead.website}
Industry: {lead.industry}
Location: {lead.city}, {lead.country}
Stage: {lead.funding_stage}

Best approach channel: {channel}
All company channels:
{chan_lines or '(none listed — write as if to the company / ' + role_hint + ' desk)'}
Intended function to reach: {role_hint}
No verified named decision-maker was found — do NOT invent a person name.

Signal ({lead.signal.confidence}, {lead.signal.type}, date={lead.signal.date}):
{lead.signal.summary}
Evidence quote: {lead.signal.evidence_quote}
Sources:
{_sources_block(lead)}

Matched {brand_name()} proof points for THIS company + ICP (ONLY these — do not cite others):
{_proofs_block(lead)}

Write BOTH:
1) EMAIL — reusable outreach message ({tone['email_word_range'][0]}-{tone['email_word_range'][1]} words)
   usable as email / LinkedIn InMail / message paste to the company channel.
2) LINKEDIN — shorter note ({tone['linkedin_word_range'][0]}-{tone['linkedin_word_range'][1]} words).
Open with Hello / team / role — never invent a name. Tailor to this ICP and company.
Proofs in the message must be relevant to this company and the ICP/search above.
Label blocks exactly EMAIL: and LINKEDIN:
"""
    raw = llm.text(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.5,
    )
    email, linkedin = _split_blocks(raw)
    flags = qa_outreach(lead, email, linkedin)
    return email.strip(), linkedin.strip(), flags


def draft_outreach(llm: LLM, lead: CompanyLead, icp: dict) -> tuple[str, str, list[str]]:
    """Primary draft (backward compatible) — uses primary contact or approach channel."""
    if lead.verified_contacts or (
        lead.contact
        and lead.contact.name not in {"not_found", "unknown", ""}
        and lead.contact.usable_in_outreach
    ):
        person = lead.verified_contacts[0] if lead.verified_contacts else lead.contact
        return draft_for_person(llm, lead, person, icp, mode="direct")
    if lead.approach_channels or lead.best_approach_channel:
        return draft_for_approach_channel(llm, lead, icp)
    return draft_for_person(llm, lead, lead.contact, icp, mode="direct")


def attach_person_drafts(
    llm: LLM,
    lead: CompanyLead,
    icp: dict,
    *,
    max_people: int | None = None,
) -> CompanyLead:
    """Craft 1 email + 1 LinkedIn note for every established (named) contact on the company."""
    from concurrent.futures import ThreadPoolExecutor

    lead = _ensure_matched_proofs(lead, icp)

    # Prefer verified list; otherwise all named contacts shown for the company
    people: list[ContactCandidate] = []
    seen: set[str] = set()
    for src in (lead.verified_contacts or [], lead.contacts or []):
        for p in src:
            key = (p.name or "").strip().lower()
            if not key or key in {"not_found", "unknown"} or key in seen:
                continue
            seen.add(key)
            people.append(p)
    if not people and lead.contact and lead.contact.name not in {"not_found", "unknown", ""}:
        from .schemas import ContactCandidate as CC

        people = [
            CC.model_validate(
                {**lead.contact.model_dump(), "rank": 1, "is_primary": True, "person_verified": True}
            )
        ]

    # Every established contact — soft ceiling only for runaway lists.
    cap = max_people if max_people is not None else int(os.getenv("OUTREACH_MAX_PEOPLE", "12") or "12")
    people = people[: max(1, cap)] if people else []

    if people:
        def _one(p: ContactCandidate) -> ContactCandidate:
            email, li, _flags = draft_for_person(llm, lead, p, icp, mode="direct")
            email = (email or "").strip()
            li = (li or "").strip()
            if email and not li and not email.startswith("[BLOCKED"):
                li = _linkedin_fallback_from_email(email)
            if li and not email and not li.startswith("[BLOCKED"):
                email = li
            return p.model_copy(update={"email_draft": email, "linkedin_note": li})

        workers = min(6, max(1, len(people)))
        if len(people) > 1:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                people = list(pool.map(_one, people))
        else:
            people = [_one(people[0])]

        # Keep primary first
        people = sorted(people, key=lambda c: (0 if c.is_primary else 1, c.rank or 99))
        for i, p in enumerate(people):
            people[i] = p.model_copy(update={"rank": i + 1, "is_primary": i == 0})

        lead.verified_contacts = [p for p in people if p.person_verified] or people
        lead.contacts = people
        lead.contact = fresh_contact(people[0])
        lead.email_draft = people[0].email_draft
        lead.linkedin_note = people[0].linkedin_note
        lead.qa_flags = qa_outreach(lead, lead.email_draft, lead.linkedin_note)
        return lead

    # Indirect / role-only — still one email + one LinkedIn/company note
    email, li, flags = draft_for_approach_channel(llm, lead, icp) if (
        lead.approach_channels or lead.best_approach_channel
    ) else draft_for_person(llm, lead, lead.contact, icp, mode="indirect")
    email = (email or "").strip()
    li = (li or "").strip()
    if email and not li and not email.startswith("[BLOCKED"):
        li = _linkedin_fallback_from_email(email)
    lead.email_draft = email
    lead.linkedin_note = li
    lead.qa_flags = flags
    return lead
