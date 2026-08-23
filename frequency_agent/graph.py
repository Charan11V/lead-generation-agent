"""LangGraph researcher: ICP → public search → verify → score → draft → review queue."""

from __future__ import annotations

import hashlib
import os
import uuid
from operator import add
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from .contacts import discover_contacts_for_lead
from .extract import enrich_company, extract_from_hits
from .fetch import fetch_text
from .llm import LLM, load_json
from .memory import Memory, icp_fingerprint
from .outreach import draft_outreach
from .proofs import match_proofs
from .schemas import (
    CompanyLead,
    ICP,
    ParsedICP,
    SearchHit,
    Signal,
    Source,
)
from .scoring import score_lead
from .search import SearchClient, expand_queries, publisher_from_url
from .search_export import write_search_csv
from .util import domain_of, normalize_name, slug_id
from .interest import explain_interest
from .verify import verify_signal


class AgentState(TypedDict, total=False):
    openai_key: str
    tavily_key: str
    service_line: str
    icp_text: str
    icp: dict
    icp_hash: str
    seen_domains: list
    seen_names: list
    queries: list
    hits: list
    extracted: list
    leads: list
    funnel: dict
    logs: Annotated[list[str], add]
    error: str
    run_id: str
    search_provider: str
    csv_path: str
    skipped_seen: int
    new_lead_ids: list
    run_started: str
    query_id: str


def _llm(state: AgentState) -> LLM:
    return LLM(api_key=state["openai_key"])


def _search(state: AgentState) -> SearchClient:
    return SearchClient(tavily_key=state.get("tavily_key") or "")


def _memory() -> Memory:
    return Memory()


def _excludes() -> tuple[set[str], set[str]]:
    data = load_json("exclude_domains.json")
    domains = {d.lower() for d in data.get("domains") or []}
    names = {normalize_name(n) for n in data.get("names") or []}
    return domains, names


def parse_icp(state: AgentState) -> dict:
    from datetime import datetime, timezone

    llm = _llm(state)
    raw = state["icp_text"].strip()
    service_line = state.get("service_line") or "exec_search"
    parsed = llm.parse(
        [
            {
                "role": "system",
                "content": (
                    "Parse an ICP into structured fields for Indian GTM research. "
                    "If a field is not stated, use a conservative default. "
                    "stages like series_b, series_c. sectors like fintech, saas, gcc. "
                    "recency_days default 90."
                ),
            },
            {"role": "user", "content": raw},
        ],
        ParsedICP,
    )
    icp = ICP(
        raw_text=raw,
        service_line=service_line,  # type: ignore[arg-type]
        geo=parsed.geo or "India",
        cities=parsed.cities,
        sectors=parsed.sectors,
        stages=parsed.stages,
        recency_days=parsed.recency_days or 90,
        company_types=parsed.company_types,
        buying_signals=parsed.buying_signals,
        notes=parsed.notes,
    )
    fp = icp_fingerprint(service_line, raw)
    memory = _memory()
    query_id = (state.get("query_id") or "").strip()
    if query_id:
        seen = memory.seen_for_query(query_id)
        seen_msg = (
            f"Memory for this query: {len(seen['lead_ids'])} prior companies will be excluded "
            f"(dedup is per-query only — other queries may overlap)."
        )
    else:
        seen = {"domains": set(), "names": set(), "lead_ids": set()}
        seen_msg = "New query session — no prior companies to exclude for this search."
    return {
        "icp": icp.model_dump(),
        "icp_hash": fp,
        "seen_domains": sorted(seen["domains"]),
        "seen_names": sorted(seen["names"]),
        "run_id": uuid.uuid4().hex[:12],
        "run_started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "funnel": {
            "queries": 0,
            "hits": 0,
            "companies": 0,
            "verified": 0,
            "queued": 0,
            "skipped_seen": len(seen["lead_ids"]),
        },
        "logs": [
            f"Parsed ICP for {service_line}: sectors={icp.sectors} stages={icp.stages} geo={icp.geo}",
            seen_msg,
        ],
    }


def expand(state: AgentState) -> dict:
    llm = _llm(state)
    icp = ICP.model_validate(state["icp"])
    queries = expand_queries(llm, icp)
    funnel = dict(state.get("funnel") or {})
    funnel["queries"] = len(queries)
    return {"queries": queries, "funnel": funnel, "logs": [f"Expanded to {len(queries)} public-web queries."]}


def search_web(state: AgentState) -> dict:
    client = _search(state)
    hits: list[dict] = []
    seen_urls = set()
    geo = ((state.get("icp") or {}).get("geo") or "").lower()
    country = "india" if "india" in geo else None
    for q in state.get("queries") or []:
        try:
            found = client.search(q, max_results=5, advanced=True, country=country)
        except Exception as exc:
            return {"error": f"Search failed: {exc}", "logs": [f"Search error: {exc}"]}
        for h in found:
            if h.url in seen_urls:
                continue
            seen_urls.add(h.url)
            hits.append(h.model_dump())
    funnel = dict(state.get("funnel") or {})
    funnel["hits"] = len(hits)
    return {
        "hits": hits,
        "funnel": funnel,
        "search_provider": client.provider,
        "logs": [f"Search via {client.provider}: {len(hits)} unique public URLs."],
    }


def extract_companies(state: AgentState) -> dict:
    llm = _llm(state)
    icp = ICP.model_validate(state["icp"])
    hits = [SearchHit.model_validate(h) for h in (state.get("hits") or [])]
    # Drop obvious aggregators unless they still name companies — extractor decides relevance
    extracted = extract_from_hits(llm, icp, hits)
    funnel = dict(state.get("funnel") or {})
    funnel["extracted_mentions"] = len(extracted)
    return {
        "extracted": [e.model_dump() for e in extracted],
        "funnel": funnel,
        "logs": [f"Extracted {len(extracted)} company mentions from sources."],
    }


def _is_excluded(name: str, domain: str, ex_domains: set[str], ex_names: set[str]) -> bool:
    if domain and domain.lower() in ex_domains:
        return True
    if normalize_name(name) in ex_names:
        return True
    return False


def cluster_companies(state: AgentState) -> dict:
    ex_domains, ex_names = _excludes()
    seen_domains = {d.lower() for d in (state.get("seen_domains") or [])}
    seen_names = set(state.get("seen_names") or [])
    clusters: dict[str, dict] = {}
    skipped = 0
    for item in state.get("extracted") or []:
        if not item.get("is_relevant_to_icp"):
            continue
        name = (item.get("name") or "").strip()
        if len(name) < 2:
            continue
        website = item.get("website") or ""
        domain = domain_of(website) if website else "unknown"
        if _is_excluded(name, domain, ex_domains, ex_names):
            continue
        # Same ICP re-run: skip companies we already have for this search
        if (domain != "unknown" and domain.lower() in seen_domains) or (
            normalize_name(name) in seen_names
        ):
            skipped += 1
            continue
        key = domain if domain != "unknown" else normalize_name(name)
        bucket = clusters.get(key)
        if not bucket:
            bucket = {
                "name": name,
                "website": website or "not_found",
                "domain": domain,
                "industry": item.get("industry") or "unknown",
                "country": item.get("country") or "unknown",
                "city": item.get("city") or "unknown",
                "stage": item.get("stage") or "unknown",
                "discovery_web_query": item.get("discovery_web_query") or "",
                "mentions": [],
            }
            clusters[key] = bucket
        bucket["mentions"].append(item)
        if not bucket.get("discovery_web_query") and item.get("discovery_web_query"):
            bucket["discovery_web_query"] = item["discovery_web_query"]
        if bucket["website"] == "not_found" and website:
            bucket["website"] = website
            bucket["domain"] = domain_of(website)
    funnel = dict(state.get("funnel") or {})
    funnel["companies"] = len(clusters)
    funnel["skipped_this_run"] = skipped
    return {
        "extracted": list(clusters.values()),
        "funnel": funnel,
        "skipped_seen": skipped,
        "logs": [
            f"Clustered into {len(clusters)} new companies "
            f"(skipped {skipped} already linked to this query; client exclusions applied)."
        ],
    }


def enrich(state: AgentState) -> dict:
    from pathlib import Path

    llm = _llm(state)
    client = _search(state)
    memory = _memory()
    icp = ICP.model_validate(state["icp"])
    icp_hash = state.get("icp_hash") or icp_fingerprint(icp.service_line, icp.raw_text)
    seen_domains = {d.lower() for d in (state.get("seen_domains") or [])}
    seen_names = set(state.get("seen_names") or [])
    clusters = state.get("extracted") or []
    # Cap enrichment so the prototype stays inside the assignment time/cost box
    clusters = clusters[: int(os.getenv("MAX_DISCOVER", "22"))]
    leads: list[dict] = []
    skipped_late = 0
    for cluster in clusters:
        name = cluster["name"]
        domain = cluster.get("domain") or "unknown"
        if (domain != "unknown" and domain.lower() in seen_domains) or (
            normalize_name(name) in seen_names
        ):
            skipped_late += 1
            continue
        existing = memory.existing_lead(domain if domain != "unknown" else None, name)
        if existing and existing.get("do_not_contact"):
            continue

        query = f'"{name}" {icp.geo} funding OR raised OR appointed OR expansion OR hiring {icp.sectors[0] if icp.sectors else ""}'
        try:
            extra_hits = client.search(query, max_results=4, advanced=False)
        except Exception:
            extra_hits = []

        # Attach original mentions as synthetic hits
        mention_hits = []
        for m in cluster.get("mentions") or []:
            url = m.get("source_url") or ""
            if not url:
                continue
            mention_hits.append(
                SearchHit(
                    query="discovery",
                    url=url,
                    title=m.get("name") or "",
                    snippet=m.get("evidence_quote") or m.get("signal_summary") or "",
                    raw_content=m.get("evidence_quote") or "",
                    published_date=m.get("signal_date") or "",
                )
            )
        all_hits = mention_hits + extra_hits
        if not all_hits:
            continue
        # Fetch pages missing raw content
        corpus_parts = []
        for h in all_hits:
            if not h.raw_content:
                title, text = fetch_text(h.url, memory)
                if text:
                    h.raw_content = text
                    if title:
                        h.title = h.title or title
            corpus_parts.append(" ".join([h.title, h.snippet, h.raw_content]))
        corpus = "\n".join(corpus_parts)

        try:
            enrich_data = enrich_company(llm, icp, name, all_hits[:6])
        except Exception:
            continue

        website = enrich_data.website or cluster.get("website") or "not_found"
        if website and website != "not_found":
            domain = domain_of(website)
            # Domain may resolve after enrichment — skip if already linked to this query
            if domain.lower() in seen_domains:
                skipped_late += 1
                continue

        sources = []
        for h in all_hits[:4]:
            sources.append(
                Source(
                    url=h.url,
                    title=h.title,
                    date=h.published_date or enrich_data.signal_date or "",
                    publisher=publisher_from_url(h.url),
                    snippet=(h.snippet or "")[:400],
                )
            )
        signal = Signal(
            type=enrich_data.signal_type or "other",
            summary=enrich_data.signal_summary or "",
            date=enrich_data.signal_date or "unknown",
            sources=sources,
            evidence_quote=enrich_data.evidence_quote or "",
        )
        uncertainty = []
        for field in ("industry", "country", "city", "stage", "website"):
            val = getattr(enrich_data, field, None)
            if not val:
                uncertainty.append(f"{field}=unknown")
        if enrich_data.inferred_fields:
            uncertainty.extend([f"inferred:{f}" for f in enrich_data.inferred_fields])

        contact, all_contacts, corpus = discover_contacts_for_lead(
            llm=llm,
            search=client,
            memory=memory,
            company=name,
            domain=domain or "unknown",
            icp=icp,
            signal=signal,
            enrich_data=enrich_data,
            corpus=corpus,
            hits=all_hits,
        )

        lead = CompanyLead(
            lead_id=slug_id(domain, name),
            name=name,
            website=website if website else "not_found",
            domain=domain or "unknown",
            industry=enrich_data.industry or cluster.get("industry") or "unknown",
            country=enrich_data.country or cluster.get("country") or "unknown",
            city=enrich_data.city or cluster.get("city") or "unknown",
            funding_stage=enrich_data.stage or cluster.get("stage") or "unknown",
            funding_amount=enrich_data.funding_amount or "unknown",
            funding_date=enrich_data.funding_date or "unknown",
            service_line_fit=icp.service_line,  # type: ignore[arg-type]
            signal=signal,
            contact=contact,
            contacts=all_contacts,
            field_uncertainty=uncertainty,
            discovery_queries=state.get("queries") or [],
        )
        lead.signal = verify_signal(lead, corpus)
        lead.score = score_lead(lead, icp.model_dump())
        lead.proofs = match_proofs(lead, icp.model_dump(), k=3)
        lead.why_interested = explain_interest(llm, lead, icp)
        lead.discovery_web_query = cluster.get("discovery_web_query") or ""
        lead.query_id = state.get("query_id") or ""
        if lead.signal.usable_in_outreach:
            email, linkedin, flags = draft_outreach(llm, lead, icp.model_dump())
            lead.email_draft = email
            lead.linkedin_note = linkedin
            lead.qa_flags = flags
            if flags:
                lead.review_status = "needs_edit"
        else:
            lead.email_draft = (
                f"[BLOCKED — DO NOT SEND] Unverified or weak signal for {lead.name}. "
                f"Confidence={lead.signal.confidence}. {lead.signal.inferred_reason}"
            )
            lead.linkedin_note = lead.email_draft
            lead.qa_flags = ["Signal not usable in outreach"]
            lead.review_status = "needs_edit"

        sig_hash = hashlib.sha256((lead.signal.summary or "").encode()).hexdigest()[:16]
        payload = lead.model_dump()
        payload["signal_hash"] = sig_hash
        payload["icp_hash"] = icp_hash
        payload["run_id"] = state.get("run_id") or ""
        payload["fetch_run_id"] = state.get("run_id") or ""
        payload["query_id"] = state.get("query_id") or ""
        payload["discovery_web_query"] = cluster.get("discovery_web_query") or ""
        payload["why_interested"] = lead.why_interested
        payload["is_new"] = True
        if existing and existing.get("signal_hash") == sig_hash:
            payload["review_status"] = existing.get("review_status") or payload["review_status"]
            payload["field_uncertainty"] = payload.get("field_uncertainty") or []
            payload["field_uncertainty"].append("duplicate_signal: already in memory")
        leads.append(payload)

    leads.sort(key=lambda x: (x.get("score") or {}).get("total") or 0, reverse=True)
    max_queue = int(os.getenv("MAX_QUEUE", "15"))
    queued = []
    for lead in leads:
        usable = (lead.get("signal") or {}).get("usable_in_outreach")
        if usable and len(queued) < max_queue:
            queued.append(lead)
    if len(queued) < 10:
        for lead in leads:
            if lead in queued:
                continue
            queued.append(lead)
            if len(queued) >= min(max_queue, 12):
                break

    funnel = dict(state.get("funnel") or {})
    funnel["verified"] = sum(1 for l in leads if (l.get("signal") or {}).get("usable_in_outreach"))
    funnel["queued"] = len(queued)
    funnel["researched"] = len(leads)
    funnel["skipped_late"] = skipped_late
    skipped_total = int(funnel.get("skipped_this_run") or 0) + skipped_late

    run_id = state.get("run_id") or "run"
    query_id = state.get("query_id") or ""
    new_ids = [l["lead_id"] for l in queued]
    for lead in queued:
        memory.upsert_lead(lead, icp_hash=icp_hash)
        if query_id:
            memory.link_lead_to_query(
                query_id,
                lead["lead_id"],
                run_id,
                lead.get("discovery_web_query") or "",
            )
    if query_id:
        memory.touch_query_session(query_id)

    # Per-search CSV with every contact channel
    root = Path(__file__).resolve().parent.parent
    csv_path = write_search_csv(
        queued,
        root / "output" / "searches",
        run_id=run_id,
        service_line=icp.service_line,
        icp_text=icp.raw_text,
        new_lead_ids=set(new_ids),
    )

    all_logs = list(state.get("logs") or []) + [
        f"Enriched {len(leads)} new companies; {funnel['verified']} usable signals; queued {len(queued)}; "
        f"skipped {skipped_total} already linked to this query.",
        f"Search CSV saved: {csv_path.name}",
    ]
    memory.save_run(
        run_id,
        icp.raw_text,
        icp.service_line,
        funnel,
        queries=state.get("queries") or [],
        logs=all_logs,
        lead_ids=new_ids,
        new_lead_ids=new_ids,
        csv_path=str(csv_path),
        skipped_seen=skipped_total,
        started=state.get("run_started"),
        query_id=query_id,
    )

    return {
        "leads": queued,
        "funnel": funnel,
        "csv_path": str(csv_path),
        "skipped_seen": skipped_total,
        "new_lead_ids": new_ids,
        "logs": [
            f"Enriched {len(leads)} new companies; {funnel['verified']} usable signals; queued {len(queued)}; "
            f"skipped {skipped_total} already linked to this query.",
            f"Search CSV saved: {csv_path.name}",
        ],
    }


def compile_graph():
    g = StateGraph(AgentState)
    g.add_node("parse_icp", parse_icp)
    g.add_node("expand_queries", expand)
    g.add_node("search_web", search_web)
    g.add_node("extract_companies", extract_companies)
    g.add_node("cluster", cluster_companies)
    g.add_node("enrich", enrich)
    g.add_edge(START, "parse_icp")
    g.add_edge("parse_icp", "expand_queries")
    g.add_edge("expand_queries", "search_web")
    g.add_edge("search_web", "extract_companies")
    g.add_edge("extract_companies", "cluster")
    g.add_edge("cluster", "enrich")
    g.add_edge("enrich", END)
    return g.compile()


def run_agent(
    icp_text: str,
    service_line: str,
    openai_key: str,
    tavily_key: str = "",
    query_id: str = "",
    on_update=None,
) -> AgentState:
    app = compile_graph()
    initial: AgentState = {
        "openai_key": openai_key,
        "tavily_key": tavily_key or "",
        "service_line": service_line,
        "icp_text": icp_text,
        "query_id": query_id or "",
        "logs": [],
        "leads": [],
        "funnel": {},
    }
    state: AgentState = dict(initial)
    for update in app.stream(initial, stream_mode="updates"):
        for node, delta in update.items():
            for key, value in delta.items():
                if key == "logs":
                    state["logs"] = (state.get("logs") or []) + (value or [])
                else:
                    state[key] = value  # type: ignore[literal-required]
            if on_update:
                on_update(node, state)
    return state
