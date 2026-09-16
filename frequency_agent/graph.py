"""LangGraph researcher: ICP → public search → verify → score → draft → review queue."""

from __future__ import annotations

import hashlib
import os
import uuid
from operator import add
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from .icp import normalize_service_line, service_line_label
from .approach_channels import best_approach_channel_str, discover_company_approach_channels
from .branding import brand_domain, brand_name
from .classify import classify_result_section
from .contacts import discover_contacts_for_lead
from .extract import enrich_company, extract_from_hits
from .fetch import fetch_many, hydrate_search_hits
from .llm import LLM, load_json
from .memory import Memory, icp_fingerprint
from .outreach import attach_person_drafts
from .proofs import match_proofs
from .schemas import (
    CompanyLead,
    ICP,
    ParsedICP,
    SearchHit,
    Signal,
    Source,
    fresh_approach_channels,
    to_dict,
)
from .scoring import meets_criteria, score_lead
from .search import SearchClient, expand_queries, publisher_from_url
from .search_export import write_search_csv
from .util import domain_of, normalize_name, slug_id
from .interest import explain_interest
from .logging_utils import log_error, log_event, user_facing_error
from .parallel import map_parallel, worker_count
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
    owner_email: str


def _llm(state: AgentState) -> LLM:
    return LLM(api_key=state["openai_key"])


def _search(state: AgentState) -> SearchClient:
    return SearchClient(tavily_key=state.get("tavily_key") or "")


def _memory(state: AgentState | None = None) -> Memory:
    email = ""
    if state:
        email = (state.get("owner_email") or "").strip()
    return Memory(owner_email=email or None)


def _excludes() -> tuple[set[str], set[str]]:
    data = load_json("exclude_domains.json")
    domains = {d.lower() for d in data.get("domains") or []}
    names = {normalize_name(n) for n in data.get("names") or []}
    return domains, names


def parse_icp(state: AgentState) -> dict:
    from datetime import datetime, timezone

    raw = (state.get("icp_text") or "").strip()
    if not raw:
        return {
            "error": "ICP text is empty. Describe the companies you want before running.",
            "logs": ["ICP parse aborted: empty brief."],
        }

    try:
        llm = _llm(state)
    except ValueError as exc:
        return {"error": user_facing_error(exc), "logs": [f"ICP parse aborted: {exc}"]}

    memory = _memory(state)
    query_id = (state.get("query_id") or "").strip()
    existing_sl = ""
    if query_id:
        session = memory.get_query_session(query_id)
        existing_sl = ((session or {}).get("service_line") or "").strip()

    try:
        parsed = llm.parse(
            [
                {
                    "role": "system",
                    "content": (
                        "Parse an ICP brief into structured fields for Indian GTM research at "
                        f"{brand_name()} ({brand_domain()}). "
                        "Also choose the best service_line for this brief:\n"
                        "- exec_search: permanent leadership hiring, VP/CXO/founder roles, talent acquisition\n"
                        "- fractional_cxo: interim or part-time CXO (CFO, CEO, CHRO, etc.)\n"
                        "- capital_advisory: M&A, structured credit, working capital, growth capital, fundraise support\n"
                        "Pick the single best fit; if ambiguous, prefer exec_search. "
                        "If a field is not stated, use a conservative default. "
                        "stages like series_b, series_c. sectors like fintech, saas, gcc. "
                        "recency_days default 90."
                    ),
                },
                {"role": "user", "content": raw},
            ],
            ParsedICP,
        )
    except Exception as exc:
        reason = log_error(
            query_id=query_id,
            node="parse_icp",
            exc=exc,
            message="ICP parse failed",
        )
        return {
            "error": user_facing_error(exc),
            "logs": [f"ICP parse failed: {reason}"],
        }
    if existing_sl and existing_sl not in ("", "auto"):
        service_line = normalize_service_line(existing_sl, raw)
    else:
        inferred_sl = getattr(parsed, "service_line", None)
        if inferred_sl is None and isinstance(parsed, dict):
            inferred_sl = parsed.get("service_line")
        service_line = normalize_service_line(inferred_sl, raw)
        if query_id:
            memory.update_query_session(query_id, service_line=service_line, icp_text=raw)

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
        "service_line": service_line,
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
            f"Inferred service line: {service_line_label(service_line)} ({service_line}) · "
            f"sectors={icp.sectors} stages={icp.stages} geo={icp.geo}",
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
    geo = ((state.get("icp") or {}).get("geo") or "").lower()
    country = "india" if "india" in geo else None
    queries = state.get("queries") or []
    try:
        found = client.search_many(
            queries,
            max_results=5,
            advanced=True,
            country=country,
            max_workers=worker_count("SEARCH_WORKERS", 6),
        )
    except Exception as exc:
        reason = log_error(
            run_id=state.get("run_id") or "",
            query_id=state.get("query_id") or "",
            node="search_web",
            exc=exc,
            message="search failed",
        )
        return {
            "error": user_facing_error(exc),
            "logs": [f"Search error: {reason}"],
        }
    hits = [h.model_dump() for h in found]
    funnel = dict(state.get("funnel") or {})
    funnel["hits"] = len(hits)
    logs = [f"Search via {client.provider}: {len(hits)} unique public URLs (parallel)."]
    if client.fallback_reason:
        logs.insert(
            0,
            f"Tavily unavailable ({client.fallback_reason}). Using DuckDuckGo instead.",
        )
    if not hits:
        tavily_bit = (
            f" Tavily failed ({client.fallback_reason})."
            if client.fallback_reason
            else ""
        )
        return {
            "hits": hits,
            "funnel": funnel,
            "search_provider": client.provider,
            "error": (
                "Search returned no public URLs."
                + tavily_bit
                + " DuckDuckGo also returned none — wait a minute and retry, or top up Tavily credits."
            ),
            "logs": logs,
        }
    return {
        "hits": hits,
        "funnel": funnel,
        "search_provider": client.provider,
        "logs": logs,
    }


def extract_companies(state: AgentState) -> dict:
    llm = _llm(state)
    memory = _memory(state)
    icp = ICP.model_validate(state["icp"])
    hits = [SearchHit.model_validate(h) for h in (state.get("hits") or [])]
    hydrate_search_hits(hits, memory)
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


def _enrich_cluster(
    cluster: dict,
    *,
    llm: LLM,
    client,
    memory: Memory,
    icp: ICP,
    icp_hash: str,
    seen_domains: set[str],
    seen_names: set[str],
    discovery_queries: list,
    query_id: str,
    run_id: str,
) -> tuple[dict | None, int]:
    """Enrich one company cluster. Returns (payload, skipped_late_count)."""
    name = cluster["name"]
    domain = cluster.get("domain") or "unknown"
    if (domain != "unknown" and domain.lower() in seen_domains) or (
        normalize_name(name) in seen_names
    ):
        return None, 1
    existing = memory.existing_lead(domain if domain != "unknown" else None, name)
    if existing and existing.get("do_not_contact"):
        return None, 0

    query = f'"{name}" {icp.geo} funding OR raised OR appointed OR expansion OR hiring {icp.sectors[0] if icp.sectors else ""}'
    try:
        extra_hits = client.search(query, max_results=4, advanced=False)
    except Exception:
        extra_hits = []

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
        return None, 0

    hydrate_search_hits(all_hits, memory)
    corpus_parts = [" ".join([h.title, h.snippet, h.raw_content]) for h in all_hits]
    corpus = "\n".join(corpus_parts)

    try:
        enrich_data = enrich_company(llm, icp, name, all_hits[:6])
    except Exception:
        return None, 0

    website = enrich_data.website or cluster.get("website") or "not_found"
    if website and website != "not_found":
        domain = domain_of(website)
        if domain.lower() in seen_domains:
            return None, 1

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

    contact, all_contacts, corpus, verified_contacts = discover_contacts_for_lead(
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

    person_emails = {
        (c.email or "").lower()
        for c in (verified_contacts or all_contacts or [])
        if getattr(c, "email", None)
    }
    if contact.email:
        person_emails.add(contact.email.lower())

    approach_channels = []
    if not verified_contacts:
        approach_channels = fresh_approach_channels(
            discover_company_approach_channels(
                corpus,
                company=name,
                domain=domain or "unknown",
                website=website if website else "",
                hits=all_hits,
                person_emails=person_emails,
            )
        )

    lead = CompanyLead(
        lead_id=slug_id(domain, name, memory.owner_email or ""),
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
        # Dump nested models so hot-reload duplicate class identities can't fail validation.
        signal=to_dict(signal) or {},
        contact=to_dict(contact) or {},
        contacts=[to_dict(c) or {} for c in (all_contacts or [])],
        verified_contacts=[to_dict(c) or {} for c in (verified_contacts or [])],
        approach_channels=[to_dict(c) or {} for c in (approach_channels or [])],
        best_approach_channel=best_approach_channel_str(approach_channels),
        field_uncertainty=uncertainty,
        discovery_queries=discovery_queries,
    )
    lead.signal = verify_signal(lead, corpus)
    if lead.signal.confidence in {"UNVERIFIED", "LOW"} and lead.verified_contacts:
        lead.verified_contacts = []
        if not lead.approach_channels:
            lead.approach_channels = fresh_approach_channels(
                discover_company_approach_channels(
                    corpus,
                    company=name,
                    domain=domain or "unknown",
                    website=website if website else "",
                    hits=all_hits,
                    person_emails=person_emails,
                )
            )
            lead.best_approach_channel = best_approach_channel_str(lead.approach_channels)
    lead.score = score_lead(lead, icp.model_dump())
    lead.result_section = classify_result_section(lead)  # type: ignore[assignment]
    lead.proofs = match_proofs(lead, icp.model_dump(), k=3)
    lead.discovery_web_query = cluster.get("discovery_web_query") or ""
    lead.query_id = query_id or ""

    # Always generate sample mail + LinkedIn for every company (named contacts or company channel).
    lead.why_interested = explain_interest(llm, lead, icp)
    lead = attach_person_drafts(llm, lead, icp.model_dump())
    if not lead.signal.usable_in_outreach:
        flag = (
            f"Signal confidence is {lead.signal.confidence or 'UNVERIFIED'} — sample drafts were still "
            "generated for review; verify before sending."
        )
        lead.qa_flags = list(lead.qa_flags or [])
        if flag not in lead.qa_flags:
            lead.qa_flags.append(flag)
        lead.review_status = "needs_edit"
    elif lead.qa_flags:
        lead.review_status = "needs_edit"

    sig_hash = hashlib.sha256((lead.signal.summary or "").encode()).hexdigest()[:16]
    payload = lead.model_dump()
    payload["signal_hash"] = sig_hash
    payload["icp_hash"] = icp_hash
    payload["run_id"] = run_id or ""
    payload["fetch_run_id"] = run_id or ""
    payload["query_id"] = query_id or ""
    payload["discovery_web_query"] = cluster.get("discovery_web_query") or ""
    payload["why_interested"] = lead.why_interested
    payload["is_new"] = True
    if existing and existing.get("signal_hash") == sig_hash:
        payload["review_status"] = existing.get("review_status") or payload["review_status"]
        payload["field_uncertainty"] = payload.get("field_uncertainty") or []
        payload["field_uncertainty"].append("duplicate_signal: already in memory")
    return payload, 0


def enrich(state: AgentState) -> dict:
    from pathlib import Path

    llm = _llm(state)
    client = _search(state)
    memory = _memory(state)
    icp = ICP.model_validate(state["icp"])
    icp_hash = state.get("icp_hash") or icp_fingerprint(icp.service_line, icp.raw_text)
    seen_domains = {d.lower() for d in (state.get("seen_domains") or [])}
    seen_names = set(state.get("seen_names") or [])
    clusters = state.get("extracted") or []
    # Cost/time control only — not quality ranking. Default 40.
    clusters = clusters[: int(os.getenv("MAX_DISCOVER", "40"))]
    discovery_queries = state.get("queries") or []
    query_id = state.get("query_id") or ""
    run_id = state.get("run_id") or "run"

    def _work(cluster: dict) -> tuple[dict | None, int]:
        company = (cluster.get("name") or "?").strip() or "?"
        try:
            return _enrich_cluster(
                cluster,
                llm=llm,
                client=client,
                memory=memory,
                icp=icp,
                icp_hash=icp_hash,
                seen_domains=seen_domains,
                seen_names=seen_names,
                discovery_queries=discovery_queries,
                query_id=query_id,
                run_id=run_id,
            )
        except Exception as exc:
            reason = log_error(
                run_id=run_id,
                query_id=query_id,
                node="enrich",
                company=company,
                exc=exc,
                message="per-cluster enrich failed",
            )
            # Sentinel payload — filtered below so one bad company never kills the run.
            return {"__enrich_error__": True, "company": company, "reason": reason}, 0

    enrich_workers = worker_count("ENRICH_WORKERS", 5)
    raw_results = map_parallel(
        clusters,
        _work,
        max_workers=enrich_workers,
        env_name="ENRICH_WORKERS",
        default_workers=5,
        return_exceptions=True,
    )
    leads: list[dict] = []
    skipped_late = 0
    enrich_errors: list[str] = []
    for item in raw_results:
        if isinstance(item, BaseException):
            reason = log_error(
                run_id=run_id,
                query_id=query_id,
                node="enrich",
                exc=item,
                message="parallel enrich worker crashed",
            )
            enrich_errors.append(reason)
            continue
        payload, skip = item
        skipped_late += skip
        if not payload:
            continue
        if payload.get("__enrich_error__"):
            enrich_errors.append(
                f"{payload.get('company') or '?'}: {payload.get('reason') or 'enrich failed'}"
            )
            continue
        leads.append(payload)

    # Optional safety valve; default 0 = unlimited (return every criteria match)
    max_queue = int(os.getenv("MAX_QUEUE", "0") or "0")

    matched: list[dict] = []
    for lead in leads:
        if meets_criteria(lead):
            matched.append(lead)

    matched.sort(key=lambda x: (x.get("score") or {}).get("total") or 0, reverse=True)
    if max_queue > 0:
        matched = matched[:max_queue]

    funnel = dict(state.get("funnel") or {})
    funnel["verified"] = sum(1 for l in matched if (l.get("signal") or {}).get("usable_in_outreach"))
    funnel["queued"] = len(matched)
    funnel["returned"] = len(matched)
    funnel["matched"] = len(matched)
    funnel["researched"] = len(leads)
    funnel["enrich_errors"] = len(enrich_errors)
    funnel["with_people"] = sum(1 for l in matched if l.get("result_section") == "verified_people")
    funnel["channel_only"] = sum(1 for l in matched if l.get("result_section") == "approach_channels")
    funnel["unresolved"] = sum(1 for l in matched if l.get("result_section") == "unresolved")
    funnel["skipped_late"] = skipped_late
    skipped_total = int(funnel.get("skipped_this_run") or 0) + skipped_late

    new_ids = [l["lead_id"] for l in matched]
    for lead in matched:
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

    root = Path(__file__).resolve().parent.parent
    csv_path = write_search_csv(
        matched,
        root / "output" / "searches",
        run_id=run_id,
        service_line=icp.service_line,
        icp_text=icp.raw_text,
        new_lead_ids=set(new_ids),
    )

    err_log = []
    if enrich_errors:
        err_log.append(
            f"Enrich skipped {len(enrich_errors)} compan"
            f"{'y' if len(enrich_errors) == 1 else 'ies'} due to errors "
            f"(partial results kept)."
        )
        for line in enrich_errors[:8]:
            err_log.append(f"  · {line}")
        log_event(
            "enrich_partial_failures",
            run_id=run_id,
            query_id=query_id,
            node="enrich",
            message=f"{len(enrich_errors)} cluster failures",
            count=len(enrich_errors),
        )

    summary = (
        f"Enriched {len(leads)} new companies; {funnel['verified']} usable signals; "
        f"returned {len(matched)} matching "
        f"({funnel['with_people']} verified people, {funnel['channel_only']} approach channels); "
        f"skipped {skipped_total} already linked to this query (parallel enrich x{enrich_workers})."
    )
    all_logs = list(state.get("logs") or []) + err_log + [
        summary,
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
        "leads": matched,
        "funnel": funnel,
        "csv_path": str(csv_path),
        "skipped_seen": skipped_total,
        "new_lead_ids": new_ids,
        "logs": err_log
        + [
            f"Enriched {len(leads)} new companies; {funnel['verified']} usable signals; "
            f"returned {len(matched)} matching "
            f"({funnel['with_people']} verified people, {funnel['channel_only']} approach channels); "
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

    def _after_parse(state: AgentState) -> str:
        if state.get("error"):
            return "halt"
        return "expand_queries"

    def _after_search(state: AgentState) -> str:
        if state.get("error") or not (state.get("hits") or []):
            return "halt"
        return "extract_companies"

    g.add_edge(START, "parse_icp")
    g.add_conditional_edges(
        "parse_icp",
        _after_parse,
        {"halt": END, "expand_queries": "expand_queries"},
    )
    g.add_edge("expand_queries", "search_web")
    g.add_conditional_edges(
        "search_web",
        _after_search,
        {"halt": END, "extract_companies": "extract_companies"},
    )
    g.add_edge("extract_companies", "cluster")
    g.add_edge("cluster", "enrich")
    g.add_edge("enrich", END)
    return g.compile()


def run_agent(
    icp_text: str,
    openai_key: str,
    tavily_key: str = "",
    query_id: str = "",
    on_update=None,
    *,
    service_line: str = "",  # deprecated — inferred from ICP text in parse_icp
    owner_email: str = "",
) -> AgentState:
    from .search import reset_provider_circuit

    reset_provider_circuit()
    app = compile_graph()
    initial: AgentState = {
        "openai_key": openai_key,
        "tavily_key": tavily_key or "",
        "icp_text": icp_text,
        "query_id": query_id or "",
        "owner_email": (owner_email or "").strip().lower(),
        "logs": [],
        "leads": [],
        "funnel": {},
    }
    if service_line:
        initial["service_line"] = service_line
    state: AgentState = dict(initial)
    log_event(
        "agent_start",
        query_id=query_id or "",
        node="run_agent",
        message="research run started",
    )
    try:
        for update in app.stream(initial, stream_mode="updates"):
            for node, delta in update.items():
                for key, value in delta.items():
                    if key == "logs":
                        state["logs"] = (state.get("logs") or []) + (value or [])
                    else:
                        state[key] = value  # type: ignore[literal-required]
                if on_update:
                    on_update(node, state)
                if state.get("error"):
                    log_event(
                        "agent_halt",
                        run_id=state.get("run_id") or "",
                        query_id=query_id or "",
                        node=node,
                        message=str(state.get("error") or ""),
                    )
    except Exception as exc:
        reason = log_error(
            run_id=state.get("run_id") or "",
            query_id=query_id or "",
            node="run_agent",
            exc=exc,
            message="top-level agent failure",
        )
        state["error"] = user_facing_error(exc)
        state["logs"] = (state.get("logs") or []) + [f"Agent failed: {reason}"]
    else:
        if not state.get("error"):
            log_event(
                "agent_complete",
                run_id=state.get("run_id") or "",
                query_id=query_id or "",
                node="run_agent",
                message=f"returned {len(state.get('leads') or [])} leads",
            )
    return state
