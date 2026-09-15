"""Company and enrichment extraction. Quotes must come from source text."""

from __future__ import annotations

import json

from .branding import brand_name
from .llm import LLM
from .schemas import ContactExtractBatch, EnrichmentExtract, ExtractBatch, ExtractedOrg, ICP, SearchHit


def _extract_system() -> str:
    return f"""You extract REAL companies from public search results for a GTM researcher.
Rules:
- Only extract companies clearly named in the text.
- Do not invent funding amounts, dates, cities, or websites.
- If a field is not in the text, omit it (null).
- evidence_quote must be a short span copied from the source.
- is_relevant_to_icp should be true only if the company plausibly matches the ICP.
- Ignore listicle fluff like 'top 10 startups' unless a specific company+signal is named.
- Ignore {brand_name()}'s own clients if mentioned as case studies.
- source_url MUST be copied from the result's url field.
"""

CONTACT_EXTRACT_SYSTEM = """You extract REAL decision-makers at a specific TARGET COMPANY from public search results and page text.

TARGET COMPANY is named in the user message — only include people who work there in a hiring/budget-owning role.

Rules:
- ONLY decision-makers: founders, CEOs, CFOs, CTOs, CHROs, Heads of Talent/HR/People, VPs and Directors who own hiring or leadership budgets.
- EXCLUDE: journalists, reporters, authors, editors, press/PR/spokespersons, investors, VCs, board members at other firms, LinkedIn post authors, and anyone quoted only as external commentary.
- EXCLUDE people at other companies even if mentioned in the same article.
- Only include people clearly named in the text with an explicit role/title AT THE TARGET COMPANY.
- Do not invent names, titles, emails, phones, or social profile URLs.
- If an email, phone, LinkedIn (/in/...), X/Twitter appears NEXT TO that person in the source, copy it exactly — only if the surrounding text confirms they work at the target company in the stated role.
- evidence_quote must show name + role + company together (copied verbatim).
- why_relevant must explain why this person can approve exec search / fractional CXO / capital advisory — not why they were quoted in news.
- If a name is guessed from context but not explicitly stated, set inferred=true.
- Return up to 6 distinct people, ordered by outreach relevance (economic buyer first).
- source_url MUST be copied from the result's url field where the person appears.
"""


def extract_from_hits(llm: LLM, icp: ICP, hits: list[SearchHit], chunk: int = 4) -> list[ExtractedOrg]:
    if not hits:
        return []

    def _process_batch(batch: list[SearchHit]) -> list[ExtractedOrg]:
        batch_found: list[ExtractedOrg] = []
        payload = []
        for h in batch:
            body = (h.raw_content or h.snippet or "")[:4000]
            payload.append(
                {
                    "url": h.url,
                    "title": h.title,
                    "date": h.published_date,
                    "text": body,
                }
            )
        parsed = llm.parse(
            [
                {"role": "system", "content": _extract_system()},
                {
                    "role": "user",
                    "content": (
                        f"ICP: {icp.raw_text}\n"
                        f"Geo={icp.geo} sectors={icp.sectors} stages={icp.stages} recency_days={icp.recency_days}\n"
                        f"Results JSON:\n{json.dumps(payload)}"
                    ),
                },
            ],
            ExtractBatch,
        )
        for org in parsed.companies:
            if not org.name or len(org.name) < 2:
                continue
            if not org.source_url:
                org.source_url = batch[0].url
            for h in batch:
                if h.url == org.source_url or (org.source_url and org.source_url in h.url):
                    org.discovery_web_query = h.query
                    break
            if not org.discovery_web_query and batch:
                org.discovery_web_query = batch[0].query
            batch_found.append(org)
        return batch_found

    batches = [hits[i : i + chunk] for i in range(0, len(hits), chunk)]
    from .parallel import map_parallel, worker_count

    parts = map_parallel(
        batches,
        _process_batch,
        max_workers=worker_count("LLM_WORKERS", 4),
        env_name="LLM_WORKERS",
        default_workers=4,
    )
    found: list[ExtractedOrg] = []
    for part in parts:
        found.extend(part)
    return found


def enrich_company(llm: LLM, icp: ICP, company: str, hits: list[SearchHit]) -> EnrichmentExtract:
    payload = []
    for h in hits:
        payload.append(
            {
                "url": h.url,
                "title": h.title,
                "date": h.published_date,
                "text": (h.raw_content or h.snippet or "")[:3500],
            }
        )
    return llm.parse(
        [
            {
                "role": "system",
                "content": (
                    "Extract ONLY facts present in the sources about this company. "
                    "If a contact name is not explicitly in the text, contact_name must be null. "
                    "Put any guesswork in inferred_fields and do not present it as fact. "
                    "evidence_quote must be copied from a source. "
                    "signal_type must be one of: funding, leadership_departure, new_executive, expansion, "
                    "hiring_surge, new_business_line, acquisition, product_launch, other, none."
                ),
            },
            {
                "role": "user",
                "content": f"Company: {company}\nICP: {icp.raw_text}\nSources:\n{json.dumps(payload)}",
            },
        ],
        EnrichmentExtract,
    )


def extract_contacts_from_corpus(
    llm: LLM,
    company: str,
    icp: ICP,
    hits: list[SearchHit],
    corpus: str,
    chunk: int = 3,
) -> list:
    """Extract all named decision-makers from gathered sources."""
    from .schemas import ExtractedContact

    found: list[ExtractedContact] = []
    if not hits:
        return found

    def _process_batch(batch: list[SearchHit]) -> list[ExtractedContact]:
        batch_found: list[ExtractedContact] = []
        payload = []
        for h in batch:
            body = (h.raw_content or h.snippet or "")[:4000]
            payload.append(
                {
                    "url": h.url,
                    "title": h.title,
                    "date": h.published_date,
                    "text": body,
                }
            )
        try:
            parsed = llm.parse(
                [
                    {"role": "system", "content": CONTACT_EXTRACT_SYSTEM},
                    {
                        "role": "user",
                        "content": (
                            f"Company: {company}\n"
                            f"Service line: {icp.service_line}\n"
                            f"ICP: {icp.raw_text}\n"
                            f"Sources JSON:\n{json.dumps(payload)}"
                        ),
                    },
                ],
                ContactExtractBatch,
            )
        except Exception:
            return batch_found
        for person in parsed.contacts:
            if not person.name or len(person.name.strip()) < 2:
                continue
            if not person.source_url and batch:
                person = person.model_copy(update={"source_url": batch[0].url})
            batch_found.append(person)
        return batch_found

    batches = [hits[i : i + chunk] for i in range(0, len(hits), chunk)]
    from .parallel import map_parallel, worker_count

    parts = map_parallel(
        batches,
        _process_batch,
        max_workers=worker_count("LLM_WORKERS", 4),
        env_name="LLM_WORKERS",
        default_workers=4,
    )
    for part in parts:
        found.extend(part)
    return found
