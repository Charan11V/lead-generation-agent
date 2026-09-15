"""Per-search CSV / JSON export — companies + every contact + outreach drafts."""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path


SEARCH_CSV_COLUMNS = [
    "Owner Email",
    "Query ID",
    "Run ID",
    "Lead ID",
    "Service Line",
    "Result Section",
    "Company",
    "Website",
    "Domain",
    "Industry",
    "City",
    "Country",
    "Stage",
    "Funding Amount",
    "Funding Date",
    "Discovery Web Query",
    "Signal Type",
    "Signal",
    "Signal Date",
    "Signal Confidence",
    "Signal Evidence Quote",
    "Signal Sources",
    "Why Interested",
    "ICP Fit Score",
    "Signal Strength Score",
    "Recency Score",
    "Approach Quality Score",
    "Evidence Depth Score",
    "Contact Relevance Score",
    "Overall Score",
    "Score Why",
    "Best Approach Channel",
    "Company Approach Channels",
    "Person Rank",
    "Primary Contact",
    "Full Name",
    "Title",
    "Email",
    "Phone",
    "LinkedIn URL",
    "Twitter/X URL",
    "Other Social",
    "Best Channel",
    "All Channels",
    "Contact Confidence",
    "Contact Usable",
    "Person Verified",
    "Verification Reason",
    "Person Email Draft",
    "Person LinkedIn Note",
    "Company Email Draft",
    "Company LinkedIn Note",
    "Contact Why",
    "Relevance Score",
    "Likelihood Reason",
    "Contact Source",
    "Apollo Hint",
    "Draft Email",
    "LinkedIn Note",
    "QA Flags",
    "Field Uncertainty",
    "Is New This Run",
    "Review Status",
    "Outreach Status",
    "Proof Points",
]


def _proofs(lead: dict) -> str:
    return " | ".join(
        f"{p.get('company')}: {p.get('outcome')}" for p in (lead.get("proofs") or [])
    )


def _sources(lead: dict) -> str:
    signal = lead.get("signal") or {}
    return " | ".join((s.get("url") or "") for s in (signal.get("sources") or []) if s.get("url"))


def _join_flags(items: list | None) -> str:
    return " | ".join(str(x) for x in (items or []) if x)


def _format_channels(person: dict) -> str:
    parts: list[str] = []
    for ch in person.get("channels") or []:
        if isinstance(ch, dict):
            kind = ch.get("kind") or "other"
            value = ch.get("value") or ""
            conf = ch.get("confidence") or ""
            src = ch.get("source_url") or ""
        else:
            kind = getattr(ch, "kind", "other")
            value = getattr(ch, "value", "")
            conf = getattr(ch, "confidence", "")
            src = getattr(ch, "source_url", "")
        if not value:
            continue
        bit = f"{kind}:{value}"
        if conf:
            bit += f" ({conf})"
        if src:
            bit += f" [{src}]"
        parts.append(bit)
    return " | ".join(parts)


def _person_key(person: dict) -> str:
    name = (person.get("name") or "").strip().lower()
    role = (person.get("role") or "").strip().lower()
    return f"{name}|{role}"


def _merge_person(a: dict, b: dict) -> dict:
    """Prefer non-empty fields; keep the richer contact when merging duplicates."""
    out = dict(a)
    for key, val in b.items():
        if key == "channels":
            if not out.get("channels") and val:
                out["channels"] = val
            continue
        cur = out.get(key)
        empty = cur in (None, "", [], False)
        if empty and val not in (None, "", []):
            out[key] = val
        elif key in {"email_draft", "linkedin_note"} and len(str(val or "")) > len(str(cur or "")):
            out[key] = val
        elif key == "person_verified" and val and not cur:
            out[key] = val
        elif key == "is_primary" and val and not cur:
            out[key] = val
    return out


def people_for_export(lead: dict) -> list[dict]:
    """
    Every fetched contact for a lead — verified + all contacts + primary fallback.
    Dedupes by name+role while keeping the richest outreach/channel fields.
    """
    ordered: list[dict] = []
    for src in (
        lead.get("verified_contacts") or [],
        lead.get("contacts") or [],
        [lead["contact"]] if lead.get("contact") else [],
    ):
        for raw in src:
            if not isinstance(raw, dict):
                continue
            name = (raw.get("name") or "").strip()
            if not name or name.lower() in {"", "unknown", "not_found"}:
                continue
            ordered.append(dict(raw))

    merged: dict[str, dict] = {}
    order: list[str] = []
    for person in ordered:
        key = _person_key(person)
        if key not in merged:
            merged[key] = person
            order.append(key)
        else:
            merged[key] = _merge_person(merged[key], person)

    people = [merged[k] for k in order]
    if not people:
        people = [
            {
                "name": "not_found",
                "role": (lead.get("contact") or {}).get("role") or "unknown",
                "rank": 1,
                "is_primary": True,
            }
        ]
    return people


def search_contact_rows(
    leads: list[dict],
    *,
    run_id: str = "",
    new_lead_ids: set[str] | None = None,
) -> list[dict]:
    """One row per person (or one company row if no named contacts)."""
    new_lead_ids = new_lead_ids or set()
    rows: list[dict] = []
    for lead in leads:
        people = people_for_export(lead)
        signal = lead.get("signal") or {}
        score = lead.get("score") or {}
        company_chans = lead.get("approach_channels") or []
        company_chan_txt = " | ".join(
            f"{(c.get('kind') if isinstance(c, dict) else getattr(c, 'kind', ''))}:"
            f"{(c.get('value') if isinstance(c, dict) else getattr(c, 'value', ''))}"
            for c in company_chans
        )
        company_email = lead.get("email_draft") or ""
        company_li = lead.get("linkedin_note") or ""
        base = {
            "Owner Email": lead.get("owner_email") or "",
            "Query ID": lead.get("query_id") or "",
            "Run ID": run_id or lead.get("run_id") or lead.get("fetch_run_id") or "",
            "Lead ID": lead.get("lead_id") or "",
            "Service Line": lead.get("service_line_fit") or "",
            "Result Section": lead.get("result_section") or "",
            "Company": lead.get("name") or "",
            "Website": lead.get("website") or "",
            "Domain": lead.get("domain") or "",
            "Industry": lead.get("industry") or "",
            "City": lead.get("city") or "",
            "Country": lead.get("country") or "",
            "Stage": lead.get("funding_stage") or "",
            "Funding Amount": lead.get("funding_amount") or "",
            "Funding Date": lead.get("funding_date") or "",
            "Discovery Web Query": lead.get("discovery_web_query") or "",
            "Signal Type": signal.get("type") or "",
            "Signal": signal.get("summary") or "",
            "Signal Date": signal.get("date") or "",
            "Signal Confidence": signal.get("confidence") or "",
            "Signal Evidence Quote": signal.get("evidence_quote") or "",
            "Signal Sources": _sources(lead),
            "Why Interested": lead.get("why_interested") or "",
            "ICP Fit Score": score.get("icp_fit") or "",
            "Signal Strength Score": score.get("signal_strength") or "",
            "Recency Score": score.get("recency") or "",
            "Approach Quality Score": score.get("approach_quality") or score.get("contact_relevance") or "",
            "Evidence Depth Score": score.get("evidence_depth") or "",
            "Contact Relevance Score": score.get("contact_relevance") or score.get("approach_quality") or "",
            "Overall Score": score.get("total") or "",
            "Score Why": score.get("why") or "",
            "Best Approach Channel": lead.get("best_approach_channel") or "",
            "Company Approach Channels": company_chan_txt,
            "Company Email Draft": company_email,
            "Company LinkedIn Note": company_li,
            # Back-compat aliases used by older downloads / tests
            "Draft Email": company_email,
            "LinkedIn Note": company_li,
            "QA Flags": _join_flags(lead.get("qa_flags")),
            "Field Uncertainty": _join_flags(lead.get("field_uncertainty")),
            "Is New This Run": "yes" if lead.get("lead_id") in new_lead_ids else "no",
            "Review Status": lead.get("review_status") or "",
            "Outreach Status": lead.get("outreach_status") or "",
            "Proof Points": _proofs(lead),
        }
        for p in people:
            person_email = (p.get("email_draft") or "").strip() or company_email
            person_li = (p.get("linkedin_note") or "").strip() or company_li
            rows.append(
                {
                    **base,
                    "Person Rank": p.get("rank") or "",
                    "Primary Contact": "yes" if p.get("is_primary") else "no",
                    "Full Name": p.get("name") or "",
                    "Title": p.get("role") or "",
                    "Email": p.get("email") or "",
                    "Phone": p.get("phone") or "",
                    "LinkedIn URL": p.get("linkedin_url") or "",
                    "Twitter/X URL": p.get("twitter_url") or "",
                    "Other Social": " | ".join(p.get("other_social") or []),
                    "Best Channel": p.get("best_channel") or "",
                    "All Channels": _format_channels(p),
                    "Contact Confidence": p.get("confidence") or "",
                    "Contact Usable": "yes" if p.get("usable_in_outreach") else "no",
                    "Person Verified": "yes" if p.get("person_verified") else "no",
                    "Verification Reason": p.get("verification_reason") or "",
                    "Person Email Draft": person_email,
                    "Person LinkedIn Note": person_li,
                    "Contact Why": p.get("why") or "",
                    "Relevance Score": p.get("relevance_score") or "",
                    "Likelihood Reason": p.get("likelihood_reason") or "",
                    "Contact Source": p.get("source_url") or "",
                    "Apollo Hint": p.get("apollo_hint") or "",
                }
            )
    return rows


def search_csv_text(
    leads: list[dict],
    *,
    run_id: str = "",
    new_lead_ids: set[str] | None = None,
) -> str:
    rows = search_contact_rows(leads, run_id=run_id, new_lead_ids=new_lead_ids)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=SEARCH_CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def full_results_json_text(
    leads: list[dict],
    *,
    run_id: str = "",
    meta: dict | None = None,
) -> str:
    """
    Full lead payloads (contacts, verified contacts, channels, company + person outreach).
    Wrapped with light export metadata so downloads are self-describing.
    """
    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id or "",
        "company_count": len(leads),
        "contact_row_count": len(search_contact_rows(leads, run_id=run_id)),
        "meta": meta or {},
        "leads": leads,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _safe_slug(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return (s or "search")[:max_len]


def write_search_csv(
    leads: list[dict],
    directory: str | Path,
    *,
    run_id: str,
    service_line: str = "",
    icp_text: str = "",
    new_lead_ids: set[str] | None = None,
) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{run_id}_{_safe_slug(service_line)}_{_safe_slug(icp_text)}.csv"
    path = directory / name
    path.write_text(
        search_csv_text(leads, run_id=run_id, new_lead_ids=new_lead_ids),
        encoding="utf-8",
    )
    return path
