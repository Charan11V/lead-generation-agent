"""Contact discovery, ranking, and policy by service line + signal. Never fabricate a person."""

from __future__ import annotations

import os
import re
from difflib import SequenceMatcher

from .channels import (
    apply_channels_to_candidate,
    assign_exclusive_channels,
    channel_search_queries,
    confirm_channels_with_llm,
    extract_channels_from_hits,
    extract_channels_from_text,
    filter_channels_for_person,
    merge_channels,
)
from .contact_policy import is_excluded_contact, validate_outreach_contact
from functools import lru_cache

from .extract import extract_contacts_from_corpus
from .fetch import fetch_many, fetch_text
from .llm import LLM, load_json
from .memory import Memory
from .schemas import Contact, ContactCandidate, ContactChannel, EnrichmentExtract, ICP, SearchHit, Signal
from .schemas import fresh_contact, fresh_contact_candidate
from .search import SearchClient


ROLE_ALIASES: dict[str, list[str]] = {
    "founder": ["founder", "co-founder", "cofounder"],
    "ceo": ["ceo", "chief executive", "managing director"],
    "chro": ["chro", "chief human resources", "chief people", "vp people", "head of people", "head of hr"],
    "head of talent": ["head of talent", "talent acquisition", "vp talent", "director talent", "recruiting"],
    "cfo": ["cfo", "chief financial"],
    "cto": ["cto", "chief technology", "chief product"],
    "vp talent": ["vp talent", "vp people", "director hr"],
    "functional cxo": ["chief", "cxo", "president", "svp", "evp"],
}


@lru_cache(maxsize=1)
def load_playbooks() -> dict:
    return dict(load_json("playbooks.json"))


def suggested_roles(service_line: str, signal_type: str) -> list[str]:
    books = load_playbooks()
    book = books.get(service_line) or books["exec_search"]
    mapping = book.get("signal_to_contact") or {}
    return mapping.get(signal_type) or mapping.get("default") or book.get("preferred_contacts") or ["founder", "ceo"]


def contact_search_queries(
    company: str,
    *,
    service_line: str,
    signal_type: str,
    domain: str = "unknown",
) -> list[str]:
    """Targeted public-web queries to surface leadership and hiring decision-makers."""
    roles = suggested_roles(service_line, signal_type)
    role_or = " OR ".join(f'"{r.replace("_", " ")}"' for r in roles[:5])
    queries = [
        f'"{company}" {role_or} India',
        f'"{company}" founder OR CEO OR "managing director" appointed OR joins',
        f'"{company}" CHRO OR "head of talent" OR "VP People" OR "head of HR"',
        f'"{company}" leadership team OR executive OR "named" OR "promoted"',
    ]
    if signal_type == "hiring_surge":
        queries.insert(1, f'"{company}" hiring OR recruiting OR "talent acquisition" OR "people team"')
    if signal_type in {"funding", "acquisition", "expansion"}:
        queries.append(f'"{company}" CFO OR "chief financial" OR investor OR board')
    seen: set[str] = set()
    out: list[str] = []
    for q in queries:
        key = q.lower()
        if key not in seen:
            seen.add(key)
            out.append(q)
    if domain and domain != "unknown":
        site_q = f"site:{domain} team OR leadership OR about OR people"
        if site_q.lower() not in seen:
            out.append(site_q)
    return out[:6]


def _role_matches(role: str, target_roles: list[str]) -> tuple[bool, int]:
    """Return (matched, priority_index). Lower index = higher priority."""
    r = (role or "").lower()
    for i, pref in enumerate(target_roles):
        aliases = ROLE_ALIASES.get(pref, [pref.replace("_", " ")])
        for alias in aliases:
            if alias in r or r in alias:
                return True, i
    return False, len(target_roles)


def is_verified_person_contact(
    cand: ContactCandidate | Contact | dict,
    *,
    service_line: str = "",
    signal_type: str = "",
    company: str = "",
    domain: str = "",
    corpus: str = "",
) -> tuple[bool, str]:
    """Strict gate: named DM, playbook role, not inferred, person-tied channels only."""
    if hasattr(cand, "model_dump"):
        data = cand.model_dump()
    else:
        data = dict(cand)

    name = (data.get("name") or "").strip()
    role = (data.get("role") or "").strip()
    if name.lower() in {"", "not_found", "unknown"}:
        return False, "no named contact"
    if data.get("inferred"):
        return False, "name is inferred"
    if not data.get("usable_in_outreach"):
        return False, "not usable in outreach"
    if data.get("confidence") not in {"HIGH", "MEDIUM"}:
        return False, f"confidence {data.get('confidence')} too low"

    sl = service_line or ""
    st = signal_type or "default"
    target_roles = suggested_roles(sl, st) if sl else []
    if not target_roles:
        books = load_playbooks()
        book = books.get(sl) or books.get("exec_search") or {}
        target_roles = book.get("preferred_contacts") or ["founder", "ceo"]
    matched, _idx = _role_matches(role, target_roles)
    if not matched:
        return False, "role not in ICP playbook approach list"

    # Re-validate person↔company when corpus available
    if company and corpus:
        ok, reason = validate_outreach_contact(
            name, role, company, corpus, domain=domain or "", quote=data.get("why") or ""
        )
        if not ok:
            return False, reason

    # If LinkedIn present, slug must match person (defense in depth)
    li = data.get("linkedin_url") or ""
    if li:
        from .channels import handle_belongs_to_person, linkedin_matches_person

        if not handle_belongs_to_person(li, name):
            return False, "LinkedIn slug does not match person"
        if corpus and company:
            if not linkedin_matches_person(
                li,
                name,
                company=company,
                role=role,
                context=corpus,
                company_domain=domain or "",
            ) and not handle_belongs_to_person(li, name):
                return False, "LinkedIn not verified to person/company"

    # Email if present must look person-tied (already filtered upstream; belt-and-suspenders)
    email = (data.get("email") or "").strip()
    if email:
        from .channels import email_belongs_to_person

        if not email_belongs_to_person(email, name, corpus or ""):
            return False, "email not tied to person"

    return True, "ok"


def mark_and_select_verified_people(
    candidates: list[ContactCandidate],
    *,
    service_line: str,
    signal_type: str,
    company: str = "",
    domain: str = "",
    corpus: str = "",
    max_people: int = 3,
) -> tuple[list[ContactCandidate], list[ContactCandidate]]:
    """Flag playbook/verified contacts; return (display_verified top N, all_marked)."""
    marked: list[ContactCandidate] = []
    verified: list[ContactCandidate] = []
    for c in candidates:
        matched, _ = _role_matches(c.role, suggested_roles(service_line, signal_type))
        ok, reason = is_verified_person_contact(
            c,
            service_line=service_line,
            signal_type=signal_type,
            company=company,
            domain=domain,
            corpus=corpus,
        )
        updated = c.model_copy(
            update={
                "playbook_role_match": matched,
                "person_verified": ok,
                "verification_reason": reason,
                # Strip non-verified from usable display for Section A
                "usable_in_outreach": bool(ok and c.usable_in_outreach),
            }
        )
        # If verification failed due to channels/LI, clear channels so we never show wrong links
        if not ok and reason.startswith("LinkedIn"):
            updated = updated.model_copy(
                update={
                    "linkedin_url": "",
                    "channels": [ch for ch in (updated.channels or []) if ch.kind != "linkedin"],
                    "best_channel": "",
                }
            )
        marked.append(updated)
        if ok:
            verified.append(updated)

    verified = rank_contacts(verified, service_line=service_line, signal_type=signal_type)
    display = verified[: max(1, max_people)] if verified else []
    # Re-rank display primary flags
    display = [
        c.model_copy(update={"rank": i + 1, "is_primary": i == 0}) for i, c in enumerate(display)
    ]
    return display, marked


def _quote_supported(quote: str | None, corpus: str) -> bool:
    if not quote or not corpus:
        return False
    q = quote.strip().lower()
    c = corpus.lower()
    if len(q) >= 12 and q in c:
        return True
    return SequenceMatcher(None, q[:120], c).ratio() > 0.22


def _normalize_person_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def build_contact(
    *,
    name: str | None,
    role: str | None,
    why: str | None,
    source_url: str,
    quote: str | None,
    corpus: str,
    inferred_fields: list[str],
    service_line: str,
    signal_type: str,
) -> Contact:
    roles = suggested_roles(service_line, signal_type)
    default_role = roles[0].replace("_", " ").title() if roles else "Founder / CEO"
    inferred = "contact_name" in (inferred_fields or [])
    usable_name = bool(name) and not inferred and name.strip().lower() not in {"not_found", "unknown"}

    if not usable_name:
        return Contact(
            name="not_found",
            role=role or default_role,
            why=why
            or (
                f"No public name found. Reach the {default_role} because this is a "
                f"{service_line.replace('_', ' ')} motion on a {signal_type} signal."
            ),
            source_url=source_url or "",
            confidence="LOW",
            usable_in_outreach=False,
            inferred=False,
        )

    supported = _quote_supported(quote, corpus)
    return Contact(
        name=name.strip(),
        role=(role or default_role).strip(),
        why=why
        or f"Publicly associated with {name} as {role or default_role}; fits {service_line} contact policy for {signal_type}.",
        source_url=source_url,
        confidence="HIGH" if supported else "MEDIUM",
        usable_in_outreach=True,
        inferred=False,
    )


def _candidate_from_raw(
    *,
    name: str,
    role: str,
    why: str,
    source_url: str,
    quote: str,
    corpus: str,
    inferred: bool,
    service_line: str,
    signal_type: str,
    signal_summary: str,
    company: str = "",
    domain: str = "unknown",
) -> ContactCandidate | None:
    clean_name = (name or "").strip()
    if len(clean_name) < 2:
        return None
    if clean_name.lower() in {"not_found", "unknown", "n/a"}:
        return None

    target_roles = suggested_roles(service_line, signal_type)
    role = (role or target_roles[0].replace("_", " ").title()).strip()

    excluded, ex_reason = is_excluded_contact(clean_name, role, company, f"{corpus} {quote}")
    if excluded:
        return None

    ok, gate_reason = validate_outreach_contact(
        clean_name, role, company, corpus, domain=domain, quote=quote or ""
    )
    if not ok and not inferred:
        return None

    matched, role_idx = _role_matches(role, target_roles)

    if inferred:
        confidence = "LOW"
        usable = False
    elif not ok:
        confidence = "LOW"
        usable = False
    elif _quote_supported(quote, corpus):
        confidence = "HIGH"
        usable = True
    elif clean_name.lower() in corpus.lower():
        confidence = "MEDIUM"
        usable = True
    else:
        confidence = "UNVERIFIED"
        usable = False

    score = 0
    reasons: list[str] = []

    if matched:
        score += max(8, 40 - role_idx * 8)
        reasons.append(f"Role fits {service_line} policy for {signal_type} (+{max(8, 40 - role_idx * 8)}).")
    else:
        score += 4
        reasons.append("Role is adjacent to policy — lower priority (+4).")

    if usable:
        score += 25
        reasons.append("Name sourced in public text (+25).")
    elif inferred:
        score += 2
        reasons.append("Name inferred — not usable (+2).")
    else:
        score += 6
        reasons.append("Name present but weakly sourced (+6).")

    conf_pts = {"HIGH": 15, "MEDIUM": 10, "LOW": 4, "UNVERIFIED": 0}
    score += conf_pts.get(confidence, 0)
    reasons.append(f"Confidence {confidence} (+{conf_pts.get(confidence, 0)}).")

    sig_blob = (signal_summary or "").lower()
    if sig_blob and (clean_name.lower() in sig_blob or role.lower() in sig_blob):
        score += 12
        reasons.append("Mentioned in signal context (+12).")

    if signal_type == "hiring_surge" and any(
        k in role.lower() for k in ("talent", "people", "hr", "chro", "recruit")
    ):
        score += 10
        reasons.append("People/talent owner on a hiring signal (+10).")
    elif signal_type == "funding" and any(k in role.lower() for k in ("founder", "ceo", "chief executive")):
        score += 10
        reasons.append("Economic buyer on a funding signal (+10).")
    elif signal_type == "leadership_departure" and any(
        k in role.lower() for k in ("founder", "ceo", "chro", "people", "talent")
    ):
        score += 10
        reasons.append("Likely owner of backfill decision (+10).")

    why_text = why or f"{clean_name} as {role} — decision-maker at {company} for {service_line.replace('_', ' ')}."
    return ContactCandidate(
        name=clean_name,
        role=role,
        why=why_text,
        source_url=source_url or "",
        confidence=confidence,  # type: ignore[arg-type]
        usable_in_outreach=usable,
        inferred=inferred,
        relevance_score=score,
        likelihood_reason=" ".join(reasons),
        playbook_role_match=matched,
        person_verified=False,
        verification_reason="",
    )


def rank_contacts(
    candidates: list[ContactCandidate],
    *,
    service_line: str,
    signal_type: str,
) -> list[ContactCandidate]:
    """Sort by reachability then relevance; assign rank and primary flag."""

    def sort_key(c: ContactCandidate) -> tuple:
        has_email = 1 if c.email else 0
        has_phone = 1 if c.phone else 0
        has_li = 1 if c.linkedin_url else 0
        has_x = 1 if c.twitter_url else 0
        return (has_email, has_phone, has_li, has_x, c.relevance_score, 1 if c.usable_in_outreach else 0)

    usable = [c for c in candidates if c.usable_in_outreach]
    pool = usable if usable else candidates
    pool = sorted(pool, key=sort_key, reverse=True)
    ranked: list[ContactCandidate] = []
    for i, c in enumerate(pool):
        ranked.append(
            c.model_copy(update={"rank": i + 1, "is_primary": i == 0})
        )
    rest = [c for c in candidates if c not in pool]
    rest = sorted(rest, key=sort_key, reverse=True)
    offset = len(ranked)
    for j, c in enumerate(rest):
        ranked.append(c.model_copy(update={"rank": offset + j + 1, "is_primary": False}))
    return ranked


def _dedupe_candidates(candidates: list[ContactCandidate]) -> list[ContactCandidate]:
    seen: dict[str, ContactCandidate] = {}
    order: list[str] = []
    for c in candidates:
        key = _normalize_person_name(c.name)
        if not key:
            continue
        if key not in seen:
            seen[key] = c
            order.append(key)
            continue
        # Prefer richer channel set / higher score when merging duplicates
        prev = seen[key]
        merged_chans = merge_channels(list(prev.channels or []) + list(c.channels or []))
        richer = apply_channels_to_candidate(prev if prev.relevance_score >= c.relevance_score else c, merged_chans)
        if c.relevance_score > prev.relevance_score and not (prev.email or prev.linkedin_url):
            richer = apply_channels_to_candidate(c, merged_chans)
        seen[key] = richer
    return [seen[k] for k in order]


def _channels_from_extracted(raw) -> list[ContactChannel]:
    """Turn LLM-extracted channel fields into ContactChannel objects (still verified later)."""
    out: list[ContactChannel] = []
    src = getattr(raw, "source_url", "") or ""
    if getattr(raw, "email", None):
        out.append(ContactChannel(kind="email", value=raw.email.strip().lower(), source_url=src, confidence="MEDIUM", priority=100))
    if getattr(raw, "phone", None):
        out.append(ContactChannel(kind="phone", value=raw.phone.strip(), source_url=src, confidence="MEDIUM", priority=95))
    if getattr(raw, "linkedin_url", None):
        out.append(ContactChannel(kind="linkedin", value=raw.linkedin_url.strip(), source_url=src, confidence="MEDIUM", priority=80))
    if getattr(raw, "twitter_url", None):
        out.append(ContactChannel(kind="twitter", value=raw.twitter_url.strip(), source_url=src, confidence="MEDIUM", priority=60))
    for o in getattr(raw, "other_social", None) or []:
        if o:
            out.append(ContactChannel(kind="other", value=o.strip(), source_url=src, confidence="LOW", priority=30))
    return out


def _apollo_hint(name: str, company: str, domain: str, linkedin: str) -> str:
    if linkedin:
        return f"Open LinkedIn → Apollo/DAG extension: {linkedin}"
    parts = [p for p in [name, company, domain if domain != "unknown" else ""] if p]
    return "Apollo search: " + " · ".join(parts)


def _enrich_candidate_channels(
    cand: ContactCandidate,
    *,
    company: str,
    domain: str,
    corpus: str,
    hits: list[SearchHit],
    search: SearchClient | None,
    memory: Memory | None,
) -> tuple[ContactCandidate, list[SearchHit], str]:
    """Find public email/phone/social for one person; optional extra search."""
    person = cand.name
    if person.lower() in {"not_found", "unknown"}:
        return cand, hits, corpus

    # Channels already on corpus/hits near this person
    from_hits = extract_channels_from_hits(hits, company_domain=domain, person_hint=person)
    from_corpus = extract_channels_from_text(corpus, company_domain=domain, person_hint=person)
    pooled = filter_channels_for_person(
        merge_channels(from_hits + from_corpus),
        person=person,
        corpus=corpus,
        company_domain=domain,
        company=company,
        role=cand.role,
    )
    cand = apply_channels_to_candidate(cand, pooled)

    needs_more = not cand.email and not cand.linkedin_url
    if search and needs_more:
        extra_parts = [corpus]
        for q in channel_search_queries(person, company, domain)[:2]:
            if cand.email and cand.linkedin_url:
                break
            try:
                found = search.search(q, max_results=3, advanced=False)
            except Exception:
                continue
            for h in found:
                if h.url in {x.url for x in hits}:
                    chans = extract_channels_from_hits([h], company_domain=domain, person_hint=person)
                    cand = apply_channels_to_candidate(
                        cand,
                        filter_channels_for_person(
                            chans, person=person, corpus=h.url + " " + (h.title or ""),
                            company_domain=domain, company=company, role=cand.role,
                        ),
                    )
                    continue
                hits = hits + [h]
                if "linkedin.com/in/" in (h.url or "").lower() or "twitter.com/" in (h.url or "").lower() or "x.com/" in (h.url or "").lower():
                    title_blob = " ".join([h.url, h.title or "", h.snippet or ""])
                    chans = extract_channels_from_hits([h], company_domain=domain, person_hint=person)
                    cand = apply_channels_to_candidate(
                        cand,
                        filter_channels_for_person(
                            chans,
                            person=person,
                            corpus=title_blob,
                            company_domain=domain,
                            company=company,
                            role=cand.role,
                        ),
                    )
                    continue
                extra_parts.append(" ".join([h.title, h.snippet, h.raw_content or ""]))
                chans = extract_channels_from_hits([h], company_domain=domain, person_hint=person)
                cand = apply_channels_to_candidate(
                    cand,
                    filter_channels_for_person(
                        chans,
                        person=person,
                        corpus=" ".join([h.title, h.snippet, h.raw_content or ""]),
                        company_domain=domain,
                        company=company,
                        role=cand.role,
                    ),
                )
            if cand.email and (cand.linkedin_url or cand.phone):
                break
        # Batch-fetch any pages we discovered without content
        to_fetch = [h for h in hits if not h.raw_content and h.url]
        if to_fetch and memory:
            for url, (title, text) in fetch_many([h.url for h in to_fetch], memory).items():
                for h in to_fetch:
                    if h.url == url and text:
                        h.raw_content = text
                        if title:
                            h.title = h.title or title
        for h in to_fetch:
            if h.raw_content:
                extra_parts.append(" ".join([h.title, h.snippet, h.raw_content]))
        corpus = "\n".join(extra_parts)

    cand = cand.model_copy(
        update={"apollo_hint": _apollo_hint(person, company, domain, cand.linkedin_url)}
    )
    return cand, hits, corpus


def discover_contacts_for_lead(
    *,
    llm: LLM,
    search: SearchClient | None,
    memory: Memory | None,
    company: str,
    domain: str,
    icp: ICP,
    signal: Signal,
    enrich_data: EnrichmentExtract,
    corpus: str,
    hits: list[SearchHit],
    geo: str = "India",
) -> tuple[Contact, list[ContactCandidate], str, list[ContactCandidate]]:
    """
    Discover all plausible outreach targets from gathered company data.
    Runs extra public searches when no strong named contact is found.
    Attaches public email / phone / LinkedIn / X when present in sources.
    Returns (primary_contact, ranked_contacts_for_display, final_corpus, verified_contacts).
    """
    service_line = icp.service_line
    signal_type = signal.type
    candidates: list[ContactCandidate] = []

    # Seed from enrichment extract (often the person tied to the signal article)
    if enrich_data.contact_name:
        seeded = _candidate_from_raw(
            name=enrich_data.contact_name,
            role=enrich_data.contact_role or suggested_roles(service_line, signal_type)[0].replace("_", " ").title(),
            why=enrich_data.contact_why
            or "Named in the primary signal source.",
            source_url=hits[0].url if hits else "",
            quote=enrich_data.contact_quote or enrich_data.evidence_quote or "",
            corpus=corpus,
            inferred="contact_name" in (enrich_data.inferred_fields or []),
            service_line=service_line,
            signal_type=signal_type,
            signal_summary=signal.summary,
            company=company,
            domain=domain,
        )
        if seeded:
            candidates.append(seeded)

    # Multi-contact extraction from everything we already fetched
    extracted = extract_contacts_from_corpus(llm, company, icp, hits, corpus)
    for raw in extracted:
        cand = _candidate_from_raw(
            name=raw.name,
            role=raw.role,
            why=raw.why_relevant,
            source_url=raw.source_url,
            quote=raw.evidence_quote,
            corpus=corpus,
            inferred=raw.inferred,
            service_line=service_line,
            signal_type=signal_type,
            signal_summary=signal.summary,
            company=company,
            domain=domain,
        )
        if cand:
            # Seed LLM-copied channels, then verify via regex against corpus
            llm_chans = _channels_from_extracted(raw)
            verified = filter_channels_for_person(
                merge_channels(
                    llm_chans
                    + extract_channels_from_text(
                        corpus,
                        company_domain=domain,
                        person_hint=raw.name,
                        source_url=raw.source_url or "",
                    )
                ),
                person=raw.name,
                corpus=corpus,
                company_domain=domain,
                company=company,
                role=raw.role or cand.role,
            )
            cand = apply_channels_to_candidate(cand, verified)
            candidates.append(cand)

    candidates = _dedupe_candidates(candidates)
    has_usable = any(c.usable_in_outreach for c in candidates)

    # Extra leadership searches when we lack named decision-makers
    if search and (not has_usable or len(candidates) < 2):
        extra_corpus_parts = [corpus]
        new_hits: list[SearchHit] = []
        for q in contact_search_queries(
            company,
            service_line=service_line,
            signal_type=signal_type,
            domain=domain,
        )[:4]:
            try:
                found = search.search(q, max_results=3, advanced=False)
            except Exception:
                continue
            for h in found:
                if h.url in {x.url for x in hits}:
                    continue
                hits = hits + [h]
                new_hits.append(h)
        if new_hits and memory:
            hydrate = fetch_many([h.url for h in new_hits if not h.raw_content], memory)
            for h in new_hits:
                title, text = hydrate.get(h.url, ("", ""))
                if text:
                    h.raw_content = text
                    if title:
                        h.title = h.title or title
                extra_corpus_parts.append(" ".join([h.title, h.snippet, h.raw_content or ""]))
        expanded_corpus = "\n".join(extra_corpus_parts)
        more = extract_contacts_from_corpus(llm, company, icp, hits[-8:], expanded_corpus)
        for raw in more:
            cand = _candidate_from_raw(
                name=raw.name,
                role=raw.role,
                why=raw.why_relevant,
                source_url=raw.source_url,
                quote=raw.evidence_quote,
                corpus=expanded_corpus,
                inferred=raw.inferred,
                service_line=service_line,
                signal_type=signal_type,
                signal_summary=signal.summary,
                company=company,
                domain=domain,
            )
            if cand:
                cand = apply_channels_to_candidate(
                    cand,
                    filter_channels_for_person(
                        merge_channels(
                            _channels_from_extracted(raw)
                            + extract_channels_from_text(
                                expanded_corpus,
                                company_domain=domain,
                                person_hint=raw.name,
                            )
                        ),
                        person=raw.name,
                        corpus=expanded_corpus,
                        company_domain=domain,
                        company=company,
                        role=raw.role or cand.role,
                    ),
                )
                candidates.append(cand)
        corpus = expanded_corpus
        candidates = _dedupe_candidates(candidates)

    # Per-person channel enrichment for top candidates (parallel when >1)
    top = candidates[:6]
    from .parallel import map_parallel, worker_count

    def _enrich_one(cand: ContactCandidate) -> ContactCandidate:
        out, _, _ = _enrich_candidate_channels(
            cand,
            company=company,
            domain=domain,
            corpus=corpus,
            hits=list(hits),
            search=search,
            memory=memory,
        )
        return out

    if len(top) > 1:
        enriched = map_parallel(
            top,
            _enrich_one,
            max_workers=worker_count("CONTACT_WORKERS", 4),
            env_name="CONTACT_WORKERS",
            default_workers=4,
        )
    else:
        enriched = [_enrich_one(c) for c in top]
    # Keep any remaining candidates without extra search
    for cand in candidates[6:]:
        enriched.append(cand)
    candidates = _dedupe_candidates(enriched)
    candidates = assign_exclusive_channels(candidates)
    candidates = confirm_channels_with_llm(
        llm, company=company, candidates=candidates, corpus=corpus
    )

    ranked = rank_contacts(
        candidates,
        service_line=service_line,
        signal_type=signal_type,
    )

    verified_display, marked = mark_and_select_verified_people(
        ranked,
        service_line=service_line,
        signal_type=signal_type,
        company=company,
        domain=domain,
        corpus=corpus,
        max_people=int(os.getenv("CONTACT_MAX_PEOPLE", "8") or "8"),
    )

    if verified_display:
        primary = verified_display[0]
        contact = fresh_contact(primary)
        # Section A list = verified only; keep marked non-verified out of primary contacts list
        return (
            contact,
            [fresh_contact_candidate(c) for c in verified_display],
            corpus,
            [fresh_contact_candidate(c) for c in verified_display],
        )

    if marked:
        # Keep full marked list for debugging/enrich tray but primary is role-only
        pass

    # Fallback: role-only contact from playbook (no verified person)
    fallback = build_contact(
        name=None,
        role=None,
        why=None,
        source_url=hits[0].url if hits else "",
        quote=None,
        corpus=corpus,
        inferred_fields=enrich_data.inferred_fields or [],
        service_line=service_line,
        signal_type=signal_type,
    )
    role_only = ContactCandidate(
        **fallback.model_dump(),
        relevance_score=7,
        rank=1,
        is_primary=True,
        likelihood_reason="No verified public decision-maker found; role-only fallback from playbook.",
        apollo_hint=_apollo_hint(fallback.role, company, domain, ""),
        playbook_role_match=True,
        person_verified=False,
        verification_reason="no verified person",
    )
    return fallback, [role_only], corpus, []
