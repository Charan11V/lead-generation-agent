"""Per-search CSV export — companies + every contact channel found."""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path


SEARCH_CSV_COLUMNS = [
    "Run ID",
    "Company",
    "Website",
    "Domain",
    "Industry",
    "City",
    "Country",
    "Stage",
    "Signal Type",
    "Signal",
    "Signal Date",
    "Signal Confidence",
    "Signal Sources",
    "Overall Score",
    "Score Why",
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
    "Contact Source",
    "Apollo Hint",
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
        people = [p for p in (lead.get("contacts") or []) if (p.get("name") or "").lower() not in {"", "unknown"}]
        if not people and lead.get("contact"):
            people = [lead["contact"]]
        if not people:
            people = [{"name": "not_found", "role": (lead.get("contact") or {}).get("role") or "unknown", "rank": 1, "is_primary": True}]

        signal = lead.get("signal") or {}
        score = lead.get("score") or {}
        base = {
            "Run ID": run_id or lead.get("run_id") or "",
            "Company": lead.get("name") or "",
            "Website": lead.get("website") or "",
            "Domain": lead.get("domain") or "",
            "Industry": lead.get("industry") or "",
            "City": lead.get("city") or "",
            "Country": lead.get("country") or "",
            "Stage": lead.get("funding_stage") or "",
            "Signal Type": signal.get("type") or "",
            "Signal": signal.get("summary") or "",
            "Signal Date": signal.get("date") or "",
            "Signal Confidence": signal.get("confidence") or "",
            "Signal Sources": _sources(lead),
            "Overall Score": score.get("total") or "",
            "Score Why": score.get("why") or "",
            "Is New This Run": "yes" if lead.get("lead_id") in new_lead_ids else "no",
            "Review Status": lead.get("review_status") or "",
            "Outreach Status": lead.get("outreach_status") or "",
            "Proof Points": _proofs(lead),
        }
        for p in people:
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
